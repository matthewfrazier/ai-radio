#!/usr/bin/env python3
"""Shared Jellyfin client: auth, library/playlist listing, track resolution.

Used by jf_source.py (CLI, unchanged output shape) and block_render.py
(music-segment resolution). Authenticates once per process and reuses the
token: Jellyfin invalidates a device's prior token on re-auth, so a shared
DeviceId let concurrent clients knock each other's tokens dead (music URLs
embed the token and 401'd mid-air). DeviceId is now unique per process and
the token is cached; pass auth(force=True) to deliberately re-mint.
"""
import json
import threading
import urllib.parse
import urllib.request
import uuid

CONF_DEFAULT = "/opt/writ-fm/jellyfin.conf"

# One DeviceId per PROCESS. Jellyfin ties a token to its device and invalidates
# the prior token whenever the same device re-authenticates -- so a shared,
# hardcoded DeviceId made the panel, player, jf_source and every music segment
# all mint on ONE device and knock each other's tokens dead. Music URLs embed
# api_key=<token>, so an earlier segment's URLs 401'd mid-air the moment anything
# else re-authed. A unique per-process id keeps each process's token independent.
_DEVICE_ID = "te-radio-" + uuid.uuid4().hex[:12]
_TOKEN_LOCK = threading.Lock()
_TOKEN = {}  # cached (base, tok, uid) for THIS process -- reused, not re-minted


def load_conf(path=CONF_DEFAULT):
    c = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                c[k] = v
    return c


def auth(conf=None, force=False):
    """Authenticate once per process and reuse the token. Re-minting on the same
    device invalidates the prior token (and any music URL that embedded it), so
    callers share one cached token instead of each minting a fresh one. Pass
    force=True to re-mint (e.g. after a token was invalidated out of band)."""
    with _TOKEN_LOCK:
        if _TOKEN and not force:
            return _TOKEN["base"], _TOKEN["tok"], _TOKEN["uid"]
        c = conf or load_conf()
        body = json.dumps({"Username": c["JELLYFIN_USER"], "Pw": c["JELLYFIN_PASS"]}).encode()
        req = urllib.request.Request(
            c["JELLYFIN_URL"] + "/Users/AuthenticateByName", data=body,
            headers={"Content-Type": "application/json",
                     "X-Emby-Authorization": 'MediaBrowser Client="te-radio", Device="te-radio", DeviceId="%s", Version="1.0"' % _DEVICE_ID})
        r = json.loads(urllib.request.urlopen(req, timeout=10).read())
        base, tok, uid = c["JELLYFIN_URL"], r["AccessToken"], r["User"]["Id"]
        _TOKEN.update(base=base, tok=tok, uid=uid)
        return base, tok, uid


def jget(base, tok, path):
    req = urllib.request.Request(base + path, headers={"X-Emby-Token": tok})
    return json.loads(urllib.request.urlopen(req, timeout=25).read())


def list_views_and_playlists(base, tok, uid):
    out = []
    views = jget(base, tok, "/Users/%s/Views" % uid)
    mid = next((v["Id"] for v in views.get("Items", []) if v.get("CollectionType") == "music"), None)
    if mid:
        out.append({"id": "library:" + mid, "name": "Music Library (shuffle)"})
    pls = jget(base, tok, "/Users/%s/Items?IncludeItemTypes=Playlist&Recursive=true" % uid)
    for p in pls.get("Items", []):
        out.append({"id": "playlist:" + p["Id"], "name": "Playlist: " + p["Name"]})
    return out


def track_url(base, tok, item_id, bitrate=128000):
    return "%s/Audio/%s/stream.mp3?api_key=%s&audioBitRate=%d" % (base, item_id, tok, bitrate)


def resolve_by_ref(ref, base, tok, uid, limit=500):
    kind, sid = ref.split(":", 1)
    if kind == "library":
        items = jget(base, tok, "/Users/%s/Items?ParentId=%s&IncludeItemTypes=Audio&Recursive=true&SortBy=Random&Limit=%d" % (uid, sid, limit))
    else:
        items = jget(base, tok, "/Playlists/%s/Items?UserId=%s&Limit=%d" % (sid, uid, limit))
    return items.get("Items", [])


def search_tracks(base, tok, uid, term, limit=200):
    q = urllib.parse.quote(term)
    items = jget(base, tok, "/Users/%s/Items?searchTerm=%s&IncludeItemTypes=Audio&Recursive=true&Limit=%d" % (uid, q, limit))
    return items.get("Items", [])


def resolve_music(query, limit=200):
    """High-level music-segment resolver. Blank query -> library shuffle;
    else substring-match against playlist names; else free-text search.
    Returns {"ref","title","tracks":[{id,name,url}],"track_count"}.
    """
    conf = load_conf()
    base, tok, uid = auth(conf)
    query = (query or "").strip()

    if not query:
        views = jget(base, tok, "/Users/%s/Views" % uid)
        mid = next((v["Id"] for v in views.get("Items", []) if v.get("CollectionType") == "music"), None)
        if not mid:
            raise RuntimeError("no music library found in Jellyfin")
        ref = "library:" + mid
        items = resolve_by_ref(ref, base, tok, uid, limit=limit)
        title = "Music Library (shuffle)"
    else:
        playlists = [p for p in list_views_and_playlists(base, tok, uid) if p["id"].startswith("playlist:")]
        match = next((p for p in playlists if query.lower() in p["name"].lower()), None)
        if match:
            ref = match["id"]
            items = resolve_by_ref(ref, base, tok, uid, limit=limit)
            title = match["name"]
        else:
            ref = "search:" + query
            items = search_tracks(base, tok, uid, query, limit=limit)
            title = "Search: " + query

    tracks = [{"id": i["Id"], "name": i.get("Name", i["Id"]),
               "artist": _track_artist(i),
               "duration_s": round((i.get("RunTimeTicks") or 0) / 10_000_000, 1),
               "url": track_url(base, tok, i["Id"])} for i in items]
    return {"ref": ref, "title": title, "tracks": tracks, "track_count": len(tracks)}


def delete_item(base, tok, item_id):
    """Delete one item (and its file) from Jellyfin. Requires the account to
    have content-deletion enabled. Returns the HTTP status (204 on success)."""
    req = urllib.request.Request(base + "/Items/" + item_id, method="DELETE",
                                 headers={"X-Emby-Token": tok})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status


def _track_artist(i):
    # Jellyfin returns Artists (list) + AlbumArtist by default; prefer the
    # first track artist, fall back to the album artist.
    a = i.get("Artists") or []
    return (a[0] if a else i.get("AlbumArtist")) or ""


def tracks_by_ids(ids, limit=500):
    """Resolve specific tracks by Jellyfin id, in the requested order (Jellyfin
    doesn't preserve Ids= order). Returns [{id,name,artist,duration_s,url}] for
    the ids that resolved -- the explicit-track-list path for a hand-picked set.
    """
    ids = list(ids)[:limit]
    if not ids:
        return []
    base, tok, uid = auth()
    # Chunk the Ids= query: a few hundred ids overflow the request URI (Jellyfin
    # 414s at ~500). 100/call keeps the URL well under any limit.
    by_id = {}
    for c in range(0, len(ids), 100):
        chunk = ids[c:c + 100]
        items = jget(base, tok, "/Users/%s/Items?Ids=%s&IncludeItemTypes=Audio&Recursive=true&Limit=%d"
                     % (uid, urllib.parse.quote(",".join(chunk)), len(chunk)))
        for i in items.get("Items", []):
            by_id[i["Id"]] = i
    out = []
    for tid in ids:
        i = by_id.get(tid)
        if i:
            out.append({"id": i["Id"], "name": i.get("Name", i["Id"]), "artist": _track_artist(i),
                        "duration_s": round((i.get("RunTimeTicks") or 0) / 10_000_000, 1),
                        "url": track_url(base, tok, i["Id"])})
    return out


if __name__ == "__main__":
    import sys
    q = sys.argv[1] if len(sys.argv) > 1 else ""
    print(json.dumps(resolve_music(q)))
