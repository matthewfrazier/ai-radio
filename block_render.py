#!/usr/bin/env python3
"""Programming-block CRUD + render orchestration.

A block is a directory under BLOCKS_DIR with a block.json manifest (source
of truth) and a derived block.md rundown. render_block() is the single
entry point that (re)resolves/(re)renders only what's missing or stale —
used by the whole-block Test/Preview action, the manual "regenerate"
action, and the schedule ("play now"/"queue") action alike, so there is one
render code path, not three.
"""
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


def save_block(block):
    d = block_dir(block["id"])
    os.makedirs(d, exist_ok=True)
    tmp = os.path.join(d, "block.json.tmp")
    with open(tmp, "w") as f:
        json.dump(block, f, indent=2)
    os.replace(tmp, os.path.join(d, "block.json"))
    write_markdown(block)


def delete_block(block_id):
    d = block_dir(block_id)
    if os.path.isdir(d):
        shutil.rmtree(d)


def create_block(title):
    bid = new_block_id()
    block = {"id": bid, "title": title or bid, "created_at": now_iso(), "updated_at": now_iso(),
              "segments": [], "schedule": {"state": "draft", "queued_at": None, "aired_at": None}}
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


def build_tts_text(topic, params):
    if topic == "weather":
        return tts_content.build_weather_text(params.get("location", ""))
    if topic == "freeform":
        text = llm_backends.generate(params["llm_backend"], params["llm_model"], params["prompt"])
        return text, params["prompt"][:60]
    raise ValueError(f"unknown tts topic: {topic}")


def resolve_live_segment(seg):
    r = live_source.resolve_live(seg["params"]["source_id"])
    seg["resolved"] = {"title": r["title"], "url": r["url"]}
    seg["status"] = "ok"
    seg["resolved_at"] = now_iso()


def resolve_music_segment(seg, bdir):
    r = jellyfin_client.resolve_music(seg["params"].get("query", ""), limit=200)
    playlist_path = f"music_{seg['id']}.txt"
    with open(os.path.join(bdir, playlist_path), "w") as f:
        for t in r["tracks"]:
            f.write("file '%s'\n" % t["url"])
    seg["resolved"] = {"ref": r["ref"], "title": r["title"], "track_count": r["track_count"],
                        "playlist_path": playlist_path}
    seg["status"] = "ok"
    seg["resolved_at"] = now_iso()


def render_tts_segment(bdir, seg, cfg):
    text, title = build_tts_text(seg["params"]["topic"], seg["params"])
    engine = seg["params"].get("engine", "kokoro")
    voice = seg["params"].get("voice") or cfg.get("voice", "am_michael")
    speed = seg["params"].get("speed") or cfg.get("speed", 1.0)
    wav_bytes = tts_engines.speech(engine, voice, speed, text, cfg, fmt="wav")

    wav_path = os.path.join(bdir, f"tts_{seg['id']}.wav")
    ogg_path = os.path.join(bdir, f"tts_{seg['id']}.ogg")
    with open(wav_path, "wb") as f:
        f.write(wav_bytes)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", wav_path,
                    "-c:a", "libvorbis", "-q:a", "4", ogg_path], check=True)
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
    for seg in block["segments"]:
        try:
            # live/music are always re-resolved -- cheap config-lookup/ICY-probe
            # or Jellyfin-list calls, no external cost to worry about like the
            # weather API, so there's no reason to cache them and every reason
            # not to: a stale cached URL survives config changes indefinitely
            # otherwise (e.g. a live-sources.json fix never takes effect on an
            # already-resolved segment without a manual force-render).
            if seg["type"] == "live":
                resolve_live_segment(seg)
                changed = True
            elif seg["type"] == "music":
                resolve_music_segment(seg, bdir)
                changed = True
            elif seg["type"] == "tts" and (force or is_stale(seg)):
                render_tts_segment(bdir, seg, cfg)
                changed = True
        except Exception as e:
            seg["status"] = "error"
            seg["error"] = str(e)
            changed = True
    if changed:
        block["updated_at"] = now_iso()
        save_block(block)
    return block


def mark_scheduled(block_id, state):
    block = load_block(block_id)
    block["schedule"]["state"] = state
    if state == "queued":
        block["schedule"]["queued_at"] = now_iso()
    elif state == "played":
        block["schedule"]["aired_at"] = now_iso()
    save_block(block)
    return block


def load_queue():
    if not os.path.exists(QUEUE_FILE):
        return []
    with open(QUEUE_FILE) as f:
        return json.load(f).get("queue", [])


def save_queue(queue):
    tmp = QUEUE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"queue": queue}, f)
    os.replace(tmp, QUEUE_FILE)


def queue_now(block_id):
    save_queue([block_id])


def queue_append(block_id):
    q = load_queue()
    q.append(block_id)
    save_queue(q)
    return q


def pop_front(expected_id=None):
    # expected_id guards the play-now cutover race: a player being torn down
    # (its queue already overwritten to the new block by schedule_block)
    # must not pop the newly-scheduled block off the front. It only removes
    # the block it actually played.
    q = load_queue()
    if q and (expected_id is None or q[0] == expected_id):
        q.pop(0)
        save_queue(q)
    return q
