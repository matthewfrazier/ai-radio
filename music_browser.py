#!/usr/bin/env python3
"""Similarity + search over the music overlay, for the /browse music browser.

Loads the compact browse_index.json (built by `overlay.py browse-index`) once
and does pure-Python weighted nearest-neighbour -- no numpy, stdlib only. The
dense space is 6 axes (energy, valence, acousticness, danceability,
instrumental, tempo_norm); era/moods/themes/live/genre are faceted filters, not
part of the distance. A brute-force scan over ~40k tracks is a few tens of ms.
"""
import json
import math
import os
import random
import re

BASE = "/opt/writ-fm"
INDEX_PATH = os.path.join(BASE, "browse_index.json")

# --- duplicate detection ---------------------------------------------------
# A dedup key groups the SAME recording across copies/albums. Conservative on
# purpose: strip a leading track number and remaster/reissue/mono/stereo
# markers (truly the same recording) but KEEP live/acoustic/demo/remix/version
# (distinct performances) so pruning never collapses a real alternate take.
_NUMPFX = re.compile(r"^\s*\d{1,3}\s*[-._)\]]+\s*")
_PAREN_MASTER = re.compile(r"\s*[\(\[][^\)\]]*\b(?:remaster(?:ed)?|reissue|mono|stereo)\b[^\)\]]*[\)\]]", re.I)
_DASH_MASTER = re.compile(r"\s*[-–]\s*(?:\d{4}\s+)?(?:remaster(?:ed)?|reissue|mono|stereo)\b.*$", re.I)
_NONAL = re.compile(r"[^a-z0-9]+")


def _norm(s):
    s = _NUMPFX.sub("", s or "")
    s = _PAREN_MASTER.sub("", s)
    s = _DASH_MASTER.sub("", s)
    return _NONAL.sub(" ", s.lower()).strip()


# Titles too generic to identify a recording -- never cluster these (they'd
# false-merge dozens of distinct tracks that happen to share a placeholder name).
_GENERIC = {"", "untitled", "intro", "outro", "interlude", "hidden", "silence",
            "reprise", "track", "bonus track", "hidden track", "no title"}


def dedup_key(name, artist):
    """Stable key grouping the same recording, or None if the title is too
    generic to identify (caller should fall back to the unique track id)."""
    t = _norm(name)
    if not t or t in _GENERIC or t.isdigit():
        return None
    return _norm(artist) + "\x1f" + t

# Axis order MUST match browse_index.json "axes" (overlay.BROWSE_AXES).
AXES = ("energy", "valence", "acousticness", "danceability", "instrumental", "tempo_norm")
# Per-axis distance weights: energy/valence/danceability carry the vibe hardest;
# instrumental least. Tunable.
WEIGHTS = (1.0, 1.0, 0.8, 1.0, 0.7, 0.9)
_SUMW = sum(WEIGHTS)

_INDEX = None   # raw loaded dict
_IDS = None     # list[str], parallel to _VECS/_FILT
_VECS = None    # list[tuple(float x6)]
_FILT = None    # list[tuple(live, era, moods:set, themes:set, genres:set)]
_META = None    # id -> record
_FACETS = None  # {axes, moods, themes, eras} present in the index


def _nset(xs):
    return frozenset(x.lower() for x in (xs or []))


def ready(path=INDEX_PATH):
    return os.path.exists(path)


def load_index(path=INDEX_PATH, force=False):
    """Lazy-load + cache the index and its derived scan structures."""
    global _INDEX, _IDS, _VECS, _FILT, _META, _FACETS
    if _INDEX is not None and not force:
        return _INDEX
    _FACETS = None
    with open(path) as f:
        _INDEX = json.load(f)
    recs = _INDEX["tracks"]
    _IDS = [r["id"] for r in recs]
    _VECS = [tuple(float(x) for x in r["vec"]) for r in recs]
    _FILT = [(bool(r.get("live")), r.get("era"), _nset(r.get("moods")),
              _nset(r.get("themes")), _nset(r.get("genres"))) for r in recs]
    _META = {r["id"]: r for r in recs}
    return _INDEX


def get(track_id):
    load_index()
    return _META.get(track_id)


def facets():
    """Distinct facet values present in the index (for the browser's filters)."""
    global _FACETS
    load_index()
    if _FACETS is None:
        moods, themes, eras = set(), set(), set()
        for r in _INDEX["tracks"]:
            moods.update(r.get("moods") or [])
            themes.update(r.get("themes") or [])
            if r.get("era"):
                eras.add(r["era"])
        _FACETS = {"axes": list(AXES), "moods": sorted(moods),
                   "themes": sorted(themes), "eras": sorted(eras)}
    return _FACETS


def random_track():
    load_index()
    return _META[random.choice(_IDS)] if _IDS else None


def _passes(i, studio_only, era, moods, themes, genre):
    live, e, m, th, g = _FILT[i]
    if studio_only and live:
        return False
    if era and e != era:
        return False
    if moods and not (moods & m):
        return False
    if themes and not (themes & th):
        return False
    if genre and genre not in g:
        return False
    return True


def _dkey(r):
    # None dkey (generic title) -> a unique id key so it never folds with others.
    k = r["dkey"] if "dkey" in r else dedup_key(r.get("name", ""), r.get("artist", ""))
    return k or ("id:" + r["id"])


def nearest(vec, k=40, studio_only=True, era=None, moods=None, themes=None,
            genre=None, exclude=None, collapse=True):
    """Top-k nearest tracks to `vec` under the weighted distance + facet filters.
    Each result is the track record plus a 0-1 `score` (1 = identical). When
    `collapse`, near-duplicate copies of the same recording fold into one result
    carrying a `dupes` count instead of cluttering the list."""
    load_index()
    v0, v1, v2, v3, v4, v5 = (float(x) for x in vec)
    w0, w1, w2, w3, w4, w5 = WEIGHTS
    ex = set(exclude or ())
    ms = _nset(moods) if moods else None
    ths = _nset(themes) if themes else None
    g = genre.lower() if genre else None
    scored = []
    for i, u in enumerate(_VECS):
        if _IDS[i] in ex or not _passes(i, studio_only, era, ms, ths, g):
            continue
        d = (w0 * (u[0] - v0) ** 2 + w1 * (u[1] - v1) ** 2 + w2 * (u[2] - v2) ** 2
             + w3 * (u[3] - v3) ** 2 + w4 * (u[4] - v4) ** 2 + w5 * (u[5] - v5) ** 2)
        scored.append((d, i))
    scored.sort(key=lambda x: x[0])
    out, seen = [], {}
    for d, i in scored:
        r = _META[_IDS[i]]
        key = _dkey(r) if collapse else i
        if key in seen:
            seen[key]["dupes"] += 1
            continue
        rec = {**r, "score": round(1.0 - min(1.0, math.sqrt(d / _SUMW)), 3), "dupes": 1}
        seen[key] = rec
        out.append(rec)
        if len(out) >= k:
            break
    return out


def similar(seed_id, k=40, exclude=None, **filters):
    """Nearest neighbours of a seed track (excluding the seed itself)."""
    load_index()
    r = _META.get(seed_id)
    if not r:
        return []
    ex = set(exclude or ())
    ex.add(seed_id)
    return nearest(r["vec"], k=k, exclude=ex, **filters)


def search(q, limit=30, collapse=True):
    """Substring match over name/artist/album (offline of Jellyfin), duplicates
    folded into one hit with a `dupes` count when `collapse`."""
    load_index()
    q = (q or "").strip().lower()
    if not q:
        return []
    out, seen = [], {}
    for r in _INDEX["tracks"]:
        if q in ("%s %s %s" % (r["name"], r["artist"], r["album"])).lower():
            key = _dkey(r) if collapse else r["id"]
            if key in seen:
                seen[key]["dupes"] += 1
                continue
            seen[key] = {**r, "dupes": 1}
            out.append(seen[key])
            if len(out) >= limit:
                break
    return out


def browse(studio_only=True, era=None, moods=None, themes=None, genre=None,
           sort=None, desc=True, limit=60, collapse=True):
    """Seedless facet-first listing: every track passing the filters, ordered by
    an axis / bpm / name, or randomly sampled when sort is None ('show me upbeat
    90s'). Duplicates fold like nearest()."""
    load_index()
    ms = _nset(moods) if moods else None
    ths = _nset(themes) if themes else None
    g = genre.lower() if genre else None
    idxs = [i for i in range(len(_IDS)) if _passes(i, studio_only, era, ms, ths, g)]
    total = len(idxs)
    if sort in AXES:
        ax = AXES.index(sort)
        idxs.sort(key=lambda i: _VECS[i][ax], reverse=desc)
    elif sort == "name":
        idxs.sort(key=lambda i: (_META[_IDS[i]].get("name") or "").lower())
    else:
        random.shuffle(idxs)
    out, seen = [], set()
    for i in idxs:
        r = _META[_IDS[i]]
        key = _dkey(r) if collapse else i
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
        if len(out) >= limit:
            break
    return {"total": total, "results": out}


def _keep_rank(r):
    """Higher sorts first = the copy to KEEP: prefer studio over live, a copy
    that sits on a tagged album, the longer take, then a known year."""
    return (0 if r.get("live") else 1, 1 if r.get("album") else 0,
            round(r.get("duration_s") or 0, 1), 1 if r.get("year") else 0)


def dedup_clusters(min_size=2):
    """Duplicate groups (same recording), largest first. Each: {key, size, keep,
    prune:[...], divergent}. `divergent` = members' durations spread > 4s, so
    they may NOT be the same recording -- flagged for review, never auto-pruned."""
    load_index()
    groups = {}
    for r in _INDEX["tracks"]:
        groups.setdefault(_dkey(r), []).append(r)
    clusters = []
    for key, recs in groups.items():
        if len(recs) < min_size:
            continue
        recs = sorted(recs, key=_keep_rank, reverse=True)
        durs = [r["duration_s"] for r in recs if r.get("duration_s")]
        kv = recs[0].get("vec")
        vspread = max((sum((a - b) ** 2 for a, b in zip(kv, r["vec"])) for r in recs[1:]),
                      default=0.0) if kv else 0.0
        # Same recording -> near-identical duration AND audio features. Otherwise
        # it's a live/alternate take or a title collision -> review, don't prune.
        divergent = (bool(durs) and max(durs) - min(durs) > 4.0) or vspread > 0.06
        clusters.append({"key": key, "size": len(recs), "keep": recs[0],
                         "prune": recs[1:], "divergent": divergent})
    clusters.sort(key=lambda c: c["size"], reverse=True)
    return clusters


def safe_prune_plan():
    """Manifest of same-recording duplicate groups that are safe to auto-prune:
    keep the best copy (studio > tagged album > longer > has-year), drop the
    rest. Excludes divergent groups (live/alt takes) entirely."""
    clusters = [c for c in dedup_clusters() if not c["divergent"]]

    def slim(r):
        return {"id": r["id"], "name": r.get("name"), "artist": r.get("artist"),
                "album": r.get("album"), "duration_s": r.get("duration_s")}

    manifest = [{"key": c["key"], "keep": slim(c["keep"]), "prune": [slim(r) for r in c["prune"]]}
                for c in clusters]
    prune_ids = [r["id"] for c in clusters for r in c["prune"]]
    return {"groups": len(clusters), "keep": len(clusters), "prune": len(prune_ids),
            "prune_ids": prune_ids, "manifest": manifest}


def dedup_report():
    cl = dedup_clusters()
    safe = [c for c in cl if not c["divergent"]]
    div = [c for c in cl if c["divergent"]]
    return {"tracks": len(_INDEX["tracks"]),
            "duplicate_groups": len(cl),
            "prunable_safe": sum(len(c["prune"]) for c in safe),
            "review_groups": len(div),
            "review_extra_copies": sum(len(c["prune"]) for c in div),
            "top": [{"copies": c["size"], "divergent": c["divergent"],
                     "keep": "%s — %s" % (c["keep"].get("artist") or "?", c["keep"].get("name", ""))}
                    for c in cl[:20]]}


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "dupes":
        print(json.dumps(dedup_report(), indent=2))
    else:
        print("usage: music_browser.py dupes")
