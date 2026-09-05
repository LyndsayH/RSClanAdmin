import csv
import os
from datetime import date
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

SNAPSHOT_DATE = date.today().isoformat()
FAILED_LOOKUPS_FILE = Path(f"failed_hiscores_{SNAPSHOT_DATE}.csv")

HISCORES_URL = "https://secure.runescape.com/m=hiscore/index_lite.ws"

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
}

# RuneScape hiscores:
# row 0 = overall
# rows 1–29 = skills
SKILL_LINE_TO_ID = {
    1: 0,    # Attack
    2: 1,    # Defence
    3: 2,    # Strength
    4: 3,    # Constitution
    5: 4,    # Ranged
    6: 5,    # Prayer
    7: 6,    # Magic
    8: 7,    # Cooking
    9: 8,    # Woodcutting
    10: 9,   # Fletching
    11: 10,  # Fishing
    12: 11,  # Firemaking
    13: 12,  # Crafting
    14: 13,  # Smithing
    15: 14,  # Mining
    16: 15,  # Herblore
    17: 16,  # Agility
    18: 17,  # Thieving
    19: 18,  # Slayer
    20: 19,  # Farming
    21: 20,  # Runecrafting
    22: 21,  # Hunter
    23: 22,  # Construction
    24: 23,  # Summoning
    25: 24,  # Dungeoneering
    26: 25,  # Divination
    27: 26,  # Invention
    28: 27,  # Archaeology
    29: 28,  # Necromancy
}


def supabase_url(table: str) -> str:
    return f"{SUPABASE_URL}/rest/v1/{table}"


def get_players_to_collect() -> list[dict]:
    """
    Pulls skill-collection candidates from Supabase.

    We collect skills for:
    - current clan members
    - where collect_skills is true
    - or watchlist is true
    """
    response = requests.get(
        supabase_url("players"),
        headers=HEADERS,
        params={
            "select": "id,current_name,hiscore_lookup_name,collection_status,collect_skills,watchlist",
            "is_current_clan_member": "eq.true",
            "or": "(collect_skills.eq.true,watchlist.eq.true)",
            "order": "current_name.asc",
            "limit": "10000",
        },
        timeout=60,
    )

    if not response.ok:
        print("Failed to fetch players to collect")
        print("Status code:", response.status_code)
        print("Response text:", response.text)
        raise RuntimeError("Could not fetch players to collect")

    return response.json()

def hiscore_name_candidates(player_name: str) -> list[str]:
    """
    Generate safe lookup variants for RuneScape hiscores.

    The clan API / Sheets imports can contain:
    - non-breaking spaces: \u00a0
    - replacement characters: � / \ufffd

    Hiscores generally expects normal spaces.
    """
    candidates = []

    def add(value: str) -> None:
        value = " ".join(value.strip().split())
        if value and value not in candidates:
            candidates.append(value)

    add(player_name)

    cleaned = (
        player_name
        .replace("\u00a0", " ")
        .replace("\ufffd", " ")
        .replace("�", " ")
    )

    add(cleaned)

    return candidates


def fetch_hiscores(player_name: str) -> list[list[int]]:
    last_error = None

    for lookup_name in hiscore_name_candidates(player_name):
        try:
            response = requests.get(
                HISCORES_URL,
                params={"player": lookup_name},
                timeout=30,
            )

            response.raise_for_status()

            rows = []
            for line in response.text.strip().splitlines():
                rows.append([int(x) for x in line.split(",")])

            if len(rows) < 30:
                raise ValueError(f"Expected at least 30 hiscore rows, got {len(rows)}")

            if lookup_name != player_name:
                print(f"Resolved hiscores name: {player_name!r} -> {lookup_name!r}")

            return rows

        except Exception as e:
            last_error = e

    raise last_error


def upsert_total_snapshot(player_id: int, overall_row: list[int]) -> None:
    overall_rank, total_level, total_xp = overall_row

    payload = {
        "snapshot_date": SNAPSHOT_DATE,
        "player_id": player_id,
        "total_xp": total_xp,
        "kills": None,
        "source": "python_skill_collector",
    }

    response = requests.post(
        supabase_url("total_xp_snapshots"),
        headers={
            **HEADERS,
            "Prefer": "resolution=merge-duplicates,return=representation",
        },
        params={"on_conflict": "snapshot_date,player_id"},
        json=payload,
        timeout=30,
    )

    if not response.ok:
        print("Total XP snapshot upsert failed")
        print("Status code:", response.status_code)
        print("Response text:", response.text)
        print("Payload:", payload)
        raise RuntimeError("Total XP snapshot upsert failed")


def upsert_skill_snapshots(player_id: int, rows: list[list[int]]) -> None:
    payload = []

    for line_index, skill_id in SKILL_LINE_TO_ID.items():
        rank, level, xp = rows[line_index]

        payload.append(
            {
                "snapshot_date": SNAPSHOT_DATE,
                "player_id": player_id,
                "skill_id": skill_id,
                "level": level,
                "xp": xp,
                "rank": rank,
                "source": "python_skill_collector",
            }
        )

    if len(payload) != 29:
        raise ValueError(f"Expected 29 skill records, got {len(payload)}")

    response = requests.post(
        supabase_url("skill_snapshots"),
        headers={
            **HEADERS,
            "Prefer": "resolution=merge-duplicates,return=representation",
        },
        params={"on_conflict": "snapshot_date,player_id,skill_id"},
        json=payload,
        timeout=30,
    )

    if not response.ok:
        print("Skill snapshot upsert failed")
        print("Status code:", response.status_code)
        print("Response text:", response.text)
        print("First payload row:", payload[0] if payload else None)
        raise RuntimeError("Skill snapshot upsert failed")
    
def write_failed_lookups(failures: list[dict]) -> None:
    if not failures:
        if FAILED_LOOKUPS_FILE.exists():
            FAILED_LOOKUPS_FILE.unlink()
        return

    with FAILED_LOOKUPS_FILE.open("w", encoding="utf-8", newline="") as f:
        fieldnames = [
            "current_name",
            "collection_status",
            "collect_skills",
            "watchlist",
            "error",
        ]

        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for failure in failures:
            writer.writerow(failure)

def update_hiscore_status(
    player_id: int,
    status: str,
    error: str | None = None,
) -> None:
    payload = {
        "hiscore_lookup_status": status,
        "hiscore_last_error": error,
        "hiscore_last_checked": SNAPSHOT_DATE,
    }

    response = requests.patch(
        supabase_url("players"),
        headers=HEADERS,
        params={"id": f"eq.{player_id}"},
        json=payload,
        timeout=30,
    )

    if not response.ok:
        print("Failed to update hiscore status")
        print("Status code:", response.status_code)
        print("Response text:", response.text)            


def main() -> None:
    print(f"Snapshot date: {SNAPSHOT_DATE}")
    print(f"Skills mapped: {len(SKILL_LINE_TO_ID)}")

    if len(SKILL_LINE_TO_ID) != 29:
        raise ValueError("Skill mapping is incomplete.")

    players = get_players_to_collect()

    print(f"Players selected for skill collection: {len(players):,}")

    success_count = 0
    failure_count = 0
    failures = []

    for player in players:
        player_id = player["id"]
        player_name = player["current_name"]
        lookup_name = player.get("hiscore_lookup_name") or player_name

        try:
            rows = fetch_hiscores(lookup_name)

# Total XP snapshots are owned by ingest_clan_totals.py.
# Do not write hiscore-derived totals here.
# upsert_total_snapshot(player_id, rows[0])
            upsert_skill_snapshots(player_id, rows)
            update_hiscore_status(player_id, "ok", None)

            success_count += 1
            print(f"SUCCESS: {player_name} | Overall XP: {rows[0][2]:,}")

        except Exception as e:
            failure_count += 1
            update_hiscore_status(player_id, "failed", str(e))

            failures.append(
                {
                    "current_name": player_name,
                    "collection_status": player.get("collection_status"),
                    "collect_skills": player.get("collect_skills"),
                    "watchlist": player.get("watchlist"),
                    "error": str(e),
                }
            )

            print(f"FAILED: {player_name} -> {e}")

    write_failed_lookups(failures)

    print()
    print("Skill collection complete.")
    print(f"Successful players: {success_count:,}")
    print(f"Failed players: {failure_count:,}")

    if failures:
        print(f"Failure log written to: {FAILED_LOOKUPS_FILE.resolve()}")


if __name__ == "__main__":
    main()