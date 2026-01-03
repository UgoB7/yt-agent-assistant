from __future__ import annotations

import io
import re
import shutil
from pathlib import Path
from typing import List, Optional, Tuple

from PIL import Image, ImageOps

from ..config import Settings


class ImageRepository:
    """
    Handles thumbnail ingestion, housekeeping, and scoped working directories.
    """

    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def image_dir(self) -> Path:
        return self.settings.paths.image_dir

    @property
    def output_dir(self) -> Path:
        return self.settings.paths.output_dir

    @property
    def track_root(self) -> Path:
        return self.settings.paths.track_root

    @property
    def log_dir(self) -> Path:
        return self.settings.paths.log_dir

    # ---- public API -------------------------------------------------
    def ensure_dirs(self) -> None:
        self.image_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.track_root.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        if self.settings.images.auto_import_images:
            self._import_new_images_from_incoming()

    def hard_reset_state(self) -> None:
        """
        Purge derived outputs while preserving imported thumbnails.
        """
        if self.output_dir.exists():
            for path in self.output_dir.iterdir():
                try:
                    if path.is_dir():
                        shutil.rmtree(path)
                    else:
                        path.unlink()
                except Exception:
                    pass

        if self.track_root.exists():
            for path in self.track_root.iterdir():
                try:
                    if path.is_dir() and re.fullmatch(r"track\d{2}", path.name):
                        shutil.rmtree(path)
                    elif path.is_file() and re.fullmatch(r"chapters\d{2}\.txt", path.name):
                        path.unlink()
                except Exception:
                    pass

    def list_images(self) -> List[Path]:
        imgs = [
            p
            for p in self.image_dir.iterdir()
            if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png"}
        ]

        def _idx_key(path: Path) -> int:
            match = re.search(r"(\d+)", path.stem)
            return int(match.group(1)) if match else 10**9

        imgs.sort(key=lambda p: (_idx_key(p), p.name.lower()))
        return imgs

    def subdir_for_image(self, image_path: Path) -> Path:
        safe_name = re.sub(r"[^\w\-]+", "_", image_path.stem)[:80]
        dest = self.output_dir / safe_name
        dest.mkdir(parents=True, exist_ok=True)
        return dest

    def ensure_yt_thumbnail(self, img_path: Path) -> Tuple[Optional[Path], int, Optional[int]]:
        """
        Create a <=2 MB version (target ~1.8 MB) and store it in yt_thumb_dir.
        """
        if not img_path.exists():
            return None, 0, None
        orig_bytes = img_path.stat().st_size
        yt_dir = self.settings.paths.yt_thumb_dir
        yt_dir.mkdir(parents=True, exist_ok=True)
        max_bytes = self.settings.images.yt_thumb_max_bytes
        target_bytes = min(
            max_bytes,
            getattr(self.settings.images, "yt_thumb_target_bytes", max_bytes) or max_bytes,
        )

        def _copy_as_is(path: Path) -> Tuple[Path, int, int]:
            dst = yt_dir / path.name
            if dst != path:
                shutil.copy2(path, dst)
            return dst, orig_bytes, dst.stat().st_size

        if orig_bytes <= max_bytes:
            return _copy_as_is(img_path)

        suffix = self.settings.images.yt_thumb_suffix or "_yt"
        target = yt_dir / f"{img_path.stem}{suffix}.jpg"

        try:
            img = Image.open(img_path)
            if img_path.suffix.lower() == ".png":
                png_try = ImageOps.exif_transpose(img.copy())
                png_bytes = self._save_png_optimized(png_try)
                if len(png_bytes) <= target_bytes:
                    target = yt_dir / f"{img_path.stem}{suffix}.png"
                    target.write_bytes(png_bytes)
                    return target, orig_bytes, len(png_bytes)
        except Exception:
            pass

        try:
            im_jpg = self._ensure_rgb_no_alpha(Image.open(img_path))
            lo, hi = 50, 95
            best_data: Optional[bytes] = None

            while lo <= hi:
                q = (lo + hi) // 2
                data = self._save_jpeg(im_jpg, q)
                if len(data) <= target_bytes:
                    best_data = data
                    lo = q + 1
                else:
                    hi = q - 1

            if best_data is None:
                best_data = self._save_jpeg(im_jpg, 40)

            target.write_bytes(best_data)
            return target, orig_bytes, len(best_data)
        except Exception:
            return _copy_as_is(img_path)

    # ---- private helpers -------------------------------------------
    def _import_new_images_from_incoming(self) -> None:
        incoming = self.settings.paths.incoming_image_dir
        incoming.mkdir(parents=True, exist_ok=True)
        files = [
            p
            for p in incoming.iterdir()
            if p.is_file() and p.suffix.lower() in self.settings.images.auto_import_image_exts
        ]
        if not files:
            return
        files.sort(key=lambda p: p.stat().st_mtime)

        idx = self._next_im_index()
        for src in files:
            dest = self.image_dir / f"im{idx:02d}.png"
            while dest.exists():
                idx += 1
                dest = self.image_dir / f"im{idx:02d}.png"
            try:
                with Image.open(src) as im:
                    im = ImageOps.exif_transpose(im)
                    im.save(dest, format="PNG")
            except Exception:
                continue
            idx += 1
            self._archive_import_source(src)

    def _existing_im_indices(self) -> List[int]:
        pat = re.compile(r"^im(\d+)$", re.I)
        idxs: List[int] = []
        if not self.image_dir.exists():
            return idxs
        for path in self.image_dir.iterdir():
            if not path.is_file():
                continue
            match = pat.match(path.stem)
            if match:
                try:
                    idxs.append(int(match.group(1)))
                except ValueError:
                    continue
        return sorted(idxs)

    def _next_im_index(self) -> int:
        idxs = self._existing_im_indices()
        return (max(idxs) + 1) if idxs else 0

    def _archive_import_source(self, src: Path) -> None:
        archive = self.settings.paths.imported_archive_dir
        archive.mkdir(parents=True, exist_ok=True)
        dst = archive / src.name
        counter = 1
        while dst.exists():
            dst = archive / f"{src.stem}_{counter}{src.suffix}"
            counter += 1
        try:
            src.rename(dst)
        except Exception:
            try:
                src.unlink()
            except Exception:
                pass

    @staticmethod
    def _save_png_optimized(image: Image.Image) -> bytes:
        buf = io.BytesIO()
        image.save(buf, format="PNG", optimize=True)
        return buf.getvalue()

    @staticmethod
    def _save_jpeg(image: Image.Image, quality: int) -> bytes:
        buf = io.BytesIO()
        image.save(
            buf,
            format="JPEG",
            quality=quality,
            optimize=True,
            progressive=True,
        )
        return buf.getvalue()

    @staticmethod
    def _ensure_rgb_no_alpha(image: Image.Image) -> Image.Image:
        image = ImageOps.exif_transpose(image)
        if image.mode in ("RGBA", "LA"):
            bg = Image.new("RGB", image.size, (255, 255, 255))
            bg.paste(image, mask=image.split()[-1])
            return bg
        return image.convert("RGB")


def human_mb(n_bytes: int) -> str:
    return f"{n_bytes / 1024 / 1024:.2f} MB"
