"""Fetch Google Maps reviews and print JSON (used by the Streamlit app via subprocess)."""

from __future__ import annotations

import json
import sys

from maps import fetch_reviews


def main() -> int:
    if len(sys.argv) < 2:
        print(json.dumps({"error": "maps_url required"}))
        return 1
    maps_url = sys.argv[1]
    max_reviews = int(sys.argv[2]) if len(sys.argv) > 2 else 250
    try:
        details = fetch_reviews(maps_url, max_reviews=max_reviews)
        print(json.dumps(details.to_dict(), ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"error": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
