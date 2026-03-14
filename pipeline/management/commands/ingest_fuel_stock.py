"""
Management command: ingest_fuel_stock

Manual entry of MBIE fuel stock levels for NZ.

Usage:
    python manage.py ingest_fuel_stock --date 2026-03-08 \\
        --petrol-onshore 32.8 --petrol-water 25.2 \\
        --diesel-onshore 27.6 --diesel-water 22.3 \\
        --jet-onshore 32.3 --jet-water 14.3
"""

from datetime import date

from django.core.management.base import BaseCommand, CommandError

from pipeline.models import FuelStockLevel

# MSO minimums (since Jan 2025)
MSO_MINIMUMS = {
    "petrol": 28.0,
    "diesel": 21.0,
    "jet": 24.0,
}


class Command(BaseCommand):
    help = "Manually enter MBIE fuel stock levels for NZ"

    def add_arguments(self, parser):
        parser.add_argument("--date", required=True, help="Stock date (YYYY-MM-DD)")
        parser.add_argument("--petrol-onshore", type=float, help="Petrol onshore days")
        parser.add_argument("--petrol-water", type=float, help="Petrol on-water days")
        parser.add_argument("--diesel-onshore", type=float, help="Diesel onshore days")
        parser.add_argument("--diesel-water", type=float, help="Diesel on-water days")
        parser.add_argument("--jet-onshore", type=float, help="Jet fuel onshore days")
        parser.add_argument("--jet-water", type=float, help="Jet fuel on-water days")

    def handle(self, *args, **options):
        try:
            stock_date = date.fromisoformat(options["date"])
        except ValueError:
            raise CommandError("Invalid date format. Use YYYY-MM-DD")

        fuel_data = {
            "petrol": (options.get("petrol_onshore"), options.get("petrol_water")),
            "diesel": (options.get("diesel_onshore"), options.get("diesel_water")),
            "jet": (options.get("jet_onshore"), options.get("jet_water")),
        }

        created = 0
        for fuel_type, (onshore, on_water) in fuel_data.items():
            if onshore is None and on_water is None:
                continue

            mso = MSO_MINIMUMS.get(fuel_type)

            if onshore is not None:
                FuelStockLevel.objects.update_or_create(
                    date=stock_date,
                    fuel_type=fuel_type,
                    stock_type="onshore",
                    defaults={
                        "days_of_supply": onshore,
                        "mso_minimum_days": mso,
                    },
                )
                created += 1
                self.stdout.write(
                    f"  {fuel_type:7} onshore: {onshore:.1f} days "
                    f"(MSO min: {mso} → margin: {onshore - mso:+.1f} days)"
                )

            if on_water is not None:
                FuelStockLevel.objects.update_or_create(
                    date=stock_date,
                    fuel_type=fuel_type,
                    stock_type="on_water",
                    defaults={
                        "days_of_supply": on_water,
                        "mso_minimum_days": None,
                    },
                )
                created += 1
                self.stdout.write(f"  {fuel_type:7} on-water: {on_water:.1f} days")

            if onshore is not None and on_water is not None:
                total = onshore + on_water
                FuelStockLevel.objects.update_or_create(
                    date=stock_date,
                    fuel_type=fuel_type,
                    stock_type="total",
                    defaults={
                        "days_of_supply": total,
                        "mso_minimum_days": mso,
                    },
                )
                created += 1
                self.stdout.write(f"  {fuel_type:7} total:   {total:.1f} days")

        self.stdout.write(
            self.style.SUCCESS(f"\nCreated/updated {created} stock records for {stock_date}")
        )
