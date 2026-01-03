# yt-agent-assistant

Agent/assistant to generate YouTube-friendly assets (titles, scripture references, playlists, thumbnails) with a single CLI/UI. Built from the original VibesPro workflows, refactored into reusable modules, a YAML config, and an installable package.

## Features
- YAML-driven settings (paths, OpenAI, audio selection, thumbnail rules).
- Title ideation + scripture references from OpenAI Vision.
- Audio playlist builder (psalms/gospels) with chapters files and deterministic seeds.
- Thumbnail ingestion/compression helpers (imports `incoming/` -> `images/`, optional YouTube-ready copy).
- Typer-based CLI `ytagent` with subcommands; ready for `pip install -e .`.
- Flask UI for thumbnail review + title selection + playlist regen.
- DaVinci Resolve sync pipeline (timeline update + subtitles + optional render).
- Tests + CI scaffold; Business Source License 1.1 for protection.

## Quickstart
```bash
cd yt-agent-assistant
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp configs/settings.example.yaml configs/settings.yaml  # adjust paths + OpenAI model
```

CLI (examples):
```bash
ytagent titles style --image ./runtime/images/im01.png --config configs/settings.yaml
ytagent titles refs --image ./runtime/images/im01.png --title "Calm in the Storm"
ytagent audio build --timeline 5 --config configs/settings.yaml
ytagent images import --config configs/settings.yaml
ytagent ui --config configs/settings.yaml --port 5050
ytagent resolve sync --config configs/settings.yaml --only 5 --only 6
```

Environment:
- Requires `OPENAI_API_KEY`.
- `ffprobe`/`ffmpeg` must be available in `PATH` for audio inspection and Resolve sync.
- DaVinci Resolve scripting bindings must be installed for `resolve sync`.

## Tests & CI
```bash
pytest
```
GitHub Actions workflow runs lint/tests on push/PR.

## License
Business Source License 1.1 (see `LICENSE`). Production use requires a commercial grant until the change date.
