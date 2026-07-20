#!/usr/bin/env python3
import json
import os
import re
import subprocess
import sys

from jellyfin_client import (auth, jget, list_views_and_playlists,
                             track_url, tracks_by_ids, _track_artist)

PLAYLIST = "/opt/writ-fm/music_playlist.txt"
META = "/opt/writ-fm/music_playlist_meta.json"  # per-track name/dur for /now idle detail
STATE = "/opt/writ-fm/current_source.txt"


def _meta_from_items(items):
    return [{"id": i["Id"], "name": i.get("Name", i["Id"]), "artist": _track_artist(i),
             "duration_s": round((i.get("RunTimeTicks") or 0) / 10_000_000, 1)} for i in items]


def playlist_ids():
    """Jellyfin ids from the current playlist, in order (for meta backfill)."""
    try:
        with open(PLAYLIST) as f:
            return re.findall(r"/Audio/([0-9a-f]+)/stream", f.read())
    except OSError:
        return []


def backfill_meta():
    """Rebuild music_playlist_meta.json for the EXISTING playlist without
    regenerating it -- so /now names idle tracks on the live station now."""
    ids = playlist_ids()
    meta = tracks_by_ids(ids) if ids else []
    with open(META, "w") as f:
        json.dump([{k: t[k] for k in ("id", "name", "artist", "duration_s")} for t in meta], f)
    return {"ok": True, "tracks": len(meta)}


def sources():
    base, tok, uid = auth()
    out = list_views_and_playlists(base, tok, uid)
    cur = open(STATE).read().strip() if os.path.exists(STATE) else ""
    return {"sources": out, "current": cur}


def set_source(src):
    base, tok, uid = auth()
    kind, sid = src.split(":", 1)
    if kind == "library":
        items = jget(base, tok, "/Users/%s/Items?ParentId=%s&IncludeItemTypes=Audio&Recursive=true&SortBy=Random&Limit=500" % (uid, sid))
    else:
        items = jget(base, tok, "/Playlists/%s/Items?UserId=%s&Limit=1000" % (sid, uid))
    items = items.get("Items", [])
    ids = [i["Id"] for i in items]
    with open(PLAYLIST, "w") as f:
        for i in ids:
            f.write("file '%s'\n" % track_url(base, tok, i))
    with open(META, "w") as f:  # same order as the playlist -> /now idle track detail
        json.dump(_meta_from_items(items), f)
    subprocess.run(["systemctl", "restart", "writ-stream.service"], capture_output=True)
    open(STATE, "w").write(src)
    return {"ok": True, "tracks": len(ids)}


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    try:
        if cmd == "list":
            out = sources()
        elif cmd == "backfill":
            out = backfill_meta()
        else:
            out = set_source(sys.argv[2])
        print(json.dumps(out))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
