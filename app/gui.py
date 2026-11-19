"""Hauptfenster von ScanForge 3D."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThread, QThreadPool, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog,
                               QGridLayout, QGroupBox, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit,
                               QProgressBar, QPushButton, QSplitter, QTabWidget, QTextBrowser,
                               QVBoxLayout, QWidget)

from . import imageprep, markers
from .pipeline import PRESETS, Cancelled, Pipeline, PipelineError, Settings
from .viewer import MeshViewer

APP_NAME = "ScanForge 3D"
VERSION = "1.0.0"
STATUS_COLORS = {"ok": "#3fb950", "warn": "#d29922", "bad": "#f85149", "pending": "#6e7681"}

STYLE = """
QWidget { background:#1c1e23; color:#e6e6e6; font-size:13px; }
QGroupBox { border:1px solid #30343c; border-radius:8px; margin-top:14px; padding:10px; }
QGroupBox::title { subcontrol-origin: margin; left:10px; color:#f0883e; font-weight:bold; }
QPushButton { background:#2d3139; border:1px solid #3d424b; border-radius:6px; padding:7px 12px; }
QPushButton:hover { background:#383d46; }
QPushButton:disabled { color:#666; }
QPushButton#primary { background:#e8772e; border:none; color:white; font-weight:bold; font-size:15px; padding:11px; }
QPushButton#primary:hover { background:#f08a45; }
QPushButton#primary:disabled { background:#5a3a24; color:#aaa; }
QListWidget, QPlainTextEdit, QTextBrowser { background:#15171b; border:1px solid #30343c; border-radius:6px; }
QProgressBar { border:1px solid #30343c; border-radius:6px; text-align:center; height:20px; background:#15171b; }
QProgressBar::chunk { background:#e8772e; border-radius:5px; }
QComboBox, QDoubleSpinBox { background:#2d3139; border:1px solid #3d424b; border-radius:5px; padding:4px; }
QTabWidget::pane { border:none; }
QTabBar::tab { background:#23262c; padding:8px 16px; border-top-left-radius:6px; border-top-right-radius:6px; }
QTabBar::tab:selected { background:#2d3139; color:#f0883e; }
"""

GUIDE = """
<h2>So gelingt der Scan</h2>
<ol>
<li><b>Maßstabsbogen drucken</b> (Knopf links) – mit <i>100 % / tatsächliche Größe</i>.
Die Kontrolllinie mit dem Lineal prüfen: genau 100 mm.</li>
<li>Bogen flach auf einen Tisch legen und das Teil in die Mitte stellen. Die Marker dürfen nicht verdeckt sein.</li>
<li><b>Licht:</b> hell und gleichmäßig, am besten Tageslicht ohne direkte Sonne. Keine harten Schatten, kein Blitz.</li>
<li><b>Fotos:</b> 40–100 Stück. Zwei bis drei Runden um das Teil (flach, schräg von oben, steil von oben).
Zwischen zwei Fotos nur ca. 10° weitergehen – jedes Foto sollte sich zu ~70 % mit dem vorherigen überdecken.</li>
<li>Das Teil soll das Bild gut ausfüllen, aber ein paar Marker sollten immer mit drauf sein.</li>
<li>Nicht zoomen, die Hauptkamera (1×) verwenden, scharf stellen (aufs Teil tippen).</li>
</ol>
<h3>Problematische Oberflächen</h3>
<p>Glänzend, durchsichtig, tiefschwarz oder völlig einfarbig glatt funktioniert schlecht.
Abhilfe: Scanspray (verfliegt von selbst) oder dünn Trockenshampoo/Puder auftragen.</p>
<h3>Genauigkeit</h3>
<p>Typisch 0,3–1 mm. Für Passungen, Lagersitze oder Gewinde das Modell als Vorlage nehmen und
die Funktionsmaße in CAD (z. B. FreeCAD, Fusion) mit dem Messschieber nachkonstruieren.</p>
<h3>Rückseite / Unterseite</h3>
<p>Die Standfläche wird automatisch flach abgeschnitten – ideal fürs Druckbett.</p>
"""


def dot_icon(color: str) -> QIcon:
    pm = QPixmap(14, 14)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(color))
    p.setPen(Qt.NoPen)
    p.drawEllipse(1, 1, 12, 12)
    p.end()
    return QIcon(pm)


def workspace_root() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share"))
    return base / "ScanForge3D" / "projekte"


def open_path(p: Path):
    if sys.platform.startswith("win"):
        os.startfile(str(p))  # noqa
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(p)])
    else:
        subprocess.Popen(["xdg-open", str(p)])


# ---------------- Hintergrund-Aufgaben ----------------
class CheckSignals(QObject):
    done = Signal(object)


class CheckTask(QRunnable):
    def __init__(self, path: Path):
        super().__init__()
        self.path, self.signals = path, CheckSignals()

    def run(self):
        self.signals.done.emit(imageprep.check_image(self.path))


class Worker(QObject):
    log = Signal(str)
    stage = Signal(str)
    progress = Signal(float)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, checks, workspace, settings):
        super().__init__()
        self.pipe = Pipeline(checks, workspace, settings, log=self.log.emit,
                             on_stage=lambda k, n: self.stage.emit(n),
                             on_progress=self.progress.emit)

    def run(self):
        try:
            self.finished.emit(self.pipe.run())
        except Cancelled:
            self.failed.emit("Abgebrochen.")
        except PipelineError as e:
            self.failed.emit(str(e))
        except Exception as e:  # unerwartet
            import traceback
            self.log.emit(traceback.format_exc())
            self.failed.emit(f"Unerwarteter Fehler: {e}")


# ---------------- Hauptfenster ----------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} – Fotos zu 3D-Druck")
        self.resize(1320, 820)
        self.setAcceptDrops(True)
        self.checks: dict[str, imageprep.ImageCheck] = {}
        self.items: dict[str, QListWidgetItem] = {}
        self.pool = QThreadPool.globalInstance()
        self.thread: QThread | None = None
        self.worker: Worker | None = None
        self.result = None
        self.t_start = 0.0
        self.timer = QTimer(self, interval=1000, timeout=self._tick)
        self._build()

    # ----- Aufbau -----
    def _build(self):
        root = QWidget()
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        split = QSplitter(Qt.Horizontal)
        outer.addWidget(split)

        # links: Fotos + Einstellungen
        left = QWidget()
        L = QVBoxLayout(left)
        title = QLabel(f"<span style='font-size:22px;font-weight:bold;color:#f0883e'>{APP_NAME}</span>"
                       f"<br><span style='color:#8a8f98'>Fotos rein – druckfertige STL raus</span>")
        L.addWidget(title)

        g_img = QGroupBox("1 · Fotos")
        gi = QVBoxLayout(g_img)
        self.list = QListWidget()
        self.list.setViewMode(QListWidget.IconMode)
        self.list.setIconSize(QSize(96, 72))
        self.list.setGridSize(QSize(112, 100))
        self.list.setResizeMode(QListWidget.Adjust)
        self.list.setSelectionMode(QListWidget.ExtendedSelection)
        self.list.setMinimumHeight(250)
        self.drop_hint = QLabel("Fotos oder Ordner hierher ziehen\n(JPG, PNG, iPhone-HEIC)")
        self.drop_hint.setAlignment(Qt.AlignCenter)
        self.drop_hint.setStyleSheet("color:#6e7681; border:2px dashed #3d424b; border-radius:8px; padding:30px;")
        gi.addWidget(self.drop_hint)
        gi.addWidget(self.list)
        self.list.hide()
        row = QHBoxLayout()
        b_add = QPushButton("Fotos hinzufügen…")
        b_add.clicked.connect(self._add_files)
        b_dir = QPushButton("Ordner…")
        b_dir.clicked.connect(self._add_dir)
        b_rm = QPushButton("Auswahl entfernen")
        b_rm.clicked.connect(self._remove_selected)
        b_clr = QPushButton("Alle leeren")
        b_clr.clicked.connect(self._clear)
        for b in (b_add, b_dir, b_rm, b_clr):
            row.addWidget(b)
        gi.addLayout(row)
        self.summary = QLabel("Noch keine Fotos.")
        self.summary.setStyleSheet("color:#8a8f98")
        gi.addWidget(self.summary)
        L.addWidget(g_img, 1)

        g_set = QGroupBox("2 · Einstellungen")
        gs = QGridLayout(g_set)
        gs.addWidget(QLabel("Qualität:"), 0, 0)
        self.preset = QComboBox()
        self.preset.addItems(list(PRESETS))
        self.preset.setCurrentText("Standard")
        self.preset.setToolTip("Schnell: Test · Standard: empfohlen · Hoch: feinere Details, dauert deutlich länger")
        gs.addWidget(self.preset, 0, 1)
        self.use_sheet = QCheckBox("Maßstabsbogen verwenden (echte mm, automatische Ausrichtung)")
        self.use_sheet.setChecked(True)
        self.use_sheet.toggled.connect(self._sheet_toggled)
        gs.addWidget(self.use_sheet, 1, 0, 1, 2)
        b_sheet = QPushButton("Maßstabsbogen als PDF speichern…")
        b_sheet.clicked.connect(self._save_sheet)
        gs.addWidget(b_sheet, 2, 0, 1, 2)
        self.lbl_len = QLabel("Ohne Bogen – längste Kante (mm):")
        gs.addWidget(self.lbl_len, 3, 0)
        self.longest = QDoubleSpinBox()
        self.longest.setRange(0, 2000)
        self.longest.setDecimals(1)
        self.longest.setSpecialValueText("unbekannt")
        self.longest.setToolTip("Mit dem Messschieber die längste Abmessung messen. 0 = ohne Maßstab")
        gs.addWidget(self.longest, 3, 1)
        gs.addWidget(QLabel("Bodenschnitt (mm):"), 4, 0)
        self.cut = QDoubleSpinBox()
        self.cut.setRange(0.0, 10.0)
        self.cut.setSingleStep(0.1)
        self.cut.setValue(0.6)
        self.cut.setToolTip("So viel wird unten abgeschnitten, um Papier/Tisch sauber zu entfernen")
        gs.addWidget(self.cut, 4, 1)
        L.addWidget(g_set)
        self._sheet_toggled(True)

        g_run = QGroupBox("3 · Erstellen")
        gr = QVBoxLayout(g_run)
        self.btn_start = QPushButton("3D-Modell erstellen")
        self.btn_start.setObjectName("primary")
        self.btn_start.clicked.connect(self._start)
        self.btn_cancel = QPushButton("Abbrechen")
        self.btn_cancel.clicked.connect(self._cancel)
        self.btn_cancel.setEnabled(False)
        self.stage_lbl = QLabel("Bereit.")
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setFormat("%p %")
        gr.addWidget(self.btn_start)
        gr.addWidget(self.stage_lbl)
        gr.addWidget(self.bar)
        gr.addWidget(self.btn_cancel)
        L.addWidget(g_run)
        split.addWidget(left)

        # rechts: Tabs
        tabs = QTabWidget()
        prev = QWidget()
        P = QVBoxLayout(prev)
        self.viewer = MeshViewer()
        P.addWidget(self.viewer, 1)
        self.info = QLabel("")
        self.info.setStyleSheet("font-size:14px; padding:6px;")
        self.info.setWordWrap(True)
        P.addWidget(self.info)
        r2 = QHBoxLayout()
        self.btn_save = QPushButton("STL speichern unter…")
        self.btn_save.clicked.connect(self._save_stl)
        self.btn_slicer = QPushButton("Im Slicer / 3D-Viewer öffnen")
        self.btn_slicer.clicked.connect(lambda: self.result and open_path(self.result.stl))
        self.btn_folder = QPushButton("Projektordner öffnen")
        self.btn_folder.clicked.connect(lambda: self.result and open_path(self.result.stl.parent))
        for b in (self.btn_save, self.btn_slicer, self.btn_folder):
            b.setEnabled(False)
            r2.addWidget(b)
        P.addLayout(r2)
        tabs.addTab(prev, "3D-Vorschau")
        guide = QTextBrowser()
        guide.setHtml(GUIDE)
        tabs.addTab(guide, "Anleitung")
        self.logbox = QPlainTextEdit()
        self.logbox.setReadOnly(True)
        self.logbox.setFont(QFont("Consolas", 9))
        self.logbox.setMaximumBlockCount(5000)
        tabs.addTab(self.logbox, "Protokoll")
        self.tabs = tabs
        split.addWidget(tabs)
        split.setSizes([480, 840])

    # ----- Fotos -----
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self._add_paths([u.toLocalFile() for u in e.mimeData().urls()])

    def _add_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Fotos wählen", "",
                                                "Bilder (*.jpg *.jpeg *.png *.heic *.heif *.tif *.tiff)")
        self._add_paths(files)

    def _add_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Ordner mit Fotos wählen")
        if d:
            self._add_paths([d])

    def _add_paths(self, paths):
        new = [p for p in imageprep.collect_images(paths) if str(p) not in self.checks]
        for p in new:
            key = str(p)
            self.checks[key] = imageprep.ImageCheck(p, status="pending")
            it = QListWidgetItem(dot_icon(STATUS_COLORS["pending"]), p.name[:16])
            it.setData(Qt.UserRole, key)
            it.setToolTip("wird geprüft…")
            self.list.addItem(it)
            self.items[key] = it
            task = CheckTask(p)
            task.signals.done.connect(self._on_checked)
            self.pool.start(task)
        if self.checks:
            self.drop_hint.hide()
            self.list.show()
        self._update_summary()

    def _on_checked(self, c: imageprep.ImageCheck):
        key = str(c.path)
        if key not in self.checks:
            return
        self.checks[key] = c
        it = self.items[key]
        try:
            img = imageprep.load_rgb(c.path, 200)
            from PIL.ImageQt import ImageQt
            pm = QPixmap.fromImage(ImageQt(img))
            canvas = QPixmap(96, 72)
            canvas.fill(Qt.transparent)
            p = QPainter(canvas)
            sc = pm.scaled(96, 72, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            p.drawPixmap((96 - sc.width()) // 2, (72 - sc.height()) // 2, sc)
            p.setRenderHint(QPainter.Antialiasing)
            p.setBrush(QColor(STATUS_COLORS[c.status]))
            p.setPen(QColor("#15171b"))
            p.drawEllipse(78, 54, 15, 15)
            p.end()
            it.setIcon(QIcon(canvas))
        except Exception:
            it.setIcon(dot_icon(STATUS_COLORS[c.status]))
        txt = {"ok": "gut", "warn": "nutzbar", "bad": "wird aussortiert"}[c.status]
        it.setToolTip(f"{c.path.name}\n{c.width}×{c.height}px · Schärfe {c.sharpness:.0f}\n{txt}"
                      + (": " + ", ".join(c.reasons) if c.reasons else ""))
        self._update_summary()

    def _remove_selected(self):
        for it in self.list.selectedItems():
            key = it.data(Qt.UserRole)
            self.checks.pop(key, None)
            self.items.pop(key, None)
            self.list.takeItem(self.list.row(it))
        self._update_summary()

    def _clear(self):
        self.checks.clear()
        self.items.clear()
        self.list.clear()
        self.list.hide()
        self.drop_hint.show()
        self._update_summary()

    def _update_summary(self):
        cs = list(self.checks.values())
        if not cs:
            self.summary.setText("Noch keine Fotos.")
            return
        n = {k: sum(c.status == k for c in cs) for k in STATUS_COLORS}
        tip = ""
        usable = n["ok"] + n["warn"]
        if n["pending"] == 0:
            if usable < 20:
                tip = " – Tipp: mindestens 40 Fotos für ein gutes Ergebnis"
            elif usable > 250:
                tip = " – viele Fotos: die Berechnung dauert lange"
        self.summary.setText(
            f"<span style='color:{STATUS_COLORS['ok']}'>● {n['ok']} gut</span> &nbsp; "
            f"<span style='color:{STATUS_COLORS['warn']}'>● {n['warn']} nutzbar</span> &nbsp; "
            f"<span style='color:{STATUS_COLORS['bad']}'>● {n['bad']} aussortiert</span>"
            + (f" &nbsp; ⏳ {n['pending']} in Prüfung" if n["pending"] else "") + tip)

    # ----- Einstellungen -----
    def _sheet_toggled(self, on):
        self.longest.setEnabled(not on)
        self.lbl_len.setEnabled(not on)

    def _save_sheet(self):
        f, _ = QFileDialog.getSaveFileName(self, "Maßstabsbogen speichern",
                                           str(Path.home() / "ScanForge_Massstabsbogen.pdf"), "PDF (*.pdf)")
        if f:
            markers.make_sheet(Path(f))
            open_path(Path(f))

    # ----- Ablauf -----
    def _start(self):
        cs = list(self.checks.values())
        if any(c.status == "pending" for c in cs):
            QMessageBox.information(self, APP_NAME, "Die Fotos werden noch geprüft – einen Moment bitte.")
            return
        usable = [c for c in cs if c.usable]
        if len(usable) < 8:
            QMessageBox.warning(self, APP_NAME, "Bitte mindestens 8 brauchbare Fotos hinzufügen (empfohlen: 40+).")
            return
        ws = workspace_root() / datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        ws.mkdir(parents=True, exist_ok=True)
        s = Settings(preset=self.preset.currentText(), use_sheet=self.use_sheet.isChecked(),
                     cut_mm=self.cut.value(),
                     target_longest_mm=self.longest.value() or None)
        self.logbox.clear()
        self._log(f"{APP_NAME} {VERSION} – Projekt: {ws}")
        self.thread = QThread()
        self.worker = Worker(usable, ws, s)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.log.connect(self._log)
        self.worker.stage.connect(lambda n: self.stage_lbl.setText(f"<b>{n}</b> …"))
        self.worker.progress.connect(lambda f: self.bar.setValue(int(f * 1000)))
        self.worker.finished.connect(self._done)
        self.worker.failed.connect(self._failed)
        for sig in (self.worker.finished, self.worker.failed):
            sig.connect(self.thread.quit)
        self.btn_start.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.bar.setValue(0)
        self.t_start = time.time()
        self.timer.start()
        self.thread.start()

    def _tick(self):
        el = int(time.time() - self.t_start)
        frac = self.bar.value() / 1000
        eta = ""
        if frac > 0.08:
            rest = int(el / frac - el)
            eta = f" · noch ca. {rest // 60} min" if rest > 60 else " · gleich fertig"
        self.bar.setFormat(f"%p %  ·  {el // 60}:{el % 60:02d}{eta}")

    def _cancel(self):
        if self.worker:
            self.worker.pipe.cancel()
            self.stage_lbl.setText("Wird abgebrochen …")

    def _log(self, s: str):
        self.logbox.appendPlainText(s)

    def _finish_ui(self):
        self.timer.stop()
        self.btn_start.setEnabled(True)
        self.btn_cancel.setEnabled(False)

    def _done(self, res):
        self._finish_ui()
        self.result = res
        self.bar.setValue(1000)
        self.stage_lbl.setText("<b style='color:#3fb950'>Fertig!</b>")
        import trimesh
        self.viewer.show_mesh(trimesh.load(res.stl, force="mesh"))
        r = res.report
        unit = "mm" if r.scaled else "(ohne Maßstab)"
        vol = f" · Volumen {r.volume_cm3:.1f} cm³" if r.volume_cm3 else ""
        warn = "" if r.watertight else ("<br><span style='color:#d29922'>Hinweis: Das Modell ist nicht ganz "
                                        "geschlossen – die meisten Slicer reparieren das automatisch.</span>")
        self.info.setText(f"<b>Größe:</b> {r.size_mm[0]:.1f} × {r.size_mm[1]:.1f} × {r.size_mm[2]:.1f} {unit}"
                          f"{vol} · {r.faces:,} Dreiecke · Maßstab: {res.scale_source}".replace(",", ".") + warn)
        for b in (self.btn_save, self.btn_slicer, self.btn_folder):
            b.setEnabled(True)
        self.tabs.setCurrentIndex(0)

    def _failed(self, msg):
        self._finish_ui()
        self.stage_lbl.setText("<b style='color:#f85149'>Nicht erfolgreich</b>")
        self._log("FEHLER: " + msg)
        if msg != "Abgebrochen.":
            QMessageBox.warning(self, APP_NAME, msg + "\n\nDetails im Tab „Protokoll“. Tipps im Tab „Anleitung“.")

    def _save_stl(self):
        if not self.result:
            return
        f, _ = QFileDialog.getSaveFileName(self, "STL speichern", str(Path.home() / "scan.stl"), "STL (*.stl)")
        if f:
            shutil.copy(self.result.stl, f)

    def closeEvent(self, e):
        if self.worker and self.btn_cancel.isEnabled():
            if QMessageBox.question(self, APP_NAME, "Berechnung läuft noch. Wirklich beenden?") != QMessageBox.Yes:
                e.ignore()
                return
            self.worker.pipe.cancel()
            self.thread.quit()
            self.thread.wait(3000)
        e.accept()


def run():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyleSheet(STYLE)
    icon = Path(getattr(sys, "_MEIPASS", Path(__file__).parent.parent)) / "assets" / "icon.ico"
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    w = MainWindow()
    w.show()
    sys.exit(app.exec())
