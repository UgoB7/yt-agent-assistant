from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Sequence

from .utils import expand_path, frames_to_seconds, tc_to_frames

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("PyYAML is required to load configuration files.") from exc


@dataclass
class CoreSettings:
    fps: int = 30
    final_duration_tc: str = "3:33:32:20"
    trim_first_audio_seconds: float = 3.2

    @property
    def target_seconds(self) -> float:
        frames = tc_to_frames(self.final_duration_tc, self.fps)
        return frames_to_seconds(frames, self.fps)


@dataclass
class PathSettings:
    base_dir: Path = field(default_factory=lambda: Path("./runtime"))
    image_dir: Optional[Path] = None
    output_dir: Optional[Path] = None
    track_root: Optional[Path] = None
    log_dir: Optional[Path] = None
    incoming_image_dir: Optional[Path] = None
    imported_archive_dir: Optional[Path] = None
    yt_thumb_dir: Optional[Path] = None
    trimmed_dir: Path = field(default_factory=lambda: Path("./runtime/audio/psalms"))
    gospel_root: Path = field(default_factory=lambda: Path("./runtime/audio/gospels"))
    tmp_stills_dir: Path = field(default_factory=lambda: Path("./runtime/tmp_stills"))
    silence_stub_path: Path = field(default_factory=lambda: Path("./runtime/audio/silence_stub.wav"))

    def __post_init__(self) -> None:
        base = expand_path(self.base_dir)
        self.base_dir = base
        self.image_dir = expand_path(self.image_dir or (base / "images"))
        self.output_dir = expand_path(self.output_dir or (base / "outputs"))
        self.track_root = expand_path(self.track_root or base)
        self.log_dir = expand_path(self.log_dir or (base / "logs"))
        self.incoming_image_dir = expand_path(self.incoming_image_dir or (base / "incoming"))
        self.imported_archive_dir = expand_path(self.imported_archive_dir or (self.incoming_image_dir / "_processed"))
        self.yt_thumb_dir = expand_path(self.yt_thumb_dir or (base / "yt_thumbs"))
        self.trimmed_dir = expand_path(self.trimmed_dir, base=None)
        self.gospel_root = expand_path(self.gospel_root, base=None)
        self.tmp_stills_dir = expand_path(self.tmp_stills_dir, base=None)
        self.silence_stub_path = expand_path(self.silence_stub_path, base=None)


@dataclass
class ImageSettings:
    auto_import_images: bool = True
    auto_import_image_exts: Iterable[str] = field(default_factory=lambda: (".png", ".jpg", ".jpeg", ".webp"))
    yt_thumb_max_bytes: int = 2 * 1024 * 1024
    yt_thumb_suffix: str = "_yt"
    yt_thumb_target_bytes: int = 1_800_000

    def __post_init__(self) -> None:
        self.auto_import_image_exts = tuple(sorted({ext.lower() for ext in self.auto_import_image_exts}))


@dataclass
class AudioSettings:
    include_gospel: bool = True
    random_seed: Optional[int] = None
    max_head_items: Optional[int] = None
    preferred_head: Sequence[str | int] = field(default_factory=tuple)
    auto_trigger_resolve: bool = True


@dataclass
class OpenAISettings:
    model: str = "gpt-4.1"
    title_examples_input: str = ""
    devotional_examples_input: str = ""
    default_guide_hint: Optional[str] = None


@dataclass
class FlaskSettings:
    debug: bool = True
    secret_key: str = "dev-key"
    reset_on_start: bool = True


@dataclass
class ResolveSettings:
    width: int = 1920
    height: int = 1080
    use_still_duration_in_resolve: bool = True
    do_render_all_timelines: bool = True
    auto_caption_lang: str = "ENGLISH"
    auto_caption_preset: str = "DEFAULT"
    chars_per_line: int = 42
    double_line: bool = True
    caption_gap_frames: int = 0
    render_dir: Path = field(default_factory=lambda: Path("./runtime/renders"))
    render_format: str = "QuickTime"
    render_codec: str = "H265"
    h264_profile: str = "High"
    hw_encode_if_available: bool = True
    subtitles_burn_in: bool = True
    timeline_prefix: str = "timeline"
    pad_short_audio_with_silence: bool = False
    silence_chunk_seconds: float = 5.0

    def __post_init__(self) -> None:
        self.render_dir = expand_path(self.render_dir, base=None)


@dataclass
class Settings:
    core: CoreSettings = field(default_factory=CoreSettings)
    paths: PathSettings = field(default_factory=PathSettings)
    images: ImageSettings = field(default_factory=ImageSettings)
    audio: AudioSettings = field(default_factory=AudioSettings)
    openai: OpenAISettings = field(default_factory=OpenAISettings)
    flask: FlaskSettings = field(default_factory=FlaskSettings)
    resolve: ResolveSettings = field(default_factory=ResolveSettings)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "Settings":
        payload = data or {}
        return cls(
            core=CoreSettings(**(payload.get("core") or {})),
            paths=PathSettings(**(payload.get("paths") or {})),
            images=ImageSettings(**(payload.get("images") or {})),
            audio=AudioSettings(**(payload.get("audio") or {})),
            openai=OpenAISettings(**(payload.get("openai") or {})),
            flask=FlaskSettings(**(payload.get("flask") or {})),
            resolve=ResolveSettings(**(payload.get("resolve") or {})),
        )

    def to_dict(self) -> Dict[str, Any]:
        def _serialize(obj: Any) -> Any:
            if is_dataclass(obj):
                return {f.name: _serialize(getattr(obj, f.name)) for f in fields(obj)}
            if isinstance(obj, Path):
                return str(obj)
            if isinstance(obj, tuple):
                return list(obj)
            return obj

        return _serialize(self)


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "configs" / "settings.yaml"
EXAMPLE_CONFIG_PATH = Path(__file__).resolve().parents[2] / "configs" / "settings.example.yaml"


def load_settings(config_path: Optional[str | Path] = None) -> Settings:
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    if not path.exists():
        fallback = EXAMPLE_CONFIG_PATH if EXAMPLE_CONFIG_PATH.exists() else None
        if fallback:
            data = yaml.safe_load(fallback.read_text(encoding="utf-8"))
        else:
            data = None
    else:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Settings.from_dict(data)


def dump_settings(settings: Settings, destination: Path) -> None:
    destination.write_text(yaml.safe_dump(settings.to_dict(), sort_keys=False), encoding="utf-8")
