#!/usr/bin/env python3
"""Panel-driven playlist casting: play a station playlist on a Chromecast by
casting one track at a time and advancing when the receiver finishes.

The receiver only ever sees a single BUFFERED media URL (the default receiver
has no reliable cross-model queue support), so the panel is the sequencer: a
small thread sleeps through most of the track (we know duration_s), then polls
the receiver until it reports FINISHED and casts the next track. If something
else takes the device over (a human casts YouTube), the session bows out.

cast_fn/sleep_fn/time_fn are injectable so tests can drive a whole session
without a device or real time.
"""
import threading

POLL_EARLY_S = 8      # start polling this long before the track should end
POLL_INTERVAL_S = 3
MAX_CAST_ERRORS = 2   # consecutive start failures before giving up


class PlaylistCaster:
    def __init__(self, cast_fn, sleep_fn, time_fn, log_fn=lambda m: None):
        self._cast = cast_fn
        self._sleep = sleep_fn
        self._time = time_fn
        self._log = log_fn
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._state = None  # dict while a session runs / after it ends

    def status(self):
        with self._lock:
            return dict(self._state) if self._state else None

    def start(self, playlist_id, title, tracks, uuid, device, budget=12):
        """tracks: [{id,name,artist,duration_s,url}]; device: (host,port,model,name)."""
        self.stop(quiet=True)
        self._stop = threading.Event()
        with self._lock:
            self._state = {"playlist_id": playlist_id, "title": title, "uuid": uuid,
                           "device": device[3] or uuid, "index": 0, "count": len(tracks),
                           "track": None, "state": "starting"}
        self._thread = threading.Thread(
            target=self._run, args=(tracks, uuid, device, budget), daemon=True)
        self._thread.start()
        return self.status()

    def stop(self, quiet=False):
        """End the session; stop the receiver too unless it was taken over."""
        self._stop.set()
        t = self._thread
        if t and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=10)
        with self._lock:
            st, self._state = self._state, None
        if st and st.get("state") not in ("finished", "taken_over") and not quiet:
            try:
                self._cast("stop", st["uuid"])
            except Exception:
                pass
        return st

    def _set(self, **kw):
        with self._lock:
            if self._state is not None:
                self._state.update(kw)

    def _run(self, tracks, uuid, device, budget):
        host, port, model, name = device
        errors = 0
        for idx, tr in enumerate(tracks):
            if self._stop.is_set():
                return
            label = "%s — %s" % (tr.get("artist") or "?", tr.get("name") or tr["id"])
            r = self._cast("start", uuid, tr["url"], "audio/mpeg",
                           host, port, model, name, str(budget), "BUFFERED", label)
            if not isinstance(r, dict) or r.get("state") not in ("PLAYING", "BUFFERING"):
                errors += 1
                self._log("playlist cast: start failed on %s (%s)" % (label, (r or {}).get("hint") or (r or {}).get("error") or "?"))
                if errors >= MAX_CAST_ERRORS:
                    self._set(state="failed", error=(r or {}).get("hint") or "cast failed")
                    return
                continue  # skip the bad track, try the next
            errors = 0
            self._set(index=idx, track={"id": tr["id"], "name": tr.get("name"),
                                        "artist": tr.get("artist"),
                                        "duration_s": tr.get("duration_s")},
                      state="playing")
            self._log("playlist cast: %d/%d %s -> %s" % (idx + 1, len(tracks), label, name or uuid))
            if not self._wait_track_end(uuid, host, port, tr):
                return  # stopped or taken over mid-track
        self._set(state="finished", track=None)
        self._log("playlist cast: finished")

    def _wait_track_end(self, uuid, host, port, tr):
        """True when the receiver finished this track; False on stop/takeover."""
        dur = float(tr.get("duration_s") or 0)
        started = self._time()
        # sleep through the body of the track cheaply, then poll the tail
        quiet_until = started + max(dur - POLL_EARLY_S, 0)
        hard_cap = started + max(dur * 2, dur + 300, 60)
        while not self._stop.is_set():
            now = self._time()
            if now >= hard_cap:
                return True  # receiver never reported FINISHED -- move on anyway
            if now < quiet_until:
                self._sleep(min(2, quiet_until - now))
                continue
            st = self._cast("status", uuid, host, str(port))
            state = (st or {}).get("state")
            if state in ("PLAYING", "BUFFERING"):
                if (st.get("content_id") or "") not in ("", tr["url"]):
                    self._set(state="taken_over")
                    self._log("playlist cast: device taken over, ending session")
                    return False
            elif state == "PAUSED":
                hard_cap = self._time() + max(dur, 300)  # human paused: keep waiting
            else:
                return True  # IDLE/UNKNOWN/error after the tail -> track is done
            self._sleep(POLL_INTERVAL_S)
        return False
