# Third-party notices

The source code in this repository is licensed under the MIT License (see `LICENSE`).

The release build (`PhotoCompressor-win.zip`) bundles the following third-party components, each under its own license. Their full license texts ship inside the build, in `runtime\LICENSE.txt` (Python) and in each package's `*.dist-info` folder under `runtime\Lib\site-packages\`.

| Component | Version | License | Source |
|---|---|---|---|
| CPython (python-build-standalone) | 3.12.14 | PSF-2.0 (plus OpenSSL Apache-2.0, SQLite public domain, zlib, libffi MIT, bundled in the runtime) | https://github.com/astral-sh/python-build-standalone |
| Pillow | 12.3.0 | MIT-CMU (bundled libjpeg-turbo, libpng, libwebp, libavif, OpenJPEG, libtiff, FreeType etc. under their own permissive licenses) | https://github.com/python-pillow/Pillow |
| pillow-heif | 1.8.0 | BSD-3-Clause source; the binary wheel is GPLv2 as a whole because it includes x265 | https://github.com/bigcat88/pillow_heif |
| — libheif | 1.23.4 | LGPLv3 | https://github.com/strukturag/libheif |
| — libde265 | 1.1.3 | LGPLv3 | https://github.com/strukturag/libde265 |
| — x265 | 4.2 | GPLv2 | https://bitbucket.org/multicoreware/x265_git |
| — MinGW-w64 runtime | — | GPL-3.0 with GCC Runtime Library Exception; MIT/BSD (libwinpthread) | https://www.mingw-w64.org/ |
| rawpy | 0.27.1 | MIT | https://github.com/letmaik/rawpy |
| — LibRaw | — | LGPL-2.1 or CDDL-1.0 | https://www.libraw.org/ |
| NumPy | 2.5.3 | BSD-3-Clause (bundled OpenBLAS BSD-3-Clause, others per its license file) | https://github.com/numpy/numpy |
| pywebview | 6.2.1 | BSD-3-Clause (includes Microsoft WebView2 SDK binaries, BSD-3-Clause) | https://github.com/r0x0r/pywebview |
| pythonnet | 3.2.0 | MIT | https://github.com/pythonnet/pythonnet |
| clr_loader | 0.3.1 | MIT | https://github.com/pythonnet/clr-loader |
| cffi | 2.1.1 | MIT-0 | https://github.com/python-cffi/cffi |
| pycparser | 3.0 | BSD-3-Clause | https://github.com/eliben/pycparser |
| bottle | 0.13.4 | MIT | https://github.com/bottlepy/bottle |
| proxy_tools | 0.1.0 | BSD | https://pypi.org/project/proxy_tools/ |
| typing_extensions | 4.16.0 | PSF-2.0 | https://github.com/python/typing_extensions |

The Microsoft Edge WebView2 Runtime and .NET Framework used at run time are parts of Windows and are not redistributed here.

None of these components were modified. Source code for each is available at the links above.
