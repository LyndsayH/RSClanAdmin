import csv
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

CSV_FILE = Path("snapshots_export.csv")
ANOMALY_FILE = Path("import_anomalies.csv")

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
}


def supabase_url(table: str) -> str:
    return f"{SUPABASE_URL}/rest/v1/{table}"


def parse_date(value: str) -> str:
    value = value.strip()

    # Preferred Google Sheets export format, e.g. 2026-01-23
    try:
        return datetime.fromisoformat(value).date().isoformat()
    except ValueError:
        pass

    # Fallbacks, in case CSV export uses local display formatting
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue

    raise ValueError(f"Could not parse date: {value!r}")


def parse_xp(value: str) -> int:
    cleaned = value.replace(",", "").replace(" ", "").strip()
    return int(cleaned)


def chunked(items, size=500):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def read_csv_rows() -> list[dict]:
    if not CSV_FILE.exists():
        raise FileNotFoundError(f"Could not find {CSV_FILE.resolve()}")

    rows = []

    with CSV_FILE.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)

        required = {"snapshot_date", "clanmate", "experience"}
        found = set(reader.fieldnames or [])

        if not required.issubset(found):
            raise ValueError(
                f"CSV headers must include {required}. Found: {reader.fieldnames}"
            )

        for raw in reader:
            try:
                snapshot_date = parse_date(raw["snapshot_date"])
                clanmate = raw["clanmate"].strip()
                xp = parse_xp(raw["experience"])

                if not clanmate:
                    continue

                rows.append(
                    {
                        "snapshot_date": snapshot_date,
                        "clanmate": clanmate,
                        "total_xp": xp,
                    }
                )

            except Exception as e:
                rows.append(
                    {
                        "snapshot_date": None,
                        "clanmate": raw.get("clanmate", ""),
                        "total_xp": None,
                        "error": f"CSV parse error: {e}",
                        "raw": dict(raw),
                    }
                )

    return rows


def upsert_players(names: list[str]) -> dict[str, int]:
    unique_names = sorted(set(names))
    name_to_id = {}

    for batch in chunked(unique_names, 500):
        payload = [{"current_name": name} for name in batch]

        response = requests.post(
            supabase_url("players"),
            headers={
                **HEADERS,
                "Prefer": "resolution=merge-duplicates,return=representation",
            },
            params={"on_conflict": "current_name"},
            json=payload,
            timeout=60,
        )
        response.raise_for_status()

        for item in response.json():
            name_to_id[item["current_name"]] = item["id"]

    return name_to_id


def filter_anomalies(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    XP should never decrease for the same clanmate.
    Keep valid rows; log impossible decreases.
    """
    valid_parse_rows = [r for r in rows if "error" not in r]
    parse_errors = [r for r in rows if "error" in r]

    by_player = defaultdict(list)

    for row in valid_parse_rows:
        by_player[row["clanmate"]].append(row)

    cleaned = []
    anomalies = parse_errors[:]

    for clanmate, player_rows in by_player.items():
        player_rows.sort(key=lambda r: r["snapshot_date"])

        last_xp = None
        last_date = None

        for row in player_rows:
            xp = row["total_xp"]

            if last_xp is not None and xp < last_xp:
                anomalies.append(
                    {
                        "snapshot_date": row["snapshot_date"],
                        "clanmate": clanmate,
                        "total_xp": xp,
                        "error": (
                            f"XP decreased: {xp} < previous {last_xp} "
                            f"from {last_date}"
                        ),
                    }
                )
                continue

            cleaned.append(row)
            last_xp = xp
            last_date = row["snapshot_date"]

    return cleaned, anomalies


def write_anomalies(anomalies: list[dict]) -> None:
    if not anomalies:
        if ANOMALY_FILE.exists():
            ANOMALY_FILE.unlink()
        return

    with ANOMALY_FILE.open("w", encoding="utf-8", newline="") as f:
        fieldnames = ["snapshot_date", "clanmate", "total_xp", "error"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for row in anomalies:
            writer.writerow(
                {
                    "snapshot_date": row.get("snapshot_date", ""),
                    "clanmate": row.get("clanmate", ""),
                    "total_xp": row.get("total_xp", ""),
                    "error": row.get("error", ""),
                }
            )


def upsert_total_snapshots(rows: list[dict], name_to_id: dict[str, int]) -> None:
    payload = []

    for row in rows:
        player_id = name_to_id.get(row["clanmate"])

        if not player_id:
            continue

        payload.append(
            {
                "snapshot_date": row["snapshot_date"],
                "player_id": player_id,
                "total_xp": row["total_xp"],
                "source": "google_sheet_import",
                "notes": "Imported from Google Sheets Snapshots_Export CSV",
            }
        )

    for batch in chunked(payload, 500):
        response = requests.post(
            supabase_url("total_xp_snapshots"),
            headers={
                **HEADERS,
                "Prefer": "resolution=merge-duplicates,return=representation",
            },
            params={"on_conflict": "snapshot_date,player_id"},
            json=batch,
            timeout=60,
        )
        response.raise_for_status()


def main() -> None:
    print(f"Reading {CSV_FILE}...")
    rows = read_csv_rows()
    print(f"Rows read: {len(rows):,}")

    cleaned_rows, anomalies = filter_anomalies(rows)
    print(f"Clean rows: {len(cleaned_rows):,}")
    print(f"Anomalies skipped: {len(anomalies):,}")

    write_anomalies(anomalies)

    names = [r["clanmate"] for r in cleaned_rows]
    print(f"Unique clanmates: {len(set(names)):,}")

    print("Upserting players...")
    name_to_id = upsert_players(names)

    print("Upserting total XP snapshots...")
    upsert_total_snapshots(cleaned_rows, name_to_id)

    print("Import complete.")

    if anomalies:
        print(f"Anomaly report written to: {ANOMALY_FILE.resolve()}")


if __name__ == "__main__":
    main()