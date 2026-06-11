import csv
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

CSV_FILE = Path("hiscore_corrections.csv")

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
}


def supabase_url(table: str) -> str:
    return f"{SUPABASE_URL}/rest/v1/{table}"


def read_corrections() -> list[dict]:
    if not CSV_FILE.exists():
        raise FileNotFoundError(f"Could not find {CSV_FILE.resolve()}")

    rows = []

    with CSV_FILE.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)

        required = {"current_name", "hiscore_lookup_name"}
        found = set(reader.fieldnames or [])

        if not required.issubset(found):
            raise ValueError(
                f"CSV headers must include {required}. Found: {reader.fieldnames}"
            )

        for raw in reader:
            current_name = (raw.get("current_name") or "").strip()
            hiscore_lookup_name = (raw.get("hiscore_lookup_name") or "").strip()

            if not current_name or not hiscore_lookup_name:
                continue

            rows.append(
                {
                    "current_name": current_name,
                    "hiscore_lookup_name": hiscore_lookup_name,
                }
            )

    return rows


def update_player(current_name: str, hiscore_lookup_name: str) -> None:
    payload = {
        "hiscore_lookup_name": hiscore_lookup_name,
        "hiscore_lookup_status": "unknown",
        "hiscore_last_error": None,
    }

    response = requests.patch(
        supabase_url("players"),
        headers=HEADERS,
        params={"current_name": f"eq.{current_name}"},
        json=payload,
        timeout=30,
    )

    if not response.ok:
        print("Failed update:")
        print("Current name:", current_name)
        print("Lookup name:", hiscore_lookup_name)
        print("Status code:", response.status_code)
        print("Response text:", response.text)
        raise RuntimeError("Correction update failed")


def main() -> None:
    rows = read_corrections()
    print(f"Corrections read: {len(rows):,}")

    for row in rows:
        update_player(row["current_name"], row["hiscore_lookup_name"])
        print(f"UPDATED: {row['current_name']} -> {row['hiscore_lookup_name']}")

    print("Hiscore corrections import complete.")


if __name__ == "__main__":
    main()