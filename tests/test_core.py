"""Synthetische Tests: Maßstabsbogen-Erkennung + Mesh-Nachbearbeitung ohne echte Fotos.

Aufruf:  python -m tests.test_core   (im Projektordner)
"""
import tempfile
from pathlib import Path

import cv2
import numpy as np
import trimesh

from app import colmap_io, markers, meshtools


def look_at(C, target=np.zeros(3), up=np.array([0, 1.0, 0])):
    z = target - C
    z /= np.linalg.norm(z)
    x = np.cross(z, up)
    if np.linalg.norm(x) < 1e-6:
        x = np.cross(z, [1, 0, 0])
    x /= np.linalg.norm(x)
    y = np.cross(z, x)
    R = np.vstack([x, y, z])
    return R, -R @ C


def random_similarity(rng):
    q = rng.normal(size=4)
    q /= np.linalg.norm(q)
    R = colmap_io.qvec_to_R(q)
    s = rng.uniform(0.005, 0.05)          # COLMAP-Einheiten sind willkürlich
    t = rng.normal(size=3)
    T = np.eye(4)
    T[:3, :3] = s * R
    T[:3, 3] = t
    return T


def make_dataset(tmp: Path):
    """Synthetischer 'Scan': Bilder eines Maßstabsbogens + Kamera-Posen + Roh-Mesh in COLMAP-Koordinaten."""
    rng = np.random.default_rng(1)
    pdf, png = tmp / "bogen.pdf", tmp / "bogen.png"
    markers.make_sheet(pdf, png)
    sheet = cv2.imread(str(png), cv2.IMREAD_GRAYSCALE)
    H_px, W_px = sheet.shape
    mm2px = markers.DPI / 25.4
    # Abbildung Bogen-mm (Mitte, y hoch) -> Pixel des Bogenbilds
    S = np.array([[mm2px, 0, markers.SHEET_W / 2 * mm2px],
                  [0, -mm2px, markers.SHEET_H / 2 * mm2px],
                  [0, 0, 1]])

    # Welt = Bogen-mm. Modellkoordinaten = willkürliche Ähnlichkeit davon (wie COLMAP).
    T_w2m = random_similarity(rng)
    s_wm = np.cbrt(np.linalg.det(T_w2m[:3, :3]))
    R_wm = T_w2m[:3, :3] / s_wm
    K = np.array([[2400, 0, 1200], [0, 2400, 900], [0, 0, 1.0]])
    cams = {1: colmap_io.Camera(1, "PINHOLE", 2400, 1800, np.array([2400, 2400, 1200, 900.0]))}
    views, centers_world = {}, []
    img_dir = tmp / "imgs"
    img_dir.mkdir()
    for i in range(14):
        ang = 2 * np.pi * i / 14
        C = np.array([330 * np.cos(ang), 330 * np.sin(ang), 260 + 40 * np.sin(3 * ang)])
        R, t = look_at(C)
        centers_world.append(C)
        # Homographie Bogenpixel -> Kamerapixel
        Hm = K @ np.column_stack([R[:, 0], R[:, 1], t])        # Bogen-mm (z=0) -> Bild
        Hpx = Hm @ np.linalg.inv(S)
        img = cv2.warpPerspective(sheet, Hpx, (2400, 1800), borderValue=90)
        img = cv2.GaussianBlur(img, (3, 3), 0)
        name = f"img_{i:04d}.jpg"
        cv2.imwrite(str(img_dir / name), img)
        # gleiche Kamera in Modellkoordinaten ausdrücken: X_w = (X_m - t_wm)/s R^T
        R_m = R @ R_wm.T
        t_m = s_wm * t - R_m @ T_w2m[:3, 3]
        views[name] = colmap_io.View(i, name, 1, R_m, t_m)

    part = trimesh.creation.box(extents=[40, 25, 15])
    part.apply_translation([5, -10, 7.5])
    table = trimesh.creation.box(extents=[400, 400, 2])
    table.apply_translation([0, 0, -1])
    scene = trimesh.util.concatenate([part, table])
    scene = trimesh.Trimesh(*trimesh.remesh.subdivide_to_size(scene.vertices, scene.faces, 3.0))
    scene.vertices += rng.normal(scale=0.05, size=scene.vertices.shape)
    scene.apply_transform(T_w2m)
    raw = tmp / "scene_dense_mesh.ply"
    scene.export(raw)
    centers_m = (T_w2m[:3, :3] @ np.array(centers_world).T).T + T_w2m[:3, 3]
    return img_dir, cams, views, T_w2m, centers_m, raw


def main():
    tmp = Path(tempfile.mkdtemp())
    img_dir, cams, views, T_w2m, centers_m, raw = make_dataset(tmp)
    al = markers.align_to_sheet(img_dir, cams, views)
    assert al is not None, "Bogen nicht erkannt"
    T_expected = np.linalg.inv(T_w2m)
    err = np.abs(al.T - T_expected).max()
    print(f"Ecken: {al.n_corners}, Marker: {al.n_markers}, Rest {al.rms_mm:.3f} mm, Matrixabw. {err:.2e}")
    assert al.n_markers >= 8 and al.rms_mm < 0.5
    assert np.median(al.camera_z) > 200, "Kameras sollten über dem Bogen liegen"


    stl, rep = meshtools.postprocess(raw, tmp / "out1", sheet_T=al.T, camera_centers=centers_m, cut_mm=0.6)
    print("Mit Bogen:", [round(x, 2) for x in rep.size_mm], "wasserdicht:", rep.watertight, rep.volume_cm3)
    assert abs(rep.size_mm[0] - 40) < 0.6 and abs(rep.size_mm[1] - 25) < 0.6
    assert abs(rep.size_mm[2] - (15 - 0.6)) < 0.6

    stl2, rep2 = meshtools.postprocess(raw, tmp / "out2", sheet_T=None, camera_centers=centers_m,
                                       target_longest_mm=40.0)
    print("Ohne Bogen, längste Kante=40:", [round(x, 2) for x in rep2.size_mm])
    assert abs(max(rep2.size_mm) - 40) < 0.01
    assert abs(rep2.size_mm[1] - 25) < 1.0, "Grundfläche sollte an x/y ausgerichtet sein"
    assert rep2.size_mm[2] < max(rep2.size_mm[:2]), "Teil sollte flach auf dem Druckbett liegen"
    print("ALLE TESTS OK")


if __name__ == "__main__":
    main()
