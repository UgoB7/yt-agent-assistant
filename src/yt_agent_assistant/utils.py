from __future__ import annotations

import base64
import re
import shutil
from datetime import timedelta
from pathlib import Path
from typing import Iterable, List, Optional

_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)


def expand_path(value: str | Path, base: Path | None = None) -> Path:
    path = Path(value).expanduser()
    if base and not path.is_absolute():
        return (base / path).resolve()
    return path.resolve()


def split_examples(raw: str) -> List[str]:
    return [s.strip() for s in (raw or "").split("/") if s.strip()]


def normalize_title(title: str) -> str:
    txt = title.strip().casefold()
    txt = _PUNCT_RE.sub("", txt)
    txt = _WS_RE.sub(" ", txt)
    return txt


def tc_to_frames(tc: str, fps: int) -> int:
    h, m, s, f = [int(x) for x in tc.split(":")]
    return int(round(((h * 3600 + m * 60 + s) * fps) + f))


def frames_to_seconds(frames: int, fps: int) -> float:
    return frames / float(fps)


def format_ts(seconds_float: float) -> str:
    return str(timedelta(seconds=int(max(0, seconds_float))))


def img_to_data_url(img_path: Path) -> str:
    mime = "image/jpeg" if img_path.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
    b64 = base64.b64encode(img_path.read_bytes()).decode("utf-8")
    return f"data:{mime};base64,{b64}"


def extract_index_from_name(name: str) -> Optional[int]:
    match = re.search(r"(\d+)", Path(name).stem)
    return int(match.group(1)) if match else None


def coerce_iterable_str(items: Iterable[str | int]) -> List[str | int]:
    out: List[str | int] = []
    for it in items:
        if isinstance(it, int):
            out.append(it)
        elif isinstance(it, str):
            val = it.strip()
            if val:
                try:
                    out.append(int(val))
                except ValueError:
                    out.append(val)
    return out


def require_bin(bin_name: str) -> str:
    path = shutil.which(bin_name)
    if not path:
        raise RuntimeError(f"{bin_name} not found in PATH. Install it (e.g. brew install {bin_name}).")
    return path
