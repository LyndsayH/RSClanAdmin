from pathlib import Path
import requests

PLAYER_NAME = "Bepsmum"

# RuneMetrics appears to use -1 for Overall.
# Based on the skill order we are using, Archaeology is skill id 27.
SKILL_ID = 27
SKILL_NAME = "Archaeology"

URL = f"https://apps.runescape.com/runemetrics/app/xp-monthly/player/{PLAYER_NAME}/{SKILL_ID}"

def main() -> None:
    print(f"Fetching RuneMetrics monthly XP for {PLAYER_NAME} / {SKILL_NAME}")
    print(URL)

    response = requests.get(URL, timeout=30)

    print(f"Status code: {response.status_code}")
    print(f"Content type: {response.headers.get('content-type')}")
    print(f"Length: {len(response.text):,} characters")

    output_file = Path(f"runemetrics_{PLAYER_NAME}_{SKILL_NAME}.html")
    output_file.write_text(response.text, encoding="utf-8")

    print(f"Saved raw response to: {output_file.resolve()}")
    print()
    print("First 1,000 characters:")
    print(response.text[:1000])


if __name__ == "__main__":
    main()