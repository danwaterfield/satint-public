from pathlib import Path
from unittest import TestCase


SITE_HTML = (Path(__file__).resolve().parents[1] / "docs" / "index.html").read_text()


class StaticChartContractTests(TestCase):
    def test_event_markers_cannot_expand_beyond_the_observed_date_range(self):
        self.assertIn("function eventsWithinDates(dates)", SITE_HTML)
        self.assertIn("shapes: makeEventShapes(dates)", SITE_HTML)
        self.assertNotIn("label: 'Major strikes'", SITE_HTML)
        self.assertNotIn("label: 'Grid collapse'", SITE_HTML)

    def test_sar_density_is_not_labelled_as_commercial_traffic(self):
        self.assertIn("Hormuz SAR Vessel Density", SITE_HTML)
        self.assertIn("Coverage-normalised detections", SITE_HTML)
        self.assertNotIn("Hormuz Vessel Traffic", SITE_HTML)

    def test_fuel_chart_uses_commercial_throughput(self):
        self.assertIn("load(DATA + '/maritime.json')", SITE_HTML)
        self.assertIn("function renderFuelMaritimeChart", SITE_HTML)
        self.assertNotIn("function renderFuelHormuzChart", SITE_HTML)

    def test_withheld_nz_nightlight_comparison_has_no_empty_axis(self):
        self.assertIn("var hasComparison = pct.some", SITE_HTML)
        self.assertIn("if (hasComparison) {\n    layout.yaxis2", SITE_HTML)
