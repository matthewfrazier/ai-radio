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
import urllib.request
import xml.etree.ElementTree as ET

LIVE_CFG = "/opt/writ-fm/live_sources.json"
LIVE_CFG_EXAMPLE = "/opt/writ-fm/live_sources.json.example"

DEFAULT_SOURCES = [
    # npr-ice.streamguys1.com/live.mp3 is NPR's full 24/7 program stream
    # (whatever's currently airing), NOT the newscast -- pd.npr.org's
    # newscast.mp3 is the actual ~5min hourly bulletin (verified 280s).
    {"id": "npr", "name": "NPR Newscast", "url": "http://pd.npr.org/anon.npr-mp3/npr/news/newscast.mp3", "homepage": "https://www.npr.org/podcasts/500005/npr-news-now"},
    # bbc_world used to be the full 24/7 World Service live stream (not a
    # brief, despite the name) -- now resolves to the latest episode of
    # BBC's actual "5 minute news bulletin" podcast feed instead (verified
    # 300s via ffprobe). kind/feed_url kept id-compatible with any saved
    # block that already references source_id "bbc_world".
    {"id": "bbc_world", "name": "BBC World Service News (5min bulletin)", "kind": "podcast_latest",
     "feed_url": "https://podcast.voice.api.bbci.co.uk/rss/audio/p002vsmz?api_key=Wbek5zSqxz0Hk1blo5IBqbd9SCWIfNbT",
     "homepage": "https://www.bbc.co.uk/programmes/p002vsmz"},
    {"id": "dw_brief", "name": "DW News Brief", "kind": "podcast_latest",
     "feed_url": "https://rss.dw.com/syndication/feeds/podcast_en_newsbrief.33191-mrss.xml",
     "homepage": "https://www.dw.com/en/dw-news/program-262267"},
    {"id": "cnn", "name": "CNN", "url": "https://tunein.cdnstream1.com/2868_96.mp3", "homepage": "https://www.cnn.com/audio"},
    {"id": "fox_news_radio", "name": "Fox News Radio", "url": "https://live.amperwave.net/direct/foxnewsradio-foxnewsradioaac-imc?source=fnr.web", "homepage": "https://www.foxnewsradio.com/"},
    {"id": "msnbc", "name": "MSNBC", "url": "https://tunein.cdnstream1.com/3511_96.mp3", "homepage": "https://www.msnbc.com/"},
    {"id": "nbc_news_radio", "name": "NBC News Radio", "url": "http://stream.revma.ihrhls.com/zc6043", "homepage": "https://nbcnewsradio.com/"},
    {"id": "bloomberg_radio", "name": "Bloomberg Radio", "url": "http://26433.live.streamtheworld.com/WBBRAMAAC_SC", "homepage": "https://www.bloomberg.com/audio"},
    {"id": "deutschlandfunk", "name": "Deutschlandfunk", "url": "https://st01.sslstream.dlf.de/dlf/01/128/mp3/stream.mp3?aggregator=web", "homepage": "https://www.deutschlandfunk.de/"},
    {"id": "rfi_monde", "name": "RFI Monde", "url": "http://live02.rfi.fr/rfimonde-64.mp3", "homepage": "https://www.rfi.fr/"},
    {"id": "npo_radio1", "name": "NPO Radio 1", "url": "http://icecast.omroep.nl/radio1-bb-mp3", "homepage": "https://www.nporadio1.nl/"},
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


def _fetch_bytes(url, timeout=10.0):
    req = urllib.request.Request(url, headers={"User-Agent": "ai-radio-station/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def resolve_podcast_latest(feed_url):
    """Fetch a podcast RSS feed and return (url, title) for its most recent
    episode's <enclosure>. For sources that publish periodic short bulletins
    (BBC's 5min world news, DW's ~90s news brief) rather than run a
    continuous live stream -- the whole point is that the URL genuinely
    changes per episode, so this is never cached, same as the rest of
    live/music resolution (cheap call, no reason to)."""
    root = ET.fromstring(_fetch_bytes(feed_url))
    item = root.find("./channel/item")
    if item is None:
        raise RuntimeError("podcast feed has no items: %s" % feed_url)
    enclosure = item.find("enclosure")
    url = enclosure.get("url") if enclosure is not None else None
    if not url:
        raise RuntimeError("podcast feed item has no enclosure: %s" % feed_url)
    title = (item.findtext("title") or "").strip()
    return url, title


def resolve_live(source_id):
    src = get_source(source_id)
    if not src:
        raise ValueError("unknown live source: %s" % source_id)

    if src.get("kind") == "podcast_latest":
        url, episode_title = resolve_podcast_latest(src["feed_url"])
        return {"id": src["id"], "name": src["name"], "url": url,
                "title": episode_title or src["name"], "homepage": src.get("homepage", "")}

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
