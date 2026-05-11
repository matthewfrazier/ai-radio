import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from mac import feeder


class FeederPlaylistTests(unittest.TestCase):
    def test_build_playlist_caps_talk_and_uses_music_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            talk_root = root / "talk_segments"
            bumper_root = root / "music_bumpers"
            slot_dir = talk_root / "sonic_archaeology" / "2026-05-08_0900"
            show_bumpers = bumper_root / "sonic_archaeology"
            slot_dir.mkdir(parents=True)
            show_bumpers.mkdir(parents=True)

            for i in range(5):
                (slot_dir / f"{i:02d}_deep_dive_topic_{i}.wav").write_bytes(b"")
            for i in range(8):
                (show_bumpers / f"sonic_archaeology_bumper_{i}.flac").write_bytes(b"")

            with (
                patch.object(feeder, "TALK_DIR", talk_root),
                patch.object(feeder, "BUMPER_DIR", bumper_root),
                patch.object(
                    feeder,
                    "STATION",
                    SimpleNamespace(id="test-fm", call_sign="TEST-FM", output_dir=root),
                ),
                patch.object(feeder, "HISTORY_ENABLED", False),
                patch.object(feeder, "TALK_SEGMENTS_PER_PLAYLIST", 2),
                patch.object(feeder, "MUSIC_LEAD_IN_BUMPERS_RANGE", (2, 2)),
                patch.object(feeder, "MUSIC_BUMPERS_AFTER_TALK_RANGE", (3, 3)),
            ):
                entries = feeder.build_playlist("sonic_archaeology", "2026-05-08_0900")

        types = [entry["type"] for entry in entries]
        self.assertEqual(
            types,
            [
                "bumper", "bumper",
                "talk",
                "bumper", "bumper", "bumper",
                "talk",
                "bumper", "bumper", "bumper",
            ],
        )
        self.assertEqual(types.count("talk"), 2)
        self.assertGreater(types.count("bumper"), types.count("talk"))

    def test_music_only_playlist_uses_more_than_three_tracks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            talk_root = root / "talk_segments"
            bumper_root = root / "music_bumpers"
            show_bumpers = bumper_root / "midnight_signal"
            show_bumpers.mkdir(parents=True)

            for i in range(6):
                (show_bumpers / f"midnight_signal_bumper_{i}.flac").write_bytes(b"")

            with (
                patch.object(feeder, "TALK_DIR", talk_root),
                patch.object(feeder, "BUMPER_DIR", bumper_root),
                patch.object(
                    feeder,
                    "STATION",
                    SimpleNamespace(id="test-fm", call_sign="TEST-FM", output_dir=root),
                ),
                patch.object(feeder, "SILENCE_FILE", root / "silence.wav"),
                patch.object(feeder, "HISTORY_ENABLED", False),
                patch.object(feeder, "MUSIC_ONLY_TRACK_LIMIT", 6),
            ):
                entries = feeder.build_playlist("midnight_signal", "2026-05-08_0000")

        types = [entry["type"] for entry in entries]
        self.assertEqual(types.count("bumper"), 6)
        self.assertEqual(types[-1], "silence")

    def test_playlist_ignores_content_outside_station_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            station_root = root / "station"
            shared_root = root / "shared"
            talk_root = station_root / "talk_segments"
            bumper_root = station_root / "music_bumpers"
            slot_dir = talk_root / "sonic_archaeology" / "2026-05-08_0900"
            show_bumpers = bumper_root / "sonic_archaeology"
            shared_slot = shared_root / "talk_segments"
            shared_music = shared_root / "music_bumpers"
            slot_dir.mkdir(parents=True)
            show_bumpers.mkdir(parents=True)
            shared_slot.mkdir(parents=True)
            shared_music.mkdir(parents=True)

            station_talk = slot_dir / "00_deep_dive_station.wav"
            station_bumper = show_bumpers / "sonic_archaeology_bumper_station.flac"
            shared_talk = shared_slot / "00_deep_dive_shared.wav"
            shared_bumper = shared_music / "shared_bumper.flac"
            station_talk.write_bytes(b"")
            station_bumper.write_bytes(b"")
            shared_talk.write_bytes(b"")
            shared_bumper.write_bytes(b"")
            (slot_dir / "01_deep_dive_shared.wav").symlink_to(shared_talk)
            (show_bumpers / "sonic_archaeology_bumper_shared.flac").symlink_to(shared_bumper)

            with (
                patch.object(feeder, "TALK_DIR", talk_root),
                patch.object(feeder, "BUMPER_DIR", bumper_root),
                patch.object(
                    feeder,
                    "STATION",
                    SimpleNamespace(id="test-fm", call_sign="TEST-FM", output_dir=station_root),
                ),
                patch.object(feeder, "HISTORY_ENABLED", False),
                patch.object(feeder, "TALK_SEGMENTS_PER_PLAYLIST", 3),
                patch.object(feeder, "MUSIC_LEAD_IN_BUMPERS_RANGE", (1, 1)),
                patch.object(feeder, "MUSIC_BUMPERS_AFTER_TALK_RANGE", (1, 1)),
            ):
                entries = feeder.build_playlist("sonic_archaeology", "2026-05-08_0900")

        paths = [Path(entry["path"]).name for entry in entries]
        self.assertIn("00_deep_dive_station.wav", paths)
        self.assertIn("sonic_archaeology_bumper_station.flac", paths)
        self.assertNotIn("01_deep_dive_shared.wav", paths)
        self.assertNotIn("sonic_archaeology_bumper_shared.flac", paths)

    def test_bumpers_ignore_mismatched_station_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bumper_root = root / "music_bumpers"
            show_bumpers = bumper_root / "stack_trace_after_dark"
            show_bumpers.mkdir(parents=True)
            local_bumper = show_bumpers / "stack_trace_after_dark_bumper_local.flac"
            foreign_bumper = show_bumpers / "stack_trace_after_dark_bumper_foreign.flac"
            wrong_show_bumper = show_bumpers / "sonic_archaeology_bumper_foreign.flac"
            local_bumper.write_bytes(b"")
            foreign_bumper.write_bytes(b"")
            wrong_show_bumper.write_bytes(b"")
            local_bumper.with_suffix(".json").write_text(
                '{"station_id": "cdex-fm", "show_id": "stack_trace_after_dark"}'
            )
            foreign_bumper.with_suffix(".json").write_text(
                '{"station_id": "klod-fm", "show_id": "stack_trace_after_dark"}'
            )
            wrong_show_bumper.with_suffix(".json").write_text(
                '{"station_id": "cdex-fm", "show_id": "sonic_archaeology"}'
            )

            with (
                patch.object(feeder, "BUMPER_DIR", bumper_root),
                patch.object(
                    feeder,
                    "STATION",
                    SimpleNamespace(id="cdex-fm", call_sign="CDEX-FM", output_dir=root),
                ),
                patch.object(feeder, "HISTORY_ENABLED", False),
            ):
                bumpers = feeder.get_bumpers("stack_trace_after_dark")

        self.assertEqual([b.name for b in bumpers], ["stack_trace_after_dark_bumper_local.flac"])


if __name__ == "__main__":
    unittest.main()
