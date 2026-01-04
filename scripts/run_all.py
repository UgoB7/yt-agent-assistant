#!/usr/bin/env python3
"""
Launch everything in one go: Flask UI for title selection, then Resolve sync/render.
Just run this script; stop the UI with Ctrl+C when you've chosen all titles.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yt_agent_assistant.config import load_settings  # noqa: E402
from yt_agent_assistant.web_app import create_app  # noqa: E402
from yt_agent_assistant.services.resolve import sync_timelines  # noqa: E402


def main():
    config_path = ROOT / "configs" / "settings.yaml"
    settings = load_settings(config_path)

    app_flask = create_app(settings, config_path=config_path)
    try:
        print(f"Flask UI running on http://0.0.0.0:5050 with config {config_path}")
        app_flask.run(host="0.0.0.0", port=5050, debug=settings.flask.debug, use_reloader=False)
    except KeyboardInterrupt:
        print("\nUI stopped, starting Resolve sync...")
    except Exception as exc:
        print(f"UI failed: {exc}")

    sync_timelines(settings, only_indices=None)


if __name__ == "__main__":
    try:
        main()
    except SystemExit as exc:
        sys.exit(exc.code)
