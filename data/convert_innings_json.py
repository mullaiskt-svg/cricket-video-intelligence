"""Convert per-innings flat JSON files to the combined ball-by-ball format
expected by BallByBallJsonProvider.

Input format (per innings file):
  {
    "match_info": {...},
    "commentary": [
      {"over": "0.1", "event": "FOUR", "detail": "to Deep point"},
      ...
    ]
  }

Output format (combined):
  {
    "innings": [
      {"innings": 1, "commentary": [{"ball": "0.1", "description": "FOUR, to Deep point"}, ...]},
      {"innings": 2, "commentary": [...]}
    ]
  }
"""
import json
import sys
from pathlib import Path


def convert_file(path: str, innings_number: int) -> dict:
    with open(path, encoding="utf-8-sig") as f:
        data = json.load(f)

    converted = []
    for entry in data["commentary"]:
        over = entry["over"]
        event = entry.get("event", "")
        detail = entry.get("detail", "")
        description = f"{event}, {detail}".strip(", ") if detail else event
        converted.append({"ball": over, "description": description})

    return {"innings": innings_number, "commentary": converted}


def main():
    if len(sys.argv) != 4:
        print("Usage: python convert_innings_json.py <innings1.json> <innings2.json> <output.json>")
        sys.exit(1)

    innings1_path, innings2_path, output_path = sys.argv[1], sys.argv[2], sys.argv[3]

    combined = {
        "innings": [
            convert_file(innings1_path, 1),
            convert_file(innings2_path, 2),
        ]
    }

    Path(output_path).write_text(json.dumps(combined, indent=2), encoding="utf-8")
    print(f"Written {output_path}")
    for i, inn in enumerate(combined["innings"], 1):
        print(f"  Innings {i}: {len(inn['commentary'])} deliveries")


if __name__ == "__main__":
    main()
