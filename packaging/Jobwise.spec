# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec shared by Windows and Linux. Build from the repo root:
#   pyinstaller --noconfirm --clean packaging/Jobwise.spec
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).resolve().parent
IS_WIN = sys.platform == "win32"

hiddenimports = (
    collect_submodules("google.genai")
    + collect_submodules("resume_matcher")
    + collect_submodules("httpx")
    + ["sqlalchemy.dialects.sqlite", "PySide6.QtSvg", "pymupdf", "h11", "anyio", "certifi"]
)

# Qt modules the app never uses: keep the bundle smaller.
excludes = [
    "tkinter", "matplotlib", "numpy.tests", "pytest", "IPython", "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.Qt3DCore",
    "PySide6.QtMultimedia", "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtBluetooth",
    "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtDesigner",
    # optional PyMuPDF add-ons / scientific stack the app does not use
    "scipy", "numpy", "pandas", "onnxruntime", "pymupdf.layout", "pymupdf4llm",  # (PIL is required by ReportLab - keep)
]

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / "assets" / "icon.png"), "assets"),
        (str(ROOT / "assets" / "icon.ico"), "assets"),
        (str(ROOT / "assets" / "fonts"), "assets/fonts"),
        # python-docx resolves templates as docx/parts/../templates; the folder must exist on disk.
        (str(ROOT / "packaging" / "keep.txt"), "docx/parts"),
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Jobwise",
    debug=False,
    strip=False,
    upx=False,
    console=False,          # GUI app; --selftest prints are still visible when run from a terminal on Linux
    icon=str(ROOT / "assets" / "icon.ico") if IS_WIN else None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Jobwise")
