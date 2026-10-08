# Photo Compressor for Windows

A small, self-contained Windows app for batch-compressing photos. Drop in photos or whole folders, choose a quality or a target file size, and get compressed copies. Your originals are never modified.

Everything runs locally on your PC. No photos are uploaded anywhere.

This is the Windows edition of [Photo Compressor for macOS](https://github.com/PeterChang02/Photo_Compressor_mac). Both use the same compression engine and interface.

## Features

- **Two compression modes**
  - **Quality**: a fixed quality level from 10 to 95.
  - **Target size**: every photo is kept at or under a size you choose (B / KB / MB / GB / TB). The app finds the highest quality that fits and only shrinks the image dimensions if it has to. Units convert automatically, so 1024 KB becomes 1 MB.
- **Output formats**: keep the original format, or convert to JPEG, PNG, WebP, AVIF, HEIC, TIFF, GIF, JPEG 2000 or BMP.
- **Input formats**: JPEG, PNG, WebP, AVIF, HEIC/HEIF, TIFF, GIF, JPEG 2000, BMP, and camera RAW (CR2, CR3, NEF, ARW, DNG, RAF, ORF, RW2 and more, decoded with LibRaw).
- **Longest side**: optionally resize so the longer edge is at most N pixels. The aspect ratio is kept.
- **EXIF**: stripped by default for privacy and smaller files, or kept on request. Photos are always rotated upright according to their orientation tag.
- **Batch processing**: drag and drop photos or folders from File Explorer (subfolder structure is preserved), with parallel processing.
- **English / Chinese interface**: switch with the `中 / ENG` toggle. Your choice is remembered.
- **Self-contained**: bundles its own Python runtime, so nothing needs to be installed. No installer, no admin rights.

## Download

Download `PhotoCompressor-win.zip` from the [Releases](https://github.com/PeterChang02/Photo_Compressor_windows/releases) page, unzip it anywhere (for example `C:\Program Files` or your Desktop), and run `Photo Compressor.exe` inside the `Photo Compressor` folder. Keep the `runtime` folder next to the exe.

The app is not code-signed, so the first time you open it Windows SmartScreen may show "Windows protected your PC". Click **More info**, then **Run anyway**. You only need to do this once.

**Requirements:** Windows 10 or 11, 64-bit, with the Microsoft Edge WebView2 Runtime. WebView2 is built into Windows 11 and installed on almost every Windows 10 PC through Edge updates. If the app reports that it is missing, install it from [Microsoft](https://developer.microsoft.com/microsoft-edge/webview2/).

## Usage

1. Drop photos or folders into the window, or click **Choose Folder…**.
2. Pick a mode: **Quality**, or **Target Size** with a unit.
3. Optionally choose an output format, a longest side, and whether to keep EXIF.
4. Check the **Save To** folder, then click **Compress**.

Default output locations:

- Dropped photos: `Downloads\Compressed_<date-time>`
- A chosen folder: a sibling folder named `<folder>_compressed`

If a compressed file would come out larger than the original (same format, no resizing), the original is copied instead.

Settings are stored in `%APPDATA%\PhotoCompress`. If the app fails to start, the error is written to `%APPDATA%\PhotoCompress\error.log`.

## Build from source

Requirements: Python 3.9 or later and an internet connection. The build works on Windows, Linux or macOS. Visual Studio is not needed: the launcher is compiled with [Zig](https://ziglang.org/), which the script installs from PyPI.

```bash
git clone https://github.com/PeterChang02/Photo_Compressor_windows.git
cd Photo_Compressor_windows
python build_win.py
```

The script:

1. Downloads a portable CPython 3.12 for Windows x64 from [python-build-standalone](https://github.com/astral-sh/python-build-standalone).
2. Downloads pinned `win_amd64` wheels for Pillow, pillow-heif, rawpy, NumPy, pywebview and pythonnet.
3. Trims unused parts of the runtime (tests, Tk, pip, headers).
4. Compiles `Photo Compressor.exe` from `launcher/`.
5. Assembles `dist\Photo Compressor\` and `dist\PhotoCompressor-win.zip`.

The finished folder is about 110 MB, and the zip is about 35 MB.

To try the app without building it, install the dependencies into any 64-bit Python 3.9+ on Windows and run the script directly:

```bash
pip install pillow pillow-heif rawpy pywebview
python photo_compress.py
```

## Project structure

```
photo_compress.py       The whole app: compression engine, UI (HTML/JS) and local server
launcher/launcher.c     Photo Compressor.exe: loads the bundled python312.dll and runs the app
launcher/launcher.rc    Exe resources: icon, version info, manifest
launcher/app.manifest   Windows application manifest
launcher/AppIcon.ico    App icon
build_win.py            Builds the app folder and the zip
```

## How it works

`Photo Compressor.exe` is a small native launcher. It loads the bundled Python from `runtime\` in-process, so the window and taskbar button belong to the app and carry its icon, and no console window appears. The app starts a local web server bound to `127.0.0.1` on a random port, protected by a random per-launch token, and shows the interface in a native window using Microsoft Edge WebView2 through [pywebview](https://pywebview.flowrl.com/). Photos are processed with [Pillow](https://python-pillow.org/), [pillow-heif](https://github.com/bigcat88/pillow_heif) and [rawpy](https://github.com/letmaik/rawpy).

## License

[MIT](LICENSE). The release build bundles third-party components under their own licenses; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
