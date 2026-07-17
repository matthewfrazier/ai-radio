#!/usr/bin/env python3
"""Live NPR/BBC-style source config + best-effort ICY title probe.

Public Icecast-style streams only expose a "now playing" title inside the
stream itself (ICY metadata interleaved at icy-metaint intervals), not via a
separate API — and several (e.g. bbcmedia.co.uk) reject HEAD requests with
400, so any reachability check here must use a real GET, not HEAD. This
module does a bounded, best-effort raw-socket read; any failure just falls
back to the source's static configured name.
"""
import json
import os
import re
import socket
import ssl
import time
import urllib.parse

LIVE_CFG = "/opt/writ-fm/live_sources.json"
LIVE_CFG_EXAMPLE = "/opt/writ-fm/live_sources.json.example"

DEFAULT_SOURCES = [
    {"id": "npr", "name": "NPR Newscast", "url": "https://npr-ice.streamguys1.com/live.mp3", "homepage": "https://www.npr.org/"},
    {"id": "bbc_world", "name": "BBC World Service", "url": "https://stream.live.vc.bbcmedia.co.uk/bbc_world_service", "homepage": "https://www.bbc.co.uk/worldserviceradio"},
]

_title_cache = {}  # source_id -> (title, fetched_at)
_CACHE_TTL_S = 60


def load_sources(path=LIVE_CFG):
    if not os.path.exists(path):
        with open(path, "w") as f:
            json.dump({"sources": DEFAULT_SOURCES}, f, indent=2)
        return list(DEFAULT_SOURCES)
    with open(path) as f:
        return json.load(f).get("sources", [])


def get_source(source_id, path=LIVE_CFG):
    return next((s for s in load_sources(path) if s["id"] == source_id), None)


def probe_icy_title(url, timeout=5.0):
    """Best-effort: read one ICY metadata block. Returns a title string or None."""
    try:
        parsed = urllib.parse.urlparse(url)
        host = parsed.hostname
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query

        sock = socket.create_connection((host, port), timeout=timeout)
        if parsed.scheme == "https":
            sock = ssl.create_default_context().wrap_socket(sock, server_hostname=host)
        sock.settimeout(timeout)

        req = ("GET %s HTTP/1.0\r\nHost: %s\r\nIcy-MetaData: 1\r\nUser-Agent: ai-radio/1.0\r\nConnection: close\r\n\r\n" % (path, host)).encode()
        sock.sendall(req)

        buf = b""
        deadline = time.time() + timeout
        while b"\r\n\r\n" not in buf and time.time() < deadline:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buf += chunk
        if b"\r\n\r\n" not in buf:
            return None
        header_bytes, rest = buf.split(b"\r\n\r\n", 1)
        headers = {}
        for line in header_bytes.decode(errors="replace").split("\r\n")[1:]:
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip().lower()] = v.strip()

        metaint = int(headers.get("icy-metaint", 0))
        if not metaint:
            return None

        while len(rest) < metaint + 1 and time.time() < deadline:
            chunk = sock.recv(4096)
            if not chunk:
                break
            rest += chunk
        if len(rest) < metaint + 1:
            return None

        meta_len = rest[metaint] * 16
        while len(rest) < metaint + 1 + meta_len and time.time() < deadline:
            chunk = sock.recv(4096)
            if not chunk:
                break
            rest += chunk
        meta = rest[metaint + 1: metaint + 1 + meta_len]
        m = re.search(rb"StreamTitle='([^']*)'", meta)
        return m.group(1).decode(errors="replace") if m else None
    except Exception:
        return None
    finally:
        try:
            sock.close()
        except Exception:
            pass


def resolve_live(source_id):
    src = get_source(source_id)
    if not src:
        raise ValueError("unknown live source: %s" % source_id)

    cached = _title_cache.get(source_id)
    if cached and time.time() - cached[1] < _CACHE_TTL_S:
        title = cached[0]
    else:
        title = probe_icy_title(src["url"]) or src["name"]
        _title_cache[source_id] = (title, time.time())

    return {"id": src["id"], "name": src["name"], "url": src["url"],
            "title": title, "homepage": src.get("homepage", "")}


if __name__ == "__main__":
    import sys
    print(json.dumps(resolve_live(sys.argv[1] if len(sys.argv) > 1 else "npr")))
