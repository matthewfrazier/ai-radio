import tempfile
import unittest
from pathlib import Path
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
                (show_bumpers / f"bumper_{i}.flac").write_bytes(b"")

            with (
                patch.object(feeder, "TALK_DIR", talk_root),
                patch.object(feeder, "BUMPER_DIR", bumper_root),
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
                (show_bumpers / f"bumper_{i}.flac").write_bytes(b"")

            with (
                patch.object(feeder, "TALK_DIR", talk_root),
                patch.object(feeder, "BUMPER_DIR", bumper_root),
                patch.object(feeder, "SILENCE_FILE", root / "silence.wav"),
                patch.object(feeder, "HISTORY_ENABLED", False),
                patch.object(feeder, "MUSIC_ONLY_TRACK_LIMIT", 6),
            ):
                entries = feeder.build_playlist("midnight_signal", "2026-05-08_0000")

        types = [entry["type"] for entry in entries]
        self.assertEqual(types.count("bumper"), 6)
        self.assertEqual(types[-1], "silence")


if __name__ == "__main__":
    unittest.main()
