from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

from ..config import Settings
from ..utils import tc_to_frames

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".m4v", ".avi", ".mpg", ".mpeg"}


def fatal(msg: str) -> None:
    print("[ERROR]", msg)
    sys.exit(1)


def info(msg: str) -> None:
    print("[INFO]", msg)


def require_bin(bin_name: str) -> str:
    path = shutil.which(bin_name)
    if not path:
        fatal(f"{bin_name} missing. Install it (e.g. brew install {bin_name}).")
    return path


def _ensure_dir(path):
    Path(path).mkdir(parents=True, exist_ok=True)
    return str(path)


def iter_all_clips_recursive(folder):
    try:
        for clip in (folder.GetClipList() or []):
            yield clip
        for sub in (folder.GetSubFolderList() or []):
            yield from iter_all_clips_recursive(sub)
    except Exception:
        return


def find_media_item_by_path(root_folder, target_abs_path, timeout_s=10, poll_ms=200):
    target_abs_path = os.path.abspath(target_abs_path)
    start = time.time()
    while True:
        for clip in iter_all_clips_recursive(root_folder):
            file_path = (clip.GetClipProperty("File Path") or "").strip()
            if file_path and os.path.abspath(file_path) == target_abs_path:
                return clip
        if (time.time() - start) >= timeout_s:
            return None
        time.sleep(poll_ms / 1000.0)


def apply_render_settings(project, resolve, settings: Settings):
    rs = settings.resolve
    try:
        project.SetCurrentRenderFormatAndCodec(rs.render_format, rs.render_codec)
    except Exception:
        pass

    payload = {
        "SelectAllFrames": True,
        "TargetDir": _ensure_dir(rs.render_dir),
        "Format": rs.render_format,
        "VideoCodec": rs.render_codec,
        "ExportVideo": True,
        "ExportAudio": True,
        "Quality": "Automatic",
        "H264Profile": rs.h264_profile,
        "EncodingProfile": rs.h264_profile,
        "EnableHardwareEncoding": rs.hw_encode_if_available,
        "UseHardwareEncoderIfAvailable": rs.hw_encode_if_available,
        "HardwareEncoding": rs.hw_encode_if_available,
    }

    payload["ExportSubtitle"] = True
    payload["SubtitleFormat"] = "BurnIn" if rs.subtitles_burn_in else "SeparateFile"

    try:
        project.SetRenderSettings(payload)
    except Exception:
        try:
            project.SetRenderSettings({"TargetDir": _ensure_dir(rs.render_dir)})
        except Exception:
            pass


def render_all_timelines_with_prefix(project, settings: Settings, only_names=None):
    prefix = settings.resolve.timeline_prefix
    try:
        count = int(project.GetTimelineCount() or 0)
    except Exception:
        count = 0
    if count == 0:
        info("[RENDER] No timelines in project.")
        return
    try:
        project.DeleteAllRenderJobs()
    except Exception:
        pass

    only = set(only_names) if only_names else None
    jobs = 0

    for idx in range(1, count + 1):
        timeline = project.GetTimelineByIndex(idx)
        if not timeline:
            continue
        try:
            name = timeline.GetName()
        except Exception:
            name = None
        if not name or not name.lower().startswith(prefix.lower()):
            continue
        if only is not None and name not in only:
            continue
        try:
            project.SetCurrentTimeline(timeline)
        except Exception:
            pass
        custom = {"TargetDir": _ensure_dir(settings.resolve.render_dir), "CustomName": name}
        try:
            project.SetRenderSettings(custom.copy())
        except Exception:
            pass
        job_id = project.AddRenderJob()
        if job_id:
            jobs += 1
            info(f"[RENDER] Added job: {name}")
        else:
            info(f"[RENDER] Failed to add job: {name}")

    if jobs == 0:
        info("[RENDER] No render jobs added.")
        return

    try:
        ok = project.StartRendering()
    except TypeError:
        ok = project.StartRendering()
    info(f"[RENDER] Start: {'OK' if ok else 'FAIL'}")
    if ok:
        while True:
            try:
                if not project.IsRenderingInProgress():
                    break
            except Exception:
                break
            time.sleep(0.5)
        info("[RENDER] Done.")


def probe_duration_seconds(path, ffprobe_bin):
    out = subprocess.check_output(
        [ffprobe_bin, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", path],
        stderr=subprocess.STDOUT,
    )
    return float(out.decode().strip())


def _is_timeline_item(item) -> bool:
    try:
        clip_type = item.GetClipProperty("Type") or ""
        return str(clip_type).strip().lower() == "timeline"
    except Exception:
        return False


def _get_item_name(item):
    try:
        name = item.GetName()
        if isinstance(name, str) and name:
            return name
    except Exception:
        pass
    try:
        props = item.GetClipProperty() or {}
        return props.get("Clip Name") or props.get("Name") or ""
    except Exception:
        return ""


def _folder_contains_protected_timeline(folder, protect_names):
    try:
        for item in (folder.GetClipList() or []):
            if _is_timeline_item(item) and _get_item_name(item) in protect_names:
                return True
        for sub in (folder.GetSubFolderList() or []):
            if _folder_contains_protected_timeline(sub, protect_names):
                return True
    except Exception:
        pass
    return False


def purge_media_pool_except_timelineXX(project, media_pool, settings: Settings, keep_paths: Optional[set[Path]] = None):
    prefix = settings.resolve.timeline_prefix
    protect = set()
    try:
        count = int(project.GetTimelineCount() or 0)
    except Exception:
        count = 0
    for idx in range(1, count + 1):
        timeline = project.GetTimelineByIndex(idx)
        if not timeline:
            continue
        try:
            name = timeline.GetName()
        except Exception:
            name = None
        name = name or f"timeline_{idx:02d}"
        if name.lower().startswith(prefix.lower()):
            protect.add(name)

    root = media_pool.GetRootFolder()

    def _purge(folder):
        clips = list(folder.GetClipList() or [])
        to_delete = []
        for clip in clips:
            if _is_timeline_item(clip):
                continue
            if keep_paths:
                try:
                    p = Path((clip.GetClipProperty("File Path") or "").strip()).resolve()
                except Exception:
                    p = None
                if p and p in keep_paths:
                    continue
            to_delete.append(clip)
        if to_delete:
            try:
                media_pool.DeleteClips(to_delete)
            except Exception:
                for clip in to_delete:
                    try:
                        media_pool.DeleteClips([clip])
                    except Exception:
                        pass

        timelines_here = [clip for clip in clips if _is_timeline_item(clip)]
        to_delete_tl = [clip for clip in timelines_here if _get_item_name(clip) not in protect]
        if to_delete_tl:
            try:
                media_pool.DeleteTimelines(to_delete_tl)
            except Exception:
                for tl in to_delete_tl:
                    try:
                        media_pool.DeleteTimelines([tl])
                    except Exception:
                        pass

        subfolders = list(folder.GetSubFolderList() or [])
        for sub in subfolders:
            if _folder_contains_protected_timeline(sub, protect):
                _purge(sub)
            else:
                try:
                    media_pool.DeleteFolders([sub])
                except Exception:
                    _purge(sub)
                    try:
                        media_pool.DeleteFolders([sub])
                    except Exception:
                        pass

    _purge(root)


def natural_key(path):
    return os.path.basename(path).lower()


def ensure_resolve_modules():
    module_dirs = [
        "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules/",
        "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Frameworks/Fusion.framework/Versions/Current/Resources/Modules/",
    ]
    for path in module_dirs:
        if os.path.isdir(path) and path not in sys.path:
            sys.path.append(path)


def build_auto_caption_settings(resolve, settings: Settings):
    rs = settings.resolve
    mapping_lang = {
        "FRENCH": getattr(resolve, "AUTO_CAPTION_FRENCH", None),
        "KOREAN": getattr(resolve, "AUTO_CAPTION_KOREAN", None),
        "ENGLISH": getattr(resolve, "AUTO_CAPTION_ENGLISH", None),
    }
    mapping_preset = {
        "NETFLIX": getattr(resolve, "AUTO_CAPTION_NETFLIX", None),
        "DEFAULT": getattr(resolve, "AUTO_CAPTION_SUBTITLE_DEFAULT", None),
    }
    line_mode = (
        getattr(resolve, "AUTO_CAPTION_LINE_DOUBLE", None)
        if rs.double_line
        else getattr(resolve, "AUTO_CAPTION_LINE_SINGLE", None)
    )

    payload = {}
    if hasattr(resolve, "SUBTITLE_LANGUAGE"):
        payload[getattr(resolve, "SUBTITLE_LANGUAGE")] = (
            mapping_lang.get(rs.auto_caption_lang) or getattr(resolve, "AUTO_CAPTION_ENGLISH", None)
        )
        payload[getattr(resolve, "SUBTITLE_CAPTION_PRESET")] = (
            mapping_preset.get(rs.auto_caption_preset) or getattr(resolve, "AUTO_CAPTION_SUBTITLE_DEFAULT", None)
        )
        payload[getattr(resolve, "SUBTITLE_CHARS_PER_LINE")] = int(rs.chars_per_line)
        if line_mode is not None:
            payload[getattr(resolve, "SUBTITLE_LINE_BREAK")] = line_mode
        payload[getattr(resolve, "SUBTITLE_GAP")] = int(rs.caption_gap_frames)
    else:
        payload["subtitleLanguage"] = rs.auto_caption_lang.title()
        payload["subtitleCaptionPreset"] = rs.auto_caption_preset.title()
        payload["subtitleCharsPerLine"] = int(rs.chars_per_line)
        payload["subtitleLineBreak"] = "Double" if rs.double_line else "Single"
        payload["subtitleGap"] = int(rs.caption_gap_frames)
    return payload


def _get_track_count_safe(timeline, track_type):
    getter = getattr(timeline, "GetTrackCount", None)
    if callable(getter):
        try:
            count = int(getter(track_type) or 0)
            return max(0, count)
        except Exception:
            return 0
    return 0


def clear_all_tracks_items(timeline, preserve_video_paths: Optional[set[str]] = None):
    def _items(track_type, idx):
        try:
            return list(timeline.GetItemListInTrack(track_type, idx) or [])
        except Exception:
            return []

    def _delete(items):
        delete_fn = getattr(timeline, "DeleteClips", None)
        if callable(delete_fn) and items:
            try:
                return bool(delete_fn(items, False))
            except Exception:
                return False
        return False

    video_cnt = _get_track_count_safe(timeline, "video")
    audio_cnt = _get_track_count_safe(timeline, "audio")
    subtitle_cnt = _get_track_count_safe(timeline, "subtitle")

    deleted = False

    def _item_abs_path(item) -> Optional[str]:
        try:
            p = (item.GetClipProperty("File Path") or "").strip()
            if p:
                return os.path.abspath(p)
        except Exception:
            return None
        return None

    preserve_video_paths = {os.path.abspath(p) for p in (preserve_video_paths or set())}

    for track in range(1, video_cnt + 1):
        items = _items("video", track)
        to_keep, to_drop = [], []
        if preserve_video_paths:
            for it in items:
                if _item_abs_path(it) in preserve_video_paths:
                    to_keep.append(it)
                else:
                    to_drop.append(it)
        else:
            to_drop = items
        if _delete(to_drop):
            deleted = True
    for track in range(1, audio_cnt + 1):
        if _delete(_items("audio", track)):
            deleted = True
    for track in range(1, subtitle_cnt + 1):
        if _delete(_items("subtitle", track)):
            deleted = True
    if deleted:
        return

    for track in range(1, video_cnt + 1):
        for item in _items("video", track):
            if preserve_video_paths and _item_abs_path(item) in preserve_video_paths:
                continue
            try:
                item.SetProperty("Enabled", False)
            except Exception:
                pass
    for track in range(1, audio_cnt + 1):
        for item in _items("audio", track):
            try:
                item.SetProperty("Enabled", False)
            except Exception:
                pass
    for track in range(1, subtitle_cnt + 1):
        for item in _items("subtitle", track):
            try:
                item.SetProperty("Enabled", False)
            except Exception:
                pass


def _parse_hms_to_seconds(text):
    match = re.search(r"(\d+):(\d+):(\d+)\.(\d+)", text)
    if not match:
        return None
    h, m, s, frac = match.groups()
    return int(h) * 3600 + int(m) * 60 + int(s) + (int(frac) / (10 ** len(frac)))


def make_still_video(img_path, out_path, seconds, ffmpeg_bin, fps, width, height, label=""):
    vf = (
        f"scale=w={width}:h={height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
    )
    cmd = [
        ffmpeg_bin,
        "-y",
        "-hide_banner",
        "-nostdin",
        "-stats",
        "-loop",
        "1",
        "-i",
        img_path,
        "-t",
        f"{seconds:.3f}",
        "-r",
        str(fps),
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-crf",
        "18",
        "-preset",
        "veryfast",
        "-tune",
        "stillimage",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        out_path,
    ]

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
    last_pct = -1
    try:
        for line in proc.stderr:
            if "time=" in line:
                match = re.search(r"time=(\d+:\d+:\d+\.\d+)", line)
                if match:
                    t = _parse_hms_to_seconds(match.group(1)) or 0.0
                    pct = min(100, int((t / max(0.001, seconds)) * 100))
                    if pct != last_pct:
                        sys.stdout.write(f"\r[FFMPEG] {label} {pct:3d}% ({match.group(1)}/{seconds:.2f}s)")
                        sys.stdout.flush()
                        last_pct = pct
        ret = proc.wait()
        if ret != 0:
            err = proc.stderr.read() if proc.stderr else ""
            sys.stderr.write("\n[ffmpeg stderr]\n" + (err or "") + "\n")
            raise subprocess.CalledProcessError(ret, cmd)
    finally:
        sys.stdout.write("\r[FFMPEG] " + (label or os.path.basename(out_path)) + " 100%\n")
        sys.stdout.flush()

    if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
        raise RuntimeError(f"ffmpeg finished without producing {out_path}")


def wait_media_item_by_path(root_folder, target_abs_path, timeout_s=10, poll_ms=200):
    start = time.time()
    target_abs_path = os.path.abspath(target_abs_path)
    while True:
        clips = root_folder.GetClips() or {}
        for _, clip in clips.items():
            path = (clip.GetClipProperty("File Path") or "").strip()
            if path and os.path.abspath(path) == target_abs_path:
                return clip
        if (time.time() - start) >= timeout_s:
            return None
        time.sleep(poll_ms / 1000.0)


def discover_images_map(image_dir: Path) -> dict[int, str]:
    mapping = {}
    try:
        for name in os.listdir(image_dir):
            path = os.path.join(image_dir, name)
            if not os.path.isfile(path):
                continue
            if not re.search(r"(?i)\.(png|jpe?g)$", name):
                continue
            match = re.match(r"(?i)^im(\d+)\.(png|jpe?g)$", name)
            if match:
                idx = int(match.group(1))
            else:
                any_digits = re.search(r"(\d+)", Path(name).stem)
                if not any_digits:
                    continue
                idx = int(any_digits.group(1))
            mapping[idx] = path
    except FileNotFoundError:
        pass
    return mapping


def discover_videos_map(folder: Path) -> dict[int, Path]:
    mapping: dict[int, Path] = {}
    if not folder.exists():
        return mapping
    for p in folder.iterdir():
        if not p.is_file():
            continue
        if p.suffix.lower() not in VIDEO_EXTS:
            continue
        match = re.search(r"(\d+)", p.stem)
        if not match:
            continue
        mapping[int(match.group(1))] = p
    return mapping


def find_video_for_index(base_dir: Path, idx: int, extra_dirs: Optional[Sequence[Path]] = None) -> Optional[Path]:
    patterns = {f"{idx:02d}", str(idx)}
    candidates: List[Path] = []

    def _scan(folder: Path):
        if not folder.exists():
            return
        for p in folder.iterdir():
            if not p.is_file():
                continue
            if p.suffix.lower() not in VIDEO_EXTS:
                continue
            if any(tok in p.stem for tok in patterns):
                candidates.append(p)

    _scan(base_dir)
    video_dir = base_dir / "video"
    _scan(video_dir)
    for extra in extra_dirs or []:
        _scan(extra)
    if candidates:
        return candidates[0]
    return None


def list_timelines_with_index(project, prefix: str):
    timelines = []
    try:
        count = int(project.GetTimelineCount() or 0)
    except Exception:
        count = 0
    for idx in range(1, count + 1):
        timeline = project.GetTimelineByIndex(idx)
        if not timeline:
            continue
        try:
            name = timeline.GetName() or ""
        except Exception:
            name = ""
        if not name.lower().startswith(prefix.lower()):
            continue
        match = re.search(r"(\d+)$", name)
        if not match:
            info(f"[WARN] Timeline without numeric index: {name} (ignored)")
            continue
        timelines.append((int(match.group(1)), name, timeline))
    return timelines


def sync_timelines(settings: Settings, only_indices: Optional[Sequence[int]] = None):
    allowed = set(only_indices) if only_indices else None

    image_dir = settings.paths.image_dir
    audio_root = settings.paths.track_root
    if not image_dir.exists():
        fatal(f"Images folder missing: {image_dir}")
    if not audio_root.exists():
        fatal(f"Track root missing: {audio_root}")

    ffprobe = require_bin("ffprobe")
    ffmpeg = require_bin("ffmpeg")

    ensure_resolve_modules()
    try:
        import DaVinciResolveScript as bmd
    except Exception:
        fatal("Cannot import DaVinciResolveScript. Open DaVinci Resolve then rerun.")

    resolve = bmd.scriptapp("Resolve") or fatal("Resolve API unavailable.")
    manager = resolve.GetProjectManager() or fatal("ProjectManager not found.")
    project = manager.GetCurrentProject()
    if not project:
        fatal("No active project. Open one then retry.")

    mpool = project.GetMediaPool() or fatal("MediaPool not found.")
    root = mpool.GetRootFolder()

    images_map = discover_images_map(image_dir)
    timelines = list_timelines_with_index(project, settings.resolve.timeline_prefix)

    incoming_dir = settings.paths.incoming_image_dir
    videos_map_incoming = discover_videos_map(incoming_dir) if incoming_dir else {}
    video_keep_candidates = {}
    for idx, _, _ in timelines:
        vid = videos_map_incoming.get(idx)
        if not vid:
            vid = find_video_for_index(
                settings.paths.base_dir,
                idx,
                extra_dirs=[incoming_dir] if incoming_dir else None,
            )
        if vid:
            video_keep_candidates[idx] = vid

    pairs = []
    for idx, tl_name, tl_obj in sorted(timelines, key=lambda x: x[0]):
        if allowed and idx not in allowed:
            continue
        img_path = images_map.get(idx)
        video_path = video_keep_candidates.get(idx)
        if not img_path and not video_path:
            info(f"[SKIP] {tl_name} : no image or video for index {idx:02d}")
            continue

        candidates = [
            audio_root / f"track{idx:02d}",
            audio_root / f"track{idx:03d}",
        ]
        track_dir = next((d for d in candidates if d.is_dir()), None)
        if not track_dir:
            info(f"[SKIP] {tl_name} : no audio folder {candidates[0]} (or {candidates[1]})")
            continue

        mp3s = sorted(glob.glob(str(track_dir / "*.mp3")), key=natural_key)
        if not mp3s:
            info(f"[SKIP] {tl_name} : no .mp3 files in {track_dir}")
            continue

        pairs.append((idx, img_path, video_path, track_dir, mp3s, tl_name, tl_obj))

    if not pairs:
        if allowed:
            info(f"No timelines to process for indices: {sorted(allowed)}")
        else:
            info("No timelines to process.")
        return

    info(f"Timelines ready: {len(pairs)}")
    for idx, _, vid_path, track_dir, mp3s, tl_name, _ in pairs:
        label = vid_path.name if vid_path else f"im{idx:02d}"
        print(f"  {tl_name}  -> {label}  ({len(mp3s)} mp3)")

    keep_paths = set(video_keep_candidates.values())
    purge_media_pool_except_timelineXX(project, mpool, settings, keep_paths=keep_paths)

    to_import: set[str] = set()
    for _, img, vid, _, mp3s, _, _ in pairs:
        if vid:
            to_import.add(os.path.abspath(str(vid)))
        elif img:
            to_import.add(os.path.abspath(img))
        for m in mp3s:
            to_import.add(os.path.abspath(m))
    if to_import:
        mpool.ImportMedia(list(to_import))

    path2item = {}
    for clip in iter_all_clips_recursive(root):
        path = (clip.GetClipProperty("File Path") or "").strip()
        if path:
            path2item[os.path.abspath(path)] = clip

    frames_final = tc_to_frames(settings.core.final_duration_tc, settings.core.fps)
    dur_seconds = frames_final / settings.core.fps
    info(f"Target duration: {settings.core.final_duration_tc} ({frames_final} frames @ {settings.core.fps} fps)")

    tmp_dir = settings.paths.tmp_stills_dir
    tmp_dir.mkdir(parents=True, exist_ok=True)

    silence_item = None
    if settings.resolve.pad_short_audio_with_silence:
        silence_wav = settings.paths.silence_stub_path
        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-f",
                "lavfi",
                "-i",
                "anullsrc=r=48000:cl=stereo",
                "-t",
                f"{settings.resolve.silence_chunk_seconds:.3f}",
                "-c:a",
                "pcm_s16le",
                str(silence_wav),
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        mpool.ImportMedia([str(silence_wav)])
        clips = root.GetClips() or {}
        for _, clip in clips.items():
            path = (clip.GetClipProperty("File Path") or "").strip()
            if path:
                path2item[os.path.abspath(path)] = clip
        silence_item = path2item.get(os.path.abspath(str(silence_wav)))

    ai_settings = build_auto_caption_settings(resolve, settings)

    for idx, img_path, video_path, track_dir, mp3_list, timeline_name, timeline in pairs:
        info(f"\n[{timeline_name}] Updating...")
        project.SetCurrentTimeline(timeline)
        preserve_video_paths = set()
        preserved_video_item = None
        vid_candidate = video_keep_candidates.get(idx)
        if vid_candidate:
            preserved_video_item = path2item.get(os.path.abspath(str(vid_candidate)))
            if not preserved_video_item:
                mpool.ImportMedia([str(vid_candidate)])
                preserved_video_item = find_media_item_by_path(root, str(vid_candidate), timeout_s=10, poll_ms=200)
            if preserved_video_item:
                preserve_video_paths.add(os.path.abspath(str(vid_candidate)))
        clear_all_tracks_items(timeline, preserve_video_paths if preserve_video_paths else None)

        if preserved_video_item:
            info(f"[{timeline_name}] Existing video kept: {vid_candidate.name}")
        elif video_path:
            vid_item = path2item.get(os.path.abspath(str(video_path)))
            if not vid_item:
                mpool.ImportMedia([str(video_path)])
                vid_item = find_media_item_by_path(root, str(video_path), timeout_s=10, poll_ms=200)
            if not vid_item:
                fatal(f"Video not found in Media Pool after import: {video_path}")

            clip_frames = int(round(probe_duration_seconds(str(video_path), ffprobe) * settings.core.fps))
            clip_frames = max(1, clip_frames)
            end_frame = min(clip_frames - 1, max(0, frames_final - 1))
            video_instr = [
                {
                    "mediaPoolItem": vid_item,
                    "startFrame": 0,
                    "endFrame": end_frame,
                    "recordFrame": 0,
                    "trackIndex": 1,
                }
            ]
            ok = mpool.AppendToTimeline(video_instr)
            assert ok, "Append video failed"
        elif settings.resolve.use_still_duration_in_resolve:
            if not img_path:
                fatal(f"No image for index {idx:02d}")
            still_item = path2item.get(os.path.abspath(img_path))
            if not still_item:
                mpool.ImportMedia([img_path])
                still_item = find_media_item_by_path(root, img_path, timeout_s=10, poll_ms=200)
            if not still_item:
                fatal(f"Image not found in Media Pool after import: {img_path}")

            video_instr = [
                {
                    "mediaPoolItem": still_item,
                    "startFrame": 0,
                    "endFrame": max(0, frames_final - 1),
                    "recordFrame": 0,
                    "trackIndex": 1,
                }
            ]
            ok = mpool.AppendToTimeline(video_instr)
            if not ok:
                info("[WARN] Append still failed, fallback to ffmpeg still MP4...")
                tmp_mp4 = tmp_dir / f"still_{idx:02d}.mp4"
                make_still_video(
                    img_path,
                    str(tmp_mp4),
                    dur_seconds,
                    ffmpeg,
                    settings.core.fps,
                    settings.resolve.width,
                    settings.resolve.height,
                    label=timeline_name,
                )
                mpool.ImportMedia([str(tmp_mp4)])
                vid_item = find_media_item_by_path(root, str(tmp_mp4), timeout_s=10, poll_ms=200)
                if not vid_item:
                    fatal(f"Temporary video missing after import: {tmp_mp4}")
                video_instr = [
                    {
                        "mediaPoolItem": vid_item,
                        "startFrame": 0,
                        "endFrame": max(0, frames_final - 1),
                        "recordFrame": 0,
                        "trackIndex": 1,
                    }
                ]
                ok = mpool.AppendToTimeline(video_instr)
                assert ok, "Append video (fallback) failed"
        else:
            if not img_path:
                fatal(f"No image for index {idx:02d}")
            tmp_mp4 = tmp_dir / f"still_{idx:02d}.mp4"
            make_still_video(
                img_path,
                str(tmp_mp4),
                dur_seconds,
                ffmpeg,
                settings.core.fps,
                settings.resolve.width,
                settings.resolve.height,
                label=timeline_name,
            )
            mpool.ImportMedia([str(tmp_mp4)])
            vid_item = find_media_item_by_path(root, str(tmp_mp4), timeout_s=10, poll_ms=200)
            if not vid_item:
                fatal(f"Temporary video missing after import: {tmp_mp4}")
            video_instr = [
                {
                    "mediaPoolItem": vid_item,
                    "startFrame": 0,
                    "endFrame": max(0, frames_final - 1),
                    "recordFrame": 0,
                    "trackIndex": 1,
                }
            ]
            ok = mpool.AppendToTimeline(video_instr)
            assert ok, "Append video failed"

        audio_items = []
        for audio_path in mp3_list:
            abs_audio = os.path.abspath(audio_path)
            clip = path2item.get(abs_audio)
            if not clip:
                mpool.ImportMedia([audio_path])
                clip = find_media_item_by_path(root, audio_path, timeout_s=10, poll_ms=200)
                if clip:
                    path2item[abs_audio] = clip
            if not clip:
                fatal(f"Audio clip not found: {audio_path}")
            audio_items.append(clip)

        audio_instr = []
        a_rec = 0
        remaining = frames_final
        trim_remaining = max(0, int(round(settings.core.trim_first_audio_seconds * settings.core.fps)))
        first_audio_seen = False

        for item in audio_items:
            file_path = (item.GetClipProperty("File Path") or "").strip()
            dur_sec = probe_duration_seconds(file_path, ffprobe)
            clip_frames = int(round(dur_sec * settings.core.fps))
            if remaining <= 0 or clip_frames <= 0:
                continue
            start_in_clip = 0
            if not first_audio_seen:
                first_audio_seen = True
                if trim_remaining > 0:
                    if trim_remaining >= clip_frames:
                        trim_remaining -= clip_frames
                        continue
                    start_in_clip = trim_remaining
                    clip_frames -= trim_remaining
                    trim_remaining = 0
            put = min(clip_frames, remaining)
            audio_instr.append(
                {
                    "mediaPoolItem": item,
                    "startFrame": start_in_clip,
                    "endFrame": start_in_clip + max(0, put - 1),
                    "recordFrame": a_rec,
                    "trackIndex": 1,
                }
            )
            a_rec += put
            remaining -= put

        if settings.resolve.pad_short_audio_with_silence and remaining > 0 and silence_item:
            sil_frames = int(round(settings.resolve.silence_chunk_seconds * settings.core.fps))
            while remaining > 0:
                put = min(sil_frames, remaining)
                audio_instr.append(
                    {
                        "mediaPoolItem": silence_item,
                        "startFrame": 0,
                        "endFrame": max(0, put - 1),
                        "recordFrame": a_rec,
                        "trackIndex": 1,
                    }
                )
                a_rec += put
                remaining -= put

        if audio_instr:
            ok = mpool.AppendToTimeline(audio_instr)
            assert ok, "Append audio failed"

        ok_ai = timeline.CreateSubtitlesFromAudio(ai_settings)
        info(f"[{timeline_name}] AI Subtitles: {'OK' if ok_ai else 'FAIL'}")

    info("\nDone: timelines synced.")

    if getattr(settings.resolve, "do_render_all_timelines", True):
        apply_render_settings(project, resolve, settings)
        names_to_render = [tl_name for (_, _, _, _, tl_name, _) in pairs]
        render_all_timelines_with_prefix(project, settings, only_names=names_to_render)
