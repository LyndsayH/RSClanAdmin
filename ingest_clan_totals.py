import csv
import os
from datetime import date
from io import StringIO

import requests
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

CLAN_NAME = "The High Celestial"
SNAPSHOT_DATE = date.today().isoformat()

CLAN_MEMBERS_URL = "https://services.runescape.com/m=clan-hiscores/members_lite.ws"

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
}


def supabase_url(table: str) -> str:
    return f"{SUPABASE_URL}/rest/v1/{table}"


def parse_int(value) -> int | None:
    if value is None:
        return None

    cleaned = str(value).replace(",", "").strip()

    if cleaned == "":
        return None

    return int(cleaned)


def fetch_clan_members() -> list[dict]:
    response = requests.get(
        CLAN_MEMBERS_URL,
        params={"clanName": CLAN_NAME},
        timeout=60,
    )
    response.raise_for_status()

    text = response.text.strip()

    reader = csv.reader(StringIO(text))
    rows = list(reader)

    if not rows:
        raise ValueError("Clan API returned no rows.")

    headers = [h.strip().lower() for h in rows[0]]

    def find_col(*needles: str) -> int:
        for needle in needles:
            for i, header in enumerate(headers):
                if needle in header:
                    return i
        raise ValueError(f"Could not find column matching {needles}. Headers: {rows[0]}")

    name_col = find_col("clanmate", "name")
    rank_col = find_col("rank")
    xp_col = find_col("total xp", "experience", "xp")

    kills_col = None
    for i, header in enumerate(headers):
        if "kill" in header:
            kills_col = i
            break

    members = []

    for row in rows[1:]:
        if len(row) <= max(name_col, rank_col, xp_col):
            continue

        name = row[name_col].strip()
        if not name:
            continue

        total_xp = parse_int(row[xp_col])
        if total_xp is None:
            continue

        kills = None
        if kills_col is not None and len(row) > kills_col:
            kills = parse_int(row[kills_col])

        members.append(
            {
                "current_name": name,
                "clan_rank": row[rank_col].strip(),
                "total_xp": total_xp,
                "kills": kills,
            }
        )

    return members


def get_existing_players() -> dict[str, dict]:
    response = requests.get(
        supabase_url("players"),
        headers=HEADERS,
        params={
            "select": (
                "id,current_name,collection_status,collect_skills,watchlist,"
                "last_total_xp,last_total_xp_snapshot"
            ),
            "limit": "10000",
        },
        timeout=60,
    )
    response.raise_for_status()

    return {row["current_name"]: row for row in response.json()}


def chunked(items, size=500):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def upsert_players(members: list[dict], existing: dict[str, dict]) -> dict[str, int]:
    payload = []

    for member in members:
        name = member["current_name"]
        old = existing.get(name)

        previous_xp = None
        previous_status = "active"
        previous_collect_skills = True
        watchlist = False

        if old:
            previous_xp = old.get("last_total_xp")
            previous_status = old.get("collection_status") or "active"
            previous_collect_skills = old.get("collect_skills")
            watchlist = bool(old.get("watchlist"))

        gained_xp = previous_xp is not None and member["total_xp"] > previous_xp
        is_new = old is None

        if is_new:
            collection_status = "active"
            collect_skills = True
            last_xp_gain_date = SNAPSHOT_DATE
            notes = "New clanmate detected by daily clan total collector."
        elif gained_xp:
            collection_status = "active"
            collect_skills = True
            last_xp_gain_date = SNAPSHOT_DATE
            notes = "Reactivated/confirmed active by total XP gain."
        else:
            collection_status = previous_status
            collect_skills = previous_collect_skills
            last_xp_gain_date = old.get("last_xp_gain_date") if old else None
            notes = None

        # Watchlist always forces skill collection.
        if watchlist:
            collect_skills = True

        record = {
            "current_name": name,
            "clan_rank": member["clan_rank"],
            "is_current_clan_member": True,
            "last_seen": SNAPSHOT_DATE,
            "last_total_xp": member["total_xp"],
            "last_total_xp_snapshot": SNAPSHOT_DATE,
            "collection_status": collection_status,
            "collect_skills": collect_skills,
            "last_xp_gain_date": last_xp_gain_date,
            "notes": notes,
        }

        payload.append(record)

    name_to_id = {}

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
        if not response.ok:
            print("Supabase players upsert failed")
            print("Status code:", response.status_code)
            print("Response text:")
            print(response.text)
            print("First record in failed batch:")
            print(batch[0])
            raise RuntimeError("Players upsert failed")

        for row in response.json():
            name_to_id[row["current_name"]] = row["id"]

    return name_to_id


def upsert_total_snapshots(members: list[dict], name_to_id: dict[str, int]) -> None:
    payload = []

    for member in members:
        player_id = name_to_id.get(member["current_name"])

        if not player_id:
            continue

        payload.append(
            {
                "snapshot_date": SNAPSHOT_DATE,
                "player_id": player_id,
                "total_xp": member["total_xp"],
                "kills": member["kills"],
                "source": "python_clan_total_collector",
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
    print(f"Fetching clan totals for: {CLAN_NAME}")
    print(f"Snapshot date: {SNAPSHOT_DATE}")

    members = fetch_clan_members()
    print(f"Current clanmates fetched: {len(members):,}")

    existing = get_existing_players()
    print(f"Existing players in DB: {len(existing):,}")

    name_to_id = upsert_players(members, existing)
    print(f"Players upserted: {len(name_to_id):,}")

    upsert_total_snapshots(members, name_to_id)
    print("Total XP snapshots upserted.")

    reactivated = 0
    new_players = 0

    for member in members:
        old = existing.get(member["current_name"])

        if old is None:
            new_players += 1
            continue

        previous_xp = old.get("last_total_xp")
        if previous_xp is not None and member["total_xp"] > previous_xp:
            if old.get("collection_status") == "inactive" or old.get("collect_skills") is False:
                reactivated += 1

    print(f"New players detected: {new_players:,}")
    print(f"Inactive players reactivated by XP gain: {reactivated:,}")
    print("Clan total ingestion complete.")


if __name__ == "__main__":
    main()