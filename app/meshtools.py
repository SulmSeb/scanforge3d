"""Mesh-Nachbearbeitung für den 3D-Druck: Boden abschneiden, säubern, skalieren, exportieren."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import trimesh



@dataclass
class MeshReport:
    size_mm: tuple[float, float, float]
    faces: int
    watertight: bool
    scaled: bool
    volume_cm3: float | None


def load_mesh(path: Path) -> trimesh.Trimesh:
    m = trimesh.load(path, force="mesh", process=True)
    if not isinstance(m, trimesh.Trimesh) or len(m.faces) == 0:
        raise RuntimeError(f"Kein gültiges Mesh in {path.name}")
    return m


def largest_component(m: trimesh.Trimesh) -> trimesh.Trimesh:
    parts = m.split(only_watertight=False)
    if len(parts) <= 1:
        return m
    return max(parts, key=lambda p: len(p.faces))


def fit_plane_ransac(pts: np.ndarray, thresh: float, iters: int = 400, seed: int = 0):
    """Größte Ebene (z. B. Tischplatte) in einer Punktmenge finden."""
    rng = np.random.default_rng(seed)
    best_n, best_d, best_cnt = None, None, -1
    for _ in range(iters):
        a, b, c = pts[rng.choice(len(pts), 3, replace=False)]
        n = np.cross(b - a, c - a)
        ln = np.linalg.norm(n)
        if ln < 1e-12:
            continue
        n /= ln
        d = -n @ a
        cnt = int((np.abs(pts @ n + d) < thresh).sum())
        if cnt > best_cnt:
            best_n, best_d, best_cnt = n, d, cnt
    return best_n, best_d, best_cnt


def rotation_to_z(n: np.ndarray) -> np.ndarray:
    z = np.array([0, 0, 1.0])
    v = np.cross(n, z)
    c = float(n @ z)
    if np.linalg.norm(v) < 1e-9:
        return np.eye(3) if c > 0 else np.diag([1, -1, -1.0])
    vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + vx + vx @ vx * (1 / (1 + c))


def cut_below(m: trimesh.Trimesh, z: float) -> trimesh.Trimesh:
    """Alles unterhalb z entfernen und Schnittfläche schließen (flacher Boden fürs Druckbett)."""
    try:
        out = m.slice_plane([0, 0, z], [0, 0, 1], cap=True)
    except Exception:
        out = m.slice_plane([0, 0, z], [0, 0, 1], cap=False)
    if out is None or len(out.faces) == 0:
        raise RuntimeError("Nach dem Bodenschnitt ist nichts übrig – Schnitthöhe prüfen.")
    return out


def postprocess(mesh_path: Path, out_dir: Path, *, sheet_T: np.ndarray | None,
                sheet_size: tuple[float, float] = (210.0, 297.0),
                camera_centers: np.ndarray | None = None, cut_mm: float = 0.6,
                target_longest_mm: float | None = None, max_faces: int = 400_000,
                log=print) -> tuple[Path, MeshReport]:
    m = load_mesh(mesh_path)
    log(f"Rohes Mesh: {len(m.faces):,} Dreiecke".replace(",", "."))
    scaled = False
    if sheet_T is not None:
        m.apply_transform(sheet_T)
        if camera_centers is not None and len(camera_centers):
            cz = (sheet_T[:3, :3] @ camera_centers.T).T[:, 2] + sheet_T[2, 3]
            if np.median(cz) < 0:  # sollte nicht vorkommen – zur Sicherheit umdrehen
                m.apply_transform(np.diag([1, -1, -1, 1.0]))
        # nur den Bereich über dem Bogen behalten
        keep = np.all(np.abs(m.vertices[:, :2]) < [sheet_size[0] / 2 + 20, sheet_size[1] / 2 + 20], axis=1)
        m.update_vertices(keep)
        m = cut_below(m, cut_mm)
        scaled = True
    else:
        # ohne Bogen: größte Ebene (Tisch) suchen und wegschneiden
        try:
            ext = float(np.linalg.norm(m.bounding_box_oriented.primitive.extents))
        except Exception:
            ext = float(np.linalg.norm(m.extents))
        n, d, cnt = fit_plane_ransac(m.vertices[:: max(1, len(m.vertices) // 20000)], ext * 0.005)
        if n is not None and cnt > 50:
            if camera_centers is not None and len(camera_centers):
                if np.median(camera_centers @ n + d) < 0:
                    n, d = -n, -d
            else:
                side = m.vertices @ n + d
                if (side > 0).sum() < (side < 0).sum():
                    n, d = -n, -d
            R = rotation_to_z(n)
            T = np.eye(4)
            T[:3, :3] = R
            T[:3, 3] = R @ (d * n)   # Punkt -d*n der Ebene auf den Ursprung schieben
            m.apply_transform(T)
            m = cut_below(m, ext * 0.004)
            log("Untergrund-Ebene erkannt und entfernt")
    m = largest_component(m)
    # Grundfläche an x/y ausrichten (Hauptachsen der Draufsicht) – spart Platz auf dem Druckbett
    xy = m.vertices[:, :2] - m.vertices[:, :2].mean(0)
    w, V = np.linalg.eigh(np.cov(xy.T))
    a = np.arctan2(V[1, -1], V[0, -1])
    Rz = trimesh.transformations.rotation_matrix(-a, [0, 0, 1])
    m.apply_transform(Rz)
    if sheet_T is None and target_longest_mm:
        m.apply_scale(target_longest_mm / float(max(m.extents)))
        scaled = True
    trimesh.repair.fix_normals(m)
    trimesh.repair.fill_holes(m)
    if len(m.faces) > max_faces:
        try:
            m = m.simplify_quadric_decimation(face_count=max_faces)
        except Exception as e:
            log(f"Hinweis: Reduktion übersprungen ({e.__class__.__name__})")
    # aufs Druckbett: unten auf z = 0, in xy zentriert
    lo, hi = m.bounds
    m.apply_translation([-(lo[0] + hi[0]) / 2, -(lo[1] + hi[1]) / 2, -lo[2]])
    out_dir.mkdir(parents=True, exist_ok=True)
    stl = out_dir / "modell.stl"
    m.export(stl)
    try:
        m.export(out_dir / "modell.obj")
    except Exception:
        pass
    vol = float(m.volume) / 1000 if m.is_watertight and scaled else None
    rep = MeshReport(tuple(float(x) for x in m.extents), len(m.faces), bool(m.is_watertight), scaled, vol)
    return stl, rep
