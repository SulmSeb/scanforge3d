"""Startpunkt von ScanForge 3D."""
import multiprocessing

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from app.gui import run
    run()
