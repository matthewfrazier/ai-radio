"""Minimal integration tests for the ai-radio programming-blocks overlay.

Covers the wiring between our own modules (block CRUD round-tripping through
real JSON files, HTTP route parsing, config parsing, pure logic) without
requiring any live external service (Jellyfin, Kokoro, OpenWeatherMap,
Ollama/Claude) or credentials -- those are exercised manually via curl/
Playwright against the live station, not in CI. Scoped to the overlay only
(root-level *.py), not the upstream mac/ framework, which has its own heavy
ML dependency stack unrelated to this feature.
"""
import json
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import block_presets  # noqa: E402
import block_render  # noqa: E402
import overlay  # noqa: E402
import day_program  # noqa: E402
import hour_templates  # noqa: E402
import jellyfin_client  # noqa: E402
import live_source  # noqa: E402
import llm_backends  # noqa: E402
import music_browser  # noqa: E402
import panel  # noqa: E402
import tts_content  # noqa: E402
import tts_engines  # noqa: E402


class ImportSmokeTests(unittest.TestCase):
    """All overlay modules should import cleanly with zero side effects and
    zero third-party dependencies (stdlib only, by design)."""

    def test_all_overlay_modules_import(self):
        import block_player  # noqa: F401
        import blocks_page  # noqa: F401
        import jf_source  # noqa: F401


class BlockCrudTests(unittest.TestCase):
    """block_render's block lifecycle round-trips through real files on
    disk, redirected to a temp dir so tests never touch /opt/writ-fm."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._patcher = patch.object(block_render, "BLOCKS_DIR", self._tmpdir.name)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        self._tmpdir.cleanup()

    def test_create_save_load_round_trip(self):
        block = block_render.create_block("Test Hour")
        self.assertEqual(block["title"], "Test Hour")
        self.assertEqual(block["segments"], [])
        self.assertEqual(block["schedule"]["state"], "draft")

        block["segments"] = [{"id": "seg-0", "type": "music", "params": {"query": "", "duration_s": 900}}]
        block_render.save_block(block)

        loaded = block_render.load_block(block["id"])
        self.assertEqual(loaded["segments"][0]["type"], "music")

        listed = block_render.list_blocks()
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["id"], block["id"])

        md_path = os.path.join(block_render.block_dir(block["id"]), "block.md")
        self.assertTrue(os.path.exists(md_path))
        with open(md_path) as f:
            self.assertIn("Test Hour", f.read())

    def test_delete_removes_directory(self):
        block = block_render.create_block("Throwaway")
        d = block_render.block_dir(block["id"])
        self.assertTrue(os.path.isdir(d))

        block_render.delete_block(block["id"])
        self.assertFalse(os.path.isdir(d))
        self.assertEqual(block_render.list_blocks(), [])

    def test_delete_nonexistent_block_is_a_noop(self):
        block_render.delete_block("20200101T000000")  # valid shape, absent -> no raise

    def test_new_block_id_avoids_collision(self):
        first = block_render.new_block_id()
        os.makedirs(block_render.block_dir(first))
        second = block_render.new_block_id()
        self.assertNotEqual(first, second)


class BlockIdValidationTests(unittest.TestCase):
    """block_dir() is the single chokepoint turning an id into a filesystem
    path; it must reject anything that isn't a minted block id so a URL
    segment like ".." can't escape BLOCKS_DIR (a DELETE would rmtree BASE)."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._patcher = patch.object(block_render, "BLOCKS_DIR", self._tmpdir.name)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        self._tmpdir.cleanup()

    def test_accepts_minted_ids(self):
        self.assertTrue(block_render.block_dir("20260717T052001").endswith("20260717T052001"))
        self.assertTrue(block_render.block_dir("20260717T052001-2").endswith("20260717T052001-2"))

    def test_rejects_traversal_and_junk(self):
        for bad in ["..", "../evil", "foo/bar", "", "/etc", ".", "20260717T052001/..",
                    "20260717T052001; rm -rf", "%2e%2e"]:
            with self.assertRaises(ValueError, msg="should reject %r" % bad):
                block_render.block_dir(bad)

    def test_delete_block_rejects_traversal_without_touching_fs(self):
        # a marker file one level up from BLOCKS_DIR must survive a
        # delete_block("..") attempt (which would otherwise resolve to it).
        parent = os.path.dirname(self._tmpdir.name)
        marker = os.path.join(parent, "MARKER_KEEP")
        with open(marker, "w") as f:
            f.write("keep")
        try:
            with self.assertRaises(ValueError):
                block_render.delete_block("..")
            self.assertTrue(os.path.exists(marker))
        finally:
            os.remove(marker)


class QueuePopTests(unittest.TestCase):
    """pop_front(expected_id) is the root-cause fix for the play-now cutover
    race: a torn-down player must not pop a block it didn't play."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._patcher = patch.object(block_render, "QUEUE_FILE",
                                     os.path.join(self._tmpdir.name, "block_queue.json"))
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        self._tmpdir.cleanup()

    def test_pop_matching_front_removes_it(self):
        block_render.save_queue(["a", "b"])
        block_render.pop_front("a")
        self.assertEqual(block_render.load_queue(), ["b"])

    def test_pop_non_matching_front_is_a_noop(self):
        # the play-now race: queue was overwritten to [new] before the old
        # player (which played [old]) tears down and calls pop_front("old").
        block_render.save_queue(["new_block"])
        block_render.pop_front("old_block")
        self.assertEqual(block_render.load_queue(), ["new_block"])

    def test_pop_without_expected_id_still_pops(self):
        block_render.save_queue(["a", "b"])
        block_render.pop_front()
        self.assertEqual(block_render.load_queue(), ["b"])

    def test_pop_empty_queue_is_a_noop(self):
        block_render.save_queue([])
        block_render.pop_front("anything")
        self.assertEqual(block_render.load_queue(), [])


class CutoverHintTests(unittest.TestCase):
    """The one-shot 'start this block at segment N' hint behind the /now
    per-segment ▶ play button (play-now-at-segment / scrub)."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        base = self._tmpdir.name
        self._patchers = [
            patch.object(block_render, "CUTOVER_FILE", os.path.join(base, ".cutover.json")),
            patch.object(block_render, "STATE_LOCK", os.path.join(base, ".state.lock")),
        ]
        for p in self._patchers:
            p.start()

    def tearDown(self):
        for p in self._patchers:
            p.stop()
        self._tmpdir.cleanup()

    def test_take_matching_hint_returns_index_and_consumes(self):
        block_render.set_cutover("blockA", 3)
        self.assertEqual(block_render.take_cutover("blockA"), 3)
        # one-shot: a second read (e.g. a later natural re-air) starts at 0
        self.assertEqual(block_render.take_cutover("blockA"), 0)

    def test_take_mismatched_hint_leaves_it_intact(self):
        block_render.set_cutover("blockB", 5)
        self.assertEqual(block_render.take_cutover("blockA"), 0)
        # the hint for blockB survives an unrelated block airing first
        self.assertEqual(block_render.take_cutover("blockB"), 5)

    def test_take_without_hint_is_zero(self):
        self.assertEqual(block_render.take_cutover("blockA"), 0)


class RenderMergeTests(unittest.TestCase):
    """render_block resolves outside the lock, then merges only resolution
    fields back onto the *current* on-disk block, so a title/segments edit
    made during a slow render isn't lost (the block.json write race)."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._p1 = patch.object(block_render, "BLOCKS_DIR", self._tmpdir.name)
        self._p2 = patch.object(block_render, "STATE_LOCK",
                                os.path.join(self._tmpdir.name, ".state.lock"))
        self._p1.start()
        self._p2.start()

    def tearDown(self):
        self._p2.stop()
        self._p1.stop()
        self._tmpdir.cleanup()

    def test_concurrent_title_edit_survives_render(self):
        bid = "20260101T000000"
        seg = {"id": "seg-0", "type": "live", "params": {"source_id": "npr", "duration_s": 10}}
        loaded = {"id": bid, "title": "old", "created_at": "t", "updated_at": "t",
                  "segments": [seg], "schedule": {"state": "draft", "queued_at": None, "aired_at": None}}
        # what's on disk when render re-reads under the lock: title was edited
        fresh = {"id": bid, "title": "edited mid-render", "created_at": "t", "updated_at": "t",
                 "segments": [{"id": "seg-0", "type": "live",
                               "params": {"source_id": "npr", "duration_s": 10}}],
                 "schedule": {"state": "draft", "queued_at": None, "aired_at": None}}
        loads = [loaded, fresh]

        def fake_load(_bid):
            return loads.pop(0)

        def fake_resolve(s, prior_source_ids=()):
            s["resolved"] = {"title": "NPR", "url": "http://x/newscast.mp3"}
            s["status"] = "ok"
            s["resolved_at"] = "t"

        with patch.object(block_render, "load_block", side_effect=fake_load), \
             patch.object(block_render, "resolve_live_segment", side_effect=fake_resolve):
            result = block_render.render_block(bid)

        self.assertEqual(result["title"], "edited mid-render")       # concurrent edit preserved
        self.assertEqual(result["segments"][0]["status"], "ok")      # resolution merged in
        self.assertEqual(result["segments"][0]["resolved"]["url"], "http://x/newscast.mp3")


class SelectiveRenderTests(unittest.TestCase):
    """render_block rebuilds ONLY invalidated segments, so a cutover/scrub
    within the airing hour reuses already-built live/music/recap and returns
    near-instantly instead of re-resolving and re-rendering the whole block."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._patches = [
            patch.object(block_render, "BLOCKS_DIR", self._tmp.name),
            patch.object(block_render, "STATE_LOCK", os.path.join(self._tmp.name, ".lock")),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in reversed(self._patches):
            p.stop()
        self._tmp.cleanup()

    def _fresh_block(self, bid="20260101T000000"):
        now = block_render.now_iso()
        bdir = block_render.block_dir(bid)
        os.makedirs(bdir, exist_ok=True)
        with open(os.path.join(bdir, "music_m1.txt"), "w") as f:
            f.write("file 'x'\n")  # is_music_stale requires the playlist to exist
        segs = [
            {"id": "w", "type": "tts", "params": {"topic": "weather", "location": "1", "ttl_s": 1800},
             "status": "ok", "rendered_at": now, "resolved": {"text": "w"}},
            {"id": "n1", "type": "live", "params": {"source_id": "npr", "duration_s": 300},
             "status": "ok", "resolved_at": now,
             "resolved": {"url": "http://x", "source_id": "npr", "title": "NPR", "source_name": "NPR Newscast"}},
            {"id": "m1", "type": "music", "params": {"query": "jazz", "duration_s": 600},
             "status": "ok", "resolved_at": now,
             "resolved": {"playlist_path": "music_m1.txt", "title": "jazz", "track_count": 3,
                          "tracks": [{"name": "T", "artist": "A", "duration_s": 120}], "tracks_head": []}},
            {"id": "r", "type": "tts", "params": {"topic": "recap", "ttl_s": 0},
             "status": "ok", "rendered_at": now, "resolved": {"text": "r"}},
        ]
        block = {"id": bid, "title": "t", "created_at": now, "updated_at": now,
                 "segments": segs, "schedule": {"state": "draft", "queued_at": None, "aired_at": None}}
        block_render.save_block(block)
        return bid

    def _run(self, bid, **kw):
        with patch.object(block_render, "resolve_live_segment") as rl, \
             patch.object(block_render, "resolve_music_segment") as rm, \
             patch.object(block_render, "render_tts_segment") as rt:
            block_render.render_block(bid, **kw)
        return rl, rm, rt

    def test_fresh_block_rebuilds_nothing(self):
        rl, rm, rt = self._run(self._fresh_block())
        rl.assert_not_called()
        rm.assert_not_called()
        rt.assert_not_called()

    def test_aged_live_reresolves_and_rebuilds_only_recap(self):
        bid = self._fresh_block()
        b = block_render.load_block(bid)
        b["segments"][1]["resolved_at"] = "2000-01-01T00:00:00+00:00"  # age the live seg out
        block_render.save_block(b)
        rl, rm, rt = self._run(bid)
        rl.assert_called_once()                       # stale live re-resolved
        rm.assert_not_called()                        # fresh music reused
        rt.assert_called_once()                       # recap rebuilt (upstream changed)
        self.assertEqual(rt.call_args[0][1]["id"], "r")  # the recap, not the fresh weather

    def test_force_rebuilds_everything(self):
        rl, rm, rt = self._run(self._fresh_block(), force=True)
        rl.assert_called_once()
        rm.assert_called_once()
        self.assertEqual(rt.call_count, 2)            # weather + recap


class BlockPresetsTests(unittest.TestCase):
    """The three /now construction presets build the expected segment shapes."""

    def test_menu_ids(self):
        self.assertEqual({p["id"] for p in block_presets.preset_menu()},
                         {"news_talk", "brief_music", "all_music"})

    def test_news_talk_no_music_voice_propagates(self):
        segs = block_presets.build_preset("news_talk", {"voice": "am_x"})
        self.assertFalse(any(s["type"] == "music" for s in segs))
        self.assertTrue(any(s["type"] == "live" for s in segs))
        self.assertTrue(all(s["params"]["voice"] == "am_x" for s in segs if s["type"] == "tts"))

    def test_brief_music_two_25min_sets(self):
        segs = block_presets.build_preset("brief_music", {"genre_1": "jazz", "genre_2": "soul"})
        music = [s for s in segs if s["type"] == "music"]
        self.assertEqual([s["params"]["duration_s"] for s in music], [1500, 1500])
        self.assertEqual([s["params"]["query"] for s in music], ["jazz", "soul"])

    def test_all_music_weather_every_half_hour(self):
        segs = block_presets.build_preset("all_music", {"genre_1": "ambient"})
        weathers = [s for s in segs if s["params"].get("topic") == "weather"]
        self.assertEqual(len(weathers), 2)
        self.assertTrue(all(s["params"]["duration_s"] == 1800 for s in segs if s["type"] == "music"))

    def test_unknown_preset_raises(self):
        with self.assertRaises(ValueError):
            block_presets.build_preset("nope", {})


class OverlayTests(unittest.TestCase):
    """The music-DNA overlay: derived axes + AcousticBrainz/Essentia high-level
    model mapping + provenance-aware writes."""

    HL = {
        "mood_happy": {"all": {"happy": 0.8, "not_happy": 0.2}},
        "mood_sad": {"all": {"sad": 0.2, "not_sad": 0.8}},
        "mood_aggressive": {"all": {"aggressive": 0.6, "not_aggressive": 0.4}},
        "mood_party": {"all": {"party": 0.7, "not_party": 0.3}},
        "mood_relaxed": {"all": {"relaxed": 0.3, "not_relaxed": 0.7}},
        "danceability": {"all": {"danceable": 0.65, "not_danceable": 0.35}},
        "mood_acoustic": {"all": {"acoustic": 0.1, "not_acoustic": 0.9}},
        "voice_instrumental": {"all": {"instrumental": 0.05, "voice": 0.95}},
    }

    def test_derived(self):
        self.assertEqual(overlay.era_from_year(1994), "1990s")
        self.assertIsNone(overlay.era_from_year(None))
        self.assertEqual([overlay.tempo_band(b) for b in (80, 100, 120, 140)],
                         ["slow", "mid", "up", "fast"])

    def test_axes_from_features(self):
        a = overlay.axes_from_features(self.HL, bpm=122)
        self.assertEqual(a["valence"], 0.8)                     # from mood_happy
        self.assertAlmostEqual(a["energy"], round((0.6 + 0.7 + 0.7) / 3, 3))
        self.assertEqual(a["danceability"], 0.65)
        self.assertEqual(a["acousticness"], 0.1)
        self.assertEqual(a["instrumental"], 0.05)
        self.assertEqual(a["tempo_bpm"], 122.0)
        self.assertEqual(a["tempo_band"], "up")

    def test_axes_robust_to_missing_models(self):
        self.assertEqual(overlay.axes_from_features({}, bpm=None), {})

    def test_set_axes_respects_higher_confidence(self):
        ov = {"tracks": {}}
        overlay.set_axes(ov, "x", {"energy": 0.9}, "essentia", 0.9)
        overlay.set_axes(ov, "x", {"energy": 0.1}, "acousticbrainz", 0.8)  # lower conf, ignored
        self.assertEqual(ov["tracks"]["x"]["energy"], 0.9)
        self.assertEqual(ov["tracks"]["x"]["provenance"]["energy"]["src"], "essentia")

    def test_ingest_essentia(self):
        tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump({"jid1": {"highlevel": self.HL, "rhythm": {"bpm": 128}}}, tmp)
        tmp.close()
        self.addCleanup(os.unlink, tmp.name)
        ov = {"tracks": {}}
        n = overlay.ingest_essentia(tmp.name, ov)
        self.assertEqual(n, 1)
        self.assertEqual(ov["tracks"]["jid1"]["tempo_bpm"], 128.0)
        self.assertEqual(ov["tracks"]["jid1"]["provenance"]["energy"]["src"], "essentia")

    def test_live_detection_strong_signals_only(self):
        live = ["Comfortably Numb - Live", "Such Great Heights (Live at Leeds)",
                "MTV Unplugged", "Song [Live]", "Set The Controls (Live in Boston)"]
        studio = ["Live Wire", "Live and Let Die", "Live Forever", "Alive",
                  "Living on a Prayer", "Livewire"]
        for name in live:
            self.assertTrue(overlay.is_live({"name": name}), "should be live: %s" % name)
        for name in studio:
            self.assertFalse(overlay.is_live({"name": name}), "should be studio: %s" % name)
        # album-level and tag signals also count
        self.assertTrue(overlay.is_live({"name": "Track 3", "album": "At The BBC"}))
        self.assertTrue(overlay.is_live({"name": "x", "tags": ["live"]}))

    def test_enrich_live_flags_and_defaults_studio(self):
        snap = {"tracks": [{"id": "a", "name": "Song (Live at Wembley)"},
                           {"id": "b", "name": "Live Wire"}]}
        ov = {"tracks": {}}
        n = overlay.enrich_live(snap, ov)
        self.assertEqual(n, 1)
        self.assertTrue(ov["tracks"]["a"]["live"])
        self.assertEqual(ov["tracks"]["a"]["provenance"]["live"]["src"], "meta:title")
        self.assertNotIn("b", ov["tracks"])  # studio default -> no entry/flag


class MusicMetadataTests(unittest.TestCase):
    """Per-track artist/title metadata captured at resolve time so the player
    can push the real now-playing track as each boundary passes."""

    def test_track_label(self):
        self.assertEqual(block_render.track_label({"artist": "Air", "name": "Alone"}), "Air — Alone")
        self.assertEqual(block_render.track_label({"artist": "", "name": "Solo"}), "Solo")
        self.assertEqual(block_render.track_label({}), "Music")

    def test_resolve_music_captures_per_track_meta_up_to_budget(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        seg = {"id": "m1", "type": "music", "params": {"query": "jazz", "duration_s": 300}}
        fake = {"ref": "search:jazz", "title": "Search: jazz", "track_count": 5,
                "tracks": [{"id": str(n), "name": "T%d" % n, "artist": "A%d" % n,
                            "duration_s": 120, "url": "http://x/%d" % n} for n in range(5)]}
        with patch.object(block_render.jellyfin_client, "resolve_music", return_value=fake):
            block_render.resolve_music_segment(seg, tmp.name)
        r = seg["resolved"]
        self.assertEqual(len(r["tracks"]), 3)  # 120s tracks, 300s budget -> 3 cover it
        self.assertEqual(r["tracks"][0], {"name": "T0", "artist": "A0", "duration_s": 120})
        self.assertEqual(r["tracks_head"][0], "A0 — T0")
        self.assertEqual(seg["status"], "ok")

    def test_resolve_music_segment_explicit_track_ids(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        seg = {"id": "m1", "type": "music", "params": {"track_ids": ["a", "b"]}}
        fake = [{"id": "a", "name": "TA", "artist": "AA", "duration_s": 100, "url": "http://x/a"},
                {"id": "b", "name": "TB", "artist": "AB", "duration_s": 140, "url": "http://x/b"}]
        with patch.object(block_render.jellyfin_client, "tracks_by_ids", return_value=fake):
            block_render.resolve_music_segment(seg, tmp.name)
        r = seg["resolved"]
        self.assertEqual(r["track_count"], 2)
        self.assertEqual(len(r["tracks"]), 2)          # every pick kept
        self.assertEqual(r["duration_s"], 240)         # total, for est/display
        self.assertEqual(r["tracks_head"][0], "AA — TA")
        self.assertEqual(seg["status"], "ok")
        with open(os.path.join(tmp.name, r["playlist_path"])) as f:
            body = f.read()
        self.assertIn("http://x/a", body)
        self.assertIn("http://x/b", body)
        # a crate plays its finite playlist to the end -- no -t cap; a query set caps.
        import block_player
        self.assertNotIn("-t", block_player.segment_cmd(seg, tmp.name))
        qseg = {"id": "m2", "type": "music", "params": {"query": "jazz", "duration_s": 300},
                "resolved": {"playlist_path": "music_m2.txt"}}
        self.assertIn("-t", block_player.segment_cmd(qseg, tmp.name))

    def test_music_query_no_match_falls_back_to_shuffle(self):
        # A query that matches nothing (e.g. "triphop") must NOT resolve to a
        # 0-track segment that airs silence and collapses the block to idle --
        # it falls back to a library shuffle so the slot always plays music.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        seg = {"id": "m1", "type": "music", "params": {"query": "triphop", "duration_s": 600}}
        shuffle = {"ref": "library:x", "title": "Music Library (shuffle)", "track_count": 2,
                   "tracks": [{"id": "a", "name": "TA", "artist": "AA", "duration_s": 200, "url": "http://x/a"},
                              {"id": "b", "name": "TB", "artist": "AB", "duration_s": 200, "url": "http://x/b"}]}
        empty = {"ref": "search:triphop", "title": "Search: triphop", "track_count": 0, "tracks": []}

        def fake_resolve(query, limit=200):
            return empty if query.strip() else shuffle

        with patch.object(block_render.jellyfin_client, "resolve_music", side_effect=fake_resolve):
            block_render.resolve_music_segment(seg, tmp.name)
        r = seg["resolved"]
        self.assertEqual(seg["status"], "ok")
        self.assertGreater(r["track_count"], 0)               # never an empty music slot
        self.assertIn("no match", r["title"])                 # the miss is surfaced
        self.assertIn("triphop", r["title"])

    def test_music_query_with_matches_is_not_overridden(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        seg = {"id": "m1", "type": "music", "params": {"query": "jazz", "duration_s": 600}}
        hit = {"ref": "search:jazz", "title": "Search: jazz", "track_count": 1,
               "tracks": [{"id": "a", "name": "TA", "artist": "AA", "duration_s": 200, "url": "http://x/a"}]}
        with patch.object(block_render.jellyfin_client, "resolve_music", return_value=hit) as m:
            block_render.resolve_music_segment(seg, tmp.name)
        self.assertEqual(m.call_count, 1)                      # no fallback re-query
        self.assertEqual(seg["resolved"]["title"], "Search: jazz")


class NowPlayingStateTests(unittest.TestCase):
    """The /now card must follow the CURRENT track inside a music segment, not
    the frozen resolve-time segment label (the 'Coil by Toad the Wet Sprocket'
    bug). track_state mirrors the airing track into player_state; now_state
    passes those fields through to /now."""

    def test_track_state_merges_current_track(self):
        import block_player
        base = {"phase": "airing", "block_id": "b1", "segment_index": 2, "segment_type": "music",
                "segment_title": "Playlist: 00. Toad The Wet Sprocket - Coil",
                "segment_started_at": "SEG-START"}
        tracks = [{"artist": "Air", "name": "Alone"}, {"artist": "Boards", "name": "Roygbiv"}]
        s0 = block_player.track_state(base, tracks, 0)
        self.assertEqual(s0["track_index"], 0)
        self.assertEqual(s0["track_count"], 2)
        self.assertEqual(s0["track_title"], "Air — Alone")
        self.assertEqual(s0["on_air"], "Air — Alone")            # the single audible label
        self.assertEqual(s0["phase"], "airing")
        self.assertEqual(s0["segment_started_at"], "SEG-START")  # segment anchor preserved
        self.assertNotEqual(s0.get("started_at"), "SEG-START")   # re-anchored to THIS track
        self.assertEqual(s0["block_id"], "b1")
        s1 = block_player.track_state(base, tracks, 1)           # advance
        self.assertEqual(s1["track_index"], 1)
        self.assertEqual(s1["track_title"], "Boards — Roygbiv")

    def test_track_state_out_of_range_is_safe(self):
        import block_player
        s = block_player.track_state({"block_id": "b"}, [], 0)
        self.assertEqual(s["track_count"], 0)
        self.assertEqual(s["track_title"], "Music")

    def test_idle_plan_builds_cumulative_byte_bounds(self):
        import block_player
        bps = block_player.BYTES_PER_SEC
        meta = [{"artist": "A", "name": "One", "duration_s": 10},
                {"artist": "B", "name": "Two", "duration_s": 5}]
        labels, bounds, total = block_player.idle_plan(meta)
        self.assertEqual(labels, ["A — One", "B — Two"])
        self.assertEqual(bounds, [10 * bps, 15 * bps])
        self.assertEqual(total, 15 * bps)

    def test_idle_plan_drops_zero_duration_tracks(self):
        import block_player
        meta = [{"name": "Ghost", "duration_s": 0}, {"name": "Real", "duration_s": 3}]
        labels, bounds, total = block_player.idle_plan(meta)
        self.assertEqual(labels, ["Real"])  # can't locate a 0-length track by bytes
        self.assertEqual(total, 3 * block_player.BYTES_PER_SEC)

    def test_idle_index_locates_track_and_wraps_each_loop(self):
        import block_player
        bps = block_player.BYTES_PER_SEC
        _, bounds, total = block_player.idle_plan(
            [{"name": "One", "duration_s": 10}, {"name": "Two", "duration_s": 5}])
        self.assertEqual(block_player.idle_index(0, bounds, total), 0)
        self.assertEqual(block_player.idle_index(9 * bps, bounds, total), 0)
        self.assertEqual(block_player.idle_index(10 * bps, bounds, total), 1)
        # -stream_loop -1: bytes past the total wrap back to the first track
        self.assertEqual(block_player.idle_index(16 * bps, bounds, total), 0)

    def test_idle_index_no_bounds_is_safe(self):
        import block_player
        self.assertEqual(block_player.idle_index(999, [], 0), 0)

    def test_shuffled_idle_reorders_but_keeps_audio_and_meta_in_lockstep(self):
        # Idle must reshuffle each stint (not always restart at track 0), and the
        # shuffled audio lines must stay paired with their meta so /now names the
        # right track. Playlist line N and meta N share the same Jellyfin id.
        import random
        import re
        import block_player
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        pl = os.path.join(tmp.name, "pl.txt")
        mt = os.path.join(tmp.name, "meta.json")
        sh = os.path.join(tmp.name, "sh.txt")
        ids = ["%032x" % i for i in range(20)]
        with open(pl, "w") as f:
            for i in ids:
                f.write("file 'http://h/Audio/%s/stream.mp3'\n" % i)
        with open(mt, "w") as f:
            json.dump([{"id": i, "name": "T" + i[-1], "artist": "A", "duration_s": 100} for i in ids], f)
        with patch.object(block_player, "IDLE_PLAYLIST", pl), \
             patch.object(block_player, "IDLE_META", mt), \
             patch.object(block_player, "IDLE_SHUFFLED", sh):
            random.seed(1)
            path, meta = block_player.shuffled_idle()
        self.assertEqual(path, sh)
        with open(sh) as f:
            line_ids = [re.search(r"/Audio/([0-9a-f]+)/", ln).group(1) for ln in f if ln.strip()]
        meta_ids = [m["id"] for m in meta]
        self.assertEqual(line_ids, meta_ids)          # audio + labels in lockstep
        self.assertEqual(set(line_ids), set(ids))     # same set, nothing lost
        self.assertNotEqual(line_ids, ids)            # actually reordered

    def test_shuffled_idle_without_meta_is_generic_and_unshuffled(self):
        import block_player
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        pl = os.path.join(tmp.name, "pl.txt")
        with open(pl, "w") as f:
            f.write("file 'http://h/Audio/abc/stream.mp3'\n")
        with patch.object(block_player, "IDLE_PLAYLIST", pl), \
             patch.object(block_player, "IDLE_META", os.path.join(tmp.name, "missing.json")):
            path, meta = block_player.shuffled_idle()
        self.assertEqual(path, pl)   # no meta -> play the on-disk list, generic labels
        self.assertEqual(meta, [])

    def test_now_state_serves_in_memory_state(self):
        # The panel OWNS the live state in memory (fed by the player push); a
        # fresh push means player_active. now_state passes it through verbatim.
        st = {"phase": "airing", "block_id": "b1", "segment_index": 1, "segment_count": 3,
              "segment_type": "music", "track_index": 4, "track_count": 9,
              "track_title": "Air — Alone", "on_air": "Air — Alone"}
        with patch.object(panel, "_PLAYER_STATE", st), \
             patch.object(panel, "_LAST_PUSH", time.time()), \
             patch.object(panel, "icecast_status", return_value={"live": True, "listeners": 2}), \
             patch.object(panel, "_cast_target_read", return_value=None), \
             patch.object(panel.block_render, "load_queue", return_value=[]):
            n = panel.now_state()
        self.assertTrue(n["player_active"])
        self.assertEqual(n["state"]["on_air"], "Air — Alone")
        self.assertEqual(n["state"]["track_index"], 4)

    def test_now_state_inactive_when_stale(self):
        # No recent push (>12s or never) -> the player isn't on air.
        with patch.object(panel, "_PLAYER_STATE", {}), \
             patch.object(panel, "_LAST_PUSH", 0.0), \
             patch.object(panel, "icecast_status", return_value={"live": False, "listeners": 0}), \
             patch.object(panel, "_cast_target_read", return_value=None), \
             patch.object(panel.block_render, "load_queue", return_value=[]):
            self.assertFalse(panel.now_state()["player_active"])


class CleanupTests(unittest.TestCase):
    """cleanup_blocks removes old, unreferenced block dirs and keeps anything
    queued/scheduled or recent -- the disk-hygiene fix for unbounded render
    artifact growth."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        base = self._tmpdir.name
        self._patches = [
            patch.object(block_render, "BLOCKS_DIR", os.path.join(base, "program_blocks")),
            patch.object(block_render, "QUEUE_FILE", os.path.join(base, "block_queue.json")),
            patch.object(block_render, "SCHEDULE_FILE", os.path.join(base, "schedule.json")),
            patch.object(block_render, "STATE_LOCK", os.path.join(base, ".state.lock")),
        ]
        for p in self._patches:
            p.start()
        os.makedirs(block_render.BLOCKS_DIR)

    def tearDown(self):
        for p in reversed(self._patches):
            p.stop()
        self._tmpdir.cleanup()

    def _mk(self, bid, age_days):
        d = block_render.block_dir(bid)
        os.makedirs(d)
        mf = os.path.join(d, "block.json")
        with open(mf, "w") as f:
            f.write("{}")
        t = time.time() - age_days * 86400
        os.utime(mf, (t, t))

    def test_removes_old_unreferenced_keeps_the_rest(self):
        self._mk("20200101T000000", 30)   # old + unreferenced -> remove
        self._mk("20200102T000000", 30)   # old but queued -> keep
        self._mk("20990101T000000", 0)    # recent -> keep
        block_render.save_queue(["20200102T000000"])
        removed = block_render.cleanup_blocks(max_age_days=14)
        self.assertEqual(removed, ["20200101T000000"])
        self.assertFalse(os.path.isdir(block_render.block_dir("20200101T000000")))
        self.assertTrue(os.path.isdir(block_render.block_dir("20200102T000000")))
        self.assertTrue(os.path.isdir(block_render.block_dir("20990101T000000")))


class RecapFactoidTests(unittest.TestCase):
    """recap/factoid TTS builders: reference the tracks earlier music
    segments resolved to, and ALWAYS degrade to a deterministic template
    when no LLM is configured (a dead Ollama must never error an hour)."""

    def _music(self, names, dur=720):
        return {"id": "m", "type": "music", "params": {"duration_s": dur},
                "resolved": {"tracks_head": names}}

    def test_recap_fallback_names_recent_tracks(self):
        segs = [self._music(["Song A", "Song B", "Song C"]),
                {"id": "r", "type": "tts", "params": {"topic": "recap", "scope": "music"}}]
        text, title = tts_content.build_recap_text(segs[1]["params"], {"segments": segs, "index": 1})
        self.assertEqual(title, "Recap")
        self.assertIn("Song A", text)  # no llm_backend -> deterministic, names tracks

    def test_recap_scope_music_excludes_pre_recap_tracks(self):
        segs = [self._music(["Old One"]),
                {"id": "r0", "type": "tts", "params": {"topic": "recap"}},
                self._music(["New One"]),
                {"id": "r1", "type": "tts", "params": {"topic": "recap", "scope": "music"}}]
        text, _ = tts_content.build_recap_text(segs[3]["params"], {"segments": segs, "index": 3})
        self.assertIn("New One", text)
        self.assertNotIn("Old One", text)  # excluded: before the previous recap

    def test_aired_tracks_truncated_by_duration(self):
        seg = self._music(["t%d" % i for i in range(20)], dur=420)  # 420//210 = 2
        self.assertEqual(tts_content._aired_tracks(seg), ["t0", "t1"])

    def test_recap_requires_context(self):
        with self.assertRaises(RuntimeError):
            tts_content.build_recap_text({"topic": "recap"}, None)

    def test_factoid_fallback_is_nonempty(self):
        text, title = tts_content.build_factoid_text({"topic": "factoid", "source": "freeform"}, None)
        self.assertEqual(title, "Factoid")
        self.assertTrue(text.strip())

    def test_spoken_strips_markdown(self):
        # Kokoro would otherwise read '#'/'**' aloud.
        out = tts_content._spoken("# Recap\n\nWe played **Song A**.\n- and more")
        for junk in ("#", "*", "\n\n"):
            self.assertNotIn(junk, out)
        self.assertIn("Song A", out)


class AutoSourceTests(unittest.TestCase):
    """source_id:"auto" resolves to a bulletin not already used earlier in
    the block -- the robust half of "news not from the original sources"."""

    def test_auto_picks_disjoint_podcast_source_and_records_it(self):
        srcs = [{"id": "npr", "kind": "podcast_latest"},
                {"id": "bbc_world", "kind": "podcast_latest"},
                {"id": "cnn"}]
        seg = {"type": "live", "params": {"source_id": "auto", "duration_s": 300}}
        with patch.object(block_render.live_source, "load_sources", return_value=srcs), \
             patch.object(block_render.live_source, "resolve_live",
                          side_effect=lambda sid: {"title": sid, "url": "http://x", "id": sid}):
            block_render.resolve_live_segment(seg, prior_source_ids=["npr"])
        self.assertEqual(seg["resolved"]["source_id"], "bbc_world")  # npr used -> next bulletin
        self.assertEqual(seg["status"], "ok")

    def test_auto_never_picks_talk_source(self):
        # long-form talk (category:"talk") must be excluded from the bulletin
        # rotation even when it's the only unused source -> reuse a bulletin.
        srcs = [{"id": "npr", "kind": "podcast_latest"},
                {"id": "nyt_daily", "kind": "podcast_latest", "category": "talk"}]
        seg = {"type": "live", "params": {"source_id": "auto", "duration_s": 300}}
        with patch.object(block_render.live_source, "load_sources", return_value=srcs), \
             patch.object(block_render.live_source, "get_source", return_value={"name": "NPR"}), \
             patch.object(block_render.live_source, "resolve_live",
                          side_effect=lambda sid: {"title": sid, "url": "http://x"}):
            block_render.resolve_live_segment(seg, prior_source_ids=["npr"])
        self.assertEqual(seg["resolved"]["source_id"], "npr")


class HourTemplateTests(unittest.TestCase):
    """build_hour materializes the standard hour with role tags + per-hour
    variation (genre by day-part, rotating news lead)."""

    def test_default_hour_has_no_live_news(self):
        # News is OFF by default (interruptive); music absorbs the freed time.
        segs = hour_templates.build_hour(9)
        roles = [s["role"] for s in segs]
        self.assertEqual(roles, ["weather", "music_1", "recap_mid", "music_2", "recap_hour"])
        self.assertFalse(any(s["type"] == "live" for s in segs))
        m1 = next(s for s in segs if s["role"] == "music_1")
        self.assertEqual(m1["params"]["duration_s"],
                         hour_templates.MUSIC_1_S + hour_templates.NEWS_OFF_MUSIC_BONUS_S)

    def test_include_news_restores_bulletin_slots(self):
        segs = hour_templates.build_hour(9, {"include_news": True})
        roles = [s["role"] for s in segs]
        self.assertEqual(roles, ["weather", "news_1", "news_2", "music_1", "news_3",
                                 "recap_mid", "music_2", "news_fresh", "recap_hour"])
        self.assertEqual(next(s for s in segs if s["role"] == "news_1")["type"], "live")
        # news_fresh is the disjoint "auto" source
        self.assertEqual(next(s for s in segs if s["role"] == "news_fresh")["params"]["source_id"], "auto")

    def test_news_lead_rotates_by_hour(self):
        def lead(h):
            return next(s for s in hour_templates.build_hour(h, {"include_news": True})
                        if s["role"] == "news_1")["params"]["source_id"]
        self.assertNotEqual(lead(0), lead(1))

    def test_music_genre_varies_by_daypart(self):
        overnight = next(s for s in hour_templates.build_hour(3) if s["role"] == "music_1")["params"]["query"]
        evening = next(s for s in hour_templates.build_hour(20) if s["role"] == "music_1")["params"]["query"]
        self.assertNotEqual(overnight, evening)


class DayProgramTests(unittest.TestCase):
    """generate_day: 24 deterministic-id blocks + 24 hourly entries,
    idempotent regen, past-day prune, summary, delete."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        base = self._tmpdir.name
        self._patches = [
            patch.object(block_render, "BLOCKS_DIR", os.path.join(base, "program_blocks")),
            patch.object(block_render, "QUEUE_FILE", os.path.join(base, "block_queue.json")),
            patch.object(block_render, "SCHEDULE_FILE", os.path.join(base, "schedule.json")),
            patch.object(block_render, "STATE_LOCK", os.path.join(base, ".state.lock")),
        ]
        for p in self._patches:
            p.start()
        os.makedirs(block_render.BLOCKS_DIR)

    def tearDown(self):
        for p in reversed(self._patches):
            p.stop()
        self._tmpdir.cleanup()

    def test_generate_makes_24_blocks_and_entries(self):
        r = day_program.generate_day("2026-07-18")
        self.assertEqual(len(r["blocks"]), 24)
        self.assertEqual(r["blocks"][14], "20260718T140000")
        b = block_render.load_block("20260718T140000")
        self.assertEqual(b["template"]["hour"], 14)
        self.assertEqual(len(b["segments"]), 5)  # news off by default
        self.assertEqual(len(block_render.load_schedule()), 24)

    def test_regenerate_is_idempotent(self):
        day_program.generate_day("2026-07-18")
        day_program.generate_day("2026-07-18")
        self.assertEqual(len(block_render.load_schedule()), 24)
        self.assertEqual(len(os.listdir(block_render.BLOCKS_DIR)), 24)

    def test_generate_prunes_past_day_entries(self):
        day_program.generate_day("2026-07-17", today="2026-07-18")
        day_program.generate_day("2026-07-18", today="2026-07-18")
        eids = {e["id"] for e in block_render.load_schedule()}
        self.assertTrue(eids and all(e.startswith("gen-2026-07-18-") for e in eids))

    def test_day_summary(self):
        day_program.generate_day("2026-07-18")
        s = day_program.day_summary("2026-07-18")
        self.assertEqual(len(s["hours"]), 24)
        self.assertTrue(all(h["generated"] for h in s["hours"]))
        self.assertEqual(s["hours"][14]["news"], [])  # news off by default

    def test_delete_day(self):
        day_program.generate_day("2026-07-18")
        day_program.delete_day("2026-07-18")
        self.assertEqual(block_render.load_schedule(), [])
        self.assertEqual(os.listdir(block_render.BLOCKS_DIR), [])

    def test_bad_date_rejected(self):
        with self.assertRaises(ValueError):
            day_program.generate_day("../evil")
        with self.assertRaises(ValueError):
            day_program.day_summary("nope")

    def test_generate_uses_station_default_weather_and_recap_backend(self):
        # station.json defaults flow into generated hours (weather location +
        # recap LLM backend), so the /day button produces working weather.
        cfg = os.path.join(self._tmpdir.name, "station.json")
        with open(cfg, "w") as f:
            json.dump({"weather_location": "11106", "recap_llm_backend": "claude",
                       "recap_llm_model": "claude-haiku-4-5"}, f)
        with patch.object(block_render, "STATION_CFG", cfg):
            day_program.generate_day("2026-07-18")
        b = block_render.load_block("20260718T090000")
        by = {s.get("role"): s for s in b["segments"]}
        self.assertEqual(by["weather"]["params"]["location"], "11106")
        self.assertEqual(by["recap_mid"]["params"]["llm_backend"], "claude")


class SchedulerTests(unittest.TestCase):
    """due_entries is a pure function so the firing logic is testable without
    a running clock: pass an explicit now and a last_fired dict."""

    def _entry(self, **kw):
        base = {"id": "e1", "block_id": "20260101T000000", "time": "09:00", "enabled": True}
        base.update(kw)
        return base

    def test_fires_at_matching_minute(self):
        now = datetime(2026, 7, 17, 9, 0)  # a Friday
        self.assertEqual(block_render.due_entries([self._entry()], now, {}), ["20260101T000000"])

    def test_does_not_fire_off_minute(self):
        now = datetime(2026, 7, 17, 9, 1)
        self.assertEqual(block_render.due_entries([self._entry()], now, {}), [])

    def test_disabled_entry_never_fires(self):
        now = datetime(2026, 7, 17, 9, 0)
        self.assertEqual(block_render.due_entries([self._entry(enabled=False)], now, {}), [])

    def test_fires_once_per_minute(self):
        now = datetime(2026, 7, 17, 9, 0)
        seen = {}
        self.assertEqual(block_render.due_entries([self._entry()], now, seen), ["20260101T000000"])
        self.assertEqual(block_render.due_entries([self._entry()], now, seen), [])  # deduped
        # next day's same minute fires again
        self.assertEqual(block_render.due_entries([self._entry()], datetime(2026, 7, 18, 9, 0), seen),
                         ["20260101T000000"])

    def test_days_filter(self):
        friday = datetime(2026, 7, 17, 9, 0)     # weekday()==4
        saturday = datetime(2026, 7, 18, 9, 0)   # weekday()==5
        weekdays_only = self._entry(days=[0, 1, 2, 3, 4])
        self.assertEqual(block_render.due_entries([weekdays_only], friday, {}), ["20260101T000000"])
        self.assertEqual(block_render.due_entries([weekdays_only], saturday, {}), [])

    def test_empty_days_is_daily(self):
        saturday = datetime(2026, 7, 18, 9, 0)
        self.assertEqual(block_render.due_entries([self._entry(days=[])], saturday, {}), ["20260101T000000"])


class StalenessTests(unittest.TestCase):
    """Pure logic, no I/O: TTS staleness is the mechanism that guarantees a
    weather segment never airs stale."""

    def test_unresolved_segment_is_stale(self):
        seg = {"type": "tts", "params": {}}
        self.assertTrue(block_render.is_stale(seg))

    def test_fresh_segment_within_ttl_is_not_stale(self):
        seg = {
            "type": "tts",
            "status": "ok",
            "params": {"ttl_s": 1800},
            "rendered_at": datetime.now(timezone.utc).isoformat(),
        }
        self.assertFalse(block_render.is_stale(seg))

    def test_expired_ttl_is_stale(self):
        old = datetime.now(timezone.utc) - timedelta(seconds=3600)
        seg = {"type": "tts", "status": "ok", "params": {"ttl_s": 1800}, "rendered_at": old.isoformat()}
        self.assertTrue(block_render.is_stale(seg))

    def test_non_tts_segments_are_never_stale(self):
        self.assertFalse(block_render.is_stale({"type": "live", "params": {}}))
        self.assertFalse(block_render.is_stale({"type": "music", "params": {}}))


class ApiRouteParsingTests(unittest.TestCase):
    """panel._api_route must tolerate both a bare path and one prefixed by
    a tailscale-serve mount point (/admin or /blocks), since the two mounts
    behave differently (see PROGRAM_BLOCKS.md's tailscale-serve note)."""

    def test_bare_path(self):
        self.assertEqual(panel._api_route("/api/blocks"), ["blocks"])

    def test_prefixed_path(self):
        self.assertEqual(panel._api_route("/blocks/api/blocks/20260101T000000"),
                          ["blocks", "20260101T000000"])

    def test_no_api_segment_returns_none(self):
        self.assertIsNone(panel._api_route("/blocks"))

    def test_nested_route_segments(self):
        self.assertEqual(panel._api_route("/api/blocks/abc/schedule"), ["blocks", "abc", "schedule"])


class LiveSourcesTests(unittest.TestCase):
    def test_default_sources_have_unique_ids(self):
        ids = [s["id"] for s in live_source.DEFAULT_SOURCES]
        self.assertEqual(len(ids), len(set(ids)), "duplicate live source ids")

    def test_every_default_source_has_required_fields(self):
        # two shapes: a plain continuous stream (url), or a periodic-bulletin
        # podcast feed resolved to its latest episode (feed_url) -- see
        # resolve_podcast_latest / PROGRAM_BLOCKS.md.
        for src in live_source.DEFAULT_SOURCES:
            self.assertTrue(src["id"])
            self.assertTrue(src["name"])
            if src.get("kind") == "podcast_latest":
                self.assertTrue(src["feed_url"].startswith("http"))
            else:
                self.assertTrue(src["url"].startswith("http"))

    def test_get_source_resolves_by_id(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "live_sources.json")
            src = live_source.get_source("npr", path=path)
            self.assertEqual(src["id"], "npr")

    def test_get_source_unknown_id_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "live_sources.json")
            self.assertIsNone(live_source.get_source("not-a-real-source", path=path))

    def test_resolve_live_unknown_id_raises(self):
        with self.assertRaises(ValueError):
            live_source.resolve_live("not-a-real-source")


class PodcastLatestTests(unittest.TestCase):
    """resolve_podcast_latest's XML parsing, tested against a canned feed --
    never hits the real network in CI."""

    SAMPLE_FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0"><channel>
      <title>Sample Bulletin</title>
      <item>
        <title>17/07/2026 05:01 GMT</title>
        <enclosure url="https://example.test/bulletin-latest.mp3" type="audio/mpeg" length="123"/>
      </item>
      <item>
        <title>17/07/2026 04:31 GMT</title>
        <enclosure url="https://example.test/bulletin-older.mp3" type="audio/mpeg" length="123"/>
      </item>
    </channel></rss>"""

    def test_resolves_the_first_items_enclosure(self):
        with patch.object(live_source, "_fetch_bytes", return_value=self.SAMPLE_FEED):
            url, title = live_source.resolve_podcast_latest("https://example.test/feed.xml")
        self.assertEqual(url, "https://example.test/bulletin-latest.mp3")
        self.assertEqual(title, "17/07/2026 05:01 GMT")

    def test_empty_feed_raises(self):
        empty = b'<?xml version="1.0"?><rss version="2.0"><channel></channel></rss>'
        with patch.object(live_source, "_fetch_bytes", return_value=empty):
            with self.assertRaises(RuntimeError):
                live_source.resolve_podcast_latest("https://example.test/feed.xml")

    def test_item_without_enclosure_raises(self):
        no_enclosure = b"""<?xml version="1.0"?><rss version="2.0"><channel>
        <item><title>oops</title></item></channel></rss>"""
        with patch.object(live_source, "_fetch_bytes", return_value=no_enclosure):
            with self.assertRaises(RuntimeError):
                live_source.resolve_podcast_latest("https://example.test/feed.xml")

    def test_resolve_live_dispatches_podcast_latest_sources_by_kind(self):
        fake_source = {"id": "brief", "name": "Brief", "kind": "podcast_latest",
                       "feed_url": "https://example.test/feed.xml"}
        with patch.object(live_source, "get_source", return_value=fake_source), \
             patch.object(live_source, "_fetch_bytes", return_value=self.SAMPLE_FEED):
            r = live_source.resolve_live("brief")
        self.assertEqual(r["url"], "https://example.test/bulletin-latest.mp3")
        self.assertEqual(r["title"], "17/07/2026 05:01 GMT")


class WeatherScriptTests(unittest.TestCase):
    """weather_script is a deterministic template with no network call --
    exactly the part that's safe and cheap to test without OWM credentials."""

    def test_script_mentions_place_and_temperature(self):
        w = {
            "main": {"temp": 72.4, "feels_like": 70.1, "humidity": 55},
            "weather": [{"description": "clear sky"}],
            "wind": {"speed": 5.2},
        }
        text = tts_content.weather_script("Cambridge, US", w)
        self.assertIn("Cambridge, US", text)
        self.assertIn("72", text)
        self.assertIn("clear sky", text)

    def test_script_handles_missing_wind(self):
        w = {"main": {"temp": 60, "feels_like": 58, "humidity": 40}, "weather": [{"description": "cloudy"}]}
        text = tts_content.weather_script("Nowhere", w)  # must not raise KeyError
        self.assertIn("Nowhere", text)

    def test_time_check_and_station_id(self):
        t, title = tts_content.build_time_check_text({"station_name": "WRIT-FM", "timezone": "UTC"})
        self.assertIn("WRIT-FM", t)
        self.assertEqual(title, "time check")
        self.assertTrue("AM" in t or "PM" in t)
        d, _ = tts_content.build_station_id_text({"station_name": "WRIT-FM"})
        self.assertIn("WRIT-FM", d)
        tag, _ = tts_content.build_station_id_text({"station_name": "WRIT-FM", "tagline": "all vibes"})
        self.assertIn("all vibes", tag)
        # dispatch through block_render.build_tts_text
        self.assertIn("Z", block_render.build_tts_text("station_id", {"station_name": "Z"})[0])

    def test_script_leads_with_local_day_and_time(self):
        from datetime import datetime, timezone
        w = {"main": {"temp": 72, "feels_like": 70, "humidity": 55},
             "weather": [{"description": "clear"}], "wind": {"speed": 5},
             "timezone": -14400}  # Astoria/EDT: UTC-4
        text = tts_content.weather_script("Astoria", w,
                                          now=datetime(2026, 7, 18, 12, 30, tzinfo=timezone.utc))
        self.assertIn("Saturday July 18th", text)
        self.assertIn("8:30 AM", text)


class BackendRegistryTests(unittest.TestCase):
    """Unknown ids must fail loudly with ValueError, not a confusing
    KeyError deep inside a network call -- this is the exact failure mode
    the freeform-TTS LLM-picker bug produced before it was fixed."""

    def test_unknown_llm_backend_raises_value_error(self):
        with self.assertRaises(ValueError):
            llm_backends.generate("not-a-real-backend", "some-model", "hello")

    def test_unknown_tts_engine_raises_value_error(self):
        with self.assertRaises(ValueError):
            tts_engines.speech("not-a-real-engine", "voice", 1.0, "hello", {})

    def test_llm_backends_registry_has_expected_shape(self):
        for bid, b in llm_backends.LLM_BACKENDS.items():
            self.assertIn("label", b)
            self.assertIn("kind", b)


class JellyfinClientTests(unittest.TestCase):
    """Pure parsing/URL-construction logic -- no network call."""

    def test_load_conf_parses_key_value_lines(self):
        with tempfile.NamedTemporaryFile("w", suffix=".conf", delete=False) as f:
            f.write("JELLYFIN_URL=http://example.local:8096\n# comment\nJELLYFIN_USER=bob\n")
            path = f.name
        try:
            conf = jellyfin_client.load_conf(path)
            self.assertEqual(conf["JELLYFIN_URL"], "http://example.local:8096")
            self.assertEqual(conf["JELLYFIN_USER"], "bob")
            self.assertNotIn("# comment", conf)
        finally:
            os.remove(path)

    def test_track_url_embeds_id_and_token(self):
        url = jellyfin_client.track_url("http://host:8096", "tok123", "item456")
        self.assertIn("item456", url)
        self.assertIn("tok123", url)
        self.assertIn("audioBitRate=128000", url)

    def test_auth_reuses_one_token_per_process(self):
        # A shared DeviceId made every re-auth invalidate the prior token (and
        # the music URLs that embedded it). auth() now mints once and reuses.
        conf = {"JELLYFIN_URL": "http://h:8096", "JELLYFIN_USER": "u", "JELLYFIN_PASS": "p"}
        reqs = []

        class Resp:
            def __init__(self, n):
                self.n = n

            def read(self):
                return json.dumps({"AccessToken": "tok%d" % self.n, "User": {"Id": "uid"}}).encode()

        def fake_urlopen(req, timeout=10):
            reqs.append(req)
            return Resp(len(reqs))

        with patch.object(jellyfin_client, "_TOKEN", {}), \
             patch("urllib.request.urlopen", fake_urlopen):
            _, t1, _ = jellyfin_client.auth(conf)
            _, t2, _ = jellyfin_client.auth(conf)
            self.assertEqual(t1, t2)          # reused, not re-minted
            self.assertEqual(len(reqs), 1)    # exactly one network auth
            _, t3, _ = jellyfin_client.auth(conf, force=True)
            self.assertNotEqual(t3, t1)       # force deliberately re-mints
            self.assertEqual(len(reqs), 2)
        hdr = reqs[0].headers["X-emby-authorization"]
        self.assertIn(jellyfin_client._DEVICE_ID, hdr)
        self.assertNotIn("te-radio-38", hdr)  # no shared, collision-prone id


class MusicBrowserTests(unittest.TestCase):
    """Compact browse index build + pure-Python weighted kNN / facets / search."""

    def _load(self, recs):
        tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump({"axes": list(music_browser.AXES), "tracks": recs}, tmp)
        tmp.close()
        self.addCleanup(os.unlink, tmp.name)
        self.addCleanup(lambda: setattr(music_browser, "_INDEX", None))
        music_browser.load_index(path=tmp.name, force=True)

    def _rec(self, tid, vec, **kw):
        return {"id": tid, "name": kw.get("name", tid), "artist": kw.get("artist", ""),
                "album": kw.get("album", ""), "genres": kw.get("genres", []), "year": None,
                "era": kw.get("era"), "live": kw.get("live", False),
                "moods": kw.get("moods", []), "themes": kw.get("themes", []),
                "bpm": kw.get("bpm", 120), "vec": vec}

    def test_build_browse_index_joins_and_skips(self):
        snap = {"tracks": [
            {"id": "a", "name": "A", "artists": ["Air"], "album": "Alb", "genres": ["x"], "year": 2001},
            {"id": "b", "name": "B", "artists": []},  # no overlay entry -> skipped
        ]}
        ov = {"tracks": {"a": {"energy": 0.5, "valence": 0.4, "acousticness": 0.3,
                               "danceability": 0.6, "instrumental": 0.1, "tempo_bpm": 120.0,
                               "era": "2000s", "live": True, "moods": ["Mellow"]}}}
        idx = overlay.build_browse_index(snap, ov)
        self.assertEqual([r["id"] for r in idx["tracks"]], ["a"])
        r = idx["tracks"][0]
        self.assertEqual(r["artist"], "Air")
        self.assertTrue(r["live"])
        self.assertEqual(len(r["vec"]), 6)
        self.assertAlmostEqual(r["vec"][5], overlay.tempo_norm(120.0))

    def test_nearest_ranks_by_weighted_distance(self):
        self._load([
            self._rec("seed", [0.5, 0.5, 0.5, 0.5, 0.5, 0.5]),
            self._rec("close", [0.52, 0.5, 0.5, 0.5, 0.5, 0.5]),
            self._rec("far", [0.1, 0.9, 0.1, 0.9, 0.1, 0.9]),
        ])
        res = music_browser.nearest([0.5] * 6, k=3)
        self.assertEqual([r["id"] for r in res], ["seed", "close", "far"])
        self.assertEqual(res[0]["score"], 1.0)
        self.assertGreater(res[1]["score"], res[2]["score"])

    def test_facets_studio_era_mood(self):
        self._load([
            self._rec("s", [0.5] * 6, live=False, era="2000s", moods=["Mellow"]),
            self._rec("liveone", [0.5] * 6, live=True, era="2000s"),
            self._rec("old", [0.5] * 6, era="1980s"),
        ])
        self.assertNotIn("liveone", {r["id"] for r in music_browser.nearest([0.5] * 6)})  # studio default
        self.assertIn("liveone", {r["id"] for r in music_browser.nearest([0.5] * 6, studio_only=False)})
        self.assertNotIn("old", {r["id"] for r in music_browser.nearest([0.5] * 6, era="2000s", studio_only=False)})
        self.assertEqual({r["id"] for r in music_browser.nearest([0.5] * 6, moods=["mellow"])}, {"s"})

    def test_similar_excludes_seed_and_search(self):
        self._load([
            self._rec("seed", [0.5] * 6, name="Blue Monday", artist="New Order"),
            self._rec("x", [0.5] * 6),
        ])
        self.assertNotIn("seed", {r["id"] for r in music_browser.similar("seed")})
        self.assertEqual([r["id"] for r in music_browser.search("new order")], ["seed"])
        self.assertEqual(music_browser.similar("missing"), [])

    def test_dedup_key_normalizes_masters_not_takes(self):
        k = music_browser.dedup_key
        base = k("Whatever", "Air")
        self.assertEqual(base, k("03 -Whatever", "Air"))              # leading track no.
        self.assertEqual(base, k("Whatever (2005 Remaster)", "Air"))  # remaster paren
        self.assertEqual(base, k("Whatever - 2011 Remastered", "Air"))  # dash remaster
        self.assertNotEqual(base, k("Whatever (Live)", "Air"))        # live = distinct take
        self.assertNotEqual(base, k("Whatever", "Beach House"))       # different artist
        self.assertIsNone(k("[untitled]", "Air"))                    # generic -> no key
        self.assertIsNone(k("Intro", "Air"))
        self.assertIsNone(k("07", "Air"))

    def test_nearest_collapses_duplicates(self):
        self._load([
            self._rec("a", [0.5] * 6, name="Song", artist="X"),
            self._rec("a2", [0.5] * 6, name="Song (2005 Remaster)", artist="X"),
            self._rec("b", [0.4] * 6, name="Other", artist="Y"),
        ])
        res = music_browser.nearest([0.5] * 6, k=10)
        self.assertEqual(len(res), 2)                 # a + a2 fold into one
        self.assertEqual(res[0]["dupes"], 2)
        self.assertEqual(len(music_browser.nearest([0.5] * 6, collapse=False)), 3)

    def test_dedup_clusters_keep_studio_and_flag_divergent(self):
        self._load([
            self._rec("d1", [0.5] * 6, name="Twin", artist="Z", duration_s=200, album="A"),
            self._rec("d2", [0.5] * 6, name="Twin", artist="Z", duration_s=201),
            self._rec("d3", [0.9, 0.1, 0.5, 0.5, 0.5, 0.5], name="Twin", artist="Z", duration_s=260),
        ])
        twin = next(c for c in music_browser.dedup_clusters() if c["keep"]["name"] == "Twin")
        self.assertEqual(twin["size"], 3)
        self.assertTrue(twin["divergent"])            # d3 duration + features diverge
        self.assertEqual(twin["keep"]["id"], "d1")    # tagged album wins the keep slot
        self.assertEqual({r["id"] for r in twin["prune"]}, {"d2", "d3"})

    def test_safe_prune_plan_excludes_divergent(self):
        self._load([
            self._rec("k", [0.5] * 6, name="Dup", artist="Q", album="LP", duration_s=200),
            self._rec("p", [0.5] * 6, name="Dup", artist="Q", duration_s=201),   # safe copy -> prune
            self._rec("a", [0.5] * 6, name="Alt", artist="Q", duration_s=200),
            self._rec("b", [0.1, 0.9, 0.5, 0.5, 0.5, 0.5], name="Alt", artist="Q", duration_s=280),
        ])
        plan = music_browser.safe_prune_plan()
        self.assertEqual(plan["prune_ids"], ["p"])     # only the safe extra copy
        keys = [m["keep"]["id"] for m in plan["manifest"]]
        self.assertIn("k", keys)                       # Dup kept the album copy
        self.assertNotIn("a", keys)                    # divergent Alt group excluded


if __name__ == "__main__":
    unittest.main()
