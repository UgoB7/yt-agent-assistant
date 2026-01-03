from __future__ import annotations

import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from flask import (
    Flask,
    abort,
    flash,
    redirect,
    render_template_string,
    request,
    url_for,
)

from .config import Settings
from .services.audio import AudioEngine
from .services.images import ImageRepository, human_mb
from .services.titles import TitleService, write_refs_lists
from .utils import extract_index_from_name, img_to_data_url, normalize_title, require_bin

PAGE_TMPL = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Prep Titles & Tracks</title>
  <style>
    :root { color-scheme: light dark; }
    body { font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; margin: 20px; }
    .wrap { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; align-items: start; }
    img { max-width: 100%; height: auto; border-radius: 12px; box-shadow: 0 6px 20px rgba(0,0,0,.15); }
    .card { padding: 16px; border: 1px solid #e7e7e7; border-radius: 12px; box-shadow: 0 2px 10px rgba(0,0,0,.05); }
    .title { font-weight: 600; margin-bottom: 8px; }
    ol { padding-left: 18px; }
    li { margin: 6px 0; }
    form { display: inline; }
    button { padding: 8px 12px; border: none; border-radius: 8px; cursor: pointer; }
    .pick { background: #111; color: #fff; }
    .skip { background: #ddd; color: #333; }
    .regen { background: #0d6efd; color: #fff; }
    .custom { background: #198754; color: #fff; }
    .meta { color: #666; font-size: 13px; margin-top: 8px; }
    .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
    .err { border: 1px solid #ffb3b3; background:#fff5f5; padding:14px; border-radius:12px; color:#a40000; }
    .done { margin-top:12px; font-size:13px; color:#333; }
    input[type="text"], textarea { width: 100%; padding: 8px 10px; border-radius: 8px; border: 1px solid #bbb; margin: 6px 0; }
    .footer { margin-top: 12px; display:flex; gap:12px; align-items:center; flex-wrap: wrap; }
    code { background: #f6f6f6; padding:2px 5px; border-radius:6px; }
    .flash { margin: 8px 0; color: #a40000; }
    hr { border: 0; height: 1px; background: linear-gradient(90deg, transparent, rgba(0,0,0,.15), transparent); }
    .hint { font-size: 12px; color: #555; }
  </style>
</head>
<body>
  <div class="header">
    <div>
      <strong>Image {{ idx+1 }} / {{ total }}</strong>
      - <code>{{ img_name }}</code>
      - <a href="{{ url_for('restart') }}">Re-scan</a>
      - <a href="{{ url_for('factory_reset') }}" onclick="return confirm('Reset outputs (keep thumbnails)?');">Factory reset</a>
    </div>
    <div>
      {% if prev_i is not none %}<a href="{{ url_for('index', i=prev_i) }}">Prev</a>{% endif %}
      {% if next_i is not none %}<a href="{{ url_for('index', i=next_i) }}" style="margin-left:12px;">Next</a>{% endif %}
    </div>
  </div>

  {% with messages = get_flashed_messages() %}
    {% if messages %}
      <div class="flash">{{ messages[0] }}</div>
    {% endif %}
  {% endwith %}

  {% if error %}
    <div class="err">{{ error }}</div>
  {% else %}
  <div class="wrap">
    <div class="card">
      <div class="title">Thumbnail</div>
      <img src="{{ data_url }}" alt="thumbnail">
      <div class="meta">{{ subdir }}</div>
      <div class="footer">
        <form method="post" action="{{ url_for('skip', i=idx) }}">
          <button class="skip" type="submit">Skip</button>
        </form>
        {% if not chosen_existing %}
          <form method="post" action="{{ url_for('regen', i=idx, kind='devotional') }}">
            <button class="regen" type="submit">Regen 20 (devotional)</button>
          </form>
        {% endif %}
      </div>
    </div>

    <div class="card">
      {% if chosen_existing %}
        <div class="title">Already validated (no re-selection)</div>
        <ol>
          {% for t in chosen_existing %}
            <li>{{ t }}</li>
          {% endfor %}
        </ol>
        <form method="post" action="{{ url_for('rerun', i=idx) }}">
          <div class="footer">
            <button class="custom" type="submit">Re-run playlist with these titles</button>
          </div>
        </form>
      {% else %}
        <form method="post" action="{{ url_for('choose', i=idx) }}">
          <div class="title">Devotional titles (check up to 3)</div>
          {% if titles_devotional %}
            <ol>
              {% for t in titles_devotional %}
                <li>
                  <label>
                    <input type="checkbox" name="titles" value="{{ t }}">
                    {{ t }}
                  </label>
                </li>
              {% endfor %}
            </ol>
          {% else %}
            <p>(Not generated yet - use buttons above.)</p>
          {% endif %}

          <div class="title" style="margin-top:18px;">Add your own titles (one per line)</div>
          <textarea name="custom_titles" rows="3" placeholder="Custom title #1&#10;Custom title #2"></textarea>
          <div class="hint">Max 3 total (checked boxes + custom lines).</div>
          <div class="footer">
            <button class="custom" type="submit">Validate titles</button>
          </div>
        </form>
      {% endif %}

      <div class="meta" style="margin-top:10px;">
        After validation, audio tracks regenerate in <code>{{ track_dir }}</code>
        and <code>{{ chapters_path }}</code>, ready for DaVinci.
      </div>
    </div>
  </div>
  {% endif %}
</body>
</html>
"""

DONE_TMPL = """<!doctype html>
<html>
<head><meta charset="utf-8"><title>Done</title></head>
<body style="font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; margin: 24px;">
  <h2>Done</h2>
  <p>No more images in <code>{{ image_dir }}</code>.</p>
  {% if resolve_note %}
    <p>{{ resolve_note }}</p>
  {% endif %}
  <p>Run the Resolve sync script to pull trackXX/ and chaptersXX.txt.</p>
  <p><a href="{{ url_for('restart') }}">Re-scan</a></p>
</body>
</html>
"""


def create_app(settings: Settings, config_path: Optional[Path] = None) -> Flask:
    app = Flask(__name__)
    app.secret_key = settings.flask.secret_key

    repo = ImageRepository(settings)
    title_service = TitleService(settings)
    audio_engine = AudioEngine(settings)
    state = {"ordered": []}
    trigger_event = threading.Event()

    repo.ensure_dirs()
    if settings.flask.reset_on_start:
        repo.hard_reset_state()

    def _ordered_images() -> List[Path]:
        if not state["ordered"]:
            imgs = repo.list_images()
            if not imgs:
                return []
            state["ordered"] = imgs
        return state["ordered"]

    def _load_titles(path: Path) -> List[str]:
        if path.exists():
            return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        return []

    def _persist_titles(path: Path, titles: List[str]) -> None:
        path.write_text("\n".join(titles) + "\n", encoding="utf-8")

    def _load_chosen_titles(path: Path) -> List[str]:
        if path.exists():
            return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        return []

    def _process_titles(idx: int, img: Path, titles_selected: List[str]) -> str:
        directory = repo.subdir_for_image(img)
        joined_titles = "\n".join(titles_selected) + "\n"
        (directory / "chosen.txt").write_text(joined_titles, encoding="utf-8")
        (directory / "titre1.txt").write_text(joined_titles, encoding="utf-8")

        try:
            main_title = titles_selected[0]
            gospels, psalms, combined = title_service.best_references(img, main_title)
            write_refs_lists(directory, gospels, psalms, combined)
        except Exception as exc:
            print(f"[WARN] best_references failed for {img.name}: {exc}")
            write_refs_lists(directory, [], [], [])
            combined = []

        require_bin("ffprobe")
        ps_items = audio_engine.collect_psalms()
        need_gospels_head = any(isinstance(x, str) for x in (combined or []))
        go_items = []
        if settings.audio.include_gospel or need_gospels_head:
            go_items = audio_engine.collect_gospels()
        pool = ps_items + (go_items if settings.audio.include_gospel else [])
        preferred_candidates = ps_items + go_items

        selection, total = audio_engine.build_selection(
            pool_items=pool,
            target_seconds=settings.core.target_seconds,
            seed=settings.audio.random_seed,
            preferred_head=combined,
            preferred_candidates=preferred_candidates,
        )
        idx_num = extract_index_from_name(img.name) or 0
        track_dir = repo.track_root / f"track{idx_num:02d}"
        chapters_path = repo.track_root / f"chapters{idx_num:02d}.txt"

        audio_engine.clean_track_dir(track_dir)
        tracks_meta = audio_engine.copy_and_rename(selection, track_dir, timeline_idx=idx_num)
        audio_engine.write_chapters(
            chapters_path,
            tracks_meta,
            offset_first=settings.core.trim_first_audio_seconds,
        )

        msg = f"{len(titles_selected)} title(s) saved. Tracks refreshed for track{idx_num:02d}."
        if settings.audio.auto_trigger_resolve:
            msg += " Resolve sync will start when all images are processed."
        return msg

    def _trigger_resolve(indices: Optional[List[int]] = None) -> str:
        if not settings.audio.auto_trigger_resolve:
            return "disabled"

        resolve_script = Path(__file__).resolve().parents[2] / "scripts" / "update_resolve.py"
        if not resolve_script.exists():
            return "missing"
        if trigger_event.is_set():
            return "busy"

        trigger_event.set()
        indices = indices or []
        only_args: List[str] = []
        label = "all"
        if indices:
            label = "set-" + "-".join(f"{int(idx):02d}" for idx in indices)
            for idx in indices:
                only_args.extend(["--only", str(idx)])

        def _worker():
            try:
                timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                log_path = settings.paths.log_dir / f"resolve_{label}_{timestamp}.log"
                settings.paths.log_dir.mkdir(parents=True, exist_ok=True)
                cmd = [
                    sys.executable or "python3",
                    str(resolve_script),
                ]
                cmd.extend(only_args)
                if config_path:
                    cmd.extend(["--config", str(config_path)])
                with log_path.open("w", encoding="utf-8") as log:
                    log.write(f"[INFO] Start {datetime.now().isoformat()} | cmd={' '.join(cmd)}\n")
                    log.flush()
                    proc = subprocess.Popen(
                        cmd,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        cwd=resolve_script.parent,
                    )
                    proc.wait()
                    log.write(f"[INFO] End {datetime.now().isoformat()} (code={proc.returncode})\n")
            finally:
                trigger_event.clear()

        threading.Thread(target=_worker, daemon=True).start()
        return "started"

    def _schedule_resolve_all() -> Optional[str]:
        status = _trigger_resolve()
        if status == "started":
            return "Resolve sync launched for all timelines (render may run)."
        if status == "busy":
            return "Resolve is already syncing; request ignored."
        if status == "missing":
            return "Cannot launch update_resolve.py (file missing)."
        if status == "disabled":
            return "Auto Resolve launch disabled."
        return None

    @app.route("/restart")
    def restart():
        repo.ensure_dirs()
        state["ordered"] = repo.list_images()
        if not state["ordered"]:
            return "No images (.jpg/.jpeg/.png) found in configured folder.", 200
        return redirect(url_for("index", i=0))

    @app.get("/factory_reset")
    def factory_reset():
        repo.hard_reset_state()
        repo.ensure_dirs()
        state["ordered"] = repo.list_images()
        flash("Reset done (thumbnails kept).")
        return redirect(url_for("restart"))

    @app.route("/")
    def index():
        ordered = _ordered_images()
        if not ordered:
            return "No images (.jpg/.jpeg/.png) found in configured folder.", 200

        try:
            idx = int(request.args.get("i", "0"))
        except ValueError:
            idx = 0
        if idx < 0 or idx >= len(ordered):
            return render_template_string(DONE_TMPL, image_dir=str(repo.image_dir), resolve_note=None)

        img = ordered[idx]
        directory = repo.subdir_for_image(img)

        yt_path, orig_bytes, yt_bytes = repo.ensure_yt_thumbnail(img)
        data_url = img_to_data_url(img)
        data_url_yt = img_to_data_url(yt_path) if yt_path else None

        titles_devotional_fp = directory / "titles_devotional.txt"
        titles_devotional = _load_titles(titles_devotional_fp)
        if not titles_devotional:
            try:
                titles_devotional = title_service.devotional_titles(img)
                _persist_titles(titles_devotional_fp, titles_devotional)
            except Exception as exc:
                flash(f"Title generation failed: {exc}")
                titles_devotional = []

        chosen_fp = directory / "chosen.txt"
        chosen_existing = _load_chosen_titles(chosen_fp)

        idx_num = extract_index_from_name(img.name) or 0
        track_dir = repo.track_root / f"track{idx_num:02d}"
        chapters_path = repo.track_root / f"chapters{idx_num:02d}.txt"

        return render_template_string(
            PAGE_TMPL,
            error=None,
            idx=idx,
            total=len(ordered),
            img_name=img.name,
            subdir=str(directory),
            data_url=data_url,
            data_url_yt=data_url_yt,
            orig_size_str=human_mb(orig_bytes),
            yt_size_str=(human_mb(yt_bytes) if yt_bytes is not None else None),
            yt_path_str=(str(yt_path) if yt_path else None),
            titles_devotional=titles_devotional,
            chosen_existing=chosen_existing,
            prev_i=(idx - 1 if idx > 0 else None),
            next_i=(idx + 1 if idx + 1 < len(ordered) else None),
            track_dir=str(track_dir),
            chapters_path=str(chapters_path),
        )

    @app.post("/regen")
    def regen():
        ordered = _ordered_images()
        if not ordered:
            return redirect(url_for("restart"))
        try:
            idx = int(request.args["i"])
        except Exception:
            abort(400)
        if idx < 0 or idx >= len(ordered):
            abort(400)

        img = ordered[idx]
        directory = repo.subdir_for_image(img)

        try:
            titles_devotional = title_service.devotional_titles(img)
            _persist_titles(directory / "titles_devotional.txt", titles_devotional)
            flash("Regenerated devotional titles.")
        except Exception as exc:
            flash(f"Regen failed: {exc}")

        return redirect(url_for("index", i=idx))

    def _titles_selected_from_request() -> List[str]:
        raw_checked = request.form.getlist("titles")
        raw_custom = request.form.get("custom_titles") or ""
        custom_titles = [line.strip() for line in raw_custom.splitlines() if line.strip()]
        merged = raw_checked + custom_titles

        titles_selected: List[str] = []
        seen = set()
        for t in merged:
            norm = normalize_title(t)
            if not norm or norm in seen:
                continue
            seen.add(norm)
            titles_selected.append(t.strip())
        return titles_selected

    def _handle_titles_for_idx(idx: int, titles_selected: List[str], skip_empty: bool = False):
        ordered = _ordered_images()
        if not ordered:
            return redirect(url_for("restart"))
        if idx < 0 or idx >= len(ordered):
            abort(400)
        if not titles_selected:
            if skip_empty:
                flash("No existing title for this image.")
                return redirect(url_for("index", i=idx))
            flash("No title selected.")
            return redirect(url_for("index", i=idx))
        if len(titles_selected) > 3:
            flash("Max 3 titles (checked + custom).")
            return redirect(url_for("index", i=idx))

        img = ordered[idx]
        msg = _process_titles(idx, img, titles_selected)
        flash(msg)

        next_idx = idx + 1
        if next_idx >= len(ordered):
            resolve_note = _schedule_resolve_all()
            return render_template_string(
                DONE_TMPL,
                image_dir=str(repo.image_dir),
                resolve_note=resolve_note,
            )
        return redirect(url_for("index", i=next_idx))

    @app.post("/choose")
    def choose():
        try:
            idx = int(request.args["i"])
        except Exception:
            abort(400)
        titles_selected = _titles_selected_from_request()
        return _handle_titles_for_idx(idx, titles_selected)

    @app.post("/rerun")
    def rerun():
        try:
            idx = int(request.args["i"])
        except Exception:
            abort(400)
        ordered = _ordered_images()
        if not ordered:
            return redirect(url_for("restart"))
        if idx < 0 or idx >= len(ordered):
            abort(400)
        img = ordered[idx]
        directory = repo.subdir_for_image(img)
        chosen_existing = _load_chosen_titles(directory / "chosen.txt")
        return _handle_titles_for_idx(idx, chosen_existing, skip_empty=True)

    @app.post("/skip")
    def skip():
        ordered = _ordered_images()
        if not ordered:
            return redirect(url_for("restart"))
        try:
            idx = int(request.args["i"])
        except Exception:
            abort(400)
        next_idx = idx + 1
        if next_idx >= len(ordered):
            return render_template_string(DONE_TMPL, image_dir=str(repo.image_dir), resolve_note=None)
        return redirect(url_for("index", i=next_idx))

    return app
