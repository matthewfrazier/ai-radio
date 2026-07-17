#!/usr/bin/env python3
"""Shared Jellyfin client: auth, library/playlist listing, track resolution.

Used by jf_source.py (CLI, unchanged output shape) and block_render.py
(music-segment resolution). Re-authenticates on every call, same as the
original jf_source.py — no token caching.
"""
import json
import urllib.parse
import urllib.request

CONF_DEFAULT = "/opt/writ-fm/jellyfin.conf"


def load_conf(path=CONF_DEFAULT):
    c = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                c[k] = v
    return c


def auth(conf=None):
    c = conf or load_conf()
    body = json.dumps({"Username": c["JELLYFIN_USER"], "Pw": c["JELLYFIN_PASS"]}).encode()
    req = urllib.request.Request(
        c["JELLYFIN_URL"] + "/Users/AuthenticateByName", data=body,
        headers={"Content-Type": "application/json",
                 "X-Emby-Authorization": 'MediaBrowser Client="te-radio", Device="te-radio", DeviceId="te-radio-38", Version="1.0"'})
    r = json.loads(urllib.request.urlopen(req, timeout=10).read())
    return c["JELLYFIN_URL"], r["AccessToken"], r["User"]["Id"]


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

    tracks = [{"id": i["Id"], "name": i.get("Name", i["Id"]), "url": track_url(base, tok, i["Id"])} for i in items]
    return {"ref": ref, "title": title, "tracks": tracks, "track_count": len(tracks)}


if __name__ == "__main__":
    import sys
    q = sys.argv[1] if len(sys.argv) > 1 else ""
    print(json.dumps(resolve_music(q)))
