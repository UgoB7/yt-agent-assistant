#!/usr/bin/env python3
"""
Sync generated thumbnails and audio tracks into DaVinci Resolve timelines.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yt_agent_assistant.config import load_settings  # noqa: E402
from yt_agent_assistant.services.resolve import sync_timelines  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Sync Resolve timelines from yt-vibes assets.")
    parser.add_argument(
        "--only",
        dest="only_indices",
        action="append",
        metavar="IDX",
        help="Limit update to one timeline index (repeatable).",
    )
    parser.add_argument("--config", type=Path, help="Path to settings.yaml.")
    args = parser.parse_args()

    only = None
    if args.only_indices:
        only = []
        for raw in args.only_indices:
            try:
                only.append(int(raw))
            except ValueError:
                raise SystemExit(f"Invalid --only value: {raw}")

    settings = load_settings(args.config)
    sync_timelines(settings, only_indices=only)


if __name__ == "__main__":
    main()
