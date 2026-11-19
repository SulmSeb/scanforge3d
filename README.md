# ScanForge 3D – Fotos rein, druckfertige STL raus

Windows-Programm, das aus Handyfotos (z. B. iPhone) eines Teils ein 3D-Modell erzeugt und es
direkt druckfertig macht: echte Millimeter, flache Unterseite, aufs Druckbett ausgerichtet.
Läuft ohne spezielle Grafikkarte auf jedem 64-Bit-Windows-PC (Windows 10/11).

## Was das Programm besonders macht

| Funktion | Nutzen |
|---|---|
| **Maßstabsbogen mit ArUco-Markern** | Ausdrucken, Teil draufstellen, fotografieren – das Modell kommt automatisch in **echten mm** heraus, ohne Nachmessen |
| **Automatische Druckbett-Ausrichtung** | Der Bogen definiert den Boden: Das Teil steht gerade, die Unterseite wird flach abgeschnitten und geschlossen |
| **Foto-Ampel** | Jedes Foto wird beim Hinzufügen auf Schärfe, Helligkeit und Auflösung geprüft. Verwackelte Fotos werden aussortiert |
| **iPhone-HEIC direkt** | Keine Umwandlung nötig, auch die Drehung wird korrekt übernommen |
| **3D-Vorschau** | Ergebnis drehen und zoomen, Maße und Volumen werden angezeigt |
| **Ohne Bogen nutzbar** | Tisch-Ebene wird automatisch erkannt und entfernt; Maßstab über „längste Kante in mm“ |
| **Drei Qualitätsstufen** | Schnell (Test), Standard, Hoch (mit Mesh-Feinschliff) |

## Arbeitsablauf im Programm

1. *Maßstabsbogen als PDF speichern* → mit **100 % / tatsächliche Größe** drucken, die 100-mm-Kontrolllinie nachmessen.
2. Teil in die Mitte des Bogens stellen und 40–100 Fotos rundherum machen (Tab **Anleitung** im Programm).
3. Fotos ins Fenster ziehen → **3D-Modell erstellen**.
4. Ergebnis: `modell.stl` (und `modell.obj`) → *Im Slicer öffnen* oder *STL speichern unter…*

Rechenzeit auf einem normalen PC (Standard, ~60 Fotos): ca. 15–45 Minuten.

## Die Setup.exe erzeugen

Eine `.exe` kann nur auf Windows gebaut werden. Dafür gibt es zwei Wege:

### Weg A – automatisch über GitHub (nichts installieren)
1. Kostenloses GitHub-Konto anlegen, neues Repository erstellen, diesen Ordner hochladen
   (z. B. mit GitHub Desktop).
2. Im Repository auf **Actions** gehen. Der Build startet automatisch (ca. 10 Minuten).
3. Im fertigen Lauf unter **Artifacts** → `ScanForge3D_Setup` herunterladen → enthält die `ScanForge3D_Setup.exe`.

### Weg B – auf deinem PC
1. [Python 3.12](https://www.python.org/downloads/) installieren (Haken bei „Add python.exe to PATH“).
2. [Inno Setup 6](https://jrsoftware.org/isdl.php) installieren.
3. `build.bat` doppelklicken. Am Ende liegt die Datei in `Output\ScanForge3D_Setup.exe`.

Zum Ausprobieren ohne Installer: `pip install -r requirements.txt`, `python tools/download_tools.py`, `python main.py`.

> Falls `download_tools.py` ein Paket nicht findet (die Dateinamen auf GitHub ändern sich manchmal):
> COLMAP (`colmap-x64-windows-nocuda.zip`) von github.com/colmap/colmap/releases nach `tools/colmap/`
> und die Windows-Binaries von github.com/cdcseacave/openMVS/releases nach `tools/openmvs/` entpacken.

## Technik

```
Fotos ─► Prüfung/Vorbereitung ─► COLMAP: Merkmale, Zuordnung, Kamerapositionen (SfM)
      ─► Entzerren ─► ArUco-Marker triangulieren ─► Ähnlichkeitstransformation (Umeyama) → mm
      ─► OpenMVS: dichte Punktwolke, Oberflächennetz (optional Feinschliff)
      ─► trimesh: Bodenschnitt + Deckel, größtes Teil, Löcher schließen, Ausrichten ─► STL
```

| Datei | Inhalt |
|---|---|
| `app/gui.py` | Oberfläche (PySide6) |
| `app/pipeline.py` | Steuerung von COLMAP/OpenMVS, Fortschritt, Abbruch |
| `app/markers.py` | Maßstabsbogen erzeugen, Marker erkennen, triangulieren, ausrichten |
| `app/meshtools.py` | Nachbearbeitung für den 3D-Druck |
| `app/imageprep.py` | Foto-Ampel, HEIC, Verkleinern |
| `app/colmap_io.py` | COLMAP-Modell einlesen |
| `tests/` | Synthetische Tests (Marker-Genauigkeit, Mesh, kompletter Ablauf mit Attrappen) |

Tests: `python -m tests.test_core` und (Linux/macOS) `python -m tests.test_pipeline`.

## Grenzen

- Genauigkeit typisch 0,3–1 mm. Für Passungen und Gewinde: Scan als Vorlage nehmen, Funktionsmaße in CAD nachkonstruieren.
- Glänzende, durchsichtige, schwarze oder strukturlose Teile vorher mattieren (Scanspray, Trockenshampoo).
- Die Standfläche selbst ist nicht sichtbar und wird flach angenommen.

## Lizenzen

COLMAP (BSD) und OpenMVS (AGPL-3.0) werden als eigenständige Programme mitgeliefert und aufgerufen.
Bei Weitergabe des Installers gelten deren Lizenzbedingungen (u. a. Hinweis auf den Quellcode von OpenMVS).
