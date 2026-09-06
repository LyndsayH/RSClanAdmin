import os
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

# Put the 90-day Discord webhook in .env as:
# DISCORD_90_DAY_WEBHOOK_URL=https://discord.com/api/webhooks/...
DISCORD_WEBHOOK_URL = os.environ["DISCORD_90_DAY_WEBHOOK_URL"]

SUPABASE_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}


def format_xp(value: int) -> str:
    return f"{value:,}"


def fetch_top_90_day_gainers() -> list[dict[str, Any]]:
    url = f"{SUPABASE_URL}/rest/v1/clan_total_xp_gains_90d"

    response = requests.get(
        url,
        headers=SUPABASE_HEADERS,
        params={
            "select": (
                "rank,clanmate,baseline_total_xp,latest_total_xp,"
                "xp_gain,baseline_snapshot,latest_snapshot"
            ),
            "order": "rank.asc",
            "limit": "30",
        },
        timeout=60,
    )

    if not response.ok:
        print("Supabase request failed")
        print("Status:", response.status_code)
        print("Response:", response.text)
        response.raise_for_status()

    return response.json()


def build_embeds(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return [
            {
                "title": "🏆 90-Day Total XP Gains",
                "description": "No qualifying XP gains found.",
                "color": 0x2F3136,
            }
        ]

    baseline = rows[0]["baseline_snapshot"]
    latest = rows[0]["latest_snapshot"]

    embeds = []

    chunks = [
        rows[:10],
        rows[10:20],
        rows[20:30],
    ]

    for index, chunk in enumerate(chunks):
        if not chunk:
            continue

        title = "🏆 90-Day Total XP Gains" if index == 0 else "🏆 90-Day Total XP Gains — continued"

        description_lines = [
            f"`{baseline}` → `{latest}`",
            "",
            "Clean clan-total data only. Skill hiscore totals excluded.",
            "",
        ]

        for row in chunk:
            description_lines.append(
                f"**#{row['rank']} {row['clanmate']}**\n"
                f"{format_xp(row['xp_gain'])} XP"
            )

        embeds.append(
            {
                "title": title,
                "description": "\n\n".join(description_lines),
                "color": 0x2F3136,
            }
        )

    return embeds


def post_to_discord(embeds: list[dict[str, Any]]) -> None:
    for embed in embeds:
        response = requests.post(
            DISCORD_WEBHOOK_URL,
            json={"embeds": [embed]},
            timeout=60,
        )

        if not response.ok:
            print("Discord post failed")
            print("Status:", response.status_code)
            print("Response:", response.text)
            response.raise_for_status()


def main() -> None:
    print("Fetching 90-day total XP gains...")
    rows = fetch_top_90_day_gainers()
    print(f"Rows fetched: {len(rows)}")

    embeds = build_embeds(rows)

    print("Posting to Discord...")
    post_to_discord(embeds)

    print("90-day total XP gains posted successfully.")


if __name__ == "__main__":
    main()