import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mac.content_generator import music_bumper_generator


def _caption_texts(pool):
    texts = set()
    for entry in pool:
        if isinstance(entry, dict):
            texts.add(entry["caption"])
            texts.add(entry["lyrics"])
        else:
            texts.add(entry)
    return texts


class MusicBumperGeneratorTests(unittest.TestCase):
    def test_cdex_music_pools_do_not_share_claude_show_ids_or_prompts(self):
        claude_music = music_bumper_generator.show_music_for_station("klod-fm")
        cdex_music = music_bumper_generator.show_music_for_station("cdex-fm")

        self.assertFalse(set(claude_music) & set(cdex_music))
        self.assertIn("stack_trace_after_dark", cdex_music)
        self.assertIn("protocol_archaeology", cdex_music)

        claude_texts = set().union(*(_caption_texts(pool) for pool in claude_music.values()))
        cdex_texts = set().union(*(_caption_texts(pool) for pool in cdex_music.values()))
        self.assertFalse(claude_texts & cdex_texts)

    def test_bumper_count_ignores_foreign_show_filenames(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            show_dir = root / "protocol_archaeology"
            show_dir.mkdir()
            (show_dir / "protocol_archaeology_bumper_20260511.flac").write_bytes(b"")
            (show_dir / "sonic_archaeology_bumper_20260511.flac").write_bytes(b"")

            with patch.object(music_bumper_generator, "BUMPERS_DIR", root):
                count = music_bumper_generator.bumper_count("protocol_archaeology")

        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
