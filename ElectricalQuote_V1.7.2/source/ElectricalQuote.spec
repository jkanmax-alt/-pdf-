# -*- mode: python ; coding: utf-8 -*-
"""Windows x64 onedir bundle; run from any working directory.

python -m PyInstaller --clean --noconfirm source/ElectricalQuote.spec
"""
from pathlib import Path
import sys
import json
import shutil
import importlib.metadata as metadata

from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

source_dir = Path(SPECPATH).resolve()
project_dir = source_dir.parent
engine_dir = project_dir / "vendor" / "tesseract"
# Validate the already downloaded engine and DLL closure before freezing.
sys.path.insert(0, str(project_dir / "tools"))
from prepare_tesseract_windows import validate_runtime

if sys.platform != "win32":
    raise SystemExit("This spec builds a real Windows EXE only on Windows x64 / Python 3.11.")
validate_runtime(engine_dir, run_engine=True)

datas = [(str(engine_dir), "tesseract")]
binaries = []
hiddenimports = [
    "core", "electrical_symbols", "ocr_runtime", "portable_smoke_test",
    "recognition_v14", "segmentation_v15", "segmentation_v16",
    "worker_v15", "worker_v16", "feeder_geometry_v152", "incoming_v153",
    "compact_v153", "motor_v153", "orientation_v16", "vertical_recognition_v16",
    "surge_recognition_v17", "precise_locator_v161", "tkinter", "tkinter.ttk",
    "tkinter.filedialog", "tkinter.messagebox", "unittest.mock",
    "multiprocessing", "multiprocessing.spawn", "multiprocessing.popen_spawn_win32",
]
# The packages' official hooks also run. Explicit collection makes image
# codecs, OpenCV/NumPy DLLs, MuPDF extensions and Excel XML helpers reviewable.
for package in ("pymupdf", "fitz", "pytesseract", "PIL", "cv2", "numpy", "openpyxl", "et_xmlfile"):
    package_datas, package_binaries, package_imports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_imports

# Preserve original wheel metadata and licenses (including nested licenses/).
for distribution in ("PyMuPDF", "Pillow", "pytesseract", "numpy", "opencv-python-headless", "openpyxl", "et_xmlfile", "packaging"):
    datas += copy_metadata(distribution, recursive=True)

# Preserve CPython's original distribution license too.
python_license = Path(sys.base_prefix) / "LICENSE.txt"
if python_license.is_file():
    datas.append((str(python_license), "third_party_licenses/CPython"))

# Source and build recipe accompany the binaries for review and upstream
# source obligations; no private samples, PDFs, caches, or virtualenvs.
for path in sorted(source_dir.iterdir()):
    if path.is_file() and path.suffix in {".py", ".bat", ".spec", ".txt"} and not path.name.startswith(("test_", "verify_")):
        datas.append((str(path), "source/source"))
for path in sorted((project_dir / "tools").glob("*.py")):
    datas.append((str(path), "source/tools"))
for name in ("requirements-build-windows.txt", "PORTABLE_WINDOWS.md", "README_CN.txt", "RELEASE_NOTES_V1.7.2.txt"):
    datas.append((str(project_dir / name), "source"))
# Locate the portable instructions beside the embedded files too.
datas.append((str(project_dir / "PORTABLE_WINDOWS.md"), "."))

a = Analysis(
    [str(source_dir / "portable_entry.py")],
    pathex=[str(source_dir)],
    binaries=binaries,
    datas=datas,
    hiddenimports=sorted(set(hiddenimports)),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "IPython", "matplotlib", "scipy", "numpy.f2py.tests", "numpy.tests"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ElectricalQuoteV172",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    contents_directory="_internal",
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="ElectricalQuoteV172",
)

# These review documents sit next to the EXE so users can find them directly.
distribution_dir = Path(DISTPATH) / "ElectricalQuoteV172"
shutil.copy2(project_dir / "PORTABLE_WINDOWS.md", distribution_dir / "PORTABLE_WINDOWS.md")
package_inventory = []
for distribution in ("PyMuPDF", "Pillow", "pytesseract", "numpy", "opencv-python-headless", "openpyxl", "et_xmlfile", "packaging"):
    info = metadata.metadata(distribution)
    package_inventory.append({
        "name": info["Name"], "version": metadata.version(distribution),
        "license": info.get("License-Expression") or info.get("License"),
        "license_classifiers": [value for value in info.get_all("Classifier", []) if value.startswith("License ::")],
        "metadata_location": "_internal/" + str(metadata.distribution(distribution)._path.name),
    })
(distribution_dir / "PYTHON-DEPENDENCIES.json").write_text(
    json.dumps({"python": sys.version, "dependencies": package_inventory}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
