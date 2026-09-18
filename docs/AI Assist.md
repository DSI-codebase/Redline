---
tags: [ai, settings]
---

# AI Assist

AI is **optional and opt-in**. DSI Redline works fully without it; AI only helps
read or disambiguate wire numbers on scanned/low-confidence regions.

## Enable it

In [[Settings]] ▸ **OCR & AI assist**:

1. Tick **Enable Claude vision assist**.
2. Paste your key in **API key** (use **Show** to reveal it). The key is stored
   in the app config. Alternatively set the `ANTHROPIC_API_KEY` environment
   variable and leave the field blank.
3. Click **Check API status** to verify it.

## Status indicator

- **disabled** — AI is off.
- **No API key set** — enable and paste a key.
- **Key set** — present but not yet verified.
- **Key is valid** / **Invalid API key** — result of **Check API status**.
- **anthropic SDK not installed** — run `pip install anthropic`.

The model defaults to `claude-opus-4-8` and is configurable.

## How it's used in extraction

When you run **Extract wire numbers** ([[Wire Numbers]]) on a set with **scanned
pages**, each such page is read by Claude. DSI Redline asks you to confirm first
(showing the total number of API calls), and a progress bar shows each page/tile
so you can cancel anytime.

### Tiling — accuracy vs. cost

Claude down-scales large images, so a whole dense schematic page can lose small
wire numbers. **AI tiling** (Settings) splits each scanned page into an **N×N**
grid and reads each tile at full resolution, then stitches the results back
together (overlap duplicates are removed automatically).

- **1 = whole page** — 1 call/page, fastest, may miss tiny labels.
- **2 = 2×2** (default) — 4 calls/page, ~2× the effective resolution.
- **3 = 3×3** — 9 calls/page, ~3× resolution, for very dense or low-quality scans.

Total calls = scanned pages × N². The confirmation dialog shows the count before
anything is sent.

AI is what makes **non-searchable** and **non-standard** drawings work: it reads
labels even when they don't fit the configured format, returning them as
fixed/OEM so nothing is lost.

If the key is missing or invalid, extraction falls back to [[OCR]] (or the text
layer) — nothing breaks.

#ai
