import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mac"))
import api_server  # noqa: E402


class FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 5, 5, 17, 0)


class ApiServerTests(unittest.TestCase):
    def test_schedule_upcoming_uses_exact_next_airings(self):
        with patch.object(api_server, "datetime", FixedDatetime):
            info = api_server.get_schedule_info()

        self.assertEqual(info["current"]["show_id"], "crosswire")
        self.assertEqual(info["upcoming"][0]["show_id"], "sonic_archaeology")
        self.assertEqual(info["upcoming"][0]["starts_around"], "18:00")
        self.assertEqual(info["upcoming"][0]["starts_at"], "2026-05-05T18:00:00")


if __name__ == "__main__":
    unittest.main()
