#!/usr/bin/env python3
"""Sequences a programming-block queue onto Icecast /stream.

Run as the systemd unit writ-block-player.service, which arbitrates the
single Icecast mount (Conflicts=writ-stream.service) and restores the static
music loop when the player stops for any reason (ExecStopPost), so this
process no longer manages writ-stream itself or writes a pid file.

One persistent ffmpeg ("sink") holds the Icecast source connection for the
whole run, fed via a FIFO. Each segment is a short-lived producer ffmpeg
(local file, or a bounded-duration live relay) whose raw-PCM stdout this
process relays into the FIFO's single, long-lived write fd -- NOT by
re-opening the FIFO per segment (a FIFO EOFs its reader once every writer
closes, which would kill the sink mid-block).

Signals: SIGTERM/SIGINT stop cleanly; SIGHUP means "abandon the current
block and re-read the queue" -- the play-now cutover, which the panel
triggers after overwriting the queue, avoiding a stop/start writ-stream flap.
"""
import errno
import fcntl
import json
import os
import signal
import subprocess
import time

import block_render as br

BASE = "/opt/writ-fm"
FIFO_PATH = os.path.join(BASE, ".block_sink.fifo")
STUBENV = os.path.join(BASE, ".stubenv")
STATE_FILE = os.path.join(BASE, "player_state.json")

_stop_requested = False
_skip_block = False


def log(msg):
    # stdout -> journald (systemd unit); this process is otherwise a black box.
    print("block_player: %s" % msg, flush=True)


def write_state(d):
    # Best-effort "what's airing right now" for the /now monitor view. Atomic;
    # never fatal to playback.
    try:
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(d, f)
        os.replace(tmp, STATE_FILE)
    except OSError:
        pass


def clear_state():
    try:
        os.remove(STATE_FILE)
    except OSError:
        pass


def _on_stop(signum, frame):
    global _stop_requested
    _stop_requested = True


def _on_skip(signum, frame):
    global _skip_block
    _skip_block = True


def load_srcpw():
    with open(STUBENV) as f:
        for line in f:
            line = line.strip()
            if line.startswith("SRCPW="):
                return line.split("=", 1)[1]
    raise RuntimeError("SRCPW not found in .stubenv")


def start_sink(srcpw):
    return subprocess.Popen([
        "ffmpeg", "-hide_banner", "-loglevel", "warning", "-nostdin",
        "-f", "s16le", "-ar", "44100", "-ac", "2", "-i", FIFO_PATH,
        "-c:a", "libmp3lame", "-b:a", "128k", "-content_type", "audio/mpeg", "-f", "mp3",
        "icecast://source:%s@127.0.0.1:8000/stream" % srcpw,
    ])


def segment_cmd(seg, bdir):
    t = seg["type"]
    if t == "live":
        return ["ffmpeg", "-hide_banner", "-loglevel", "warning", "-nostdin", "-re",
                "-t", str(seg["params"]["duration_s"]), "-i", seg["resolved"]["url"],
                "-f", "s16le", "-ar", "44100", "-ac", "2", "-"]
    if t == "tts":
        path = os.path.join(bdir, seg["resolved"]["audio_path"])
        return ["ffmpeg", "-hide_banner", "-loglevel", "warning", "-nostdin",
                "-i", path, "-f", "s16le", "-ar", "44100", "-ac", "2", "-"]
    if t == "music":
        path = os.path.join(bdir, seg["resolved"]["playlist_path"])
        return ["ffmpeg", "-hide_banner", "-loglevel", "warning", "-nostdin", "-re",
                "-protocol_whitelist", "file,http,https,tcp,tls,crypto",
                "-f", "concat", "-safe", "0", "-i", path,
                "-t", str(seg["params"].get("duration_s", 900)),
                "-f", "s16le", "-ar", "44100", "-ac", "2", "-"]
    raise ValueError("unknown segment type %s" % t)


class Sink:
    """Owns the persistent sink ffmpeg + its FIFO write fd, respawning both
    together if the sink dies mid-block (network blip, Icecast restart)."""

    def __init__(self, srcpw):
        self.srcpw = srcpw
        self.proc = None
        self.fd = None
        self.respawn()

    def respawn(self):
        self.close()
        if os.path.exists(FIFO_PATH):
            os.remove(FIFO_PATH)
        os.mkfifo(FIFO_PATH)
        self.proc = start_sink(self.srcpw)
        # Open the write end WITHOUT blocking forever. A plain O_WRONLY open
        # blocks until a reader appears, and -- because our SIGTERM handler
        # only sets a flag (PEP 475 auto-retries the interrupted syscall) --
        # if the sink ffmpeg dies at startup (bad SRCPW, Icecast down) that
        # open never returns and the process becomes unkillable dead air.
        # Poll O_NONBLOCK (ENXIO = no reader yet) so we stay responsive to
        # stop requests and to the sink dying, then clear O_NONBLOCK for
        # normal blocking writes.
        fd = None
        while not _stop_requested:
            try:
                fd = os.open(FIFO_PATH, os.O_WRONLY | os.O_NONBLOCK)
                break
            except OSError as e:
                if e.errno != errno.ENXIO:
                    raise
                if self.proc.poll() is not None:
                    raise RuntimeError("sink ffmpeg exited before opening the FIFO")
                time.sleep(0.1)
        if fd is None:
            raise RuntimeError("stop requested before sink was ready")
        flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, flags & ~os.O_NONBLOCK)
        self.fd = fd

    def write(self, chunk):
        # os.write on a pipe can write fewer bytes than requested (only <=
        # PIPE_BUF is atomic; we push 64KB), so loop until the whole chunk is
        # consumed -- a dropped remainder truncates raw PCM mid-frame and
        # desyncs the channels for the rest of the segment.
        mv = memoryview(chunk)
        while mv:
            try:
                n = os.write(self.fd, mv)
                mv = mv[n:]
            except OSError:
                if self.proc.poll() is not None:
                    self.respawn()  # sink died -- drop the rest of this chunk, resume next
                    return
                raise

    def close(self):
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = None
        if self.proc is not None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            self.proc = None
        try:
            os.remove(FIFO_PATH)
        except OSError:
            pass


def run_segment(seg, bdir, sink):
    if seg.get("status") != "ok":
        log("skip %s seg %s (status=%s)" % (seg.get("type"), seg.get("id"), seg.get("status")))
        return
    proc = subprocess.Popen(segment_cmd(seg, bdir), stdout=subprocess.PIPE)
    try:
        while True:
            chunk = proc.stdout.read(65536)
            if not chunk:
                break
            sink.write(chunk)
            if _stop_requested or _skip_block:
                proc.terminate()
                break
    finally:
        proc.wait()


def open_sink(srcpw, attempts=25, delay=0.2):
    # Tolerate the Icecast mount-release lag during a fallback<->player
    # handoff: systemd's Conflicts= stops the other source, but the mount may
    # take a moment to free, so retry the sink briefly before giving up.
    for i in range(attempts):
        if _stop_requested:
            raise RuntimeError("stop requested before sink was ready")
        try:
            return Sink(srcpw)
        except RuntimeError as e:
            log("sink not ready (%s), retry %d/%d" % (e, i + 1, attempts))
            time.sleep(delay)
    raise RuntimeError("could not acquire Icecast mount after %d attempts" % attempts)


def main():
    global _skip_block
    signal.signal(signal.SIGTERM, _on_stop)
    signal.signal(signal.SIGINT, _on_stop)
    signal.signal(signal.SIGHUP, _on_skip)

    sink = open_sink(load_srcpw())
    log("sink up, draining queue")
    try:
        while not _stop_requested:
            queue = br.load_queue()
            if not queue:
                log("queue drained")
                break
            block_id = queue[0]
            try:
                block = br.render_block(block_id, force=False)  # re-resolve/re-render at AIR time
            except Exception as e:
                log("render failed for %s (%s), dropping" % (block_id, e))
                br.pop_front(block_id)
                continue
            bdir = br.block_dir(block_id)
            nsegs = len(block["segments"])
            log("airing block %s (%d segments)" % (block_id, nsegs))
            _skip_block = False
            for i, seg in enumerate(block["segments"]):
                if _stop_requested or _skip_block:
                    break
                log("segment %s %s" % (seg.get("type"), seg.get("id")))
                write_state({"block_id": block_id, "title": block.get("title"),
                             "segment_count": nsegs, "segment_index": i,
                             "segment_id": seg.get("id"), "segment_role": seg.get("role"),
                             "segment_type": seg.get("type"),
                             "segment_title": (seg.get("resolved") or {}).get("title"),
                             "started_at": br.now_iso()})
                run_segment(seg, bdir, sink)
            if _skip_block:
                log("cutover: abandoning %s, re-reading queue" % block_id)
                _skip_block = False
                continue  # play-now overwrote the queue; don't pop/mark this block
            br.pop_front(block_id)
            br.mark_scheduled(block_id, "played")
            log("finished block %s" % block_id)
    finally:
        sink.close()
        clear_state()
        log("player exiting")


if __name__ == "__main__":
    main()
