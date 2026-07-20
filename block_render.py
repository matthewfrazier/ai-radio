#!/usr/bin/env python3
"""Programming-block CRUD + render orchestration.

A block is a directory under BLOCKS_DIR with a block.json manifest (source
of truth) and a derived block.md rundown. render_block() is the single
entry point that (re)resolves/(re)renders only what's missing or stale —
used by the whole-block Test/Preview action, the manual "regenerate"
action, and the schedule ("play now"/"queue") action alike, so there is one
render code path, not three.
"""
import contextlib
import fcntl
import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone

import jellyfin_client
import live_source
import tts_content
import tts_engines
import llm_backends

BASE = "/opt/writ-fm"
BLOCKS_DIR = os.path.join(BASE, "program_blocks")
STATION_CFG = os.path.join(BASE, "station.json")
QUEUE_FILE = os.path.join(BASE, "block_queue.json")
SCHEDULE_FILE = os.path.join(BASE, "schedule.json")
STATE_LOCK = os.path.join(BASE, ".state.lock")
# One-shot "start this block at segment N" hint for the play-now-at-segment
# action (the /now per-segment ▶ button). The panel writes it just before the
# cutover; the player consumes+deletes it when it begins the block, so a later
# natural re-air of the same block starts from the top.
CUTOVER_FILE = os.path.join(BASE, ".block_cutover.json")


@contextlib.contextmanager
def _state_lock():
    """Cross-process mutex around block.json / block_queue.json
    read-modify-write. The panel (threaded HTTP handlers) and the player
    (a separate process) both mutate this state; without a lock an
    "add to playlist" append can clobber the player's pop, or a render can
    lose a concurrent title/segments save. flock is released on close.
    Do NOT nest the *_unlocked helpers under an already-held lock via the
    public wrappers — that would deadlock on a second exclusive flock."""
    fd = os.open(STATE_LOCK, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)

DEFAULT_STATION_CFG = {"kokoro": "http://192.168.1.74:8880", "voice": "am_michael", "speed": 1.0,
                       # keep the Icecast source fed during the air-time render gap so
                       # Cast/clients never underrun; a spoken espeak bumper while debugging
                       # (set false post-release to fall back to silence). See block_player.
                       "cutover_filler": True,
                       "cutover_filler_text": "Operator switching tracks, one moment.",
                       # station identity for time-check / station-ID tts segments.
                       "station_name": "WRIT-FM", "timezone": "America/New_York"}
DEFAULT_TTS_TTL_S = 1800
# How long a resolved live/music segment stays valid before render_block
# re-resolves it. Kept generous so a cutover/scrub within the airing hour
# reuses the built segments (near-instant) instead of re-resolving everything;
# only genuinely aged-out state (a newer bulletin, a changed library) rebuilds.
# A live bulletin URL is good for its hour; a music search result changes
# slowly. force=True (manual regenerate) and the natural first render of an
# unresolved block still rebuild fully. Per-segment override: params.resolved_ttl_s.
DEFAULT_LIVE_TTL_S = 3600
DEFAULT_MUSIC_TTL_S = 21600

# Block ids are always minted by new_block_id() as a timestamp (optionally
# "-N" on same-second collision). Validating the shape here — at the one
# place ids are turned into filesystem paths — stops a hostile/typo'd id
# from a URL segment (e.g. "..") from escaping BLOCKS_DIR; without this a
# DELETE /api/blocks/.. would rmtree all of BASE.
_BLOCK_ID_RE = re.compile(r"^\d{8}T\d{6}(-\d+)?$")


def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat()


def track_label(t):
    """'Artist — Title' (or just Title) for now-playing metadata and the UI."""
    a = (t.get("artist") or "").strip()
    n = (t.get("name") or "").strip()
    return ("%s — %s" % (a, n)) if a else (n or "Music")


def load_station_cfg():
    try:
        with open(STATION_CFG) as f:
            c = json.load(f)
        for k, v in DEFAULT_STATION_CFG.items():
            c.setdefault(k, v)
        return c
    except Exception:
        return dict(DEFAULT_STATION_CFG)


def block_dir(block_id):
    if not _BLOCK_ID_RE.match(block_id or ""):
        raise ValueError("invalid block id: %r" % (block_id,))
    return os.path.join(BLOCKS_DIR, block_id)


def new_block_id():
    bid = time.strftime("%Y%m%dT%H%M%S")
    path = block_dir(bid)
    if not os.path.exists(path):
        return bid
    i = 2
    while os.path.exists(block_dir(f"{bid}-{i}")):
        i += 1
    return f"{bid}-{i}"


def list_blocks():
    if not os.path.isdir(BLOCKS_DIR):
        return []
    out = []
    for bid in sorted(os.listdir(BLOCKS_DIR), reverse=True):
        try:
            b = load_block(bid)
        except Exception:
            continue
        est_duration = sum(s["params"].get("duration_s", 0) for s in b["segments"] if s["type"] != "tts")
        out.append({"id": b["id"], "title": b["title"], "created_at": b["created_at"],
                     "updated_at": b["updated_at"], "segment_count": len(b["segments"]),
                     "schedule": b["schedule"], "est_duration_s": est_duration,
                     "summary": _segment_summary(b["segments"])})
    return out


def _segment_summary(segments):
    """Short human breakdown for the block-list cards, e.g. 'weather · 2 music
    · recap' -- the ordered role/topic gist without the full segment dump."""
    parts = []
    for s in segments:
        p = s.get("params") or {}
        if s["type"] == "tts":
            parts.append(p.get("topic") or "tts")
        elif s["type"] == "music":
            parts.append(p.get("query") or ("%d picks" % len(p["track_ids"]) if p.get("track_ids") else "music"))
        elif s["type"] == "live":
            parts.append("news")
    return " · ".join(parts)


def load_block(block_id):
    with open(os.path.join(block_dir(block_id), "block.json")) as f:
        return json.load(f)


def _save_block_unlocked(block):
    d = block_dir(block["id"])
    os.makedirs(d, exist_ok=True)
    tmp = os.path.join(d, "block.json.tmp")
    with open(tmp, "w") as f:
        json.dump(block, f, indent=2)
    os.replace(tmp, os.path.join(d, "block.json"))
    write_markdown(block)


def save_block(block):
    with _state_lock():
        _save_block_unlocked(block)


def delete_block(block_id):
    d = block_dir(block_id)
    if os.path.isdir(d):
        shutil.rmtree(d)


def load_schedule():
    if not os.path.exists(SCHEDULE_FILE):
        return []
    with open(SCHEDULE_FILE) as f:
        return json.load(f).get("entries", [])


def save_schedule(entries):
    with _state_lock():
        tmp = SCHEDULE_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"entries": entries}, f, indent=2)
        os.replace(tmp, SCHEDULE_FILE)


def due_entries(entries, now_dt, last_fired):
    """Pure: which block_ids should be queued at now_dt. An entry fires once
    per matching minute (last_fired dedups, keyed by entry id) when enabled,
    its HH:MM matches, and today is in its days list (empty/missing = daily;
    weekday(): Mon=0..Sun=6). Separate from the upstream config/schedule.yaml
    show schedule -- that's the mac/ framework's which-AI-show-airs model, not
    these operator-built blocks."""
    stamp = now_dt.strftime("%Y-%m-%d %H:%M")
    hhmm = now_dt.strftime("%H:%M")
    fired = []
    for e in entries:
        if not e.get("enabled", True):
            continue
        if e.get("time") != hhmm:
            continue
        days = e.get("days")
        if days and now_dt.weekday() not in days:
            continue
        eid = e.get("id")
        if last_fired.get(eid) == stamp:
            continue
        last_fired[eid] = stamp
        if e.get("block_id"):
            fired.append(e["block_id"])
    return fired


def cleanup_blocks(max_age_days=14):
    """Remove program_blocks/ dirs older than max_age_days that aren't
    referenced by the live queue or the schedule. Runs from a systemd timer;
    without it, render artifacts (rendered TTS ogg, resolved playlists) grow
    unbounded at 24/7 cadence on a disk-tight box."""
    if not os.path.isdir(BLOCKS_DIR):
        return []
    keep = set(load_queue()) | {e.get("block_id") for e in load_schedule()}
    cutoff = time.time() - max_age_days * 86400
    removed = []
    for bid in os.listdir(BLOCKS_DIR):
        d = os.path.join(BLOCKS_DIR, bid)
        if not os.path.isdir(d) or bid in keep:
            continue
        manifest = os.path.join(d, "block.json")
        mtime = os.path.getmtime(manifest) if os.path.exists(manifest) else os.path.getmtime(d)
        if mtime < cutoff:
            shutil.rmtree(d)
            removed.append(bid)
    return removed


def create_block(title):
    bid = new_block_id()
    block = {"id": bid, "title": title or bid, "created_at": now_iso(), "updated_at": now_iso(),
              "segments": [], "schedule": {"state": "draft", "queued_at": None, "aired_at": None}}
    save_block(block)
    return block


def create_block_from_segments(title, segments, template=None, block_id=None):
    """Mint a block pre-populated with segments (from a template). block_id
    lets the day generator use a deterministic wall-clock id; template stamps
    {name, day?, hour} for the generator/UI to recognize generated blocks."""
    bid = block_id or new_block_id()
    now = now_iso()
    block = {"id": bid, "title": title or bid, "created_at": now, "updated_at": now,
             "segments": segments, "schedule": {"state": "draft", "queued_at": None, "aired_at": None}}
    if template:
        block["template"] = template
    save_block(block)
    return block


def write_markdown(block):
    lines = [f"# {block['title']}", "", f"_block {block['id']} · updated {block['updated_at']}_", ""]
    for i, seg in enumerate(block["segments"], 1):
        r = seg.get("resolved", {})
        lines.append(f"## {i}. {seg['type']} — {r.get('title', seg['params'].get('topic') or seg['params'].get('source_id') or seg['params'].get('query') or '(untitled)')}")
        lines.append(f"- status: {seg.get('status', 'unresolved')}")
        if seg["type"] == "live":
            lines.append(f"- source: {seg['params'].get('source_id')} · duration {seg['params'].get('duration_s')}s")
            if r.get("url"):
                lines.append(f"- url: {r['url']}")
        elif seg["type"] == "music":
            src = seg["params"].get("query") or (
                "%d hand-picked tracks" % len(seg["params"]["track_ids"])
                if seg["params"].get("track_ids") else "(shuffle all)")
            lines.append(f"- query: {src} · duration {seg['params'].get('duration_s')}s")
            if r.get("track_count"):
                lines.append(f"- tracks: {r['track_count']}")
        elif seg["type"] == "tts":
            lines.append(f"- topic: {seg['params'].get('topic')}")
            if r.get("text"):
                lines.append("")
                lines.append("> " + r["text"].replace("\n", "\n> "))
        if seg.get("error"):
            lines.append(f"- error: {seg['error']}")
        lines.append("")
    with open(os.path.join(block_dir(block["id"]), "block.md"), "w") as f:
        f.write("\n".join(lines))


def _probe_duration(path):
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=10, check=True)
        return round(float(out.stdout.strip()), 1)
    except Exception:
        return None


def build_tts_text(topic, params, context=None):
    if topic == "weather":
        return tts_content.build_weather_text(params.get("location", ""))
    if topic == "freeform":
        text = llm_backends.generate(params["llm_backend"], params["llm_model"], params["prompt"])
        return text, params["prompt"][:60]
    if topic == "recap":
        return tts_content.build_recap_text(params, context)
    if topic == "factoid":
        return tts_content.build_factoid_text(params, context)
    if topic == "time_check":
        return tts_content.build_time_check_text(params)
    if topic == "station_id":
        return tts_content.build_station_id_text(params)
    raise ValueError(f"unknown tts topic: {topic}")


def resolve_live_segment(seg, prior_source_ids=()):
    sid = seg["params"]["source_id"]
    if sid == "auto":
        # Pick a genuine short bulletin (podcast_latest) not already used
        # earlier in this block. NEVER fall back to full-channel "(live)"
        # relays like CNN -- those are endless and interruptive. If every
        # bulletin is already used, reuse one; only if there are no bulletins
        # at all do we fall back to the whole list.
        used = set(prior_source_ids)
        srcs = live_source.load_sources()
        # short bulletins only -- exclude long-form talk (category:"talk").
        bulletins = [s for s in srcs
                     if s.get("kind") == "podcast_latest" and s.get("category") != "talk"]
        pool = [s for s in bulletins if s["id"] not in used] or bulletins or srcs
        sid = pool[0]["id"]
    r = live_source.resolve_live(sid)
    src = live_source.get_source(sid) or {}
    seg["resolved"] = {"title": r["title"], "url": r["url"], "source_id": sid,
                       "source_name": src.get("name") or sid}
    seg["status"] = "ok"
    seg["resolved_at"] = now_iso()


def resolve_music_segment(seg, bdir):
    p = seg["params"]
    ids = p.get("track_ids")
    if ids:  # explicit hand-picked crate (from the music browser)
        tracks = jellyfin_client.tracks_by_ids(ids)
        r = {"ref": "picks:%d" % len(ids), "title": "%d hand-picked tracks" % len(tracks),
             "track_count": len(tracks), "tracks": tracks}
    else:
        query = p.get("query", "")
        r = jellyfin_client.resolve_music(query, limit=200)
        if not r["tracks"] and query.strip():
            # A query that matches nothing by name (e.g. a genre/mood we don't
            # tag as a track/playlist title, like "triphop") must NOT air 0s of
            # silence and collapse the whole block to idle. Fall back to a
            # library shuffle so a music slot always plays music; the title
            # records the miss so the operator sees it on /now and in the rundown.
            r = jellyfin_client.resolve_music("", limit=200)
            r["title"] = "%s — no match, shuffling" % query.strip()
    playlist_path = f"music_{seg['id']}.txt"
    with open(os.path.join(bdir, playlist_path), "w") as f:
        for t in r["tracks"]:
            f.write("file '%s'\n" % t["url"])
    # Per-track metadata lets the player push the real artist/title as each track
    # boundary passes and a recap name what played. For a QUERY set, keep only
    # the tracks that will air within the duration budget (the concat -t cuts the
    # rest). For an explicit CRATE, keep every pick and set the segment duration
    # to their total so the whole crate plays (the -t is a cap, not padding).
    if ids:  # keep every pick; the concat (no -t cap) plays the crate through
        meta = [{"name": t["name"], "artist": t.get("artist", ""),
                 "duration_s": t.get("duration_s", 0)} for t in r["tracks"]]
    else:
        budget = p.get("duration_s", 900)
        meta, acc = [], 0.0
        for t in r["tracks"]:
            meta.append({"name": t["name"], "artist": t.get("artist", ""),
                         "duration_s": t.get("duration_s", 0)})
            acc += t.get("duration_s", 0)
            if acc >= budget:
                break
    seg["resolved"] = {"ref": r["ref"], "title": r["title"], "track_count": r["track_count"],
                        "playlist_path": playlist_path, "tracks": meta,
                        "tracks_head": [track_label(t) for t in meta[:20]],
                        "duration_s": round(sum(m["duration_s"] for m in meta), 1)}
    seg["status"] = "ok"
    seg["resolved_at"] = now_iso()


def render_tts_segment(bdir, seg, cfg, context=None):
    # station identity flows in for time_check / station_id (per-segment
    # override still wins if the params carry their own).
    params = dict(seg["params"])
    params.setdefault("station_name", cfg.get("station_name", "WRIT-FM"))
    params.setdefault("timezone", cfg.get("timezone", "America/New_York"))
    text, title = build_tts_text(params["topic"], params, context)
    engine = seg["params"].get("engine", "kokoro")
    voice = seg["params"].get("voice") or cfg.get("voice", "am_michael")
    speed = seg["params"].get("speed") or cfg.get("speed", 1.0)
    wav_bytes = tts_engines.speech(engine, voice, speed, text, cfg, fmt="wav")

    wav_path = os.path.join(bdir, f"tts_{seg['id']}.wav")
    ogg_path = os.path.join(bdir, f"tts_{seg['id']}.ogg")
    try:
        with open(wav_path, "wb") as f:
            f.write(wav_bytes)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", wav_path,
                        "-c:a", "libvorbis", "-q:a", "4", ogg_path], check=True)
    finally:
        # remove the intermediate wav even if the ffmpeg convert raised, so a
        # failed render doesn't strand a large wav on every retry.
        if os.path.exists(wav_path):
            os.remove(wav_path)

    seg["resolved"] = {"title": title, "text": text, "audio_path": os.path.basename(ogg_path),
                        "duration_s": _probe_duration(ogg_path)}
    seg["status"] = "ok"
    seg["rendered_at"] = now_iso()


def _age_exceeds(stamp, ttl_s):
    """True if the ISO timestamp is missing/unparseable or older than ttl_s."""
    try:
        t = datetime.fromisoformat(stamp)
    except Exception:
        return True
    return (datetime.now(t.tzinfo) - t).total_seconds() > ttl_s


def is_stale(seg):
    if seg["type"] != "tts":
        return False
    if seg.get("status") != "ok":
        return True
    ttl = seg["params"].get("ttl_s", DEFAULT_TTS_TTL_S)
    return _age_exceeds(seg.get("rendered_at"), ttl)


def is_live_stale(seg):
    """A live segment needs re-resolving if it isn't resolved yet or its
    resolved URL has aged out (a newer bulletin may exist)."""
    r = seg.get("resolved") or {}
    if seg.get("status") != "ok" or not r.get("url"):
        return True
    if "source_name" not in r:
        return True  # resolved before the friendly source name existed
    ttl = seg["params"].get("resolved_ttl_s", DEFAULT_LIVE_TTL_S)
    return _age_exceeds(seg.get("resolved_at"), ttl)


def is_music_stale(seg, bdir):
    """A music segment needs re-resolving if it isn't resolved, its playlist
    file is gone, or the search result has aged out."""
    r = seg.get("resolved") or {}
    if seg.get("status") != "ok":
        return True
    pp = r.get("playlist_path")
    if not (pp and os.path.exists(os.path.join(bdir, pp))):
        return True
    if "tracks" not in r:
        return True  # resolved before per-track metadata existed -> re-resolve once
    ttl = seg["params"].get("resolved_ttl_s", DEFAULT_MUSIC_TTL_S)
    return _age_exceeds(seg.get("resolved_at"), ttl)


def render_block(block_id, force=False):
    block = load_block(block_id)
    cfg = load_station_cfg()
    bdir = block_dir(block_id)
    changed = False
    prior_sources = []
    # Whether any content-bearing upstream segment (live/music) actually
    # re-resolved this pass -- recap/factoid summarize what played, so they
    # only need rebuilding when their inputs changed (or aren't built yet).
    upstream_changed = False
    for i, seg in enumerate(block["segments"]):
        try:
            # Selective re-render: rebuild a segment ONLY when its own state is
            # invalidated (unresolved, asset missing, or aged out per its TTL),
            # so a cutover/scrub within the airing hour reuses already-built
            # segments and returns near-instantly. force=True (regenerate) and
            # config changes are picked up on the next rebuild / via force.
            if seg["type"] == "live":
                if force or is_live_stale(seg):
                    resolve_live_segment(seg, prior_sources)
                    changed = True
                    upstream_changed = True
            elif seg["type"] == "music":
                if force or is_music_stale(seg, bdir):
                    resolve_music_segment(seg, bdir)
                    changed = True
                    upstream_changed = True
            elif seg["type"] == "tts":
                topic = seg["params"].get("topic")
                if topic in ("recap", "factoid"):
                    # derived from upstream segments: rebuild only if something
                    # upstream changed this pass, or it isn't built yet.
                    if force or upstream_changed or seg.get("status") != "ok":
                        render_tts_segment(bdir, seg, cfg, {"segments": block["segments"], "index": i})
                        changed = True
                elif topic == "time_check":
                    # the spoken time changes every air -> always rebuild.
                    render_tts_segment(bdir, seg, cfg, {"segments": block["segments"], "index": i})
                    changed = True
                elif force or is_stale(seg):
                    render_tts_segment(bdir, seg, cfg, {"segments": block["segments"], "index": i})
                    changed = True
        except Exception as e:
            seg["status"] = "error"
            seg["error"] = str(e)
            changed = True
        if seg["type"] == "live":
            prior_sources.append((seg.get("resolved") or {}).get("source_id")
                                 or seg["params"].get("source_id"))
    if changed:
        # Re-read under lock and merge only the resolution fields back onto
        # the current on-disk block, so a title/segments edit made in the
        # panel *during* this (possibly slow, network-bound) render isn't
        # lost. The lock is held only for the fast merge+write, never during
        # the resolution I/O above.
        with _state_lock():
            fresh = load_block(block_id)
            resolved = {s["id"]: s for s in block["segments"]}
            for fs in fresh["segments"]:
                src = resolved.get(fs["id"])
                if src is None:
                    continue
                for k in ("resolved", "status", "rendered_at", "resolved_at", "error"):
                    if k in src:
                        fs[k] = src[k]
                if fs.get("status") == "ok":
                    fs.pop("error", None)  # a prior failure that this render cleared
            fresh["updated_at"] = now_iso()
            _save_block_unlocked(fresh)
        return fresh
    return block


def set_cutover(block_id, start_index=0):
    """Record a one-shot 'begin this block at segment N' hint for the player's
    next cutover (the /now per-segment ▶ button). Paired with queue_now(), so
    the player finds this block at the queue front and consumes the hint."""
    with _state_lock():
        tmp = CUTOVER_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"block_id": block_id, "start_index": int(start_index)}, f)
        os.replace(tmp, CUTOVER_FILE)


def take_cutover(block_id):
    """Consume the cutover hint iff it targets block_id; return its start
    segment index (0 if none / mismatched). Removing only on match leaves a
    hint for a not-yet-reached block intact."""
    with _state_lock():
        try:
            with open(CUTOVER_FILE) as f:
                c = json.load(f)
        except Exception:
            return 0
        if c.get("block_id") != block_id:
            return 0
        try:
            os.remove(CUTOVER_FILE)
        except OSError:
            pass
        return max(0, int(c.get("start_index", 0)))


def mark_scheduled(block_id, state):
    with _state_lock():
        block = load_block(block_id)
        block["schedule"]["state"] = state
        if state == "queued":
            block["schedule"]["queued_at"] = now_iso()
        elif state == "played":
            block["schedule"]["aired_at"] = now_iso()
        _save_block_unlocked(block)
        return block


def load_queue():
    # Pure read; writes are atomic (os.replace) so this is torn-read safe
    # without taking the lock. Read-modify-write callers below DO lock.
    if not os.path.exists(QUEUE_FILE):
        return []
    with open(QUEUE_FILE) as f:
        return json.load(f).get("queue", [])


def _save_queue_unlocked(queue):
    tmp = QUEUE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"queue": queue}, f)
    os.replace(tmp, QUEUE_FILE)


def save_queue(queue):
    with _state_lock():
        _save_queue_unlocked(queue)


def queue_now(block_id):
    save_queue([block_id])


def queue_append(block_id):
    with _state_lock():
        q = load_queue()
        q.append(block_id)
        _save_queue_unlocked(q)
        return q


def pop_front(expected_id=None):
    # expected_id guards the play-now cutover race: a player being torn down
    # (its queue already overwritten to the new block by schedule_block)
    # must not pop the newly-scheduled block off the front. It only removes
    # the block it actually played.
    with _state_lock():
        q = load_queue()
        if q and (expected_id is None or q[0] == expected_id):
            q.pop(0)
            _save_queue_unlocked(q)
        return q
    return q
