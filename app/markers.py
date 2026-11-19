"""Maßstabsbogen mit ArUco-Markern: Erzeugen, Erkennen, Triangulieren.

Idee: Das Teil steht beim Fotografieren auf einem ausgedruckten A4-Bogen mit
Markern bekannter Lage. Nach der Rekonstruktion werden die Markerecken in den
Bildern gefunden, in 3D trianguliert und das ganze Modell per Ähnlichkeits-
transformation in das Koordinatensystem des Bogens überführt:
  * Einheit = Millimeter (echter Maßstab)
  * Bogen liegt in z = 0, das Teil steht darauf (+z nach oben)
Damit liegt das Teil automatisch richtig auf dem Druckbett.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

DICT_ID = cv2.aruco.DICT_4X4_50
SHEET_W, SHEET_H = 210.0, 297.0        # A4 in mm
MARKER_MM = 30.0                        # Kantenlänge eines Markers
MARGIN_MM = 12.0                        # Abstand zum Papierrand
DPI = 300


def _dictionary():
    return cv2.aruco.getPredefinedDictionary(DICT_ID)


def marker_layout() -> dict[int, np.ndarray]:
    """Marker-ID -> 4 Eckpunkte (mm, Ursprung = Bogenmitte, y nach oben).

    Eckreihenfolge wie bei OpenCV: oben-links, oben-rechts, unten-rechts, unten-links
    (bezogen auf das Bild des Bogens)."""
    s, m = MARKER_MM, MARGIN_MM
    xs = [m, (SHEET_W - s) / 2, SHEET_W - m - s]          # links/mitte/rechts
    ys_side = [SHEET_H * 0.36 - s / 2, SHEET_H * 0.64 - s / 2]
    positions = []                                         # obere linke Ecke (Bildkoordinaten, mm)
    positions += [(x, m) for x in xs]                      # obere Reihe
    positions += [(SHEET_W - m - s, y) for y in ys_side]   # rechte Seite
    positions += [(x, SHEET_H - m - s) for x in reversed(xs)]  # untere Reihe
    positions += [(m, y) for y in reversed(ys_side)]       # linke Seite
    layout = {}
    for mid, (x, y) in enumerate(positions):
        img_pts = np.array([[x, y], [x + s, y], [x + s, y + s], [x, y + s]])
        # Bildkoordinaten (y nach unten) -> Bogenkoordinaten (Mitte, y nach oben)
        pts = np.column_stack([img_pts[:, 0] - SHEET_W / 2, SHEET_H / 2 - img_pts[:, 1]])
        layout[mid] = pts
    return layout


def make_sheet(out_pdf: Path, out_png: Path | None = None) -> None:
    """Druckbaren A4-Maßstabsbogen erzeugen (bei 100 % / 'Tatsächliche Größe' drucken)."""
    px = lambda mm: int(round(mm / 25.4 * DPI))
    W, H = px(SHEET_W), px(SHEET_H)
    sheet = Image.new("L", (W, H), 255)
    draw = ImageDraw.Draw(sheet)
    d = _dictionary()
    for mid, pts in marker_layout().items():
        x0 = pts[0, 0] + SHEET_W / 2
        y0 = SHEET_H / 2 - pts[0, 1]
        mk = cv2.aruco.generateImageMarker(d, mid, px(MARKER_MM))
        sheet.paste(Image.fromarray(mk), (px(x0), px(y0)))
    font = small = None
    for name in ("arial.ttf", "segoeui.ttf", "DejaVuSans.ttf"):
        try:
            font, small = ImageFont.truetype(name, px(3.5)), ImageFont.truetype(name, px(2.6))
            break
        except Exception:
            continue
    if font is None:
        font = small = ImageFont.load_default()
    # Kontrolllinie 100 mm
    y = px(SHEET_H / 2 + 60)
    x0, x1 = px(SHEET_W / 2 - 50), px(SHEET_W / 2 + 50)
    draw.line([(x0, y), (x1, y)], fill=0, width=px(0.4))
    for x in (x0, x1):
        draw.line([(x, y - px(2)), (x, y + px(2))], fill=0, width=px(0.4))
    draw.text((px(SHEET_W / 2 - 48), y + px(3)),
              "Kontrolle: Diese Linie muss genau 100 mm lang sein", fill=0, font=small)
    # Stellfläche
    r = px(45)
    cx, cy = W // 2, px(SHEET_H / 2 - 10)
    draw.rectangle([cx - r, cy - r, cx + r, cy + r], outline=170, width=px(0.3))
    draw.text((cx - r, cy - r - px(5)), "Teil hier platzieren", fill=120, font=font)
    draw.text((px(MARGIN_MM), H - px(6)),
              "ScanForge 3D – Maßstabsbogen A4 – mit 100 % (tatsächliche Größe) drucken, nicht knicken",
              fill=100, font=small)
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_pdf, "PDF", resolution=DPI)
    if out_png:
        sheet.save(out_png, dpi=(DPI, DPI))


def detect(image_path: Path) -> dict[int, np.ndarray]:
    """Marker in einem Bild finden: ID -> 4x2 Pixelkoordinaten."""
    img = cv2.imdecode(np.fromfile(str(image_path), np.uint8), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return {}
    params = cv2.aruco.DetectorParameters()
    params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    det = cv2.aruco.ArucoDetector(_dictionary(), params)
    corners, ids, _ = det.detectMarkers(img)
    layout = marker_layout()
    out = {}
    if ids is not None:
        for c, i in zip(corners, ids.flatten()):
            if int(i) in layout:
                out[int(i)] = c.reshape(4, 2).astype(float)
    return out


def triangulate(Ps: list[np.ndarray], pts: list[np.ndarray]) -> tuple[np.ndarray, float]:
    """Lineare Triangulation (DLT) eines Punktes aus mehreren Ansichten.
    Gibt 3D-Punkt und mittleren Reprojektionsfehler (px) zurück."""
    A = []
    for P, (u, v) in zip(Ps, pts):
        A.append(u * P[2] - P[0])
        A.append(v * P[2] - P[1])
    _, _, Vt = np.linalg.svd(np.asarray(A))
    X = Vt[-1]
    X = X[:3] / X[3]
    errs = []
    for P, uv in zip(Ps, pts):
        x = P @ np.append(X, 1)
        if x[2] <= 0:
            return X, np.inf
        errs.append(np.linalg.norm(x[:2] / x[2] - uv))
    return X, float(np.mean(errs))


def umeyama(src: np.ndarray, dst: np.ndarray) -> tuple[float, np.ndarray, np.ndarray]:
    """Ähnlichkeitstransformation dst ≈ s * R @ src + t (kleinste Quadrate)."""
    mu_s, mu_d = src.mean(0), dst.mean(0)
    S, D = src - mu_s, dst - mu_d
    cov = D.T @ S / len(src)
    U, sig, Vt = np.linalg.svd(cov)
    E = np.eye(3)
    if np.linalg.det(U) * np.linalg.det(Vt) < 0:
        E[2, 2] = -1
    R = U @ E @ Vt
    var_s = (S ** 2).sum() / len(src)
    s = float(np.trace(np.diag(sig) @ E) / var_s)
    t = mu_d - s * R @ mu_s
    return s, R, t


@dataclass
class SheetAlignment:
    T: np.ndarray            # 4x4 Matrix: Modellkoordinaten -> Bogen-mm
    scale: float
    n_corners: int
    n_markers: int
    rms_mm: float            # Restfehler der Markerecken in mm
    camera_z: np.ndarray     # Kamerahöhen über dem Bogen (Plausibilitätsprüfung)


def align_to_sheet(image_dir: Path, cams, views, log=print,
                   max_reproj_px: float = 4.0) -> SheetAlignment | None:
    """Marker in allen rekonstruierten Bildern suchen und Modell auf den Bogen ausrichten."""
    layout = marker_layout()
    obs: dict[tuple[int, int], list[tuple[np.ndarray, np.ndarray]]] = {}
    for name, v in views.items():
        p = image_dir / name
        if not p.exists():
            continue
        found = detect(p)
        if not found:
            continue
        K = cams[v.camera_id].K()
        P = K @ np.hstack([v.R, v.t[:, None]])
        for mid, c in found.items():
            for k in range(4):
                obs.setdefault((mid, k), []).append((P, c[k]))
    src, dst = [], []
    for (mid, k), lst in obs.items():
        if len(lst) < 2:
            continue
        X, err = triangulate([o[0] for o in lst], [o[1] for o in lst])
        if err <= max_reproj_px:
            src.append(X)
            dst.append([*layout[mid][k], 0.0])
    markers = {key[0] for key in obs}
    log(f"Maßstabsbogen: {len(markers)} Marker erkannt, {len(src)} Ecken trianguliert")
    if len(src) < 8:
        return None
    src, dst = np.asarray(src), np.asarray(dst)
    # robust: zweimal schätzen, Ausreißer (> 3x Median) verwerfen
    for _ in range(2):
        s, R, t = umeyama(src, dst)
        res = np.linalg.norm((s * (R @ src.T)).T + t - dst, axis=1)
        keep = res <= max(3 * np.median(res), 0.5)
        if keep.all() or keep.sum() < 8:
            break
        src, dst = src[keep], dst[keep]
    s, R, t = umeyama(src, dst)
    res = np.linalg.norm((s * (R @ src.T)).T + t - dst, axis=1)
    T = np.eye(4)
    T[:3, :3] = s * R
    T[:3, 3] = t
    cz = np.array([(T @ np.append(v.center(), 1))[2] for v in views.values()])
    al = SheetAlignment(T, s, len(src), len({m for (m, _) in obs}), float(np.sqrt((res ** 2).mean())), cz)
    log(f"Maßstab gefunden: Restfehler {al.rms_mm:.2f} mm, Kameras im Mittel {np.median(cz):.0f} mm über dem Bogen")
    return al
