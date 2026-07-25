from django.test import SimpleTestCase

from pipeline.metrics import (
    flight_comparison_is_publishable,
    flight_source_key,
    normalise_sar_count,
    sar_percentage_change,
)


class SARMetricTests(SimpleTestCase):
    def test_hormuz_counts_are_compared_after_coverage_normalisation(self):
        self.assertAlmostEqual(normalise_sar_count(100, 0.8123962263), 123.093, places=3)
        self.assertAlmostEqual(
            sar_percentage_change(100, 0.8123962263, 123.6), -0.410, places=3
        )

    def test_missing_coverage_does_not_create_a_percentage(self):
        self.assertIsNone(normalise_sar_count(100, 0))
        self.assertIsNone(sar_percentage_change(100, None, 123.6))

    def test_low_coverage_scene_cannot_make_a_change_claim(self):
        self.assertEqual(normalise_sar_count(0, 0.1), 0)
        self.assertIsNone(sar_percentage_change(0, 0.1, 63))


class FlightPublicationGateTests(SimpleTestCase):
    def test_explicit_source_tag_is_required(self):
        self.assertIsNone(flight_source_key("OpenSky API returned a successful response"))
        self.assertEqual(
            flight_source_key("source=opensky; OpenSky API returned a successful response"),
            "opensky",
        )

    def test_legacy_baseline_is_not_publishable(self):
        self.assertFalse(
            flight_comparison_is_publishable(
                observation_state="observed",
                coverage_note="Legacy row: retrieval state was not recorded",
                baseline=4.375,
                pct_change=5454.3,
            )
        )

    def test_verified_source_matched_comparison_is_publishable(self):
        self.assertTrue(
            flight_comparison_is_publishable(
                observation_state="observed",
                coverage_note="source=opensky; successful response",
                baseline=500,
                pct_change=-20,
            )
        )
