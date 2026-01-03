#!/usr/bin/env python3
"""
Launch the Flask UI for thumbnail review, title generation, and playlist prep.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yt_agent_assistant.config import load_settings  # noqa: E402
from yt_agent_assistant.web_app import create_app  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Run the yt-vibes Flask UI.")
    parser.add_argument("--config", type=Path, help="Path to settings.yaml.")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind.")
    parser.add_argument("--port", type=int, default=5050, help="Port to bind.")
    args = parser.parse_args()

    settings = load_settings(args.config)
    app = create_app(settings, config_path=args.config)
    app.run(host=args.host, port=args.port, debug=settings.flask.debug)


if __name__ == "__main__":
    main()
