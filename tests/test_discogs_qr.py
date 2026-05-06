import unittest
from unittest.mock import patch

from mac import discogs_lookup, qr_generator


class DiscogsQrTests(unittest.TestCase):
    def test_discogs_lookup_disabled_without_credentials(self):
        with patch.object(discogs_lookup, "HAS_CREDENTIALS", False):
            self.assertIsNone(discogs_lookup.search_discogs("Track"))

    def test_qr_data_url_when_qrcode_available(self):
        result = qr_generator.generate_qr_data_url("https://example.com")
        if qr_generator.HAS_QRCODE:
            self.assertTrue(result.startswith("data:image/png;base64,"))
        else:
            self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
