---
tags: [ocr, wire]
---

# OCR

Most AutoCAD plots are **vector** PDFs with a text layer, so no OCR is needed.
For **scanned/raster** pages, DSI Redline can OCR with **Tesseract**.

## Setup

Install the Tesseract binary (the `pytesseract` wrapper is in
`requirements.txt`):

- Ubuntu/Debian: `sudo apt install tesseract-ocr`
- macOS: `brew install tesseract`
- Windows: the UB-Mannheim build, on your `PATH`.

Then tick **Enable OCR fallback** in [[Settings]].

## How it's used

During [[Wire Numbers]] extraction, pages **without** a text layer are rendered
at higher DPI and OCR'd; recognized tokens flow through the same parser. Such
labels show `Source = ocr` in the table. Low-confidence regions can optionally
be sent to [[AI Assist]].

If Tesseract isn't installed, OCR is skipped silently.

#ocr
