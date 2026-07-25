from datetime import date
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from pipeline.clients.windward import fetch_windward_daily, parse_windward_text


class WindwardParserTests(SimpleTestCase):
    def test_hormuz_transits_are_not_confused_with_gulf_presence(self):
        text = (
            "Strait of Hormuz remains limited. On March 23, five "
            "AIS-transmitting vessels were recorded transiting the Strait. "
            "Gulf vessel presence increased to 681 AIS-transmitting foreign vessels."
        )

        result = parse_windward_text(text)

        self.assertEqual(result["hormuz"]["crossings"], 5)

    @patch("pipeline.clients.windward.requests.get")
    def test_requested_url_uses_the_target_month(self, get):
        get.return_value = Mock(status_code=404)

        result = fetch_windward_daily(date(2026, 7, 24))

        self.assertIsNone(result)
        requested_urls = [call.args[0] for call in get.call_args_list]
        self.assertTrue(requested_urls)
        self.assertTrue(all("/july-24-" in url for url in requested_urls))

    def test_implausible_crossing_count_is_rejected(self):
        result = parse_windward_text(
            "Strait of Hormuz traffic reported 681 crossings."
        )

        self.assertNotIn("hormuz", result)
