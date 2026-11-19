"""End-to-End-Test der Pipeline-Steuerung mit Attrappen für COLMAP und OpenMVS.

Die Attrappen erzeugen die Dateien, die die echten Programme erzeugen würden
(aus einem synthetischen Datensatz). Geprüft wird alles, was ScanForge selbst
macht: Aufrufreihenfolge, Pfade, Modellwahl, TXT-Import, Maßstab, Nachbearbeitung.
Nur unter Linux/macOS lauffähig (Attrappen sind Shell-ausführbare Python-Skripte).
"""
import json
import pickle
import stat
import sys
import tempfile
from pathlib import Path

from app import imageprep, pipeline
from tests.test_core import make_dataset

FAKE_COLMAP = r'''#!{py}
import sys, os, shutil, pickle, json
from pathlib import Path
D = pickle.load(open({data!r}, "rb"))
a = sys.argv[1:]
cmd = a[0]
opt = dict(zip(a[1::2], a[2::2]))
open({calls!r}, "a").write(json.dumps(a) + "\n")
if "-h" in a:
    print("  --FeatureExtraction.use_gpu arg (=1)\n  --FeatureMatching.use_gpu arg (=1)"); sys.exit(0)
if cmd == "feature_extractor":
    assert opt["--FeatureExtraction.use_gpu"] == "0"
    Path(opt["--database_path"]).write_text("db")
elif cmd == "exhaustive_matcher":
    assert Path(opt["--database_path"]).exists()
elif cmd == "mapper":
    out = Path(opt["--output_path"])
    (out / "0").mkdir(parents=True); (out / "0" / "images.bin").write_bytes(b"x" * 10)
    (out / "1").mkdir(parents=True); (out / "1" / "images.bin").write_bytes(b"x" * 99)  # größeres Modell
elif cmd == "image_undistorter":
    assert opt["--input_path"].endswith("1"), "größtes Modell muss gewählt werden"
    out = Path(opt["--output_path"])
    shutil.copytree(D["img_dir"], out / "images"); (out / "sparse").mkdir(parents=True)
elif cmd == "model_converter":
    out = Path(opt["--output_path"])
    (out / "cameras.txt").write_text(D["cameras"]); (out / "images.txt").write_text(D["images"])
print("ok", cmd)
'''

FAKE_MVS = r'''#!{py}
import sys, shutil, json
from pathlib import Path
name = Path(sys.argv[0]).name
open({calls!r}, "a").write(json.dumps([name] + sys.argv[1:]) + "\n")
a = sys.argv[1:]
w = Path(a[a.index("-w") + 1])
if name == "InterfaceCOLMAP": Path(a[a.index("-o") + 1]).write_text("mvs")
elif name == "DensifyPointCloud": (w / "scene_dense.mvs").write_text("dense")
elif name == "ReconstructMesh": shutil.copy({raw!r}, w / "scene_dense_mesh.ply")
print("ok", name)
'''


def colmap_txt(cams, views):
    from scipy.spatial.transform import Rotation
    c = "".join(f"{k} {v.model} {v.width} {v.height} " + " ".join(map(str, v.params)) + "\n"
                for k, v in cams.items())
    lines = ["# Image list"]
    for v in views.values():
        x, y, z, w = Rotation.from_matrix(v.R).as_quat()
        lines.append(f"{v.id} {w} {x} {y} {z} {v.t[0]} {v.t[1]} {v.t[2]} {v.camera_id} {v.name}")
        lines.append("")
    return c, "\n".join(lines) + "\n"


def main():
    tmp = Path(tempfile.mkdtemp())
    img_dir, cams, views, T, centers, raw = make_dataset(tmp)
    cam_txt, img_txt = colmap_txt(cams, views)
    data, calls = tmp / "data.pkl", tmp / "calls.jsonl"
    pickle.dump({"img_dir": str(img_dir), "cameras": cam_txt, "images": img_txt}, open(data, "wb"))
    tools = tmp / "tools"
    (tools / "colmap" / "bin").mkdir(parents=True)
    (tools / "openmvs").mkdir(parents=True)
    scripts = {tools / "colmap" / "bin" / "colmap": FAKE_COLMAP.format(py=sys.executable, data=str(data), calls=str(calls))}
    for n in ("InterfaceCOLMAP", "DensifyPointCloud", "ReconstructMesh", "RefineMesh"):
        scripts[tools / "openmvs" / n] = FAKE_MVS.format(py=sys.executable, calls=str(calls), raw=str(raw))
    for p, src in scripts.items():
        p.write_text(src)
        p.chmod(p.stat().st_mode | stat.S_IEXEC)
    pipeline.tools_root = lambda: tools

    checks = [imageprep.check_image(p) for p in sorted(img_dir.glob("*.jpg"))]
    stages = []
    pipe = pipeline.Pipeline(checks, tmp / "ws", pipeline.Settings(preset="Schnell"),
                             log=lambda s: None, on_stage=lambda k, n: stages.append(k))
    res = pipe.run()
    print("Stufen:", stages)
    print("Ergebnis:", res.stl, [round(x, 2) for x in res.report.size_mm], res.scale_source)
    assert res.report.scaled and abs(res.report.size_mm[0] - 40) < 0.7 and abs(res.report.size_mm[1] - 25) < 0.7
    order = [json.loads(l)[0] for l in calls.read_text().splitlines() if "-h" not in l]
    print("Aufrufe:", order)
    assert order == ["feature_extractor", "exhaustive_matcher", "mapper", "image_undistorter",
                     "model_converter", "InterfaceCOLMAP", "DensifyPointCloud", "ReconstructMesh"]
    print("PIPELINE-TEST OK")


if __name__ == "__main__":
    main()
