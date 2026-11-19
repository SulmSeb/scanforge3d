"""Einlesen eines COLMAP-Modells im TXT-Format (cameras.txt, images.txt)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass
class Camera:
    id: int
    model: str
    width: int
    height: int
    params: np.ndarray

    def K(self) -> np.ndarray:
        p = self.params
        if self.model in ("SIMPLE_PINHOLE", "SIMPLE_RADIAL", "RADIAL", "SIMPLE_RADIAL_FISHEYE", "RADIAL_FISHEYE"):
            f, cx, cy = p[0], p[1], p[2]
            fx = fy = f
        else:  # PINHOLE, OPENCV, FULL_OPENCV, ...
            fx, fy, cx, cy = p[0], p[1], p[2], p[3]
        return np.array([[fx, 0, cx], [0, fy, cy], [0, 0, 1]], dtype=float)


@dataclass
class View:
    id: int
    name: str
    camera_id: int
    R: np.ndarray  # Welt -> Kamera
    t: np.ndarray

    def center(self) -> np.ndarray:
        return -self.R.T @ self.t


def qvec_to_R(q) -> np.ndarray:
    w, x, y, z = q
    return np.array([
        [1 - 2 * y * y - 2 * z * z, 2 * x * y - 2 * w * z, 2 * x * z + 2 * w * y],
        [2 * x * y + 2 * w * z, 1 - 2 * x * x - 2 * z * z, 2 * y * z - 2 * w * x],
        [2 * x * z - 2 * w * y, 2 * y * z + 2 * w * x, 1 - 2 * x * x - 2 * y * y],
    ])


def _lines(path: Path):
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            yield line


def read_model(folder: Path) -> tuple[dict[int, Camera], dict[str, View]]:
    cams: dict[int, Camera] = {}
    for line in _lines(folder / "cameras.txt"):
        e = line.split()
        cams[int(e[0])] = Camera(int(e[0]), e[1], int(e[2]), int(e[3]),
                                 np.array(list(map(float, e[4:]))))
    views: dict[str, View] = {}
    # images.txt hat je Bild zwei Zeilen; die zweite (2D-Punkte) kann leer sein
    raw = (folder / "images.txt").read_text(encoding="utf-8", errors="replace").splitlines()
    body = [l for l in raw if not l.startswith("#")]
    for i in range(0, len(body), 2):
        e = body[i].split()
        if len(e) < 10:
            continue
        q = list(map(float, e[1:5]))
        t = np.array(list(map(float, e[5:8])))
        name = " ".join(e[9:])
        views[name] = View(int(e[0]), name, int(e[8]), qvec_to_R(q), t)
    return cams, views
