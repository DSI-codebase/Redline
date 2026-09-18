# Third-party notices — DSI Redline

DSI Redline is distributed as a Windows installer and a portable zip that bundle
every runtime dependency. Those dependencies keep their own licence terms, and
several of them require their notice to travel **with the distributed form** —
a file in the repository satisfies nothing for somebody who downloads the `.exe`.
So this file and the `licenses/` directory beside it are installed with the app.

> **How this was produced.** Every copyright line below is copied **verbatim**
> from that package's own licence file in the installed distribution, resolved
> and read on **2026-09-01**. Nothing is transcribed from memory and no year is
> inferred. Where a package ships no copyright line, that is recorded as an
> absence rather than filled in.

> **Versions are as-resolved, not pinned.** `requirements.txt` uses `>=`
> constraints, so the versions here are what a fresh resolve produced on the
> date above. A build from a different date may bundle different versions —
> re-run the audit when cutting a release rather than trusting this list to be
> current.

---

## ⚠ PyMuPDF is AGPL-or-commercial, and that is unresolved

`PyMuPDF` declares **`Dual Licensed - GNU AFFERO GPL 3.0 or Artifex Commercial
License`** — measured, not assumed: that string is the entire contents of the
package's own `COPYING`. It is bundled inside the shipped installer.

Only one of the two arms can apply, and **which one has not been established**:

- if a **commercial Artifex licence is held**, that arm governs and nothing
  further is required here;
- if not, the **AGPL-3.0 arm** governs the distributed binary, and its
  obligations attach to it.

This repository is **public** and its workflow publishes the installer, so this
is not theoretical. **The question is recorded as a Phase 6 ask to whoever
handles legal** (Pathforward `data/decisions.json`, D57) and is deliberately not
answered here — it is not an engineering decision. Until it is answered, treat
external distribution as unresolved rather than permitted.

## PySide6 and shiboken6 ship no licence text of their own

Measured on the installed 6.11.2 wheels: **zero licence, COPYING or NOTICE files
are present in either distribution.** They are `LGPL-3.0-only OR GPL-2.0-only OR
GPL-3.0-only`, and this project **elects `LGPL-3.0-only`**.

The LGPL requires the licence to accompany the distribution, so **this project
supplies the text itself** — `licenses/LGPL-3.0.txt`, verbatim FSF text, Version
3 of 29 June 2007.

**That gap is now filled.** LGPL-3.0 incorporates the GNU General Public License
version 3 by reference, so `licenses/GPL-3.0.txt` is supplied beside it —
verbatim FSF text, Version 3 of 29 June 2007, 674 lines, sha256
`3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986`.

**Where it came from, because a licence text is the one file that must not be
transcribed.** `https://www.gnu.org/licenses/gpl-3.0.txt` is unreachable from
the environment this audit runs in, which is why the earlier pass recorded the
absence rather than filling it. What was used instead is two *independent*
packagings of the FSF's own file — Debian's `/usr/share/common-licenses/GPL-3`
and GNU automake's own `COPYING` — which are **byte-identical**, and one of them
ships inside a GNU project. Two sources agreeing is a cross-check; one source is
a copy.

**A reflowed copy was found first and rejected.** The Rust toolchain ships a
`GPL-3.0-or-later.txt` that is the same licence with its paragraphs unwrapped
onto single lines, `©` for `(C)`, and a broken `<https: //www.gnu.org/…>` in the
final paragraph. It is legible and it is not the document the FSF publishes,
which is the only thing "verbatim" can mean here.

---

## The bundled packages

### PySide6 6.11.2

- **License** — `LGPL-3.0-only` · elected from `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only`
- **Copyright** — *the distribution ships no copyright line.* Recorded as absent rather than invented.

### shiboken6 6.11.2

- **License** — `LGPL-3.0-only` · elected from `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only`
- **Copyright** — *the distribution ships no copyright line.* Recorded as absent rather than invented.

### PyMuPDF 1.28.2

- **License** — `AGPL-3.0-only OR Artifex Commercial` · **NOT elected — see the warning above**
- **Copyright** — *the distribution ships no copyright line.* Recorded as absent rather than invented.

### openpyxl 3.1.5

- **License** — `MIT`
- **Copyright**, verbatim from the package's own licence file:
  > Copyright (c) 2010 openpyxl

### python-docx 1.2.0

- **License** — `MIT`
- **Copyright**, verbatim from the package's own licence file:
  > Copyright (c) 2013 Steve Canny, https://github.com/scanny

### pdf2docx 0.5.13

- **License** — `MIT`
- **Copyright**, verbatim from the package's own licence file:
  > Copyright (c) 2026 Artifex Software, Inc.

### pytesseract 0.3.13

- **License** — `Apache-2.0`
- **Copyright** — *the distribution ships no copyright line.* Recorded as absent rather than invented.

### Pillow 12.3.0

- **License** — `MIT-CMU`
- **Copyright**, verbatim from the package's own licence file:
  > Copyright © 1997-2011 by Secret Labs AB
  > Copyright © 1995-2011 by Fredrik Lundh and contributors
  > Copyright © 2010 by Jeffrey 'Alex' Clark and contributors

### anthropic 1.3.0

- **License** — `MIT`
- **Copyright**, verbatim from the package's own licence file:
  > Copyright 2023 Anthropic, PBC.
  > Copyright © 2025, Karen Petrosyan.

  **Vendored inside this package** — `httpx_aiohttp`, `BSD-3-Clause`, which the top-level MIT declaration does not cover:
  > Copyright © 2025, Karen Petrosyan.

### PyYAML 6.0.3

- **License** — `MIT`
- **Copyright**, verbatim from the package's own licence file:
  > Copyright (c) 2017-2021 Ingy döt Net
  > Copyright (c) 2006-2016 Kirill Simonov
---

## Full licence texts

| File | Covers |
|---|---|
| `licenses/LGPL-3.0.txt` | PySide6, shiboken6 (elected arm) |
| `licenses/GPL-3.0.txt` | incorporated by reference into LGPL-3.0 above; also the arm AGPL-3.0 builds on |
| `licenses/Apache-2.0.txt` | pytesseract |
| `licenses/MIT-CMU-Pillow.txt` | Pillow, including the libraries it bundles |
| `licenses/BSD-3-Clause-httpx-aiohttp.txt` | `httpx_aiohttp`, vendored inside `anthropic` |

The MIT-licensed packages carry the standard MIT text with the copyright lines
quoted above; each is reproduced in that package's own installed distribution.

## Not bundled

`pydrc` is a sibling DSI project installed from a private repository and is not
redistributed in the installer. `requirements-drc.txt` explains why it is
separate.
