#!/usr/bin/env python3
"""Build the self-contained Windows version of Photo Compressor.

Downloads a portable CPython for Windows x64 (python-build-standalone), the pinned
win_amd64 wheels of every dependency, compiles "Photo Compressor.exe" from launcher/
with Zig (installed from PyPI, so no Visual Studio is needed) and assembles:

    dist/Photo Compressor/          the app folder (exe + runtime\\)
    dist/PhotoCompressor-win.zip    the same folder, zipped for Releases

Runs on Windows, Linux or macOS with Python 3.9+ and internet access:

    python build_win.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

APP_NAME = "Photo Compressor"
ZIP_NAME = "PhotoCompressor-win.zip"
VERSION = "1.0.0"

PY_VERSION = "3.12.14"
PBS_TAG = "20260924"  # https://github.com/astral-sh/python-build-standalone/releases
PBS_URL = (f"https://github.com/astral-sh/python-build-standalone/releases/download/{PBS_TAG}/"
           f"cpython-{PY_VERSION}%2B{PBS_TAG}-x86_64-pc-windows-msvc-install_only_stripped.tar.gz")

PACKAGES = [  # all pinned; installed without dependency resolution, so this list is complete
    "pillow==12.3.0", "pillow-heif==1.8.0",               # imaging, HEIC/HEIF
    "rawpy==0.27.1", "numpy==2.5.3",                       # camera RAW (LibRaw)
    "pywebview==6.2.1", "bottle==0.13.4", "typing_extensions==4.16.0",
    "pythonnet==3.2.0", "clr_loader==0.3.1", "cffi==2.1.1", "pycparser==3.0",  # WinForms + WebView2
]
SDIST_PACKAGES = ["proxy_tools==0.1.0"]  # only published as a source archive (pure Python)
ZIG = "ziglang==0.17.0"

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build"
DIST = ROOT / "dist"
APP = DIST / APP_NAME
RT = APP / "runtime"
SITE = RT / "Lib" / "site-packages"


def log(msg: str):
    print(f"\n==> {msg}", flush=True)


def run(*cmd, **kw):
    subprocess.run([str(c) for c in cmd], check=True, **kw)


def download(url: str, dest: Path):
    if dest.exists():
        return
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f)
    tmp.rename(dest)


def pip(*args):
    run(sys.executable, "-m", "pip", "--disable-pip-version-check", "--quiet", *args)


def rm(*paths: Path):
    for p in paths:
        if p.is_dir() and not p.is_symlink():
            shutil.rmtree(p)
        elif p.exists() or p.is_symlink():
            p.unlink()


def safe_extract(tf: tarfile.TarFile, member: tarfile.TarInfo, dest: Path):
    if hasattr(tarfile, "data_filter"):
        tf.extract(member, dest, filter="data")
    else:
        tf.extract(member, dest)


def install_wheel(wheel: Path, site: Path):
    """Unpack a wheel like pip would: <name>.data/{purelib,platlib} go into site-packages,
    scripts/headers/data are not needed by the app."""
    with zipfile.ZipFile(wheel) as z:
        for info in z.infolist():
            name = info.filename
            if info.is_dir() or name.startswith(("/", "..")) or "/../" in name:
                continue
            parts = name.split("/")
            if parts[0].endswith(".data"):
                if len(parts) < 3 or parts[1] not in ("purelib", "platlib"):
                    continue
                parts = parts[2:]
            target = site.joinpath(*parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)


def main():
    rm(APP, DIST / ZIP_NAME)
    BUILD.mkdir(parents=True, exist_ok=True)
    RT.mkdir(parents=True)

    # ------------------------------------------------------------ Python runtime
    log(f"Downloading Python {PY_VERSION} for Windows x64")
    tgz = BUILD / f"cpython-{PY_VERSION}-{PBS_TAG}-win64.tar.gz"
    download(PBS_URL, tgz)
    with tarfile.open(tgz) as tf:
        for m in tf.getmembers():
            if not m.name.startswith("python/") or m.issym() or m.islnk():
                continue
            m.name = m.name[len("python/"):]
            if m.name:
                safe_extract(tf, m, RT)

    # ------------------------------------------------------------ dependencies
    log("Downloading win_amd64 wheels")
    whl = BUILD / "wheels"
    pip("download", "--no-deps", "--only-binary=:all:", "--platform", "win_amd64",
        "--python-version", "3.12", "--implementation", "cp", "--abi", "cp312", "--abi", "none",
        "-d", whl, *PACKAGES)
    sdist = BUILD / "sdist"
    pip("download", "--no-deps", "--no-binary=:all:", "-d", sdist, *SDIST_PACKAGES)

    wanted = {p.split("==")[0].replace("-", "_").lower() for p in PACKAGES}
    for w in sorted(whl.glob("*.whl")):
        if w.name.split("-")[0].lower() in wanted:
            install_wheel(w, SITE)
    for a in sdist.glob("*.tar.gz"):
        with tarfile.open(a) as tf:
            for m in tf.getmembers():
                parts = m.name.split("/")
                if len(parts) > 2 and parts[1] == "proxy_tools" and m.isfile():
                    m.name = "/".join(parts[1:])
                    safe_extract(tf, m, SITE)

    # ------------------------------------------------------------ trim
    log("Trimming unused files")
    lib = RT / "Lib"
    rm(RT / "include", RT / "libs", RT / "tcl", RT / "Scripts", RT / "python.exe", RT / "pythonw.exe")
    for name in ("test", "idlelib", "tkinter", "turtledemo", "ensurepip", "lib2to3", "pydoc_data",
                 "unittest/test", "site-packages/pip"):
        rm(lib / name)
    for p in SITE.glob("pip-*.dist-info"):
        rm(p)
    for p in list((RT / "DLLs").glob("_test*")) + [RT / "DLLs" / n for n in
                                                    ("_tkinter.pyd", "tcl86t.dll", "tk86t.dll", "_msi.pyd")]:
        rm(p)
    wl = SITE / "webview" / "lib"
    rm(wl / "pywebview-android.jar")  # pywebview requires every runtimes\win-* folder to exist, so keep those
    rm(SITE / "numpy" / "_core" / "tests", SITE / "numpy" / "tests", SITE / "numpy" / "f2py")
    for p in list(SITE.rglob("tests")):
        if p.is_dir() and p.parent.name in ("numpy", "linalg", "fft", "random", "ma", "lib", "polynomial",
                                            "testing", "typing", "_core", "matrixlib", "char", "rec",
                                            "strings", "_pyinstaller"):
            rm(p)
    for p in list(RT.rglob("__pycache__")):
        rm(p)
    for p in list(SITE.rglob("*.pyi")) + list(SITE.rglob("*.lib")):
        rm(p)

    # ------------------------------------------------------------ app files
    log("Adding app files")
    shutil.copy2(ROOT / "photo_compress.py", RT / "photo_compress.py")
    shutil.copy2(ROOT / "launcher" / "AppIcon.ico", RT / "AppIcon.ico")
    shutil.copy2(ROOT / "LICENSE", APP / "LICENSE.txt")
    if (ROOT / "THIRD_PARTY_NOTICES.md").exists():
        shutil.copy2(ROOT / "THIRD_PARTY_NOTICES.md", APP / "THIRD_PARTY_NOTICES.md")

    # ------------------------------------------------------------ launcher exe
    log("Compiling Photo Compressor.exe")
    tools = BUILD / "tools"
    if not (tools / "ziglang").exists():
        pip("install", "--target", tools, ZIG)
    src = BUILD / "launcher"
    rm(src)
    shutil.copytree(ROOT / "launcher", src)
    ver4 = ",".join((VERSION.split(".") + ["0"] * 4)[:4])
    rc = (src / "launcher.rc").read_text(encoding="utf-8")
    (src / "launcher.rc").write_text(rc.replace("@VER_COMMA@", ver4).replace("@VER@", VERSION), encoding="utf-8")
    env = dict(os.environ, PYTHONPATH=str(tools))
    run(sys.executable, "-m", "ziglang", "cc", "-target", "x86_64-windows-gnu", "-O2", "-s", "-municode",
        "-Wl,--subsystem,windows", "launcher.c", "launcher.rc", "-o", APP / f"{APP_NAME}.exe",
        cwd=src, env=env)

    # ------------------------------------------------------------ zip
    log("Creating zip")
    with zipfile.ZipFile(DIST / ZIP_NAME, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in sorted(APP.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(DIST))

    size = sum(p.stat().st_size for p in APP.rglob("*") if p.is_file())
    log(f"Done: {APP} ({size / 1048576:.0f} MB), {DIST / ZIP_NAME} "
        f"({(DIST / ZIP_NAME).stat().st_size / 1048576:.0f} MB)")


if __name__ == "__main__":
    main()
