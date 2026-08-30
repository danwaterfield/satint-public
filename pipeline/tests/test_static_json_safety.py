from datetime import date
import math
from pathlib import Path
import tempfile
from unittest.mock import patch

import pandas as pd
from django.test import SimpleTestCase

from pipeline.management.commands.export_static import Command


class ExportStaticJSONTests(SimpleTestCase):
    def test_writer_rejects_non_finite_numbers(self):
        command = Command()
        command._written_files = []

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            with self.assertRaises(ValueError):
                command._write(path, {"value": math.nan})


class ExportStaticUpstreamMarketTests(SimpleTestCase):
    @patch("pipeline.clients.upstream_market._fetch_history")
    def test_market_reference_omits_unclosed_nan_rows(self, fetch_history):
        from pipeline.clients.upstream_market import fetch_upstream_market_reference

        index = pd.to_datetime(["2026-01-15", "2026-08-28"])
        histories = {
            "BZ=F": pd.DataFrame({"Close": [80.0, math.nan]}, index=index),
            "HO=F": pd.DataFrame({"Close": [2.5, math.nan]}, index=index),
            "RB=F": pd.DataFrame({"Close": [2.2, math.nan]}, index=index),
            "NZDUSD=X": pd.DataFrame({"Close": [0.6, math.nan]}, index=index),
        }
        fetch_history.side_effect = lambda symbol, *_: histories[symbol]

        payload = fetch_upstream_market_reference(
            start_date=date(2026, 1, 15),
            end_date=date(2026, 8, 28),
        )

        self.assertEqual([row["date"] for row in payload["nzdusd"]], ["2026-01-15"])
        for key in ("brent_crude", "heating_oil_futures", "rbob_gasoline_futures"):
            self.assertEqual([row["date"] for row in payload[key]], ["2026-01-15"])
            self.assertTrue(math.isfinite(payload[key][0]["close_usd"]))
            self.assertTrue(math.isfinite(payload[key][0]["nzd_litre"]))
