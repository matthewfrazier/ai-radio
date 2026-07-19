#!/usr/bin/env python3
"""Export a complete local snapshot of the Jellyfin music library to
library_snapshot.json -- the working set for music-selection experiments
(curation, similarity, and the AllMusic-style attribute overlay; see
MUSIC_DNA_OVERLAY.md). Pages through every Audio item with rich Fields, so we
have the whole library locally without hammering Jellyfin per selection.

Re-auths per run like the rest of jellyfin_client. Run: python3 library_snapshot.py
"""
import json
import os
import time
from collections import Counter

import jellyfin_client as jc

SNAPSHOT = "/opt/writ-fm/library_snapshot.json"
# Metadata Jellyfin returns per Audio item that's useful for selection/overlay.
FIELDS = ("Genres,Tags,ProductionYear,PremiereDate,DateCreated,RunTimeTicks,"
          "Artists,AlbumArtist,Album,AlbumId,IndexNumber,ParentIndexNumber")
PAGE = 500


def _music_library_id(base, tok, uid):
    views = jc.jget(base, tok, "/Users/%s/Views" % uid)
    mid = next((v["Id"] for v in views.get("Items", []) if v.get("CollectionType") == "music"), None)
    if not mid:
        raise RuntimeError("no music library found in Jellyfin")
    return mid


def export(path=SNAPSHOT):
    base, tok, uid = jc.auth()
    mid = _music_library_id(base, tok, uid)
    tracks, start, total = [], 0, None
    while True:
        q = ("/Users/%s/Items?ParentId=%s&IncludeItemTypes=Audio&Recursive=true"
             "&SortBy=AlbumArtist,Album,ParentIndexNumber,IndexNumber&SortOrder=Ascending"
             "&Fields=%s&StartIndex=%d&Limit=%d" % (uid, mid, FIELDS, start, PAGE))
        d = jc.jget(base, tok, q)
        items = d.get("Items", [])
        total = d.get("TotalRecordCount", total)
        if not items:
            break
        for i in items:
            tracks.append({
                "id": i["Id"],
                "name": i.get("Name", ""),
                "artists": i.get("Artists") or [],
                "album_artist": i.get("AlbumArtist") or "",
                "album": i.get("Album") or "",
                "album_id": i.get("AlbumId") or "",
                "genres": i.get("Genres") or [],
                "tags": i.get("Tags") or [],
                "year": i.get("ProductionYear"),
                "duration_s": round((i.get("RunTimeTicks") or 0) / 10_000_000, 1),
                "track_no": i.get("IndexNumber"),
                "disc_no": i.get("ParentIndexNumber"),
            })
        start += len(items)
        if total is not None and start >= total:
            break
    snap = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "source": base,
            "library_id": mid, "count": len(tracks), "tracks": tracks}
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(snap, f)
    os.replace(tmp, path)
    return snap


if __name__ == "__main__":
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else SNAPSHOT
    s = export(out)
    genres = Counter(g for t in s["tracks"] for g in t["genres"])
    artists = Counter(t["album_artist"] for t in s["tracks"] if t["album_artist"])
    years = [t["year"] for t in s["tracks"] if t["year"]]
    print("wrote %s" % out)
    print("tracks: %d | artists: %d | genres: %d | years: %s-%s"
          % (s["count"], len(artists), len(genres),
             min(years) if years else "?", max(years) if years else "?"))
    print("top genres:", genres.most_common(15))
