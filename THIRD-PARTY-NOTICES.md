# Third-party notices for DSI Redline

DSI Redline is distributed as a Windows installer and a portable zip, and both
bundle every runtime dependency. Those dependencies keep their own license
terms, and several of them require their notice to travel **with the
distributed form**. A file in the repository satisfies nothing for somebody who
downloads the `.exe`, so this file and the `licenses/` directory beside it are
installed with the app.

> **How this was produced.** Measured on **2026-10-31**, for v1.8.1. Every
> copyright line below is copied **verbatim** from that package's own license
> file in its Windows wheel, at the version the release build installs. Nothing
> is transcribed from memory and no year is inferred. Where a package ships no
> copyright line, that is recorded as an absence rather than filled in.
>
> 1. `packaging/DSI_Redline.spec` at `bf7d482`, which leaves out
>    `pymupdf.layout` and `pymupdf4llm`, was built with PyInstaller 6.22.3 and
>    Python 3.11 on Linux. The build installed `requirements.txt` fresh,
>    `requirements-drc.txt` at PyDRC `v0.23.1` (`636056399f36`), and setuptools
>    65.5.0, the version the Windows runner's Python carries.
> 2. Every module and file in the bundle was traced to the installed
>    distribution whose `RECORD` lists it. 40 distributions reach the bundle.
>    One is PyDRC, which is DSI's own, so 39 are listed here. onnxruntime is not
>    among them. The v1.8.0 spec, built the same way, bundles it.
> 3. The Windows tag build of v1.8.0 (Build Windows run 41248171957) installed
>    the same distributions at the same versions. The Linux build of the v1.8.0
>    spec ran the same PyInstaller hooks as that Windows run, apart from
>    `hook-PySide6.QtDBus`, which exists only on Linux.
> 4. Each license file was read from that distribution's Windows or
>    pure-Python wheel and copied byte for byte into
>    `licenses/<distribution>/`, under the path the wheel gives it.
>
> What the audit did not reach is listed under "Not covered here".

> **Versions are as resolved, not pinned.** `requirements.txt` uses `>=`
> constraints, so the versions here are what a fresh resolve produced on the
> date above. A build from a different date may bundle different versions, and
> a new version can bring a new dependency with it. Re-run the audit when
> cutting a release, by the steps under "How to re-run the audit", rather than
> trusting this list to be current.

---

## PyMuPDF is AGPL-or-commercial, and that is unresolved

`pymupdf` declares **`Dual Licensed - GNU AFFERO GPL 3.0 or Artifex Commercial
License`**. That is measured, not assumed: the string is the entire contents of
the package's own `COPYING`, unchanged in 2.0. It is bundled inside the shipped
installer.

Only one of the two arms can apply, and **which one has not been established**.

- If a **commercial Artifex license is held**, that arm governs and nothing
  further is required here.
- If not, the **AGPL-3.0 arm** governs the distributed binary, and its
  obligations attach to it.

This repository is **public** and its workflow publishes the installer, so this
is not theoretical. **The question is recorded as a Phase 6 ask to whoever
handles legal** (Pathforward `data/decisions.json`, D57). It is deliberately not
answered here, because it is not an engineering decision. Until it is answered,
treat external distribution as unresolved rather than permitted.

## PySide6 and shiboken6 ship no LGPL text

Measured on the 6.11.3 wheels of `PySide6`, `PySide6_Addons`,
`PySide6_Essentials` and `shiboken6`: each ships one license file,
`LicenseRef-Qt-Commercial.txt`, eight lines addressed to holders of a commercial
Qt license. **None of them ships an LGPL or GPL text or a copyright line.** They
declare `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only`, and this project
**elects `LGPL-3.0-only`**.

The LGPL requires the license to accompany the distribution, so **this project
supplies the text itself**: `licenses/LGPL-3.0.txt`, verbatim FSF text, Version
3 of 29 June 2007.

LGPL-3.0 incorporates the GNU General Public License version 3 by reference, so
`licenses/GPL-3.0.txt` is supplied beside it. It is verbatim FSF text, Version 3
of 29 June 2007, 674 lines, sha256
`3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986`.

**Where it came from, because a license text is the one file that must not be
transcribed.** `https://www.gnu.org/licenses/gpl-3.0.txt` is unreachable from
the environment this audit runs in. What was used instead is two *independent*
packagings of the FSF's own file, Debian's `/usr/share/common-licenses/GPL-3`
and GNU automake's own `COPYING`. They are **byte-identical**, and one of them
ships inside a GNU project. Two sources agreeing is a cross-check. One source is
a copy.

**A reflowed copy was found first and rejected.** The Rust toolchain ships a
`GPL-3.0-or-later.txt` that is the same license with its paragraphs unwrapped
onto single lines, `©` for `(C)`, and a broken `<https: //www.gnu.org/…>` in the
final paragraph. It is legible and it is not the document the FSF publishes,
which is the only thing "verbatim" can mean here.

## lxml bundles iconv, and its LGPL 2.1 text is supplied here

lxml's own `LICENSES.txt` says its binary wheels bundle zlib, iconv, libxml2,
libxslt and libexslt. It gives iconv's license as `LGPL 2.1` by URL and ships
no copy of the text. So this project supplies `licenses/LGPL-2.1.txt`, the FSF
text, Version 2.1 of February 1999, 502 lines, sha256
`dc626520dcd53a22f727af3ee42c770e56c97a64fe3adb063799d8ab032fe551`. It is
byte-identical in two independent packagings: Debian's
`/usr/share/common-licenses/LGPL-2.1` and the `LICENSE` in the chardet 5.2.0
wheel.

---

## The bundled packages

Each entry gives the license string the distribution's `METADATA` declares,
copied as written. That is its `License-Expression` where it has one, else its
`License` field, else its license classifier. Each entry's files ship in
`licenses/<distribution>/`, under the names its wheel gives them.

### Named in `requirements.txt`

#### anthropic 2.3.0

- **License**: `Apache-2.0`
- **Copyright**, verbatim from `LICENSE`:
  > Copyright 2023 Anthropic, PBC.
- `LICENSE-MIT` says the project moved from the MIT License to Apache-2.0 in
  version 2.0.0, and that the MIT License still applies to every version
  published under it and to contributions merged before the change. It carries
  the same copyright line.
- **Vendored inside this package**: `httpx_aiohttp` 0.2.0, `BSD-3-Clause` per
  its own `NOTICE.md`, which the package's top-level license does not cover:
  > Copyright © 2025, Karen Petrosyan.

#### openpyxl 3.1.5

- **License**: `MIT`
- **Copyright**, verbatim from `LICENCE.rst`:
  > Copyright (c) 2010 openpyxl

#### pdf2docx 0.5.13

- **License**: `MIT`
- **Copyright**, verbatim from `LICENSE`:
  > Copyright (c) 2026 Artifex Software, Inc.

#### pillow 13.0.0

- **License**: `MIT-CMU`
- **Copyright**, verbatim from `LICENSE`:
  > Copyright © 1997-2011 by Secret Labs AB
  > Copyright © 1995-2011 by Fredrik Lundh and contributors
  > Copyright © 2010 by Jeffrey 'Alex' Clark and contributors
- The same `LICENSE` carries the license and copyright lines of the 12
  libraries this Windows wheel bundles: brotli 1.2.0, freetype 2.14.3, harfbuzz
  14.5.0, lcms2 2.19.1, libavif 1.4.2, libjpeg-turbo 3.2.0, libpng 1.6.58,
  libwebp 1.6.0, openjpeg 2.5.4, tiff 4.7.2, xz 5.8.4 and zlib-ng 2.3.3.

#### pymupdf 2.0

- **License**: `Dual Licensed - GNU AFFERO GPL 3.0 or Artifex Commercial License`
  · **NOT elected, see the warning above**
- **Copyright**: *the wheel ships no copyright line.* Its one license file is
  `COPYING`, the single line above. Recorded as absent rather than invented.
- The wheel ships no notice for the libraries MuPDF compiles in.

#### PySide6 6.11.3

- **License**: `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only` · elected
  `LGPL-3.0-only`
- **Copyright**: *the wheel ships no copyright line.* Its one license file is
  `LicenseRef-Qt-Commercial.txt`, described above. Recorded as absent rather
  than invented.

#### pytesseract 0.3.13

- **License**: `Apache License 2.0`
- **Copyright**: *the wheel ships no copyright line.* Its `LICENSE` is the
  Apache License 2.0 with the appendix template
  `Copyright [yyyy] [name of copyright owner]` unfilled. Recorded as absent
  rather than invented.

#### python-docx 1.2.0

- **License**: `MIT`
- **Copyright**, verbatim from `LICENSE`:
  > Copyright (c) 2013 Steve Canny, https://github.com/scanny

#### PyYAML 6.0.3

- **License**: `MIT`
- **Copyright**, verbatim from `LICENSE`:
  > Copyright (c) 2017-2021 Ingy döt Net
  > Copyright (c) 2006-2016 Kirill Simonov

### Installed as requirements of those

#### annotated-types 0.8.0

- **License**: `MIT` · a requirement of pydantic
- **Copyright**, verbatim from `LICENSE`:
  > Copyright (c) 2022 the contributors

#### anyio 4.15.1

- **License**: `MIT` · a requirement of anthropic and httpx2
- **Copyright**, verbatim from `LICENSE`:
  > Copyright (c) 2018 Alex Grönholm

#### docstring_parser 0.18.0

- **License**: `MIT` · a requirement of anthropic
- **Copyright**, verbatim from `LICENSE.md`:
  > Copyright (c) 2018 Marcin Kurczewski

#### et_xmlfile 2.0.0

- **License**: `MIT` · a requirement of openpyxl
- **Copyright**, verbatim from `LICENCE.rst`:
  > Copyright (c) 2010 openpyxl
- `LICENCE.python` says et_xml includes code from the Python standard library,
  under the Python license, and carries that license with its notice:
  > Copyright (c) 2001-present Python Software Foundation; All Rights Reserved

#### fire 0.7.1

- **License**: `Apache-2.0` · a requirement of pdf2docx
- **Copyright**, verbatim from `LICENSE`:
  > Copyright 2017 Google Inc. All rights reserved.
- That `LICENSE` is the short Apache notice. The full text it points to is
  `licenses/Apache-2.0.txt`.

#### fonttools 4.68.0

- **License**: `MIT` · a requirement of pdf2docx, and of ezdxf when PyDRC is
  installed
- **Copyright**, verbatim from `LICENSE`:
  > Copyright (c) 2017 Just van Rossum
- `LICENSE.external` covers the font projects fontTools includes for testing,
  under the SIL Open Font License 1.1, with their own copyright lines.

#### h11 0.16.0

- **License**: `MIT` · a requirement of httpcore2
- **Copyright**, verbatim from `LICENSE.txt`:
  > Copyright (c) 2016 Nathaniel J. Smith <njs@pobox.com> and other contributors

#### httpcore2 2.16.0

- **License**: `BSD-3-Clause` · a requirement of httpx2
- **Copyright**, verbatim from `LICENSE.md`:
  > Copyright © 2026 to present Pydantic Services Inc. and individual contributors.
  > Copyright © 2020, [Encode OSS Ltd](https://www.encode.io/).

#### httpx2 2.16.0

- **License**: `BSD-3-Clause` · a requirement of anthropic
- **Copyright**, verbatim from `LICENSE.md`:
  > Copyright © 2026 to present Pydantic Services Inc. and individual contributors.
  > Copyright © 2019, [Encode OSS Ltd](https://www.encode.io/).

#### idna 3.20

- **License**: `BSD-3-Clause` · a requirement of anyio and httpx2
- **Copyright**, verbatim from `LICENSE.md`:
  > Copyright (c) 2013-2026, Kim Davies and contributors.

#### jiter 0.18.0

- **License**: `MIT` · a requirement of anthropic
- **Copyright**, verbatim from `LICENSE`:
  > Copyright (c) 2022 to present Samuel Colvin

#### lxml 6.1.3

- **License**: `BSD-3-Clause` · a requirement of python-docx
- **Copyright**, verbatim from `LICENSE.txt`:
  > Copyright (c) 2004 Infrae. All rights reserved.
- `LICENSES.txt` says the binary wheels bundle zlib, iconv, libxml2, libxslt and
  libexslt. Its copyright lines for libxml2, libxslt and libexslt, verbatim:
  > Copyright (C) 1998-2012 Daniel Veillard.  All Rights Reserved.
  > Copyright (C) The Libxml2 Contributors.
  > Copyright (C) 2001-2002 Daniel Veillard.  All Rights Reserved.
  > Copyright (C) 2001-2002 Thomas Broyer, Charlie Bozeman and Daniel Veillard.
- It names iconv's license as `LGPL 2.1` and zlib's as `zlib-license`, each by
  URL, with no copyright line for either. The LGPL 2.1 text is supplied, as
  described above.

#### numpy 2.4.6

- **License**: `BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0` · a
  requirement of opencv-python-headless, pdf2docx and pymupdf, and of ezdxf
  when PyDRC is installed
- **Copyright**, verbatim from `LICENSE.txt`:
  > Copyright (c) 2005-2025, NumPy Developers.
- The same `LICENSE.txt` covers what this Windows wheel bundles in
  `numpy.libs\libscipy_openblas*.dll`, each with its own copyright lines:
  OpenBLAS (`BSD-3-Clause`), LAPACK (`BSD-3-Clause-Open-MPI`) and the GCC
  runtime library (`GPL-3.0-or-later WITH GCC-exception-3.1`). Sixteen more
  license files cover code compiled into numpy itself.

#### opencv-python-headless 5.0.0.93

- **License**: `Apache 2.0` · a requirement of pdf2docx
- **Copyright**, verbatim from `LICENSE.txt`, an MIT license:
  > Copyright (c) Olli-Pekka Heinisuo
- `LICENSE-3RD-PARTY.txt` applies the Apache License 2.0 to the OpenCV binary
  in `cv2/`, with the appendix template unfilled and no copyright line. It also
  covers the libraries the wheel redistributes, each under its own license. For
  this Windows wheel that includes FFmpeg, as
  `cv2/opencv_videoio_ffmpeg500_64.dll`, under the GNU LGPL 2.1, whose full
  text is in that file.

#### opentelemetry-api 1.45.2

- **License**: `Apache-2.0` · a requirement of anthropic
- **Copyright**: *the wheel ships no copyright line.* Its `LICENSE` is the
  Apache License 2.0 with the appendix template unfilled. Recorded as absent
  rather than invented.

#### packaging 26.3

- **License**: `Apache-2.0 OR BSD-2-Clause` · a requirement of pytesseract
- **Copyright**, verbatim from `LICENSE.BSD`:
  > Copyright (c) Donald Stufft and individual contributors.
- `LICENSE.APACHE` carries no copyright line.

#### psutil 7.2.2

- **License**: `BSD-3-Clause` · a requirement of pymupdf
- **Copyright**, verbatim from `LICENSE`:
  > Copyright (c) 2009, Jay Loden, Dave Daeschler, Giampaolo Rodola

#### pydantic 2.14.2

- **License**: `MIT` · a requirement of anthropic
- **Copyright**, verbatim from `LICENSE`:
  > Copyright (c) 2017 to present Pydantic Services Inc. and individual contributors.

#### pydantic_core 2.50.2

- **License**: `MIT` · a requirement of pydantic
- **Copyright**, verbatim from `LICENSE`:
  > Copyright (c) 2022 Samuel Colvin

#### PySide6_Addons 6.11.3

- **License**: `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only` · elected
  `LGPL-3.0-only` · a requirement of PySide6
- **Copyright**: *the wheel ships no copyright line.* Its one license file is
  `LicenseRef-Qt-Commercial.txt`, described above. Recorded as absent rather
  than invented.

#### PySide6_Essentials 6.11.3

- **License**: `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only` · elected
  `LGPL-3.0-only` · a requirement of PySide6
- **Copyright**: *the wheel ships no copyright line.* Its one license file is
  `LicenseRef-Qt-Commercial.txt`, described above. Recorded as absent rather
  than invented.

#### shiboken6 6.11.3

- **License**: `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only` · elected
  `LGPL-3.0-only` · a requirement of PySide6
- **Copyright**: *the wheel ships no copyright line.* Its one license file is
  `LicenseRef-Qt-Commercial.txt`, described above. Recorded as absent rather
  than invented.

#### sniffio 1.3.1

- **License**: `MIT OR Apache-2.0` · a requirement of anthropic
- **Copyright**: *the wheel ships no copyright line.* `LICENSE.MIT` has none, and
  `LICENSE.APACHE2` has the appendix template unfilled. Recorded as absent
  rather than invented.

#### termcolor 3.3.0

- **License**: `MIT` · a requirement of fire
- **Copyright**, verbatim from `COPYING.txt`:
  > Copyright (c) 2008-2011 Volvox Development Team

#### truststore 0.10.5

- **License**: `MIT` · a requirement of httpcore2 and httpx2
- **Copyright**, verbatim from `LICENSE`:
  > Copyright (c) 2022 Seth Michael Larson

#### typing-inspection 0.4.4

- **License**: `MIT` · a requirement of pydantic
- **Copyright**, verbatim from `LICENSE`:
  > Copyright (c) Pydantic Services Inc. 2025 to present

#### typing_extensions 4.16.0

- **License**: `PSF-2.0` · a requirement of anthropic, anyio, httpx2,
  opentelemetry-api, pydantic, pydantic_core, python-docx and
  typing-inspection, and of ezdxf when PyDRC is installed
- **Copyright**: `LICENSE` is the Python license history and agreements. The
  Python Software Foundation's notice of copyright in it, verbatim:
  > Copyright (c) 2001, 2002, 2003, 2004, 2005, 2006, 2007, 2008, 2009, 2010,
  > 2011, 2012, 2013, 2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023 Python Software Foundation;
  > All Rights Reserved
- The file carries the notices of the earlier agreements in that history too.

### Bundled when the build installs PyDRC

The release build installs PyDRC whenever its `PYDRC_TOKEN` secret is set, and
the v1.8.0 tag build did. PyDRC's `dxf` extra brings these two.

#### ezdxf 1.4.5

- **License**: `License :: OSI Approved :: MIT License`, its classifier, as it
  declares no license field · a requirement of PyDRC's `dxf` extra
- **Copyright**, verbatim from `LICENSE`:
  > Copyright (c) 2020 Manfred Moitzi

#### pyparsing 3.3.3

- **License**: `MIT` · a requirement of ezdxf
- **Copyright**, verbatim from `LICENSE`:
  > Copyright (c) 2003-2025  Paul McGuire

### The build tool

#### pyinstaller 6.22.3

- **License**: `GPLv2-or-later with a special exception which allows to use
  PyInstaller to build and distribute non-free programs (including commercial
  ones)`
- What ships is the bootloader that becomes `DSI Redline.exe`, and the runtime
  modules `_pyi_rth_utils` and `_pyi_rth_utils.qt`.
- **Copyright**, verbatim from `COPYING.txt`:
  > Copyright (c) 2010-2023, PyInstaller Development Team
  > Copyright (c) 2005-2009, Giovanni Bajo
  > Based on previous work under copyright (c) 2002 McMillan Enterprises, Inc.

---

## Not covered here

- **PyDRC 0.23.1** is DSI's own and is not a third-party package. Its
  `pyproject.toml` declares its license as `Proprietary`. It is in the bundle
  whenever the build installs it, as the v1.8.0 tag build did.
- **The Python interpreter.** The bundle carries the CPython 3.11 runtime and
  the libraries the interpreter itself links. It is not a pip distribution, its
  license file is in the Windows interpreter's own install, and this audit did
  not read it. It is recorded as **not checked**, not as clean.
- **The Windows folder itself.** The package list above was measured on a Linux
  build of the same spec and cross-checked against the Windows build's install
  log and hook list. The Windows build's own folder listing was not read. From
  the next Build Windows run with the PyDRC token, the workflow reads it, as
  "How to re-run the audit" describes.

## How to re-run the audit

`tools/notices_audit.py` does steps 2 and 4 of "How this was produced". It
traces a finished build to the distributions that reach it and copies their
license files from the Windows wheels. It needs the build and PyDRC's private
repository, so the Tests workflow cannot run it. The Build Windows workflow
can, and does: after every build that installs PyDRC it runs the audit against
the bundle it just built and compares `licenses/` with what is committed. A tag
build fails on any difference, and a manual run warns. A build without the
PyDRC token logs that the notices were not checked.

So the steps below are for updating the notices before a release, and for
reading what a failed check found. Run each command from the repository root.

1. Make a Python 3.11 virtual environment for the build and activate it.
2. Install setuptools 65.5.0, the version the Windows runner's Python 3.11.9
   carries.

   ```bash
   python -m pip install setuptools==65.5.0
   ```

   With setuptools 79, httpx2's `from backports.zstd import` makes PyInstaller
   bundle the copy of `backports` that setuptools vendors, so setuptools ships
   from a Linux build and not from the Windows one. The audit refuses any other
   version on a build that is not Windows.
3. Install the app, the build tools, and PyDRC at the ref that
   `packaging/pydrc-ref.txt` names.

   ```bash
   python -m pip install -r requirements.txt -r packaging/requirements-build.txt
   python -m pip install "pydrc[dxf] @ git+https://github.com/DSI-codebase/PyDRC@<ref>"
   ```

   PyDRC needs credentials for its repository, as `CI.md` describes. The
   release build installs it and it brings ezdxf and pyparsing, so the audit
   refuses a build without it.
4. Build the spec.

   ```bash
   pyinstaller packaging/DSI_Redline.spec --noconfirm
   ```

5. Run the audit with the same interpreter.

   ```bash
   python tools/notices_audit.py
   ```

   It reads `build/DSI_Redline/PYZ-00.toc`, `base_library.zip` and
   `dist/DSI Redline/_internal/`. It prints every installed distribution with
   its module count, file count and `RECORD` size, marks the ones that ship, and
   counts the files no distribution claims. Then it downloads the Windows wheel
   of each package that ships and rewrites every directory under `licenses/`
   from those wheels, byte for byte. The four texts at the top of `licenses/`
   are supplied by hand, and it leaves them alone. It exits 2 and writes nothing
   when the build is incomplete, nothing ships, a wheel is missing, or a wheel
   holds no license file of its own. For a package whose wheel ships none,
   supply its text at the top of `licenses/`, give it a row in the table below,
   and name both in `SUPPLIED_BY_HAND` in the tool. The audit then reports that
   package as supplied by hand, and refuses the entry once the package ships a
   license file again or leaves the bundle.
6. Read `git status licenses/`. A directory added or removed is a package that
   joined or left the bundle, so add or remove its entry under "The bundled
   packages" by hand. A changed file means that entry's quoted lines are read
   again from it.
7. Run the notices test. It fails on a directory with no entry, an entry with no
   directory, or a quoted line that is not in that package's own files.

   ```bash
   python -m unittest tests.test_notices_ship
   ```

8. Update the date, the version and the counts in "How this was produced".

## Full license texts

| File | Covers |
|---|---|
| `licenses/LGPL-3.0.txt` | PySide6, PySide6_Addons, PySide6_Essentials and shiboken6, the elected arm |
| `licenses/GPL-3.0.txt` | incorporated by reference into LGPL-3.0 above, and the license AGPL-3.0 builds on |
| `licenses/LGPL-2.1.txt` | iconv, which lxml's binary wheels bundle |
| `licenses/Apache-2.0.txt` | fire, whose own `LICENSE` points to it. Byte-identical to the `LICENSE` that pytesseract and opentelemetry-api ship |
| `licenses/annotated-types/` | annotated-types 0.8.0 |
| `licenses/anthropic/` | anthropic 2.3.0, including the vendored `httpx_aiohttp` |
| `licenses/anyio/` | anyio 4.15.1 |
| `licenses/docstring_parser/` | docstring_parser 0.18.0 |
| `licenses/et_xmlfile/` | et_xmlfile 2.0.0 |
| `licenses/ezdxf/` | ezdxf 1.4.5 |
| `licenses/fire/` | fire 0.7.1 |
| `licenses/fonttools/` | fonttools 4.68.0 |
| `licenses/h11/` | h11 0.16.0 |
| `licenses/httpcore2/` | httpcore2 2.16.0 |
| `licenses/httpx2/` | httpx2 2.16.0 |
| `licenses/idna/` | idna 3.20 |
| `licenses/jiter/` | jiter 0.18.0 |
| `licenses/lxml/` | lxml 6.1.3, including the libraries its wheels bundle |
| `licenses/numpy/` | numpy 2.4.6, including OpenBLAS, LAPACK and the GCC runtime library |
| `licenses/opencv-python-headless/` | opencv-python-headless 5.0.0.93, including FFmpeg |
| `licenses/openpyxl/` | openpyxl 3.1.5 |
| `licenses/opentelemetry-api/` | opentelemetry-api 1.45.2 |
| `licenses/packaging/` | packaging 26.3 |
| `licenses/pdf2docx/` | pdf2docx 0.5.13 |
| `licenses/pillow/` | pillow 13.0.0, including the 12 libraries it bundles |
| `licenses/psutil/` | psutil 7.2.2 |
| `licenses/pydantic/` | pydantic 2.14.2 |
| `licenses/pydantic_core/` | pydantic_core 2.50.2 |
| `licenses/pyinstaller/` | pyinstaller 6.22.3 |
| `licenses/pymupdf/` | pymupdf 2.0 |
| `licenses/pyparsing/` | pyparsing 3.3.3 |
| `licenses/PySide6/` | PySide6 6.11.3 |
| `licenses/PySide6_Addons/` | PySide6_Addons 6.11.3 |
| `licenses/PySide6_Essentials/` | PySide6_Essentials 6.11.3 |
| `licenses/pytesseract/` | pytesseract 0.3.13 |
| `licenses/python-docx/` | python-docx 1.2.0 |
| `licenses/PyYAML/` | PyYAML 6.0.3 |
| `licenses/shiboken6/` | shiboken6 6.11.3 |
| `licenses/sniffio/` | sniffio 1.3.1 |
| `licenses/termcolor/` | termcolor 3.3.0 |
| `licenses/truststore/` | truststore 0.10.5 |
| `licenses/typing-inspection/` | typing-inspection 0.4.4 |
| `licenses/typing_extensions/` | typing_extensions 4.16.0 |
