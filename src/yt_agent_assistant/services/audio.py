from __future__ import annotations

import random
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Union

from ..config import Settings
from ..utils import coerce_iterable_str, format_ts

_PSALM_RE = re.compile(r"(?i)psalm[\s_\-]*0*([0-9]+)")
_GOSPEL_RE = re.compile(r"(?i)\b(luke|luc|matt(?:hew|hieu)?|john|jean|marc|mark)\b[\s_\-]*0*([0-9]+)")


TrackItem = Dict[str, Union[str, int, Path, float, None]]


@dataclass
class PlaylistResult:
    selection: List[TrackItem]
    total_seconds: float
    tracks_with_meta: List[Tuple[Path, float, str]]
    track_dir: Path
    chapters_path: Path


class AudioEngine:
    """
    Handles psalm/gospel discovery, selection, and export.
    """

    def __init__(self, settings: Settings):
        self.settings = settings

    # ---- collectors -------------------------------------------------
    def collect_psalms(self) -> List[TrackItem]:
        src = self.settings.paths.trimmed_dir
        if not src.exists():
            raise SystemExit(f"[ERROR] Missing psalm directory: {src}")
        files = sorted([p for p in src.glob("*.mp3") if p.is_file()])
        if not files:
            raise SystemExit(f"[ERROR] No MP3 found in: {src}")

        items: List[TrackItem] = []
        for mp3 in files:
            num, ok = self._parse_psalm_number(mp3)
            dur = self.ffprobe_duration_seconds(mp3)
            if dur <= 0.0:
                print(f"[WARN] Duration unreadable: {mp3.name} (skip)")
                continue
            label = f"psalm {num}" if ok and num is not None else mp3.stem
            items.append(
                {
                    "path": mp3,
                    "type": "psalm",
                    "psalm_num": num if ok else None,
                    "gospel_name": None,
                    "gospel_chapter": None,
                    "has_num": ok,
                    "label": label,
                    "dur": dur,
                }
            )
        if not items:
            raise SystemExit("[ERROR] No usable psalms.")
        return items

    def collect_gospels(self) -> List[TrackItem]:
        root = self.settings.paths.gospel_root
        if not root.exists():
            print(f"[INFO] Gospel folder missing: {root} (ignored)")
            return []
        items: List[TrackItem] = []
        for mp3 in sorted(root.glob("*/*.mp3")):
            if not mp3.is_file():
                continue
            parent = mp3.parent.name
            name_infer, ch_infer = self._parse_gospel_ref(mp3.stem)
            if not name_infer:
                name_infer = self._norm_gospel_name(parent)
                _, ch_infer = self._parse_gospel_ref(parent + " " + mp3.stem)
            if not name_infer or not ch_infer:
                print(f"[WARN] Gospel ref not recognized: {mp3}")
                continue
            dur = self.ffprobe_duration_seconds(mp3)
            if dur <= 0.0:
                print(f"[WARN] Duration unreadable (gospel): {mp3.name} (skip)")
                continue
            disp = f"{self._display_gospel_name(name_infer)} {ch_infer}"
            items.append(
                {
                    "path": mp3,
                    "type": "gospel",
                    "psalm_num": None,
                    "gospel_name": name_infer,
                    "gospel_chapter": ch_infer,
                    "has_num": True,
                    "label": disp,
                    "dur": dur,
                }
            )
        return items

    # ---- selection --------------------------------------------------
    def build_selection(
        self,
        pool_items: Sequence[TrackItem],
        target_seconds: float,
        preferred_head: Optional[Sequence[Union[str, int]]] = None,
        preferred_candidates: Optional[Sequence[TrackItem]] = None,
        seed: Optional[int] = None,
    ):
        rng = random.Random(seed)
        selection: List[TrackItem] = []
        total = 0.0
        used_paths = set()
        preferred_candidates = preferred_candidates if preferred_candidates is not None else pool_items

        by_psalm: Dict[int, TrackItem] = {}
        by_gospel: Dict[Tuple[str, int], TrackItem] = {}
        for item in preferred_candidates:
            if item["type"] == "psalm" and item["psalm_num"] is not None:
                by_psalm.setdefault(int(item["psalm_num"]), item)
            elif item["type"] == "gospel" and item["gospel_name"] and item["gospel_chapter"] is not None:
                key = (str(item["gospel_name"]), int(item["gospel_chapter"]))
                by_gospel.setdefault(key, item)

        head: List[TrackItem] = []
        if preferred_head:
            head_candidates = list(preferred_head)
            rng.shuffle(head_candidates)
            max_head = self.settings.audio.max_head_items
            if isinstance(max_head, int) and max_head > 0:
                head_candidates = head_candidates[:max_head]

            for pref in head_candidates:
                if isinstance(pref, int):
                    cand = by_psalm.get(pref)
                    if cand and cand["path"] not in used_paths:
                        head.append(cand)
                        used_paths.add(cand["path"])
                elif isinstance(pref, str):
                    gname, chap = self._parse_gospel_ref(pref)
                    if gname and chap:
                        cand = by_gospel.get((gname, chap))
                        if cand and cand["path"] not in used_paths:
                            head.append(cand)
                            used_paths.add(cand["path"])

        tail = [item for item in pool_items if item["path"] not in used_paths]
        rng.shuffle(tail)
        first_pass = head + tail

        for item in first_pass:
            selection.append(item)
            used_paths.add(item["path"])
            total += float(item["dur"])
            if total >= target_seconds:
                return selection, total

        def cycle_once():
            nonlocal total, used_paths
            remaining = [it for it in pool_items if it["path"] not in used_paths]
            if not remaining:
                used_paths = set()
                remaining = list(pool_items)
            rng.shuffle(remaining)
            for item in remaining:
                selection.append(item)
                used_paths.add(item["path"])
                total += float(item["dur"])
                if total >= target_seconds:
                    return True
            return False

        while total < target_seconds:
            if cycle_once():
                break
        return selection, total

    # ---- export ----------------------------------------------------
    @staticmethod
    def clean_track_dir(track_dir: Path) -> None:
        if track_dir.exists():
            shutil.rmtree(track_dir)
        track_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def copy_and_rename(selection, track_dir: Path, timeline_idx: int):
        pad = max(2, len(str(len(selection))))
        out = []
        for idx, item in enumerate(selection, start=1):
            src = Path(item["path"])
            dst = track_dir / f"{str(idx).zfill(pad)}_{str(timeline_idx).zfill(2)}_{src.name}"
            shutil.copy2(src, dst)
            out.append((dst, float(item["dur"]), str(item["label"])))
        return out

    @staticmethod
    def write_chapters(chapters_path: Path, tracks_with_meta, offset_first=0.0):
        lines = []
        t = 0.0
        offset_first = max(0.0, offset_first or 0.0)
        for idx, (_, dur, label) in enumerate(tracks_with_meta, start=1):
            lines.append(f"{format_ts(t)} - {label}")
            effective = dur
            if idx == 1 and offset_first > 0.0:
                effective = max(0.0, dur - offset_first)
            t += effective
        chapters_path.write_text("\n".join(lines), encoding="utf-8")

    # ---- orchestrator -------------------------------------------------
    def build_playlist(
        self,
        timeline_idx: int,
        target_seconds: Optional[float] = None,
        preferred_head: Optional[Sequence[Union[str, int]]] = None,
    ) -> PlaylistResult:
        target = target_seconds or self.settings.core.target_seconds
        psalms = self.collect_psalms()
        pool: List[TrackItem] = psalms[:]
        if self.settings.audio.include_gospel:
            pool += self.collect_gospels()

        pref = list(self.settings.audio.preferred_head or [])
        if preferred_head:
            pref.extend(coerce_iterable_str(preferred_head))

        selection, total = self.build_selection(
            pool_items=pool,
            target_seconds=target,
            preferred_head=pref,
            preferred_candidates=psalms,
            seed=self.settings.audio.random_seed,
        )

        track_dir = self.settings.paths.track_root / f"track{timeline_idx:02d}"
        chapters_path = self.settings.paths.track_root / f"chapters{timeline_idx:02d}.txt"
        self.clean_track_dir(track_dir)
        tracks = self.copy_and_rename(selection, track_dir, timeline_idx)
        self.write_chapters(chapters_path, tracks, offset_first=self.settings.core.trim_first_audio_seconds)

        return PlaylistResult(
            selection=selection,
            total_seconds=total,
            tracks_with_meta=tracks,
            track_dir=track_dir,
            chapters_path=chapters_path,
        )

    # ---- helpers ----------------------------------------------------
    @staticmethod
    def ffprobe_duration_seconds(path: Path) -> float:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            str(path),
        ]
        try:
            out = subprocess.check_output(cmd, text=True).strip()
            return float(out)
        except Exception:
            return 0.0

    @staticmethod
    def _parse_psalm_number(path: Path):
        match = _PSALM_RE.search(path.stem)
        if not match:
            return None, False
        try:
            return int(match.group(1)), True
        except ValueError:
            return None, False

    @staticmethod
    def _parse_gospel_ref(text: str):
        match = _GOSPEL_RE.search(text)
        if not match:
            return None, None
        name = AudioEngine._norm_gospel_name(match.group(1))
        try:
            chapter = int(match.group(2))
        except ValueError:
            return None, None
        return name, chapter

    @staticmethod
    def _norm_gospel_name(name: str) -> str:
        normalized = name.strip().lower()
        if normalized in ("marc", "mark"):
            return "marc"
        if normalized in ("luke", "luc"):
            return "luke"
        if normalized in ("matt", "matthew", "matthieu"):
            return "matthew"
        if normalized in ("john", "jean"):
            return "john"
        return normalized

    @staticmethod
    def _display_gospel_name(name: str) -> str:
        mapping = {"marc": "Marc", "luke": "Luke", "matthew": "Matthew", "john": "John"}
        return mapping.get(name, name.title())
