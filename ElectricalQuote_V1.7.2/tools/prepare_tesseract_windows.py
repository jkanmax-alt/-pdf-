#!/usr/bin/env python3
"""Prepare a verified, redistributable Windows x64 OCR runtime without installing it.

7-Zip extracts the NSIS archive; this never runs the installer, modifies PATH,
or downloads optional installer components. All URLs and expected hashes are
pinned. A locally supplied installer/cache is subject to the same checks.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import urllib.request

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENGINE_VERSION = "5.4.0.20240606"
INSTALLER_NAME = f"tesseract-ocr-w64-setup-{ENGINE_VERSION}.exe"
INSTALLER_URL = (
    "https://github.com/UB-Mannheim/tesseract/releases/download/"
    f"v{ENGINE_VERSION}/{INSTALLER_NAME}"
)
INSTALLER_SHA256 = "c885fff6998e0608ba4bb8ab51436e1c6775c2bafc2559a19b423e18678b60c9"
# Expected installer hash independently published by Microsoft's winget-pkgs.
WINGET_REVISION = "c98039ecea945dca5b368233b4011c5de70ee6ed"
WINGET_URL = (
    "https://raw.githubusercontent.com/microsoft/winget-pkgs/"
    f"{WINGET_REVISION}/manifests/u/UB-Mannheim/TesseractOCR/"
    f"{ENGINE_VERSION}/UB-Mannheim.TesseractOCR.installer.yaml"
)
WINGET_SHA256 = "0185f5d066f6fd44f0e61663792eeb04837ac0dfbb0e3814c9ebed7777cae160"
# Immutable commit underlying tessdata_fast's annotated 4.1.0 tag.
TESSDATA_REVISION = "65727574dfcd264acbb0c3e07860e4e9e9b22185"
TESSDATA_BASE = f"https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/{TESSDATA_REVISION}"
LANGUAGES = {
    "eng": "7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2",
    "chi_sim": "a5fcb6f0db1e1d6d8522f39db4e848f05984669172e584e8d76b6b3141e1f730",
    "osd": "9cf5d576fcc47564f11265841e5ca839001e7e6f38ff7f7aacf46d15a96b00ff",
}
TESSDATA_LICENSE_SHA256 = "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30"
# Windows system DLLs imported by this pinned runtime. Everything else must
# exist beside tesseract.exe; installed runtimes or PATH cannot fill gaps.
SYSTEM_DLLS = frozenset({
    "advapi32.dll", "bcrypt.dll", "crypt32.dll", "dnsapi.dll", "dwrite.dll",
    "gdi32.dll", "iphlpapi.dll", "kernel32.dll", "msimg32.dll", "msvcrt.dll",
    "ole32.dll", "rpcrt4.dll", "shell32.dll", "shlwapi.dll", "user32.dll",
    "usp10.dll", "ws2_32.dll",
})


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_hash(path: Path, expected: str) -> None:
    actual = sha256(path)
    if actual.lower() != expected.lower():
        raise ValueError(f"SHA256 mismatch for {path.name}: expected {expected}, got {actual}")


def download(url: str, target: Path, expected: str) -> Path:
    if target.is_file():
        check_hash(target, expected)
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".partial")
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "ElectricalQuote-portable-build/1.7.2"})
        # The default HTTPS context checks certificates; use the environment's
        # configured proxy and trust store. Do not add an insecure fallback.
        with urllib.request.urlopen(request, timeout=120) as response, temporary.open("wb") as output:
            shutil.copyfileobj(response, output)
        check_hash(temporary, expected)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def sevenzip_path(requested: str | None) -> str:
    candidates = [requested] if requested else []
    candidates.extend([shutil.which("7z"), shutil.which("7zz"), shutil.which("7za")])
    if os.name == "nt":
        candidates.extend([
            str(Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "7-Zip/7z.exe"),
            "C:/Program Files/7-Zip/7z.exe",
        ])
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate).resolve())
    raise RuntimeError("7-Zip is required on the build machine only. Pass --sevenzip PATH or install 7-Zip.")


def pe_dependencies(path: Path) -> list[str]:
    """Check x64 PE architecture and return imported DLLs (including delay imports)."""
    try:
        import pefile
    except ImportError as error:
        raise RuntimeError("Install requirements-build-windows.txt first (pefile is needed for DLL auditing).") from error
    pe = pefile.PE(str(path), fast_load=True)
    try:
        if pe.FILE_HEADER.Machine != 0x8664:
            raise ValueError(f"Expected Windows x64 PE image: {path.name}")
        pe.parse_data_directories(directories=[
            pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"],
            pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT"],
        ])
        entries = list(getattr(pe, "DIRECTORY_ENTRY_IMPORT", []))
        entries += list(getattr(pe, "DIRECTORY_ENTRY_DELAY_IMPORT", []))
        return sorted({entry.dll.decode("ascii").lower() for entry in entries})
    finally:
        pe.close()


def validate_runtime(root: Path, run_engine: bool = False) -> dict:
    exe = root / "tesseract.exe"
    if not exe.is_file():
        raise ValueError(f"Missing {exe}")
    dlls = sorted(root.glob("*.dll"))
    if not dlls:
        raise ValueError("Tesseract DLL payload is missing")
    names = {item.name.lower() for item in dlls}
    imports = {}
    for binary in [exe, *dlls]:
        dependencies = pe_dependencies(binary)
        missing = set(dependencies) - names - SYSTEM_DLLS
        if missing:
            raise ValueError(f"Unbundled non-system DLL imports in {binary.name}: {sorted(missing)}")
        imports[binary.name] = dependencies
    for language, expected in LANGUAGES.items():
        check_hash(root / "tessdata" / f"{language}.traineddata", expected)
    for required in ["doc/LICENSE", "doc/AUTHORS", "third_party_licenses/tessdata_fast-LICENSE"]:
        if not (root / required).is_file():
            raise ValueError(f"Missing upstream license/notice: {required}")
    if run_engine:
        if os.name != "nt":
            raise RuntimeError("Executing the Windows engine requires Windows; Linux checks are static only.")
        environment = os.environ.copy()
        environment["PATH"] = str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32")
        environment["TESSDATA_PREFIX"] = str((root / "tessdata").resolve())
        version = subprocess.run([str(exe.resolve()), "--version"], env=environment, cwd=root,
                                 capture_output=True, text=True, check=True, timeout=30)
        languages = subprocess.run([str(exe.resolve()), "--tessdata-dir", str((root / "tessdata").resolve()), "--list-langs"],
                                   env=environment, cwd=root, capture_output=True, text=True, check=True, timeout=30)
        found = set(languages.stdout.splitlines())
        if not set(LANGUAGES).issubset(found):
            raise ValueError(f"Tesseract did not load required languages: {languages.stdout} {languages.stderr}")
        print(version.stdout.splitlines()[0])
    return {"architecture": "x64", "dll_count": len(dlls), "imports": imports, "languages": sorted(LANGUAGES)}


def write_inventory(root: Path, audit: dict) -> None:
    files = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != "BUNDLE-MANIFEST.json":
            files[path.relative_to(root).as_posix()] = {"bytes": path.stat().st_size, "sha256": sha256(path)}
    manifest = {
        "engine_version": ENGINE_VERSION,
        "installer": {"url": INSTALLER_URL, "sha256": INSTALLER_SHA256,
                      "checksum_source": WINGET_URL, "checksum_source_sha256": WINGET_SHA256},
        "language_data": {"repository": "https://github.com/tesseract-ocr/tessdata_fast",
                          "revision": TESSDATA_REVISION, "sha256": LANGUAGES},
        "audit": audit, "files": files,
    }
    (root / "BUNDLE-MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def prepare(args: argparse.Namespace) -> None:
    output = args.output.resolve()
    cache = args.download_cache.resolve()
    if args.verify_only:
        audit = validate_runtime(output, run_engine=(os.name == "nt"))
        manifest = json.loads((output / "BUNDLE-MANIFEST.json").read_text(encoding="utf-8"))
        for name, info in manifest["files"].items():
            check_hash(output / name, info["sha256"])
        print(f"Verified: {output} ({audit['dll_count']} DLLs; {', '.join(audit['languages'])})")
        return
    if output.exists():
        raise ValueError(f"Output already exists: {output}. Use --verify-only, or remove this generated directory before rebuilding.")
    if args.installer:
        installer = args.installer.resolve()
        check_hash(installer, INSTALLER_SHA256)
    else:
        installer = download(INSTALLER_URL, cache / INSTALLER_NAME, INSTALLER_SHA256)
    metadata = download(WINGET_URL, cache / "UB-Mannheim.TesseractOCR.installer.yaml", WINGET_SHA256)
    if INSTALLER_SHA256.upper() not in metadata.read_text(encoding="utf-8-sig"):
        raise ValueError("Pinned winget metadata does not contain the expected installer checksum")
    sevenzip = sevenzip_path(args.sevenzip)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Stage beside the final directory so the last rename is atomic.
    with tempfile.TemporaryDirectory(prefix="electricalquote-ocr-", dir=output.parent) as work:
        work = Path(work)
        extracted = work / "extracted"
        extracted.mkdir()
        extraction = subprocess.run([sevenzip, "x", "-y", f"-o{extracted}", str(installer)],
                                    capture_output=True, text=True, timeout=180)
        if extraction.returncode != 0:
            raise RuntimeError(f"7-Zip extraction failed ({extraction.returncode}):\n{extraction.stdout}\n{extraction.stderr}")
        roots = [p.parent for p in extracted.rglob("tesseract.exe") if "$PLUGINSDIR" not in p.parts]
        if len(roots) != 1:
            raise ValueError(f"Expected one tesseract.exe in the pinned installer, found {len(roots)}")
        source = roots[0]
        staged = work / "runtime"
        # Preserve every original runtime DLL and documentation/configuration.
        # Installer plugins, uninstaller and unrelated training tools are not used.
        shutil.copytree(source, staged, ignore=shutil.ignore_patterns("$PLUGINSDIR", "*.exe"))
        shutil.copy2(source / "tesseract.exe", staged / "tesseract.exe")
        for language, expected in LANGUAGES.items():
            data = download(f"{TESSDATA_BASE}/{language}.traineddata", cache / f"{language}.traineddata", expected)
            (staged / "tessdata").mkdir(exist_ok=True)
            shutil.copy2(data, staged / "tessdata" / data.name)
        notices = staged / "third_party_licenses"
        notices.mkdir(exist_ok=True)
        license_file = download(f"{TESSDATA_BASE}/LICENSE", cache / "tessdata_fast-LICENSE", TESSDATA_LICENSE_SHA256)
        shutil.copy2(license_file, notices / "tessdata_fast-LICENSE")
        shutil.copy2(metadata, notices / metadata.name)
        (notices / "SOURCES.txt").write_text(
            "Original Tesseract notices are preserved in ../doc/.\n"
            "Tesseract and its DLLs: " + INSTALLER_URL + "\n"
            "Tesseract upstream source/build scripts: https://github.com/UB-Mannheim/tesseract/tree/v5.4.0.20240606\n"
            "Language data/license: " + TESSDATA_BASE + "\n"
            "The included DLLs have their respective upstream licenses; Tesseract's Apache license does not relicense them.\n"
            "Python dependency license metadata is separately included by PyInstaller.\n",
            encoding="utf-8")
        audit = validate_runtime(staged, run_engine=(os.name == "nt"))
        write_inventory(staged, audit)
        staged.replace(output)
    print(f"Prepared: {output} ({audit['dll_count']} x64 DLLs; {', '.join(audit['languages'])})")
    if os.name != "nt":
        print("Static extraction/hash/PE checks only; the Windows engine was not executed on this host.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "vendor/tesseract")
    parser.add_argument("--download-cache", type=Path, default=PROJECT_ROOT / "vendor/downloads")
    parser.add_argument("--installer", type=Path, help="Optional local installer; its pinned SHA256 is still required")
    parser.add_argument("--sevenzip", help="Path to 7z/7zz (the Windows runner includes 7-Zip)")
    parser.add_argument("--verify-only", action="store_true", help="Audit an existing generated runtime and its manifest")
    args = parser.parse_args()
    try:
        prepare(args)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"Tesseract preparation failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
