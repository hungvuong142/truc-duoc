"""Dumps one month of Assignment rows to a local CSV -- a snapshot the
"Xuất file" roster export can be tested against without a live DB (see
scripts/preview_roster_docx.py, which reads this CSV back in).

Usage:
    uv run python scripts/export_assignments_csv.py
    uv run python scripts/export_assignments_csv.py --year 2026 --month 10 --out path/to/file.csv
"""

from __future__ import annotations

import argparse
import calendar
import csv
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import repository  # noqa: E402

DEFAULT_YEAR = 2026
DEFAULT_MONTH = 10
SAMPLE_DATA_DIR = Path(__file__).parent / "sample_data"
CSV_FIELDS = ["duty_date", "base", "staff_id", "is_half_day"]


def default_csv_path(year: int, month: int) -> Path:
    return SAMPLE_DATA_DIR / f"assignments_{year:04d}_{month:02d}.csv"


def export(year: int, month: int, out_path: Path) -> int:
    last_day = calendar.monthrange(year, month)[1]
    assignments = repository.get_assignments_for_range(date(year, month, 1), date(year, month, last_day))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for a in assignments:
            writer.writerow(
                {
                    "duty_date": a.duty_date.isoformat(),
                    "base": a.base,
                    "staff_id": a.staff_id,
                    "is_half_day": a.is_half_day,
                }
            )
    return len(assignments)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, default=DEFAULT_YEAR)
    parser.add_argument("--month", type=int, default=DEFAULT_MONTH)
    parser.add_argument("--out", type=Path, default=None, help="Defaults to scripts/sample_data/assignments_YYYY_MM.csv")
    args = parser.parse_args()

    out_path = args.out or default_csv_path(args.year, args.month)
    count = export(args.year, args.month, out_path)
    print(f"Wrote {count} assignment rows for {args.month:02d}/{args.year} to {out_path}")


if __name__ == "__main__":
    main()
