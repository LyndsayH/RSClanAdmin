import csv
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

CSV_FILE = Path("inactives_export.csv")
INACTIVE_CUTOFF_DAYS = 30

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
}


def supabase_url(table: str) -> str:
    return f"{SUPABASE_URL}/rest/v1/{table}"


def normalise_header(value: str) -> str:
    return value.strip().lower().replace(" ", "_")


def parse_days_since(value: str):
    if value is None:
        return None

    value = str(value).strip()

    if value == "":
        return None

    if value.lower() == "never":
        return 99999

    if value.lower() == "today":
        return 0

    try:
        return int(float(value))
    except ValueError:
        return None


def read_inactives_csv() -> list[dict]:
    if not CSV_FILE.exists():
        raise FileNotFoundError(f"Could not find {CSV_FILE.resolve()}")

    rows = []

    with CSV_FILE.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)

        if not reader.fieldnames:
            raise ValueError("CSV has no headers.")

        header_map = {normalise_header(h): h for h in reader.fieldnames}

        clanmate_col = (
            header_map.get("clanmate")
            or header_map.get("name")
            or header_map.get("player")
        )

        days_col = (
            header_map.get("days_since")
            or header_map.get("days")
            or header_map.get("days_inactive")
        )

        reason_col = header_map.get("reason")

        if not clanmate_col:
            raise ValueError(
                f"Could not find Clanmate column. Headers found: {reader.fieldnames}"
            )

        if not days_col:
            raise ValueError(
                f"Could not find Days Since column. Headers found: {reader.fieldnames}"
            )

        for raw in reader:
            clanmate = (raw.get(clanmate_col) or "").strip()
            if not clanmate:
                continue

            days_since = parse_days_since(raw.get(days_col, ""))

            reason = ""
            if reason_col:
                reason = (raw.get(reason_col) or "").strip()

            rows.append(
                {
                    "current_name": clanmate,
                    "days_since": days_since,
                    "reason": reason,
                }
            )

    return rows


def chunked(items, size=500):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def upsert_players(rows: list[dict]) -> None:
    payload = []

    for row in rows:
        days_since = row["days_since"]

        if days_since is not None and days_since >= INACTIVE_CUTOFF_DAYS:
            collection_status = "inactive"
            collect_skills = False
            note = (
                f"Seeded from spreadsheet Inactives list. "
                f"Days since active: {days_since}. "
                f"Reason: {row['reason']}"
            )
        else:
            collection_status = "active"
            collect_skills = True
            note = (
                f"Present in Inactives export but below {INACTIVE_CUTOFF_DAYS}-day cutoff. "
                f"Days since active: {days_since}. "
                f"Reason: {row['reason']}"
            )

        payload.append(
            {
                "current_name": row["current_name"],
                "collection_status": collection_status,
                "collect_skills": collect_skills,
                "is_current_clan_member": True,
                "notes": note,
            }
        )

    for batch in chunked(payload, 500):
        response = requests.post(
            supabase_url("players"),
            headers={
                **HEADERS,
                "Prefer": "resolution=merge-duplicates,return=representation",
            },
            params={"on_conflict": "current_name"},
            json=batch,
            timeout=60,
        )

        response.raise_for_status()


def main() -> None:
    print(f"Reading {CSV_FILE}...")
    rows = read_inactives_csv()

    print(f"Rows read: {len(rows):,}")

    over_cutoff = [
        r for r in rows
        if r["days_since"] is not None and r["days_since"] >= INACTIVE_CUTOFF_DAYS
    ]

    under_cutoff = [
        r for r in rows
        if r["days_since"] is None or r["days_since"] < INACTIVE_CUTOFF_DAYS
    ]

    print(f"Will mark inactive / total-only: {len(over_cutoff):,}")
    print(f"Will leave active / skill-tracked: {len(under_cutoff):,}")

    upsert_players(rows)

    print("Inactive import complete.")


if __name__ == "__main__":
    main()