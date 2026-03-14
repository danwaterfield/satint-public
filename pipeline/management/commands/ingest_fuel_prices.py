"""
Management command: ingest_fuel_prices

Ingests MBIE weekly fuel price data from CSV (local file or attempted download).

Usage:
    python manage.py ingest_fuel_prices                    # try automated download
    python manage.py ingest_fuel_prices --csv path/to.csv  # from local file
"""

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Avg

from pipeline.clients.mbie_fuel import fetch_mbie_csv, parse_fuel_csv
from pipeline.models import FuelPriceObservation


class Command(BaseCommand):
    help = "Ingest MBIE weekly fuel prices from CSV"

    def add_arguments(self, parser):
        parser.add_argument(
            "--csv",
            help="Path to local MBIE weekly-table.csv file",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse and display but don't save to DB",
        )

    def handle(self, *args, **options):
        csv_path = options.get("csv")
        dry_run = options["dry_run"]

        if csv_path:
            try:
                with open(csv_path) as f:
                    csv_text = f.read()
            except FileNotFoundError:
                raise CommandError(f"File not found: {csv_path}")
            self.stdout.write(f"Reading from {csv_path}")
        else:
            self.stdout.write("Attempting MBIE CSV download...")
            csv_text = fetch_mbie_csv()
            if csv_text is None:
                raise CommandError(
                    "Could not download MBIE CSV. Use --csv to provide a local file.\n"
                    "Download manually from: https://www.mbie.govt.nz/building-and-energy/"
                    "energy-and-natural-resources/energy-statistics-and-modelling/"
                    "energy-statistics/weekly-fuel-price-monitoring/"
                )
            self.stdout.write(self.style.SUCCESS("Downloaded MBIE CSV"))

        records = parse_fuel_csv(csv_text)
        if not records:
            raise CommandError("No valid fuel price records found in CSV")

        self.stdout.write(f"Parsed {len(records)} records")

        # Compute baselines (pre-war average: before 2026-02-28)
        from datetime import date
        war_start = date(2026, 2, 28)

        # Get pre-war averages per fuel type from existing DB or this batch
        baselines = {}
        for fuel_type in ("91", "95", "diesel"):
            # First check DB
            db_baseline = FuelPriceObservation.objects.filter(
                fuel_type=fuel_type, date__lt=war_start,
            ).aggregate(avg=Avg("retail_price_nzd"))["avg"]

            if db_baseline:
                baselines[fuel_type] = db_baseline
            else:
                # Compute from this batch
                pre_war = [r["retail_price_nzd"] for r in records
                           if r["fuel_type"] == fuel_type and r["date"] < war_start]
                if pre_war:
                    baselines[fuel_type] = sum(pre_war) / len(pre_war)

        saved = 0
        for r in records:
            baseline = baselines.get(r["fuel_type"])
            pct_change = None
            if baseline and baseline > 0:
                pct_change = round((r["retail_price_nzd"] - baseline) / baseline * 100, 2)

            if dry_run:
                self.stdout.write(
                    f"  {r['date']}  {r['fuel_type']:6}  "
                    f"${r['retail_price_nzd']:.3f}/L  "
                    f"{'%+.1f%%' % pct_change if pct_change is not None else 'n/a'}"
                )
            else:
                FuelPriceObservation.objects.update_or_create(
                    date=r["date"],
                    fuel_type=r["fuel_type"],
                    defaults={
                        "retail_price_nzd": r["retail_price_nzd"],
                        "import_cost_nzd": r["import_cost_nzd"],
                        "margin_nzd": r["margin_nzd"],
                        "baseline_price": baseline,
                        "pct_change": pct_change,
                    },
                )
                saved += 1

        self.stdout.write(
            self.style.SUCCESS(f"Saved {saved} fuel price observations")
            if not dry_run
            else f"Dry run: {len(records)} records parsed"
        )
