#!/usr/bin/env python3
"""Sequences a programming-block queue onto Icecast /stream.

One persistent ffmpeg ("sink") holds the Icecast source connection for the
whole run, fed via a FIFO. Each segment is a short-lived producer ffmpeg
(local file, or a bounded-duration live relay) whose raw-PCM stdout this
process relays into the FIFO's single, long-lived write fd -- NOT by
re-opening the FIFO per segment (a FIFO EOFs its reader once every writer
closes, which would kill the sink mid-block). Restarts writ-stream.service
(the static Jellyfin loop) when the queue drains or on shutdown, since only
one of the two may hold the Icecast source mount at a time.
"""
import os
import signal
import subprocess
import sys

import block_render as br

BASE = "/opt/writ-fm"
FIFO_PATH = os.path.join(BASE, ".block_sink.fifo")
PID_FILE = os.path.join(BASE, "block_player.pid")
STUBENV = os.path.join(BASE, ".stubenv")

_stop_requested = False


def _handle_signal(signum, frame):
    global _stop_requested
    _stop_requested = True


def load_srcpw():
    for l in open(STUBENV):
        l = l.strip()
        if l.startswith("SRCPW="):
            return l.split("=", 1)[1]
    raise RuntimeError("SRCPW not found in .stubenv")


def start_sink(srcpw):
    return subprocess.Popen([
        "ffmpeg", "-hide_banner", "-loglevel", "warning", "-nostdin",
        "-f", "s16le", "-ar", "44100", "-ac", "2", "-i", FIFO_PATH,
        "-c:a", "libvorbis", "-q:a", "4", "-content_type", "audio/ogg", "-f", "ogg",
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
        self.fd = os.open(FIFO_PATH, os.O_WRONLY)  # blocks until sink opens its read end

    def write(self, chunk):
        try:
            os.write(self.fd, chunk)
        except OSError:
            if self.proc.poll() is not None:
                self.respawn()  # sink died -- drop this chunk, resume on the next one
            else:
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
        return
    proc = subprocess.Popen(segment_cmd(seg, bdir), stdout=subprocess.PIPE)
    try:
        while True:
            chunk = proc.stdout.read(65536)
            if not chunk:
                break
            sink.write(chunk)
            if _stop_requested:
                proc.terminate()
                break
    finally:
        proc.wait()


def main():
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    sink = Sink(load_srcpw())
    try:
        while not _stop_requested:
            queue = br.load_queue()
            if not queue:
                break
            block_id = queue[0]
            block = br.load_block(block_id)
            bdir = br.block_dir(block_id)
            for seg in block["segments"]:
                if _stop_requested:
                    break
                run_segment(seg, bdir, sink)
            br.pop_front()
            br.mark_scheduled(block_id, "played")
    finally:
        sink.close()
        try:
            os.remove(PID_FILE)
        except OSError:
            pass
        subprocess.run(["systemctl", "start", "writ-stream.service"], capture_output=True)


if __name__ == "__main__":
    main()
