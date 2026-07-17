#!/usr/bin/env python3
import json
import os
import subprocess
import sys

from jellyfin_client import auth, jget, list_views_and_playlists, track_url

PLAYLIST = "/opt/writ-fm/music_playlist.txt"
STATE = "/opt/writ-fm/current_source.txt"


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
    ids = [i["Id"] for i in items.get("Items", [])]
    with open(PLAYLIST, "w") as f:
        for i in ids:
            f.write("file '%s'\n" % track_url(base, tok, i))
    subprocess.run(["systemctl", "restart", "writ-stream.service"], capture_output=True)
    open(STATE, "w").write(src)
    return {"ok": True, "tracks": len(ids)}


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    try:
        print(json.dumps(sources() if cmd == "list" else set_source(sys.argv[2])))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
