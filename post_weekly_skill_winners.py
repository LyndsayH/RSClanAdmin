import os
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
DISCORD_WEBHOOK_URL = os.environ["DISCORD_WEEKLY_WEBHOOK_URL"]
DISCORD_THREAD_ID = os.environ["DISCORD_WEEKLY_THREAD_ID"]

SUPABASE_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}


def fetch_weekly_winners() -> list[dict[str, Any]]:
    url = f"{SUPABASE_URL}/rest/v1/weekly_skill_winners"

    response = requests.get(
        url,
        headers=SUPABASE_HEADERS,
        params={
            "select": (
                "skill,weekly_winner,xp_gain,"
                "baseline_snapshot,latest_snapshot"
            ),
            "order": "skill.asc",
        },
        timeout=60,
    )

    if not response.ok:
        print("Supabase request failed")
        print("Status:", response.status_code)
        print("Response:", response.text)
        response.raise_for_status()

    return response.json()


def format_xp(value: int | None) -> str:
    return f"{int(value or 0):,} XP"


def make_embeds(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return [
            {
                "title": "Weekly Skill Winners",
                "description": "No weekly skill gain data was available.",
            }
        ]

    start_date = rows[0]["baseline_snapshot"]
    end_date = rows[0]["latest_snapshot"]

    # Discord allows at most 25 fields per embed.
    groups = [rows[:15], rows[15:]]
    embeds: list[dict[str, Any]] = []

    for index, group in enumerate(groups, start=1):
        if not group:
            continue

        fields = []

        for row in group:
            winner = row.get("weekly_winner") or "No recorded gain"
            xp_gain = format_xp(row.get("xp_gain"))

            fields.append(
                {
                    "name": row["skill"],
                    "value": f"**{winner}**\n{xp_gain}",
                    "inline": True,
                }
            )

        embed: dict[str, Any] = {
            "title": (
                "🏆 Weekly Skill Winners"
                if index == 1
                else "🏆 Weekly Skill Winners — continued"
            ),
            "description": f"`{start_date}` → `{end_date}`",
            "fields": fields,
        }

        if index == 2:
            embed["footer"] = {
                "text": "RuneScape Clan Analytics"
            }

        embeds.append(embed)

    return embeds


def post_to_discord(embeds: list[dict[str, Any]]) -> None:
    payload = {
        "username": "RS Clan Analytics",
        "embeds": embeds,
        "allowed_mentions": {
            "parse": []
        },
    }

    response = requests.post(
        DISCORD_WEBHOOK_URL,
        params={
        "thread_id": DISCORD_THREAD_ID,
        "wait": "true",
    },
        json=payload,
        timeout=60,
    )

    if not response.ok:
        print("Discord post failed")
        print("Status:", response.status_code)
        print("Response:", response.text)
        response.raise_for_status()


def main() -> None:
    print("Fetching weekly skill winners...")

    rows = fetch_weekly_winners()

    print(f"Rows fetched: {len(rows)}")

    embeds = make_embeds(rows)

    print("Posting to Discord...")

    post_to_discord(embeds)

    print("Weekly skill winners posted successfully.")


if __name__ == "__main__":
    main()