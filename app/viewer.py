"""3D-Vorschau des Ergebnisses (pyqtgraph/OpenGL) mit Fallback, falls OpenGL fehlt."""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

try:
    import pyqtgraph as pg
    import pyqtgraph.opengl as gl
    GL_OK = True
except Exception:  # pragma: no cover
    GL_OK = False


class MeshViewer(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.view = None
        self.items = []
        if GL_OK:
            try:
                self.view = gl.GLViewWidget()
                self.view.setBackgroundColor((32, 34, 40))
                self.view.setCameraPosition(distance=200, elevation=25, azimuth=45)
                lay.addWidget(self.view)
            except Exception:
                self.view = None
        self.placeholder = QLabel("Hier erscheint dein 3D-Modell.\nZiehen = drehen · Mausrad = zoomen")
        self.placeholder.setAlignment(Qt.AlignCenter)
        self.placeholder.setStyleSheet("color:#8a8f98; font-size:14px;")
        lay.addWidget(self.placeholder)
        if self.view:
            self.view.hide()

    def show_mesh(self, mesh):
        if not self.view:
            self.placeholder.setText("3D-Vorschau nicht verfügbar (OpenGL fehlt).\n"
                                     "Öffne die STL-Datei direkt im Slicer.")
            return
        for it in self.items:
            self.view.removeItem(it)
        self.items = []
        v = np.asarray(mesh.vertices, dtype=np.float32)
        f = np.asarray(mesh.faces, dtype=np.int32)
        size = float(max(mesh.extents)) or 1.0
        # Druckbett-Raster
        grid = gl.GLGridItem()
        step = 10 ** np.floor(np.log10(size / 2)) if size > 2 else 1
        grid.setSize(size * 3, size * 3)
        grid.setSpacing(step, step)
        grid.setColor((90, 95, 105, 140))
        item = gl.GLMeshItem(vertexes=v, faces=f, smooth=False, shader="shaded",
                             color=(0.95, 0.55, 0.2, 1.0), drawEdges=False)
        for it in (grid, item):
            self.view.addItem(it)
            self.items.append(it)
        c = mesh.bounds.mean(0)
        self.view.opts["center"] = pg.Vector(c[0], c[1], c[2])
        self.view.setCameraPosition(distance=size * 2.2, elevation=28, azimuth=40)
        self.placeholder.hide()
        self.view.show()
