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

DEFAULT_STATION_CFG = {"kokoro": "http://192.168.1.74:8880", "voice": "am_michael", "speed": 1.0}
DEFAULT_TTS_TTL_S = 1800

# Block ids are always minted by new_block_id() as a timestamp (optionally
# "-N" on same-second collision). Validating the shape here — at the one
# place ids are turned into filesystem paths — stops a hostile/typo'd id
# from a URL segment (e.g. "..") from escaping BLOCKS_DIR; without this a
# DELETE /api/blocks/.. would rmtree all of BASE.
_BLOCK_ID_RE = re.compile(r"^\d{8}T\d{6}(-\d+)?$")


def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat()


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
                     "schedule": b["schedule"], "est_duration_s": est_duration})
    return out


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
            lines.append(f"- query: {seg['params'].get('query') or '(shuffle all)'} · duration {seg['params'].get('duration_s')}s")
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
    raise ValueError(f"unknown tts topic: {topic}")


def resolve_live_segment(seg, prior_source_ids=()):
    sid = seg["params"]["source_id"]
    if sid == "auto":
        # pick a bulletin not already used earlier in this block; prefer real
        # bulletins (podcast_latest) over full-channel relays, then anything
        # unused, then fall back to the whole list.
        used = set(prior_source_ids)
        srcs = live_source.load_sources()
        pool = ([s for s in srcs if s["id"] not in used and s.get("kind") == "podcast_latest"]
                or [s for s in srcs if s["id"] not in used]
                or srcs)
        sid = pool[0]["id"]
    r = live_source.resolve_live(sid)
    seg["resolved"] = {"title": r["title"], "url": r["url"], "source_id": sid}
    seg["status"] = "ok"
    seg["resolved_at"] = now_iso()


def resolve_music_segment(seg, bdir):
    r = jellyfin_client.resolve_music(seg["params"].get("query", ""), limit=200)
    playlist_path = f"music_{seg['id']}.txt"
    with open(os.path.join(bdir, playlist_path), "w") as f:
        for t in r["tracks"]:
            f.write("file '%s'\n" % t["url"])
    seg["resolved"] = {"ref": r["ref"], "title": r["title"], "track_count": r["track_count"],
                        "playlist_path": playlist_path,
                        # head track names so a recap can name what played and
                        # the preview UI can label tracks (both otherwise lost).
                        "tracks_head": [t["name"] for t in r["tracks"][:20]]}
    seg["status"] = "ok"
    seg["resolved_at"] = now_iso()


def render_tts_segment(bdir, seg, cfg, context=None):
    text, title = build_tts_text(seg["params"]["topic"], seg["params"], context)
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


def is_stale(seg):
    if seg["type"] != "tts":
        return False
    if seg.get("status") != "ok":
        return True
    ttl = seg["params"].get("ttl_s", DEFAULT_TTS_TTL_S)
    try:
        rendered_at = datetime.fromisoformat(seg["rendered_at"])
    except Exception:
        return True
    return (datetime.now(rendered_at.tzinfo) - rendered_at).total_seconds() > ttl


def render_block(block_id, force=False):
    block = load_block(block_id)
    cfg = load_station_cfg()
    bdir = block_dir(block_id)
    changed = False
    prior_sources = []
    for i, seg in enumerate(block["segments"]):
        try:
            # live/music are always re-resolved -- cheap config-lookup/ICY-probe
            # or Jellyfin-list calls, no external cost to worry about like the
            # weather API, so there's no reason to cache them and every reason
            # not to: a stale cached URL survives config changes indefinitely
            # otherwise (e.g. a live-sources.json fix never takes effect on an
            # already-resolved segment without a manual force-render).
            if seg["type"] == "live":
                resolve_live_segment(seg, prior_sources)
                changed = True
            elif seg["type"] == "music":
                resolve_music_segment(seg, bdir)
                changed = True
            elif seg["type"] == "tts":
                topic = seg["params"].get("topic")
                # recap/factoid depend on what earlier segments resolved to in
                # THIS pass, so they must re-render every air (ttl_s:0 already
                # makes is_stale True; the explicit check documents intent).
                if force or is_stale(seg) or topic in ("recap", "factoid"):
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
