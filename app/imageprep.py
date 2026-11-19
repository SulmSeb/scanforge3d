"""Bildvorbereitung: Einlesen (auch iPhone-HEIC), Qualitätsprüfung, Verkleinern."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

try:  # iPhone-Fotos (.heic) unterstützen
    from pillow_heif import register_heif_opener

    register_heif_opener()
    HEIC_OK = True
except Exception:  # pragma: no cover
    HEIC_OK = False

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".tif", ".tiff", ".bmp"}


@dataclass
class ImageCheck:
    path: Path
    width: int = 0
    height: int = 0
    sharpness: float = 0.0      # Varianz des Laplace-Filters (höher = schärfer)
    brightness: float = 0.0     # mittlere Helligkeit 0..255
    status: str = "ok"          # ok | warn | bad
    reasons: list[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        return self.status != "bad"


def collect_images(paths: list[str | Path]) -> list[Path]:
    """Dateien und Ordner (rekursiv) zu einer sortierten Bildliste zusammenfassen."""
    out: list[Path] = []
    for p in map(Path, paths):
        if p.is_dir():
            out += [f for f in p.rglob("*") if f.suffix.lower() in IMAGE_EXTS]
        elif p.suffix.lower() in IMAGE_EXTS:
            out.append(p)
    seen, unique = set(), []
    for f in sorted(out):
        key = str(f.resolve()).lower()
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return unique


def load_rgb(path: Path, max_side: int | None = None) -> Image.Image:
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)  # iPhone-Drehung korrekt anwenden
    img = img.convert("RGB")
    if max_side and max(img.size) > max_side:
        img.thumbnail((max_side, max_side), Image.LANCZOS)
    return img


def check_image(path: Path) -> ImageCheck:
    res = ImageCheck(path=path)
    try:
        img = load_rgb(path)
    except Exception as e:
        res.status, res.reasons = "bad", [f"nicht lesbar ({e.__class__.__name__})"]
        return res
    res.width, res.height = img.size
    small = img.copy()
    small.thumbnail((1200, 1200))
    gray = cv2.cvtColor(np.asarray(small), cv2.COLOR_RGB2GRAY)
    res.sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    res.brightness = float(gray.mean())

    if min(res.width, res.height) < 800:
        res.reasons.append("Auflösung sehr gering")
        res.status = "bad"
    if res.sharpness < 25:
        res.reasons.append("verwackelt/unscharf")
        res.status = "bad"
    elif res.sharpness < 60:
        res.reasons.append("leicht unscharf")
        res.status = "warn" if res.status == "ok" else res.status
    if res.brightness < 40:
        res.reasons.append("zu dunkel")
        res.status = "warn" if res.status == "ok" else res.status
    elif res.brightness > 225:
        res.reasons.append("überbelichtet")
        res.status = "warn" if res.status == "ok" else res.status
    return res


def prepare_images(checks: list[ImageCheck], out_dir: Path, max_side: int,
                   progress=None) -> list[Path]:
    """Nutzbare Bilder als JPG (verkleinert, korrekt gedreht) in out_dir schreiben."""
    out_dir.mkdir(parents=True, exist_ok=True)
    usable = [c for c in checks if c.usable]
    written = []
    for i, c in enumerate(usable):
        img = load_rgb(c.path, max_side)
        dst = out_dir / f"img_{i:04d}.jpg"
        img.save(dst, "JPEG", quality=95)
        written.append(dst)
        if progress:
            progress(i + 1, len(usable))
    return written
