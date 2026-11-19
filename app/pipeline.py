"""Steuerung der Photogrammetrie-Kette: Bilder -> COLMAP (SfM) -> OpenMVS (dicht + Mesh) -> STL."""
from __future__ import annotations

import os
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import colmap_io, imageprep, markers, meshtools

PRESETS = {
    "Schnell":  {"max_side": 1600, "res_level": 2, "refine": False},
    "Standard": {"max_side": 2400, "res_level": 1, "refine": False},
    "Hoch":     {"max_side": 3200, "res_level": 1, "refine": True},
}

STAGES = [  # (Schlüssel, Anzeigename, Gewicht für den Fortschrittsbalken)
    ("prep", "Bilder vorbereiten", 3),
    ("features", "Merkmale finden", 10),
    ("matching", "Merkmale zuordnen", 12),
    ("mapping", "Kamerapositionen berechnen", 15),
    ("undistort", "Bilder entzerren", 4),
    ("scale", "Maßstab bestimmen", 3),
    ("densify", "Dichte Punktwolke", 35),
    ("mesh", "Oberfläche erzeugen", 10),
    ("refine", "Feinschliff", 0),
    ("post", "Druckfertig machen", 8),
]


class Cancelled(Exception):
    pass


class PipelineError(Exception):
    pass


def tools_root() -> Path:
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        cand = [base / "tools", Path(sys.executable).parent / "tools"]
    else:
        cand = [Path(__file__).resolve().parent.parent / "tools"]
    for c in cand:
        if c.exists():
            return c
    return cand[0]


def _find(root: Path, exe: str) -> Path | None:
    names = [exe, exe + ".exe"] if os.name == "nt" else [exe, exe + ".exe"]
    for n in names:
        hits = sorted(root.rglob(n)) if root.exists() else []
        if hits:
            return hits[0]
    return None


@dataclass
class Tools:
    colmap: Path
    openmvs_dir: Path

    @classmethod
    def locate(cls) -> "Tools":
        root = tools_root()
        colmap = _find(root / "colmap", "colmap") or _find(root, "colmap")
        dens = _find(root / "openmvs", "DensifyPointCloud") or _find(root, "DensifyPointCloud")
        missing = []
        if not colmap:
            missing.append("COLMAP")
        if not dens:
            missing.append("OpenMVS")
        if missing:
            raise PipelineError(
                f"{' und '.join(missing)} nicht gefunden (erwartet in {root}). "
                "Bitte das Programm über den Installer installieren oder tools/download_tools.py ausführen.")
        return cls(colmap, dens.parent)

    def mvs(self, name: str) -> Path:
        p = _find(self.openmvs_dir, name)
        if not p:
            raise PipelineError(f"OpenMVS-Programm {name} fehlt")
        return p


@dataclass
class Settings:
    preset: str = "Standard"
    use_sheet: bool = True
    cut_mm: float = 0.6
    target_longest_mm: float | None = None   # nur ohne Maßstabsbogen


@dataclass
class Result:
    stl: Path
    report: meshtools.MeshReport
    scale_source: str


class Pipeline:
    def __init__(self, images: list[imageprep.ImageCheck], workspace: Path, settings: Settings,
                 log=print, on_stage=None, on_progress=None):
        self.images, self.ws, self.s = images, workspace, settings
        self.log = log
        self.on_stage = on_stage or (lambda key, name: None)
        self.on_progress = on_progress or (lambda frac: None)
        self._cancel = threading.Event()
        self._proc: subprocess.Popen | None = None
        self._done_weight = 0
        self._total_weight = sum(w for k, _, w in STAGES if k != "refine")
        if PRESETS[settings.preset]["refine"]:
            self._total_weight += 10

    # ---------- Hilfsfunktionen ----------
    def cancel(self):
        self._cancel.set()
        if self._proc and self._proc.poll() is None:
            self._proc.kill()

    def _stage(self, key: str):
        if self._cancel.is_set():
            raise Cancelled()
        name = dict((k, n) for k, n, _ in STAGES)[key]
        self.on_stage(key, name)
        self.log(f"\n=== {name} ===")
        self._cur_weight = dict((k, w) for k, _, w in STAGES)[key] or 10
        self.on_progress(self._done_weight / self._total_weight)

    def _stage_done(self):
        self._done_weight += self._cur_weight
        self.on_progress(min(1.0, self._done_weight / self._total_weight))

    def _sub_progress(self, frac: float):
        self.on_progress(min(1.0, (self._done_weight + self._cur_weight * frac) / self._total_weight))

    def _env(self, exe: Path) -> dict:
        env = os.environ.copy()
        root = exe.parent.parent if exe.parent.name.lower() == "bin" else exe.parent
        extra = [exe.parent, root / "lib", root / "bin", root]
        env["PATH"] = os.pathsep.join(str(p) for p in extra if p.exists()) + os.pathsep + env.get("PATH", "")
        plugins = root / "plugins"
        if plugins.exists():
            env["QT_PLUGIN_PATH"] = str(plugins)
        env["QT_QPA_PLATFORM"] = "offscreen"
        return env

    def _run(self, exe: Path, args: list, cwd: Path | None = None, check=True) -> str:
        if self._cancel.is_set():
            raise Cancelled()
        cmd = [str(exe)] + [str(a) for a in args]
        self.log("> " + " ".join(Path(cmd[0]).name if i == 0 else c for i, c in enumerate(cmd)))
        flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
        self._proc = subprocess.Popen(cmd, cwd=cwd, env=self._env(exe), stdout=subprocess.PIPE,
                                      stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                      errors="replace", creationflags=flags)
        tail = []
        for line in self._proc.stdout:
            line = line.rstrip()
            if line:
                tail = (tail + [line])[-60:]
                self.log(line)
        rc = self._proc.wait()
        if self._cancel.is_set():
            raise Cancelled()
        if check and rc != 0:
            raise PipelineError(f"{Path(exe).name} {args[0] if args else ''} ist fehlgeschlagen (Code {rc}).\n"
                                + "\n".join(tail[-8:]))
        return "\n".join(tail)

    # ---------- Ablauf ----------
    def run(self) -> Result:
        tools = Tools.locate()
        preset = PRESETS[self.s.preset]
        ws = self.ws
        img_dir, db = ws / "images", ws / "database.db"
        sparse, dense, mvs = ws / "sparse", ws / "dense", ws / "mvs"
        for d in (sparse, mvs):
            d.mkdir(parents=True, exist_ok=True)

        self._stage("prep")
        files = imageprep.prepare_images(self.images, img_dir, preset["max_side"],
                                         progress=lambda i, n: self._sub_progress(i / n))
        if len(files) < 8:
            raise PipelineError(f"Nur {len(files)} brauchbare Bilder – mindestens 8, besser 40+ nötig.")
        self.log(f"{len(files)} Bilder vorbereitet (max. {preset['max_side']} px)")
        self._stage_done()

        c = tools.colmap
        help_txt = self._run(c, ["feature_extractor", "-h"], check=False)
        fe = "FeatureExtraction" if "FeatureExtraction.use_gpu" in help_txt else "SiftExtraction"
        help_m = self._run(c, ["exhaustive_matcher", "-h"], check=False)
        fm = "FeatureMatching" if "FeatureMatching.use_gpu" in help_m else "SiftMatching"

        self._stage("features")
        if db.exists():
            db.unlink()
        self._run(c, ["feature_extractor", "--database_path", db, "--image_path", img_dir,
                      "--ImageReader.single_camera", 1, "--ImageReader.camera_model", "SIMPLE_RADIAL",
                      f"--{fe}.use_gpu", 0])
        self._stage_done()

        self._stage("matching")
        self._run(c, ["exhaustive_matcher", "--database_path", db, f"--{fm}.use_gpu", 0])
        self._stage_done()

        self._stage("mapping")
        self._run(c, ["mapper", "--database_path", db, "--image_path", img_dir, "--output_path", sparse])
        models = [p for p in sparse.iterdir() if (p / "images.bin").exists()]
        if not models:
            raise PipelineError("Kamerapositionen konnten nicht berechnet werden. Meist zu wenig "
                                "Überlappung, zu wenig Struktur oder spiegelnde Oberfläche.")
        best = max(models, key=lambda p: (p / "images.bin").stat().st_size)
        self._stage_done()

        self._stage("undistort")
        self._run(c, ["image_undistorter", "--image_path", img_dir, "--input_path", best,
                      "--output_path", dense, "--output_type", "COLMAP"])
        txt = ws / "sparse_txt"
        txt.mkdir(exist_ok=True)
        self._run(c, ["model_converter", "--input_path", dense / "sparse", "--output_path", txt,
                      "--output_type", "TXT"])
        cams, views = colmap_io.read_model(txt)
        self.log(f"{len(views)} von {len(files)} Bildern erfolgreich eingeordnet")
        centers = np.array([v.center() for v in views.values()])
        self._stage_done()

        self._stage("scale")
        align = None
        if self.s.use_sheet:
            align = markers.align_to_sheet(dense / "images", cams, views, log=self.log)
            if align is None:
                self.log("WARNUNG: Maßstabsbogen nicht (ausreichend) erkannt – Modell wird ohne "
                         "echten Maßstab erzeugt.")
        self._stage_done()

        self._stage("densify")
        self._run(tools.mvs("InterfaceCOLMAP"), ["-i", dense, "-o", mvs / "scene.mvs",
                                                 "--image-folder", dense / "images", "-w", mvs])
        self._run(tools.mvs("DensifyPointCloud"), [mvs / "scene.mvs", "-w", mvs,
                                                   "--resolution-level", preset["res_level"]])
        self._stage_done()

        self._stage("mesh")
        self._run(tools.mvs("ReconstructMesh"), [mvs / "scene_dense.mvs", "-w", mvs])
        mesh = self._newest_ply(mvs)
        self._stage_done()

        if preset["refine"]:
            self._stage("refine")
            try:
                mvs_mesh = mvs / "scene_dense_mesh.mvs"
                args = [mvs_mesh] if mvs_mesh.exists() else [mvs / "scene_dense.mvs", "-m", mesh]
                self._run(tools.mvs("RefineMesh"), args + ["-w", mvs, "--resolution-level", 2])
                mesh = self._newest_ply(mvs)
            except PipelineError as e:
                self.log(f"Feinschliff übersprungen: {e}")
            self._stage_done()

        self._stage("post")
        stl, rep = meshtools.postprocess(
            mesh, ws / "ergebnis", sheet_T=align.T if align else None, camera_centers=centers,
            cut_mm=self.s.cut_mm, target_longest_mm=None if align else self.s.target_longest_mm,
            log=self.log)
        self._stage_done()
        src = ("Maßstabsbogen (±%.1f mm)" % align.rms_mm) if align else (
            "manuelle Angabe" if self.s.target_longest_mm else "kein Maßstab")
        self.log(f"Fertig: {rep.size_mm[0]:.1f} × {rep.size_mm[1]:.1f} × {rep.size_mm[2]:.1f} "
                 f"{'mm' if rep.scaled else 'Einheiten'}")
        return Result(stl, rep, src)

    @staticmethod
    def _newest_ply(folder: Path) -> Path:
        plys = [p for p in folder.glob("*.ply") if "mesh" in p.stem.lower()]
        if not plys:
            raise PipelineError("OpenMVS hat kein Mesh erzeugt.")
        return max(plys, key=lambda p: p.stat().st_mtime)
