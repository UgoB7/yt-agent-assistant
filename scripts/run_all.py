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
from yt_agent_assistant.services.images import ImageRepository  # noqa: E402
from yt_agent_assistant.utils import extract_index_from_name  # noqa: E402


def main():
    """
    Start Flask UI. As soon as every image has chosen titles AND a trackXX with mp3 exists,
    the UI stops automatically and Resolve sync/render runs once. No manual ENTER needed.
    """
    config_path = ROOT / "configs" / "settings.yaml"
    settings = load_settings(config_path)
    app_flask = create_app(settings, config_path=config_path)

    def _serve():
        app_flask.run(host="127.0.0.1", port=5050, debug=settings.flask.debug, use_reloader=False)

    srv_thread = threading.Thread(target=_serve, daemon=True)
    srv_thread.start()
    print(f"Flask UI running on http://localhost:5050 with config {config_path}")
    print("Choisis tes titres pour chaque imXX. Dès que tous les trackXX ont des mp3, la synchro Resolve se lancera automatiquement.")

    repo = ImageRepository(settings)

    def all_tracks_ready() -> bool:
        imgs = repo.list_images()
        if not imgs:
            return False
        for img in imgs:
            directory = repo.subdir_for_image(img)
            chosen = directory / "chosen.txt"
            if not chosen.exists() or not chosen.read_text(encoding="utf-8").strip():
                return False
            idx = extract_index_from_name(img.name) or 0
            track_dir = repo.track_root / f"track{idx:02d}"
            if not track_dir.exists():
                return False
            mp3s = list(track_dir.glob("*.mp3"))
            if not mp3s:
                return False
        return True

    try:
        while True:
            time.sleep(5)
            if all_tracks_ready():
                print("Tracks prêts pour toutes les images. Lancement de la synchro Resolve...")
                break
    except KeyboardInterrupt:
        print("Arrêt manuel demandé.")
    # Pas d'arrêt forcé du serveur Flask ici (daemon thread s'arrêtera quand le script se termine).

    print("Synchronisation des timelines Resolve...")
    sync_timelines(settings, only_indices=None)
    print("Terminé.")


if __name__ == "__main__":
    try:
        main()
    except SystemExit as exc:
        sys.exit(exc.code)
