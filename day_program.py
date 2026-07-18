#!/usr/bin/env python3
"""24-hour day programming: generate a full day of standard hours + hourly
schedule entries, summarize a day, and prune past days. Blocks use
deterministic wall-clock ids (YYYYMMDDThh0000) so regeneration overwrites the
same directories idempotently and each schedule entry's block_id is
predictable. Queue mode (operator decision) -> no scheduler change; entries
just fire hourly and the block plays to completion.
"""
import re

import block_render
import hour_templates

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _block_id(date_str, hour):
    return "%sT%02d0000" % (date_str.replace("-", ""), hour)


def _entry_id(date_str, hour):
    return "gen-%s-%02d" % (date_str, hour)


def _est_duration_s(segments):
    # live/music carry duration_s; tts is short and variable -> nominal 40s.
    total = 0
    for s in segments:
        if s["type"] == "tts":
            total += 40
        else:
            total += s["params"].get("duration_s", 0)
    return total


def generate_day(date_str, template="standard_hour", opts=None, today=None, dry_run=False):
    """Build 24 standard-hour blocks + 24 hourly schedule entries for date_str.
    Idempotent: deterministic ids overwrite in place (never the currently-airing
    block). Replaces this day's `gen-<date>-*` schedule entries and, when
    `today` is given, prunes past days' gen entries so their blocks age out via
    the cleanup timer. dry_run returns the plan without writing."""
    if not DATE_RE.match(date_str):
        raise ValueError("bad date: %r" % (date_str,))
    builder = hour_templates.TEMPLATES.get(template)
    if not builder:
        raise ValueError("unknown template: %s" % template)
    opts = opts or {}
    airing = (block_render.load_queue() or [None])[0]

    blocks, entries, warnings = [], [], []
    for hour in range(24):
        bid = _block_id(date_str, hour)
        segments = builder(hour, opts)
        blocks.append(bid)
        entries.append({"id": _entry_id(date_str, hour), "block_id": bid,
                        "time": "%02d:00" % hour, "days": [], "enabled": True})
        if not dry_run:
            if bid == airing:
                warnings.append("skipped currently-airing block %s" % bid)
                continue
            block_render.create_block_from_segments(
                "%s %02d:00" % (date_str, hour), segments,
                template={"name": template, "day": date_str, "hour": hour},
                block_id=bid)

    if not dry_run:
        keep = []
        for e in block_render.load_schedule():
            eid = e.get("id", "")
            if eid.startswith("gen-%s-" % date_str):
                continue  # replaced below
            m = re.match(r"^gen-(\d{4}-\d{2}-\d{2})-\d{2}$", eid)
            if today and m and m.group(1) < today:
                continue  # prune past generated days -> their blocks age out
            keep.append(e)
        block_render.save_schedule(keep + entries)

    return {"date": date_str, "template": template, "blocks": blocks,
            "schedule_entries": entries, "warnings": warnings}


def day_summary(date_str):
    """Per-hour view of a generated day for the /day UI. Hours without a block
    are marked not-generated."""
    if not DATE_RE.match(date_str):
        raise ValueError("bad date: %r" % (date_str,))
    hours = []
    for hour in range(24):
        bid = _block_id(date_str, hour)
        row = {"hour": hour, "block_id": bid, "generated": False}
        try:
            b = block_render.load_block(bid)
        except FileNotFoundError:
            hours.append(row)
            continue
        by_role = {s.get("role"): s for s in b["segments"]}
        row.update({
            "generated": True,
            "title": b.get("title", bid),
            "state": b.get("schedule", {}).get("state", "draft"),
            "music": [by_role.get(r, {}).get("params", {}).get("query", "")
                      for r in ("music_1", "music_2")],
            "news": [s["params"].get("source_id") for s in b["segments"] if s["type"] == "live"],
            "weather_location": by_role.get("weather", {}).get("params", {}).get("location", ""),
            "est_duration_s": _est_duration_s(b["segments"]),
        })
        hours.append(row)
    return {"date": date_str, "hours": hours}


def patch_hour(date_str, hour, patch):
    """Apply an operator quick-edit to one generated hour, targeting segments
    by role so the operator never hand-builds segments. Recognized keys:
    music [q1,q2], weather_location, factoid_seed, recap (bool -> include
    factoid), voice (all tts). Returns the saved block."""
    bid = _block_id(date_str, int(hour))
    block = block_render.load_block(bid)
    by_role = {s.get("role"): s for s in block["segments"]}
    if "music" in patch:
        for role, q in zip(("music_1", "music_2"), patch["music"]):
            if role in by_role:
                by_role[role]["params"]["query"] = q
    if "weather_location" in patch and "weather" in by_role:
        by_role["weather"]["params"]["location"] = patch["weather_location"]
    if "factoid_seed" in patch and "recap_mid" in by_role:
        by_role["recap_mid"]["params"]["factoid_seed"] = patch["factoid_seed"]
    if "recap" in patch and "recap_mid" in by_role:
        by_role["recap_mid"]["params"]["include_factoid"] = bool(patch["recap"])
    if "voice" in patch:
        for s in block["segments"]:
            if s["type"] == "tts":
                s["params"]["voice"] = patch["voice"]
    block["updated_at"] = block_render.now_iso()
    block_render.save_block(block)
    return block


def bulk_edit(date_str, field, value, hours=None):
    """Apply one field to many generated hours (default all 24)."""
    target = list(range(24)) if hours is None else [int(h) for h in hours]
    changed = []
    for h in target:
        try:
            patch_hour(date_str, h, {field: value})
            changed.append(h)
        except FileNotFoundError:
            pass
    return {"date": date_str, "field": field, "changed": changed}


def delete_day(date_str):
    """Remove a generated day's blocks (except the airing one) and its schedule
    entries."""
    if not DATE_RE.match(date_str):
        raise ValueError("bad date: %r" % (date_str,))
    airing = (block_render.load_queue() or [None])[0]
    removed = []
    for hour in range(24):
        bid = _block_id(date_str, hour)
        if bid == airing:
            continue
        try:
            block_render.delete_block(bid)
            removed.append(bid)
        except Exception:
            pass
    keep = [e for e in block_render.load_schedule()
            if not e.get("id", "").startswith("gen-%s-" % date_str)]
    block_render.save_schedule(keep)
    return {"date": date_str, "removed": removed}
