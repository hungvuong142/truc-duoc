"""Builds the "Bảng phân công trực" .docx from a local Assignment CSV (see
scripts/export_assignments_csv.py) instead of the Streamlit UI, so layout
tweaks in app/docx_export.py can be checked by just opening a file --
staff names/trinh_do still come from the local DB (data/app.db) since the
CSV only carries Assignment rows.

Usage:
    uv run python scripts/preview_roster_docx.py
    uv run python scripts/preview_roster_docx.py --csv path/to/other.csv --month 10 --year 2026 --out outputs/test.docx
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import repository  # noqa: E402
from app.config import BASE_HANOI, BASE_NINH_BINH  # noqa: E402
from app.docx_export import build_roster_document  # noqa: E402
from app.logic.roster_export import build_roster_rows  # noqa: E402
from app.logic.types import AssignmentRecord  # noqa: E402
from scripts.export_assignments_csv import DEFAULT_MONTH, DEFAULT_YEAR, default_csv_path  # noqa: E402

DEFAULT_OUT_PATH = Path(__file__).resolve().parent.parent / "outputs" / "roster_preview.docx"


def _load_assignments_csv(path: Path) -> list[AssignmentRecord]:
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [
            AssignmentRecord(
                duty_date=date.fromisoformat(row["duty_date"]),
                base=row["base"],
                staff_id=row["staff_id"],
                is_half_day=row["is_half_day"].strip().lower() == "true",
            )
            for row in reader
        ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=None, help="Defaults to scripts/sample_data/assignments_YYYY_MM.csv")
    parser.add_argument("--month", type=int, default=DEFAULT_MONTH)
    parser.add_argument("--year", type=int, default=DEFAULT_YEAR)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_PATH)
    args = parser.parse_args()

    csv_path = args.csv or default_csv_path(args.year, args.month)
    assignments = _load_assignments_csv(csv_path)
    staff_by_id = repository.get_all_staff_by_id()

    tables = {
        base: build_roster_rows(assignments, staff_by_id, base, args.year, args.month)
        for base in (BASE_HANOI, BASE_NINH_BINH)
    }
    doc = build_roster_document(args.month, args.year, tables, datetime.now())

    args.out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(args.out)
    print(f"Read {len(assignments)} assignment rows from {csv_path}")
    print(f"Saved {args.out}")


if __name__ == "__main__":
    main()
