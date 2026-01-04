#!/usr/bin/env python3
"""
Launch everything in one go: Flask UI for title selection, then Resolve sync/render.
Just run this script; stop the UI with Ctrl+C when you've chosen all titles.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yt_agent_assistant.config import load_settings  # noqa: E402
from yt_agent_assistant.web_app import create_app  # noqa: E402
from yt_agent_assistant.services.resolve import sync_timelines  # noqa: E402


def main():
    """
    Start Flask UI and periodically sync to DaVinci Resolve (no Ctrl+C needed to trigger sync).
    Close the process when you're done (Ctrl+C) or let it keep syncing while you work.
    """
    config_path = ROOT / "configs" / "settings.yaml"
    settings = load_settings(config_path)

    app_flask = create_app(settings, config_path=config_path)

    def _serve():
        app_flask.run(host="0.0.0.0", port=5050, debug=settings.flask.debug, use_reloader=False)

    def _sync_loop():
        # First sync waits a few seconds to let you pick first titles, then syncs every 30s.
        time.sleep(10)
        while True:
            try:
                sync_timelines(settings, only_indices=None)
                print("[SYNC] Resolve timelines updated.")
            except SystemExit:
                break
            except Exception as exc:
                print(f"[SYNC] Resolve sync failed: {exc}")
            time.sleep(30)

    t_flask = threading.Thread(target=_serve, daemon=True)
    t_flask.start()
    print(f"Flask UI running on http://0.0.0.0:5050 with config {config_path}")
    print("Keep this running; Resolve sync will trigger automatically every ~30s after the first 10s.")

    t_sync = threading.Thread(target=_sync_loop, daemon=True)
    t_sync.start()

    try:
        while t_flask.is_alive():
            time.sleep(1)
    except KeyboardInterrupt:
        print("Shutting down...")


if __name__ == "__main__":
    try:
        main()
    except SystemExit as exc:
        sys.exit(exc.code)
