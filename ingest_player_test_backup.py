import os
from datetime import date

import requests
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

SNAPSHOT_DATE = date.today().isoformat()

HISCORES_URL = "https://secure.runescape.com/m=hiscore/index_lite.ws"

PLAYER_NAMES = [
    "Bepsmum",
    "CallmeBury",
    "Dr Fuzzynuts",
    "Gameplayaa",
    "Ironman Conq",
    "Smurfk1cker",
    "Trrk",
    "Leppy",
    "THC_Marine03",
    "zombzz",
]

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


def fetch_hiscores(player_name: str) -> list[list[int]]:
    response = requests.get(
        HISCORES_URL,
        params={"player": player_name},
        timeout=30,
    )
    response.raise_for_status()

    rows = []
    for line in response.text.strip().splitlines():
        rows.append([int(x) for x in line.split(",")])

    if len(rows) < 30:
        raise ValueError(f"Expected at least 30 hiscore rows, got {len(rows)}")

    return rows


def upsert_player(player_name: str) -> int:
    payload = {"current_name": player_name}

    response = requests.post(
        supabase_url("players"),
        headers={
            **HEADERS,
            "Prefer": "resolution=merge-duplicates,return=representation",
        },
        params={"on_conflict": "current_name"},
        json=payload,
        timeout=30,
    )
    response.raise_for_status()

    return response.json()[0]["id"]


def upsert_total_snapshot(player_id: int, overall_row: list[int]) -> None:
    overall_rank, total_level, total_xp = overall_row

    payload = {
        "snapshot_date": SNAPSHOT_DATE,
        "player_id": player_id,
        "total_xp": total_xp,
        "kills": None,
        "source": "python_collector",
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
    response.raise_for_status()


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
                "source": "python_collector",
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
    response.raise_for_status()


def main() -> None:
    print(f"Snapshot date: {SNAPSHOT_DATE}")
    print(f"Players listed: {len(PLAYER_NAMES)}")
    print(f"Skills mapped: {len(SKILL_LINE_TO_ID)}")

    if len(SKILL_LINE_TO_ID) != 29:
        raise ValueError("Skill mapping is incomplete.")

    for player_name in PLAYER_NAMES:
        try:
            rows = fetch_hiscores(player_name)
            player_id = upsert_player(player_name)

            upsert_total_snapshot(player_id, rows[0])
            upsert_skill_snapshots(player_id, rows)

            print(f"SUCCESS: {player_name}")
            print(f"Overall XP: {rows[0][2]:,}")

        except Exception as e:
            print(f"FAILED: {player_name} -> {e}")


if __name__ == "__main__":
    main()