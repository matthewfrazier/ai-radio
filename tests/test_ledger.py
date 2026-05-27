import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mac" / "content_generator"))
import ledger  # noqa: E402


class LedgerReactionTests(unittest.TestCase):
    def test_add_listener_reaction_writes_operator_event(self):
        old_home = ledger.WRIT_HOME
        old_ledger_path = ledger.LEDGER_PATH

        with tempfile.TemporaryDirectory() as tmp:
            try:
                ledger.WRIT_HOME = Path(tmp)
                ledger.LEDGER_PATH = Path(tmp) / "station_ledger.jsonl"

                added = ledger.add_listener_reaction(
                    "more_like_this",
                    "more like this",
                    {
                        "track": "Leon Bridges Style",
                        "type": "bumper",
                        "show_id": "the_groove_lab",
                        "show": "The Groove Lab",
                        "host": "ember",
                        "caption": "soul groove, warm horns",
                        "slot": "2026-05-26_2000",
                        "timestamp": "2026-05-26T20:44:52",
                    },
                    "abc123",
                )

                self.assertTrue(added)
                events = [json.loads(line) for line in ledger.LEDGER_PATH.read_text().splitlines()]
                self.assertEqual(len(events), 1)
                event = events[0]
                self.assertEqual(event["type"], "listener_reaction")
                self.assertEqual(event["reaction"], "more_like_this")
                self.assertEqual(event["track"], "Leon Bridges Style")
                self.assertEqual(event["show_id"], "the_groove_lab")
                self.assertIn("listener_reaction", event["tags"])
                self.assertIn("more_like_this", event["tags"])
                self.assertIn("operator_note", event)
            finally:
                ledger.WRIT_HOME = old_home
                ledger.LEDGER_PATH = old_ledger_path


if __name__ == "__main__":
    unittest.main()
