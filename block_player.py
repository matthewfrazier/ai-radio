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
import base64
import errno
import fcntl
import json
import os
import signal
import subprocess
import threading
import time
import urllib.parse
import urllib.request

import block_render as br

BASE = "/opt/writ-fm"
FIFO_PATH = os.path.join(BASE, ".block_sink.fifo")
STUBENV = os.path.join(BASE, ".stubenv")
STATE_FILE = os.path.join(BASE, "player_state.json")
FILLER_WAV = os.path.join(BASE, ".cutover_filler.wav")
IDLE_PLAYLIST = os.path.join(BASE, "music_playlist.txt")

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


def segment_metadata_title(seg):
    """A human 'now playing' label for a segment, pushed as the stream title so
    /now, direct listeners, and the Cast receiver show what's actually airing
    instead of 'Unspecified name' / 'ai-radio'."""
    r = seg.get("resolved") or {}
    p = seg.get("params") or {}
    t = seg.get("type")
    if t == "music":
        q = (p.get("query") or "").strip()
        return ("%s music" % q.title()) if q else (r.get("title") or "Music")
    if t == "live":
        return r.get("title") or p.get("source_id") or "News"
    if t == "tts":
        return {"weather": "Weather", "recap": "Station recap",
                "factoid": "Did you know?"}.get(p.get("topic"), r.get("title") or "Interlude")
    return r.get("title") or "ai-radio"


def push_metadata(srcpw, title):
    """Update the Icecast /stream title (ICY metadata). Best-effort; a failure
    never affects playback. Icecast injects this into the MP3 ICY stream, which
    the browser and the Cast receiver read as the current track title. Returns
    True on success -- Icecast 400s a metadata update until the source has
    finished connecting, so callers retry until it sticks."""
    try:
        q = urllib.parse.urlencode({"mount": "/stream", "mode": "updinfo",
                                    "charset": "UTF-8", "song": title})
        req = urllib.request.Request("http://127.0.0.1:8000/admin/metadata?" + q)
        req.add_header("Authorization", "Basic " +
                       base64.b64encode(("source:%s" % srcpw).encode()).decode())
        urllib.request.urlopen(req, timeout=3).read()
        return True
    except Exception:
        return False


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


# Per-clip loudness normalization (EBU R128 loudnorm, single-pass so it works
# on live streams too) applied to every producer, so TTS -- previously much
# quieter -- lands at the same perceived loudness as music and newscasts.
# -14 LUFS is a common streaming target (near modern music masters, so music
# barely moves while quiet speech/news come up). Two-pass measured gain per
# file could replace this later if music ever pumps at the gate.
NORM_AF = ["-af", "loudnorm=I=-14:TP=-1.5:LRA=11"]
PCM_OUT = ["-f", "s16le", "-ar", "44100", "-ac", "2", "-"]


def segment_cmd(seg, bdir):
    t = seg["type"]
    if t == "live":
        return ["ffmpeg", "-hide_banner", "-loglevel", "warning", "-nostdin", "-re",
                "-t", str(seg["params"]["duration_s"]), "-i", seg["resolved"]["url"]] \
            + NORM_AF + PCM_OUT
    if t == "tts":
        path = os.path.join(bdir, seg["resolved"]["audio_path"])
        return ["ffmpeg", "-hide_banner", "-loglevel", "warning", "-nostdin",
                "-i", path] + NORM_AF + PCM_OUT
    if t == "music":
        path = os.path.join(bdir, seg["resolved"]["playlist_path"])
        return ["ffmpeg", "-hide_banner", "-loglevel", "warning", "-nostdin", "-re",
                "-protocol_whitelist", "file,http,https,tcp,tls,crypto",
                "-f", "concat", "-safe", "0", "-i", path,
                "-t", str(seg["params"].get("duration_s", 900))] + NORM_AF + PCM_OUT
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


FILLER_GAP_S = 15  # trailing silence after each bumper so the -stream_loop
                   # repeat leaves a long pause instead of nagging back-to-back.


def _ensure_filler_wav(text):
    # espeak-ng renders the bumper once per distinct text; cache on disk so a
    # cutover doesn't pay TTS latency (it must start feeding the sink NOW).
    # Keyed on text+gap so changing either regenerates.
    marker = FILLER_WAV + ".txt"
    key = "%s\n%d" % (text, FILLER_GAP_S)
    try:
        with open(marker) as f:
            if f.read() == key and os.path.exists(FILLER_WAV):
                return FILLER_WAV
    except OSError:
        pass
    raw = FILLER_WAV + ".raw.wav"
    subprocess.run(["espeak-ng", "-w", raw, text], check=True, capture_output=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", raw,
                    "-af", "apad=pad_dur=%d" % FILLER_GAP_S, FILLER_WAV], check=True)
    os.remove(raw)
    with open(marker, "w") as f:
        f.write(key)
    return FILLER_WAV


def _filler_cmd(cfg):
    # A short-lived producer whose PCM keeps the persistent sink fed during the
    # air-time render gap (otherwise Icecast underruns and Cast receivers quit,
    # never reconnecting). -re paces it to real time to match music producers.
    base = ["ffmpeg", "-hide_banner", "-loglevel", "warning", "-nostdin", "-re"]
    tail = ["-f", "s16le", "-ar", "44100", "-ac", "2", "-"]
    if cfg.get("cutover_filler", True):
        try:
            wav = _ensure_filler_wav(cfg.get("cutover_filler_text") or "One moment.")
            return base + ["-stream_loop", "-1", "-i", wav] + tail
        except Exception as e:
            log("filler tts failed (%s), using silence" % e)
    return base + ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"] + tail


def render_with_filler(block_id, sink, cfg):
    # Render (re-resolve live/music, re-render recap/factoid TTS) in a thread
    # while the main loop pushes filler audio into the sink, so the stream
    # never stalls across the several-second render. Returns the rendered block
    # or re-raises the render's exception (caller drops the block on failure).
    result = {}

    def _do():
        try:
            result["block"] = br.render_block(block_id, force=False)
        except Exception as e:  # noqa: BLE001 -- surfaced to caller below
            result["error"] = e

    t = threading.Thread(target=_do)
    t.start()
    spoken = "spoken bumper" if cfg.get("cutover_filler", True) else "silence"
    log("render gap: %s while %s renders (holds the source so no underrun)" % (spoken, block_id))
    proc = subprocess.Popen(_filler_cmd(cfg), stdout=subprocess.PIPE)
    try:
        while t.is_alive() and not _stop_requested:
            chunk = proc.stdout.read(65536)
            if not chunk:
                break
            sink.write(chunk)
    finally:
        proc.terminate()
        proc.wait()
        t.join()
    if "error" in result:
        raise result["error"]
    return result["block"]


def idle_cmd():
    # The same looped local-music playlist the static writ-stream fallback
    # plays, but decoded to raw PCM for our persistent sink instead of its own
    # Icecast source -- so idle playout holds the SAME mount and never flaps.
    return ["ffmpeg", "-hide_banner", "-loglevel", "warning", "-nostdin", "-re",
            "-stream_loop", "-1",
            "-protocol_whitelist", "file,http,https,tcp,tls,crypto",
            "-f", "concat", "-safe", "0", "-i", IDLE_PLAYLIST] + NORM_AF + PCM_OUT


def run_idle(sink, srcpw):
    """Hold the mount with the idle music loop while the queue is empty, so the
    Icecast source never drops between programming. Returns when a block is
    queued or a stop is requested. Returns False if idle playback can't run
    (no playlist, or the producer died) -- the caller then exits and lets the
    fallback service take the mount, i.e. the pre-existing handoff behaviour."""
    if not os.path.exists(IDLE_PLAYLIST):
        log("no idle playlist (%s), exiting to fallback" % IDLE_PLAYLIST)
        return False
    log("queue empty -- holding mount with idle music loop")
    # Explicit idle marker (not clear_state) so /now can distinguish "player is
    # holding the stream with idle music" from "player off, fallback loop on".
    write_state({"idle": True, "started_at": br.now_iso()})
    proc = subprocess.Popen(idle_cmd(), stdout=subprocess.PIPE)
    pushed = False
    try:
        while not _stop_requested and not _skip_block:
            if br.load_queue():
                return True
            chunk = proc.stdout.read(65536)
            if not chunk:
                log("idle producer ended unexpectedly, exiting to fallback")
                return False
            sink.write(chunk)
            if not pushed:
                # Retry each iteration (~0.4s) until it sticks -- Icecast 400s a
                # metadata update until the freshly-connected source is ready.
                pushed = push_metadata(srcpw, "ai-radio · music mix")
    finally:
        proc.terminate()
        proc.wait()
    return True


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

    srcpw = load_srcpw()
    sink = open_sink(srcpw)
    log("sink up, draining queue")
    try:
        while not _stop_requested:
            queue = br.load_queue()
            if not queue:
                # Don't exit (which would hand the mount to the fallback
                # service and flap the source, killing any Cast). Hold the
                # mount playing idle music until a block is queued. Only exit
                # if idle playout itself can't run.
                if not run_idle(sink, srcpw):
                    log("queue drained")
                    break
                continue
            block_id = queue[0]
            cfg = br.load_station_cfg()
            try:
                # re-resolve/re-render at AIR time, feeding filler to the sink
                # so the stream doesn't underrun during the render.
                block = render_with_filler(block_id, sink, cfg)
            except Exception as e:
                log("render failed for %s (%s), dropping" % (block_id, e))
                br.pop_front(block_id)
                continue
            bdir = br.block_dir(block_id)
            nsegs = len(block["segments"])
            start_index = br.take_cutover(block_id)  # per-segment ▶ / scrub
            log("airing block %s (%d segments, from %d)" % (block_id, nsegs, start_index))
            _skip_block = False
            for i, seg in enumerate(block["segments"]):
                if _stop_requested or _skip_block:
                    break
                if i < start_index:
                    continue
                log("segment %s %s" % (seg.get("type"), seg.get("id")))
                write_state({"block_id": block_id, "title": block.get("title"),
                             "segment_count": nsegs, "segment_index": i,
                             "segment_id": seg.get("id"), "segment_role": seg.get("role"),
                             "segment_type": seg.get("type"),
                             "segment_title": (seg.get("resolved") or {}).get("title"),
                             "started_at": br.now_iso()})
                push_metadata(srcpw, segment_metadata_title(seg))
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
