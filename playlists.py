#!/usr/bin/env python3
"""Named station playlists for the /browse music page.

Source of truth is playlists.json on disk (stdlib, atomic writes) so the panel
stays dependency-free and saves are instant. A playlist can additionally be
pushed to Jellyfin (sync_jellyfin) so other Jellyfin apps see it; the Jellyfin
copy is a mirror, never the authority.
"""
import json
import os
import threading
import time
import uuid

import jellyfin_client

BASE = "/opt/writ-fm"
STORE = os.path.join(BASE, "playlists.json")

_LOCK = threading.Lock()


def _load(path=STORE):
    try:
        with open(path) as f:
            d = json.load(f)
        return d if isinstance(d.get("playlists"), list) else {"playlists": []}
    except Exception:
        return {"playlists": []}


def _save(d, path=STORE):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f, indent=1)
    os.replace(tmp, path)


def _find(d, pid):
    p = next((p for p in d["playlists"] if p["id"] == pid), None)
    if p is None:
        raise KeyError("no playlist: %s" % pid)
    return p


def list_playlists(path=STORE):
    return _load(path)["playlists"]


def get(pid, path=STORE):
    with _LOCK:
        return _find(_load(path), pid)


def create(title, track_ids=None, path=STORE):
    with _LOCK:
        d = _load(path)
        now = time.time()
        p = {"id": uuid.uuid4().hex[:12], "title": (title or "").strip() or "New playlist",
             "created_at": now, "updated_at": now,
             "track_ids": list(dict.fromkeys(track_ids or [])), "jellyfin_id": None}
        d["playlists"].insert(0, p)
        _save(d, path)
        return p


def rename(pid, title, path=STORE):
    with _LOCK:
        d = _load(path)
        p = _find(d, pid)
        p["title"] = (title or "").strip() or p["title"]
        p["updated_at"] = time.time()
        _save(d, path)
        return p


def delete(pid, path=STORE):
    with _LOCK:
        d = _load(path)
        _find(d, pid)  # raise if unknown
        d["playlists"] = [p for p in d["playlists"] if p["id"] != pid]
        _save(d, path)
        return {"ok": True}


def add_tracks(pid, track_ids, path=STORE):
    """Append tracks, skipping ids already in the playlist (queue-next semantics:
    clicking [+] twice never double-adds)."""
    with _LOCK:
        d = _load(path)
        p = _find(d, pid)
        have = set(p["track_ids"])
        p["track_ids"].extend(t for t in dict.fromkeys(track_ids or []) if t not in have)
        p["updated_at"] = time.time()
        _save(d, path)
        return p


def remove_track(pid, index, path=STORE):
    with _LOCK:
        d = _load(path)
        p = _find(d, pid)
        if 0 <= index < len(p["track_ids"]):
            p["track_ids"].pop(index)
            p["updated_at"] = time.time()
            _save(d, path)
        return p


def move_track(pid, index, to, path=STORE):
    with _LOCK:
        d = _load(path)
        p = _find(d, pid)
        ids = p["track_ids"]
        if 0 <= index < len(ids) and 0 <= to < len(ids) and index != to:
            ids.insert(to, ids.pop(index))
            p["updated_at"] = time.time()
            _save(d, path)
        return p


def sync_jellyfin(pid, path=STORE):
    """Mirror the playlist to Jellyfin: create it on first sync, else replace its
    items with ours (order included). Returns the playlist with jellyfin_id set."""
    with _LOCK:
        d = _load(path)
        p = _find(d, pid)
        base, tok, uid = jellyfin_client.auth()
        jid = p.get("jellyfin_id")
        if jid:
            try:
                jellyfin_client.clear_playlist(base, tok, uid, jid)
                jellyfin_client.add_playlist_items(base, tok, uid, jid, p["track_ids"])
            except Exception:
                jid = None  # deleted in Jellyfin out of band -> recreate below
        if not jid:
            jid = jellyfin_client.create_playlist(base, tok, uid, p["title"], p["track_ids"])
        p["jellyfin_id"] = jid
        p["synced_at"] = time.time()
        p["updated_at"] = time.time()
        _save(d, path)
        return p
