"""Shared constants for the duty-scheduling app."""

from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
DB_PATH = DATA_DIR / "app.db"

STAFF_XLSX = DATA_DIR / "staff_data.xlsx"
DUTY_WEIGHT_XLSX = DATA_DIR / "duty_weight_data.xlsx"

# Canonical (ASCII) base identifiers used internally / in the DB.
# Vietnamese display labels are only used at the UI layer.
BASE_HANOI = "Ha Noi"
BASE_NINH_BINH = "Ninh Binh"
BASES = (BASE_HANOI, BASE_NINH_BINH)

BASE_LABELS = {
    BASE_HANOI: "Hà Nội",
    BASE_NINH_BINH: "Ninh Bình",
}

# Short labels for the calendar's per-day split cells.
BASE_SHORT_LABELS = {
    BASE_HANOI: "CSHN",
    BASE_NINH_BINH: "CSNB",
}

# One-way base-exchange multiplier: applies only when a Ha-Noi-home staff
# member is assigned to work at the Ninh Binh base (see notes.md worked
# example; confirmed with the user as one-directional).
EXCHANGE_MULTIPLIER_DUTY_CODE = 9

# Half-day duty (weekend Saturday/Sunday, or a holiday): weight is this
# row's multiplier times the normal full-day weight for that day. Stacks
# with the exchange multiplier above when both apply to the same
# assignment.
HALF_DAY_DUTY_CODE = 10

WEEKDAY_LABELS = ("T2", "T3", "T4", "T5", "T6", "T7", "CN")  # Monday-start, matches date.weekday()

TRINH_DO_OPTIONS = ("Cao đẳng", "Đại học")
GIOI_TINH_OPTIONS = ("Nam", "Nữ")

# Any vi_tri not containing this substring is grouped as "Nội trú".
NHA_THUOC_KEYWORD = "Nhà thuốc"

# Number of trailing months (before the reference month) included in the
# accumulated-weight calculation, per notes.md ("last 2 months").
N_TRAILING_MONTHS = 2
