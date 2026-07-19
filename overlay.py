#!/usr/bin/env python3
"""Music "DNA" overlay: a per-track attribute layer over the Jellyfin library
for selection & sequencing. Design: MUSIC_DNA_OVERLAY.md.

overlay.json is keyed by Jellyfin item id; every field is optional and carries
per-field provenance, so partial population is first-class and any axis can be
re-derived from a better source later. Feature sources that emit
AcousticBrainz-style high-level models -- the AcousticBrainz API OR a local
Essentia streaming_extractor_music run (e.g. on rac) -- map through the SAME
axes_from_features(), so both fill the identical schema.

CLI:
  python3 overlay.py derived                 # era from year (free, all tracks)
  python3 overlay.py acousticbrainz [N]      # MB->AB pass over first N tracks
  python3 overlay.py essentia <features.json># ingest rac/Essentia output
  python3 overlay.py tags [backend model N]  # LLM mood/theme tags (Claude default)
  python3 overlay.py stats                   # coverage report
"""
import json
import os
import re
import time
import urllib.parse
import urllib.request

import llm_backends

BASE = "/opt/writ-fm"
SNAPSHOT = os.path.join(BASE, "library_snapshot.json")
OVERLAY = os.path.join(BASE, "overlay.json")
MBID_CACHE = os.path.join(BASE, ".mbid_cache.json")
VOCAB_VERSION = 1
UA = {"User-Agent": "writ-fm/1.0 (self-hosted radio; music overlay)"}

# Controlled vocabularies -- curated subsets of the real AllMusic terms, sized
# for a radio clock (see MUSIC_DNA_OVERLAY.md). Edit freely; bump VOCAB_VERSION.
MOOD_VOCAB = ["Aggressive", "Ambitious", "Atmospheric", "Bittersweet", "Bleak",
              "Boisterous", "Brooding", "Cathartic", "Dreamy", "Ethereal",
              "Exuberant", "Gritty", "Hypnotic", "Intimate", "Mellow", "Lush",
              "Melancholy", "Nocturnal", "Ominous", "Plaintive", "Rollicking",
              "Swaggering", "Trippy", "Yearning"]
THEME_VOCAB = ["Late Night", "Night Driving", "Day Driving", "Road Trip",
               "Rainy Day", "Party Time", "Club", "Workout", "Introspection",
               "Romantic Evening", "Dinner Ambiance", "Summer", "Morning",
               "Hanging Out", "Empowering", "Heartbreak"]


# ---------------- derived axes (free, full coverage) ----------------
def era_from_year(year):
    if not year:
        return None
    return "%ds" % ((int(year) // 10) * 10)


def tempo_band(bpm):
    if not bpm:
        return None
    bpm = float(bpm)
    return "slow" if bpm < 90 else "mid" if bpm < 110 else "up" if bpm < 132 else "fast"


# ------ AcousticBrainz / Essentia high-level models -> our axes ------
def axes_from_features(highlevel, bpm=None):
    """Map an AcousticBrainz/Essentia 'highlevel' dict (+ optional bpm) to our
    numeric axes. Robust to missing models -- only sets what's present."""
    def prob(model, key):
        return ((highlevel.get(model) or {}).get("all") or {}).get(key)

    happy, sad = prob("mood_happy", "happy"), prob("mood_sad", "sad")
    aggr = prob("mood_aggressive", "aggressive")
    party = prob("mood_party", "party")
    relax = prob("mood_relaxed", "relaxed")
    dance = prob("danceability", "danceable")
    acoustic = prob("mood_acoustic", "acoustic")
    instr = prob("voice_instrumental", "instrumental")

    out = {}
    valence = happy if happy is not None else ((1 - sad) if sad is not None else None)
    if valence is not None:
        out["valence"] = round(valence, 3)
    parts = [x for x in (aggr, party, (1 - relax) if relax is not None else None) if x is not None]
    if parts:
        out["energy"] = round(sum(parts) / len(parts), 3)
    if dance is not None:
        out["danceability"] = round(dance, 3)
    if acoustic is not None:
        out["acousticness"] = round(acoustic, 3)
    if instr is not None:
        out["instrumental"] = round(instr, 3)
    if bpm:
        out["tempo_bpm"] = round(float(bpm), 1)
        out["tempo_band"] = tempo_band(bpm)
    return out


# ---------------- overlay I/O with provenance ----------------
def load_overlay(path=OVERLAY):
    if os.path.exists(path):
        return json.load(open(path))
    return {"generated_at": None, "vocab_version": VOCAB_VERSION, "tracks": {}}


def save_overlay(ov, path=OVERLAY):
    ov["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(ov, f)
    os.replace(tmp, path)


def set_axes(ov, jid, axes, src, conf):
    """Write axes for a track, keeping a higher-confidence source's value."""
    t = ov["tracks"].setdefault(jid, {})
    prov = t.setdefault("provenance", {})
    at = time.strftime("%Y-%m-%d")
    for k, v in axes.items():
        old = prov.get(k)
        if old and old.get("conf", 0) > conf:
            continue
        t[k] = v
        prov[k] = {"src": src, "conf": conf, "at": at}


def load_snapshot(path=SNAPSHOT):
    if not os.path.exists(path):
        raise SystemExit("no %s -- run library_snapshot.py first" % path)
    return json.load(open(path))


# ---------------- derived pass (era) over the whole library ----------------
def enrich_derived(snap, ov):
    n = 0
    for t in snap["tracks"]:
        e = era_from_year(t.get("year"))
        if e:
            set_axes(ov, t["id"], {"era": e}, "derived:year", 1.0)
            n += 1
    return n


# ---------------- MusicBrainz + AcousticBrainz online pass ----------------
def _get(url, timeout=12):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout)


def mb_recording_mbids(artist, title, cache, limit=5):
    key = "%s\x1f%s" % (artist.lower(), title.lower())
    if key in cache:
        return cache[key]
    q = 'artist:"%s" AND recording:"%s"' % (artist.replace('"', ""), title.replace('"', ""))
    u = "https://musicbrainz.org/ws/2/recording/?" + urllib.parse.urlencode(
        {"query": q, "fmt": "json", "limit": limit})
    try:
        d = json.load(_get(u))
        ids = [r["id"] for r in d.get("recordings", [])]
    except Exception:
        ids = []
    cache[key] = ids
    return ids


def ab_highlevel(mbids):
    """Return (mbid, highlevel_dict) for the first mbid AcousticBrainz has."""
    if not mbids:
        return None, None
    u = "https://acousticbrainz.org/api/v1/high-level?recording_ids=" + ";".join(mbids)
    try:
        d = json.load(_get(u))
    except Exception:
        return None, None
    for m in mbids:
        sub = d.get(m)
        if isinstance(sub, dict) and sub:
            entry = sub.get("0") or next(iter(sub.values()))
            hl = (entry or {}).get("highlevel")
            if hl:
                return m, hl
    return None, None


def ab_bpm(mbid):
    try:
        d = json.load(_get("https://acousticbrainz.org/api/v1/%s/low-level" % mbid))
        return (d.get("rhythm") or {}).get("bpm")
    except Exception:
        return None


def _tagged(snap):
    # metadata-based passes need an artist; untagged tracks are Essentia's job.
    return [t for t in snap["tracks"] if (t.get("artists") or t.get("album_artist"))]


def enrich_acousticbrainz(snap, ov, limit=None, sleep=1.1):
    cache = json.load(open(MBID_CACHE)) if os.path.exists(MBID_CACHE) else {}
    tracks = _tagged(snap)
    tracks = tracks[:limit] if limit else tracks
    hits, done = 0, 0
    for t in tracks:
        art = (t.get("artists") or [t.get("album_artist", "")])
        art = art[0] if art else ""
        title = t.get("name", "")
        if not art or not title:
            continue
        mbids = mb_recording_mbids(art, title, cache)
        time.sleep(sleep)  # MusicBrainz asks ~1 req/s
        done += 1
        if mbids:
            mbid, hl = ab_highlevel(mbids)
            if hl:
                axes = axes_from_features(hl, ab_bpm(mbid))
                set_axes(ov, t["id"], axes, "acousticbrainz", 0.8)
                ov["tracks"][t["id"]]["recording_mbid"] = mbid
                hits += 1
        if done % 50 == 0:
            with open(MBID_CACHE, "w") as f:
                json.dump(cache, f)
            save_overlay(ov)
    with open(MBID_CACHE, "w") as f:
        json.dump(cache, f)
    return hits, done


# ---------------- Essentia ingest (features produced on rac) ----------------
def ingest_essentia(features_path, ov):
    """features_path: JSON {jellyfin_id: essentia_output}. Essentia's
    streaming_extractor_music emits highlevel + rhythm.bpm in one object."""
    feats = json.load(open(features_path))
    n = 0
    for jid, ess in feats.items():
        hl = ess.get("highlevel") or {}
        bpm = (ess.get("rhythm") or {}).get("bpm")
        axes = axes_from_features(hl, bpm)
        if axes:
            set_axes(ov, jid, axes, "essentia", 0.9)
            n += 1
    return n


# ---------------- LLM mood/theme tags (AllMusic-style) ----------------
def _extract_json_array(text):
    """Pull a JSON array out of an LLM reply, tolerating code fences and a
    stray trailing comma; if the whole array won't parse, salvage the
    individual objects so one bad row doesn't drop the batch."""
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        return []
    s = re.sub(r",\s*([\]}])", r"\1", m.group(0))  # drop trailing commas
    try:
        return json.loads(s)
    except Exception:
        objs = []
        for om in re.finditer(r"\{[^{}]*\}", s):
            try:
                objs.append(json.loads(om.group(0)))
            except Exception:
                pass
        return objs


def enrich_llm_tags(snap, ov, backend="claude", model="claude-haiku-4-5",
                    limit=None, batch=20, checkpoint=True):
    """Tag tracks with moods/themes from the controlled vocab via an LLM, in
    batches. Grounded only in artist/title/genre/year (no audio) -> confidence
    0.5, so a real audio/AcousticBrainz source always wins on merge."""
    tracks = _tagged(snap)
    tracks = tracks[:limit] if limit else tracks
    mset, tset = set(MOOD_VOCAB), set(THEME_VOCAB)
    moods_s, themes_s = ", ".join(MOOD_VOCAB), ", ".join(THEME_VOCAB)
    tagged = 0
    for start in range(0, len(tracks), batch):
        chunk = tracks[start:start + batch]
        lines = []
        for j, t in enumerate(chunk):
            arts = t.get("artists") or [t.get("album_artist", "")]
            art = arts[0] if arts else ""
            lines.append('%d) "%s" by %s [%s, %s]' % (
                j, t.get("name", ""), art,
                "/".join((t.get("genres") or [])[:2]) or "?", t.get("year") or "?"))
        prompt = (
            "You are a music librarian tagging tracks for radio sequencing. For "
            "each track choose up to 3 MOODS and up to 3 THEMES that fit it, using "
            "ONLY these controlled vocabularies (exact spelling), from your "
            "knowledge of the artist/track/genre/era. Fewer or none if unsure.\n"
            "MOODS: %s\nTHEMES: %s\n\nTracks:\n%s\n\n"
            'Reply ONLY with a JSON array, one object per track index: '
            '[{"i":0,"moods":["..."],"themes":["..."]}]. No prose.'
            % (moods_s, themes_s, "\n".join(lines)))
        try:
            out = _extract_json_array(llm_backends.generate(backend, model, prompt))
        except Exception as e:
            print("batch @%d failed: %s" % (start, e))
            continue
        for o in out:
            i = o.get("i")
            if not isinstance(i, int) or not (0 <= i < len(chunk)):
                continue
            axes = {}
            mo = [m for m in (o.get("moods") or []) if m in mset][:3]
            th = [x for x in (o.get("themes") or []) if x in tset][:3]
            if mo:
                axes["moods"] = mo
            if th:
                axes["themes"] = th
            if axes:
                set_axes(ov, chunk[i]["id"], axes, "llm:" + backend, 0.5)
                tagged += 1
        if checkpoint:
            save_overlay(ov)
    return tagged


# ---------------- coverage report ----------------
def stats(snap, ov):
    axes = ["energy", "valence", "tempo_bpm", "acousticness", "danceability",
            "instrumental", "era", "moods", "themes"]
    total = len(snap["tracks"])
    cov = {a: 0 for a in axes}
    srcs = {}
    for t in ov["tracks"].values():
        for a in axes:
            if a in t:
                cov[a] += 1
        for p in (t.get("provenance") or {}).values():
            srcs[p["src"]] = srcs.get(p["src"], 0) + 1
    return {"tracks_total": total, "tracks_in_overlay": len(ov["tracks"]),
            "coverage": {a: "%d (%.0f%%)" % (cov[a], 100 * cov[a] / total if total else 0) for a in axes},
            "by_source": srcs}


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"
    ov = load_overlay()
    if cmd == "derived":
        snap = load_snapshot()
        n = enrich_derived(snap, ov)
        save_overlay(ov)
        print("derived era for %d tracks" % n)
    elif cmd == "acousticbrainz":
        snap = load_snapshot()
        lim = int(sys.argv[2]) if len(sys.argv) > 2 else None
        h, d = enrich_acousticbrainz(snap, ov, limit=lim)
        save_overlay(ov)
        print("acousticbrainz: %d/%d tracks got features (%.0f%%)" % (h, d, 100 * h / d if d else 0))
    elif cmd == "essentia":
        n = ingest_essentia(sys.argv[2], ov)
        save_overlay(ov)
        print("essentia: ingested %d tracks" % n)
    elif cmd == "tags":
        snap = load_snapshot()
        backend = sys.argv[2] if len(sys.argv) > 2 else "claude"
        model = sys.argv[3] if len(sys.argv) > 3 else "claude-haiku-4-5"
        lim = int(sys.argv[4]) if len(sys.argv) > 4 else None
        n = enrich_llm_tags(snap, ov, backend, model, limit=lim)
        print("llm tags: %d tracks tagged" % n)
    elif cmd == "tracklist":
        import jellyfin_client as jc
        snap = load_snapshot()
        base, tok, uid = jc.auth()
        urls = {t["id"]: jc.track_url(base, tok, t["id"]) for t in snap["tracks"]}
        path = sys.argv[2] if len(sys.argv) > 2 else os.path.join(BASE, "tracklist.json")
        with open(path, "w") as f:
            json.dump({"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                       "base": base, "tracks": urls}, f)
        print("wrote %s (%d tracks) -- input for essentia_rac.py" % (path, len(urls)))
    elif cmd == "stats":
        print(json.dumps(stats(load_snapshot(), ov), indent=2))
    else:
        raise SystemExit("unknown command: %s" % cmd)
