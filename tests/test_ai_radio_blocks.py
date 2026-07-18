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

import block_render  # noqa: E402
import day_program  # noqa: E402
import hour_templates  # noqa: E402
import jellyfin_client  # noqa: E402
import live_source  # noqa: E402
import llm_backends  # noqa: E402
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


class HourTemplateTests(unittest.TestCase):
    """build_hour materializes the standard hour with role tags + per-hour
    variation (genre by day-part, rotating news lead)."""

    def test_standard_hour_shape_and_roles(self):
        segs = hour_templates.build_hour(9)
        roles = [s["role"] for s in segs]
        self.assertEqual(roles, ["weather", "news_1", "news_2", "music_1", "news_3",
                                 "recap_mid", "music_2", "news_fresh", "recap_hour"])
        types = {s["role"]: s["type"] for s in segs}
        self.assertEqual(types["weather"], "tts")
        self.assertEqual(types["news_1"], "live")
        self.assertEqual(types["music_1"], "music")
        self.assertEqual(types["recap_mid"], "tts")
        # news_fresh is the disjoint "auto" source
        nf = next(s for s in segs if s["role"] == "news_fresh")
        self.assertEqual(nf["params"]["source_id"], "auto")

    def test_news_lead_rotates_by_hour(self):
        lead0 = next(s for s in hour_templates.build_hour(0) if s["role"] == "news_1")["params"]["source_id"]
        lead1 = next(s for s in hour_templates.build_hour(1) if s["role"] == "news_1")["params"]["source_id"]
        self.assertNotEqual(lead0, lead1)

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
        self.assertEqual(len(b["segments"]), 9)
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
        self.assertEqual(len(s["hours"][14]["news"]), 4)  # 3 templated + auto

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


if __name__ == "__main__":
    unittest.main()
