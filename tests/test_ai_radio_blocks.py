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
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import block_render  # noqa: E402
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
        block_render.delete_block("does-not-exist")  # must not raise

    def test_new_block_id_avoids_collision(self):
        first = block_render.new_block_id()
        os.makedirs(block_render.block_dir(first))
        second = block_render.new_block_id()
        self.assertNotEqual(first, second)


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
        self.assertEqual(len(ids), 10)

    def test_every_default_source_has_required_fields(self):
        for src in live_source.DEFAULT_SOURCES:
            self.assertTrue(src["id"])
            self.assertTrue(src["name"])
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
