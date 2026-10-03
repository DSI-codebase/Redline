# Jev in Redline: handoff

Written 2026-10-03 by the cross-repo survey session, for the session that
integrates TypeSafe's Jev here. It reads Redline at `b810e7f`
(DSI-codebase/Redline, merge of PR #11). It is a desk read plus one suite run:
**no Jev call was made against anything from this repository, and no code was
changed.** Every `path:line` below is at that sha.

It sits at the root because nothing under `docs/` is inert: `load_vault` globs
`docs/*.md` into the in-app help (`app/help.py:90`), the spec bundles `docs/`
recursively into both distributed forms (`packaging/DSI_Redline.spec:27`), and
`docs/history/` and `docs/records/` are held to manifests
(`tests/test_help.py:111`, `tests/test_documents_are_measured.py:152`).

## What was asked

The owner asked for one handoff per repository where Jev fits best. The survey's
proposal for Redline was that Jev take over the **classification of extracted
text tokens** that Claude does today by prompt-and-parse, the vision model
keeping only the reading of pixels. Two candidates under "Later, not first" stay
later.

## Progress, 2026-10-03 (the integrating session)

**Owner answers to the four questions at the end, given 2026-10-03:**

1. Label and title-block text from real drawings may go to TypeSafe, under the
   current plan (not ZDR).
2. The key comes from `TYPESAFE_API_KEY` **and** a Settings field stored in
   QSettings; the field wins.
3. Scanned sets are reviewed with AI assist **rarely**, so **sheet role goes
   first**. The label split below ("The judgment to build") waits.
4. Jev may judge text-layer tokens **later**; nothing here does yet.

**Task 1, access:** `GET /v1/models` answered 200 listing `jev-latest` and
`jev-preview` only. The docs say versioned IDs are accepted whether listed or
not, and every request below sent `jev-1.13.0` and got `"model": "jev-1.13.0"`
back.

**Tasks 3 and 4, re-aimed at sheet role, are built** behind
`jev/sheet_roles`, default off:

- `app/extraction/jev_api.py`: stdlib client; `ask` never raises; retry 408,
  429, 5xx honoring `retry-after-ms` then `retry-after`, 4 attempts, a wait
  over 30 s gives up; key in the header only; model pinned to `jev-1.13.0`.
- `app/extraction/sheet_role.py`: one Choice over the nine `ROLES`, `unknown`
  last; state is `title_block` (the band `ROLE_KEYWORDS` reads) plus
  `page_text` on a sparse page, the same two sources; a page with no text is
  not sent. `JEV_THRESHOLD = 0.6` is **provisional** (myNameJev's). Answers
  carry `model` and `JEV_WORDING`; either changing makes them stale.
- `app/model/document.py`: `sheet_role_sources` (only `"user"`, from
  `set_sheet_role`) and `sheet_role_jev` (answers), each in its own meta key so
  an older build still opens the sidecar. `roles_for_audit(use_jev)` is user >
  Jev at or above threshold > keyword. Flag off returns HEAD's roles. Every
  revision in history was grepped: no `app/` caller of `set_sheet_role` ever
  existed, so a saved role without a source is keyword output.
- `MainWindow.run_audit`: counts pages with text and no current answer, asks
  before sending (the dialog names TypeSafe and the title-block contents),
  runs Jev in the audit worker on its own handle, and keeps answers even when
  the check is canceled. Settings ▸ OCR / AI has a **Jev (TypeSafe)** group.
- Gates, each falsified by injecting its defect (the table below, plus the
  window's flag check and a scanned page counted as waiting): 12 injections,
  12 red. The audit wiring is tested with PyDRC faked, so it runs
  without the private library.

**First live answers, synthetic text only** (sent from this session; nothing
from a real drawing):

- The 13 titles in `tests/test_sheet_role.py:50-76`, as plotted on rotated
  pages: Jev 13/13, keywords 13/13. These are the titles the keyword table was
  written from, so this separates nothing. 643-653 input tokens and 0.23-0.61 s
  per request; at 653 tokens a 41-sheet set is 26,773 tokens, $0.0011. Real
  title blocks carry more text, so this is a floor, not the price.
- 12 title blocks with a client, address, project, drawn/checked names, date
  and drawing number around the title, **written by this session to break the
  keyword table** (a client named SYMBOL TECHNOLOGIES, a note "SEE SHEET INDEX
  ON E-001"): Jev 12/12, keywords 2/12. Biased by construction; it shows the
  clutter is read, not that Jev beats keywords. One answer, `MOTOR STARTERS`
  beside "REFER TO PANEL LAYOUT E-500", was right at confidence 0.25, so the
  threshold handed it back to the keyword answer, `layout`, which is wrong.

**Tasks 5 and 6 on a real set, 2026-10-03.** The owner supplied a 26-sheet
vector plot, labeled every sheet's role, and confirmed the labels the same day.
The PDF, the labels and both recordings stay outside this repository; nothing
below quotes its text. "The 41-sheet set" above was never a named file: the
number comes from a comment at `app/audit/findings.py:49`, and any labeled real
set serves.

- **Coverage:** 5 of the 9 roles. 1 index, 2 layout, 1 topology, 3 schematic,
  19 plc-io. No bom, terminal-detail, legend or unknown sheet, and every sheet
  uses one title-block template.
- **Price:** 794-840 input tokens per sheet, 20,865 for the set, $0.0009 a
  run. 0.23-0.65 s per request, sequential.
- **Accuracy against the owner's labels:** keywords 23/26; Jev's raw choice
  25/26; what the app applies (Jev at or above 0.6, else keywords) 25/26.

  | sheet | owner | keywords | Jev, run 1 / run 2 | applied |
  |---|---|---|---|---|
  | relay-output module sheet (x2) | plc-io | schematic | plc-io 0.98 / 0.98-0.99 | plc-io |
  | PLC-slot power distributor | plc-io | schematic | plc-io 0.40 / **schematic** 0.40 | schematic |
  | operator-station control wiring | schematic | schematic | **index** 0.47 / 0.42 | schematic |
  | the other 22 | = | = | right, 0.94-1.00 | right |

- **Noise floor**, the same 26 bodies sent twice: 1 choice changed (the power
  distributor, below 0.5 both times); largest confidence change 0.05.
- **The threshold held:** every answer at or above 0.6 (24, all 0.94 or more)
  was right; both wrong or split answers were at or below 0.47. The operator-station
  miss is the dangerous direction: `index` is a referencing role and
  `text_region.SHEET_ROLE_REGIONS` marks every token on an index sheet as
  non-drawing, so applied, it would have silenced the location rules on a real
  schematic. Its best run fell 0.13 short of the threshold.
- **No criteria change.** Rewording `schematic` to catch one sheet is tuning to
  that sheet, and `JEV_WORDING` stays 1.
- **On this set Jev cannot beat keywords where the audit looks.** All three
  keyword misses are plc-io read as schematic, and neither is in
  `REFERENCING_ROLES`, so location rules treat the two alike. Whether a PyDRC
  rule reads `plc-io` was not checked (PyDRC is not installed here).

**Next, for sheet role, in order:** task 6 again on sets this one cannot
cover: one with bom, terminal-detail or legend sheets, and one with another
title-block template; task 7 (set `JEV_THRESHOLD` from bands across those sets,
bumping `JEV_WORDING` with any criteria change); task 8 (rerun the 47%/92%
measurement with Jev roles, which needs PyDRC; default on only if Jev matches
or beats keywords on referencing roles); task 9 (CHANGELOG section and the
version in its three places).

**Still open:** there is no role editor, so a wrong Jev answer can be undone in
the app only by switching Jev off. The label split stays "later" per answer 3.

## What exists at HEAD, and the finding that reshapes the ask

**No Claude call classifies already-extracted text.** Every call that asks for
a judgment sends an image, and the judgment comes back fused with the reading:

| `app/extraction/claude_api.py` | sends | asks for |
|---|---|---|
| `validate_key` :58-81 | the text `"ping"` (:73) | nothing; an auth probe |
| `read_wire_region` :129-163 | one PNG tile (:154-156) | `label, is_wire, confidence, bbox` (:103-107) |
| `read_text_region` :191-201 | one PNG | a transcription |
| `read_component_region` :222-248 | one PNG tile (:241-243) | `label, family, is_component, confidence, bbox` (:214-218) |
| `extract_region_content` :268-297 | one PNG | table or text, plus rows or text (:253-265) |
| `tag_descriptions` :328-342 | N PNGs | generated tag and description; no caller in `app/`, only `tests/test_crop_tags.py:24` |

Replies are parsed by regex (`_extract_json` :111-126, :300-314). The stated
purpose "to disambiguate low-confidence candidates ('is this a wire number or a
terminal/part number?')" (:3-4) happens only inside the vision prompt.
`DEFAULT_MODEL` is `"claude-opus-4-8"` (:18; `app/config.py:94`).

Claude runs only on pages **without** a text layer: `collect_tokens` takes the
text layer whenever `page_has_text` (`app/extraction/text_extract.py:464-465`)
and calls `ai_page` otherwise (:466-473). There the vision model's `is_wire` is
the only judgment: `_ai_results_to_tokens` drops `is_wire: false` (:226) and
keeps a self-reported confidence parsed from text with a 0.5 default
(:238-241); `WireParser.is_candidate` accepts any AI token containing a digit
(`app/extraction/wire_parser.py:254-257`). Components follow the same path
(`text_extract.py:314`, `app/extraction/component_parser.py:178-179`), and
`tests/test_extraction.py:35-38` pins the behavior.

So the build is a **split**: the vision prompt reads every short label and its
box and stops judging; Jev decides what each label is from text. Jev cannot see
the conductor the vision model sees ("Input: Text only ... No image, audio, or
video input", docs `/models.md`), so whether text plus neighbors is enough is
the first measurement, not an assumption.

## The judgment to build

One **Choice** per label read on a scanned tile. A draft, to be tuned:

- `state`, built in code, small and named:
  `{"label": "432141", "format": "digits only; matches this project's wire-number format", "neighbors": ["CR-43214", "L1", "13"]}`.
  Code derives `format` from `WireConfig.label_pattern()` (`wire_parser.py:83-90`)
  and the family-code set (`component_parser.py:71-72`), so Jev never weighs a
  width or a digit count (jaggedness 2). `neighbors` holds at most eight labels
  nearest by box. Labels inside the title-block strip
  (`app/extraction/text_region.py:77-78`) are left out. No sheet role: on a
  scanned page `detect_role` has no text to read and returns the default.
- `instructions`: "Decide what kind of printed text `label` is on an electrical
  ladder schematic. `neighbors` are the texts printed closest to it. `format`
  is what code found about its characters."
- `criteria`: `wire_number` (identifies a conductor; printed on or beside a wire
  segment), `device_tag` (a family code of letters then a number, such as
  CR-30024), `terminal` (a terminal or pin designation on a device or strip),
  `line_number` (the rung number in the margin gutter), `part_or_rating` (a
  catalog or model number, or a rating such as 24VDC), `note_or_title` (words of
  a note, title, revision table or heading), `other`.

**Code keeps** the pixels (vision), the format match and the
conforming/fixed/jumper split (`wire_parser.py:294-330`), family membership
(`component_parser.py:190-191`), tiling, box math, dedupe
(`text_extract.py:247-259`) and the threshold. **Consumed at**
`text_extract.py:226` and `:314`, in place of `is_wire`/`is_component`.
**Jev proposes; three things check it:** code's format match still decides
conforming versus fixed/OEM; below the threshold a label is kept with a review
flag, not dropped, as unknown families are (`component_parser.py:11-13`); the
user's include column (`docs/Wire Numbers.md:68-69`). No Jev key: the HEAD path.

## Later, not first

- **Sheet role.** One Choice of the nine `ROLES` (`sheet_role.py:38-39`) per
  page, in place of the substring table `ROLE_KEYWORDS` (:60-73, read at :103).
  Recorded: mismatch flags fire "on 47% of tags", and roles remove "92% of that"
  (:9-11); "inference will not always be right" (:15). State is the title-block
  band (:110-131); `unknown` maps to `schematic` (:137-141). Cheapest here, and
  the hardest data question.
- **Prose lines.** One Noul per run found by `prose_token_ids`
  (`text_region.py:109-162`), in place of counting the 40 `FUNCTION_WORDS`
  (:88-92). Recorded: one notes block "produced three false findings on its
  own" (:4-8); the word list once masked a real wire (:81-87).

Not recommended: the wire types (`wire_parser.py:27-29`) and SHX ignore patterns
(`app/model/storage.py:32-39`) are exact rules. Findings triage (92 findings over
379 places on a real 41-sheet set, `app/audit/findings.py:46-50`) stays human:
severity is the rule's or a setting (`findings.py:20-34`, `docs/Design Rule
Check.md:176-185`), a waiver is a named person's (`findings.py:305-312`), and
"this tool never does" decide compliance (`Design Rule Check.md:15-17`). Table
versus text (`claude_api.py:253-265`) needs pixels; tags are generation.

## Ground truth

- **Primary:** none in the repository (`tests/test_extraction.py` fakes three
  labels). Hand-label a real scanned set from the owner, the vision `is_wire`
  beside each as the baseline. The sidecar's `included` column (`storage.py:427`)
  records an export choice, a different question.
- **Sheet role:** 13 synthetic titles in `tests/test_sheet_role.py:50-76`.
  Saved roles are not human labels: `save()` writes detected roles
  (`app/model/document.py:405`) with no source (:66), unlike sheet numbers
  (:62-64). Label a real set's 41 sheets; rerun the 47%/92% measurement.

## Constraints that bind the design

- "`pydrc` (design rules), `ezdxf` (reading ACADE source drawings) and
  `anthropic` (AI extraction) are each absent on some real installs, and every
  one **reports itself unavailable in the place it would have been used**
  rather than raising" (`CLAUDE.md:55-57`); "A new one follows the same
  pattern" (`CONTRIBUTING.md:52`). Use stdlib `urllib` and `json`: no package,
  no `THIRD-PARTY-NOTICES.md` row, no entry in `DSI_Redline.spec:38`'s list.
- "fully functional offline" (`CLAUDE.md:5`): no key or network gives the HEAD
  path. "The original file is never overwritten" (:27): answers are sidecar state.
- Each test module runs in its own process (`CLAUDE.md:80`), survives PySide6
  blocked (`tests/test_qt_absent_degrades.py`) and keeps `if __name__` last
  (`tests/test_suite_is_discoverable.py`). The runner "groups every skip by its
  stated reason" (`CLAUDE.md:75`), and an unknown reason "is counted but
  unexplained" (`CONTRIBUTING.md:59`): fake Jev, no live-API skip.
- A Settings tab must match `docs/Settings.md` (`tests/test_settings_layout.py`),
  and "Docs move with the change" (`CONTRIBUTING.md`): `docs/AI Assist.md`.
- The repository is **public**: no real drawing text, recorded body or key.

## Data that leaves the machine

Everything in `state` goes to TypeSafe. Jev is not trained on customer
requests; zero data retention is for enterprise customers (docs `/models.md`,
"Data handling"). For the primary that is label and neighbor text from scanned
drawings; for sheet role it is the title block, where a client's name, a site
address and engineers' names are printed. AI assist already sends whole tiles to
Anthropic when the user opts in (`docs/AI Assist.md:7`); Jev is a second
processor on different terms. **Owner decision before any request carries real
drawing text:** whether it may, under which plan, and whether the confirmation
dialog (`app/panels/wire_panel.py:278-300`) names TypeSafe too.

## Jev facts (docs read 2026-10-02 and 2026-10-03; the live docs win)

- `POST https://api.typesafe.ai/v1/systemone`, `Authorization: Bearer <key>`,
  body `{state, model, questions}`; questions about one state share a request
  ([api](https://docs.typesafe.ai/api.md), [index](https://docs.typesafe.ai/llms.txt)).
- Choice: at most 255 options; answer `{choice, confidence, probabilities}`,
  confidence `(p_max - 1/n) / (1 - 1/n)` ([choice](https://docs.typesafe.ai/primitives/choice.md),
  [confidence](https://docs.typesafe.ai/confidence.md)). Score: at most 10
  levels. A Noul with neither instructions nor criteria got 400 (2026-10-02).
- `jev-latest` and `jev-preview` point to `jev-1.13.0`; aliases move, so pin
  `jev-1.13.0` ([models](https://docs.typesafe.ai/models.md)). $0.042 per
  million input tokens, output free; 64k per request, 32k for state plus the
  longest question; read 2026-10-03, 100K tokens/s and **80 requests/s** (a
  read on 2026-10-02 gave 40), "adjusting dynamically".
- Errors 401, 422, 429, 529. Retry 408, 429 and 5xx, honoring `retry-after-ms`
  then `retry-after`; anything else is fatal.
- [jev-1.13 jaggedness](https://docs.typesafe.ai/model-jaggedness/jev-1.13.md):
  literal reading; math and numbers, numeric representations included; dates;
  indirection; large irrelevant state; adversarial content; contradictory
  instructions and criteria; **choice option order**; generation.
- Noise, myNameJev 2026-10-02: 40 requests sent twice changed confidence on 17,
  by up to 0.11, with no category change; a 1,032-request replay changed 10
  categories, all below 0.5 confidence.
- Precedent, myNameJev 2026-10-02: one Choice of 14 per request, 3,600-4,300
  input tokens each, $0.15-0.18 a full run; tuning took 30 hand-labeled entries
  from 7 right to 29; threshold 0.6 from error bands (about 1 in 3 wrong at
  0.5-0.6, 1 in 6 at 0.6-0.7, about 3 in 110 above 0.7). Bare generic words
  matched more than the case they were written for.

## Tasks in order

1. **Confirm access:** `GET https://api.typesafe.ai/v1/models` with
   `TYPESAFE_API_KEY` (in a Claude Code cloud session a placeholder works; the
   proxy injects the key). Done: it lists `jev-latest`; pin `jev-1.13.0`.
2. **Owner answers** to the questions at the end. Done: written into this file.
3. **`app/extraction/jev_api.py`**, GUI-free, shaped like `claude_api.py`:
   `resolve_key`, `available`, `status`, one `ask(state, questions, model)` over
   `urllib` with the retry rule, returning `None` instead of raising. Done:
   tests with a fake transport pass with no network.
4. **The split, behind a flag that defaults off:** a read-only vision prompt,
   the Jev Choice, consumption at `text_extract.py:226`/`:314`. Done: flag off,
   `tests/test_extraction.py` passes unchanged; flag on, fakes reach every
   branch, Jev failing mid-run included.
5. **Record bodies, then price:** Pathforward's `/tuning-jev` `record.py` on the
   owner's scanned set, **outside this checkout**; tokens from
   `usage.input_tokens` x labels x $0.042/M. Done: the owner accepts the figure.
6. **Hand-label targets and guards** for every option, beside the vision
   `is_wire`, in a keyed file outside the repository; then measure the noise
   floor by replaying the same bodies twice with `--model jev-1.13.0`.
7. **Tune and calibrate:** criteria as exact conditions, replay, read
   `compare.py`'s unlabeled moves first, reorder the options once (jaggedness
   8), set the threshold from confidence bands. Done: the band table.
8. **Decide:** switch the default only if Jev matches or beats the vision
   `is_wire` on the labels; otherwise stop and record why.
9. **Docs and release:** `docs/AI Assist.md`, `docs/Settings.md`, the version in
   its three places (`CLAUDE.md:110-112`). Answers from real drawings are never
   committed here.

## Gates to write, and the defect that must turn each red

| gate | inject |
|---|---|
| `ask` never raises; the caller sees "unavailable" | transport raises `OSError` with the `try` removed |
| body is `{state, model, questions}` with `jev-1.13.0` | send `jev-latest` |
| no key in any body or recording | put the key in `state` |
| 429 waits `retry-after-ms`; 400 is not retried | retry on 400 |
| Jev never makes a label conforming | map `wire_number` straight to conforming on a 5-digit label |
| flag off yields HEAD's tokens | route through Jev with the flag off |
| below threshold: kept and flagged | drop it |
| the label comparison refuses an empty match (exit 2) | an empty label file |
| later, sheet role: a human-set role is never replaced (needs a source map like `sheet_sources`) | let Jev overwrite a saved role |

## Cost, with the arithmetic

Assumed, unmeasured: 1,500-4,000 input tokens per request (myNameJev's
3,600-4,300 with 14 long descriptions bounds it) and 100-300 labels per page.

- Primary, one request per label: 100 x 1,500 = 150,000 tokens = $0.0063 a
  page; 300 x 4,000 = 1,200,000 = $0.050. A 41-page set, all scanned: $0.26 to
  $2.07 in 4,100 to 12,300 requests, 51 to 154 s at 80 req/s. Packing a tile
  into one request is capped by 64k (about 40 questions at 1,500 tokens) and a
  larger state costs accuracy (jaggedness 5).
- Tuning: 500 labels x 4,000 x 10 replays = 20M tokens = $0.84; noise floor
  2 x 500 x 4,000 = 4M = $0.17.
- Sheet role, later: 41 x 1,300-2,800 = 53,300-114,800 tokens = $0.0022 to
  $0.0048 a set.

## Traps

- `set_sheet_role` (`document.py:311-319`) has no caller in `app/`, only
  `tests/test_sheets.py:201,213-214`, yet `docs/Design Rule Check.md:208` says
  roles are editable. Check before leaning on an override.
- `.gitignore` covers no recordings directory; keep recordings outside.

## Not verified, and questions only the owner can answer

Not verified: any Jev answer on Redline data; whether text plus neighbors
separates wire numbers from terminals and part numbers; labels per scanned page;
whether `urllib` in the frozen Windows build verifies TLS; the missing role
editor (a grep, not a run of the app).

1. May label text and title-block text from real drawings go to TypeSafe, and
   under which plan?
2. The key from `TYPESAFE_API_KEY` only, or also a Settings field stored like
   the Claude key in QSettings (`config.py:95`, `docs/AI Assist.md:15-17`)?
3. How often is a scanned set reviewed with AI assist on? If rarely, should
   sheet role go first?
4. Should Jev ever judge text-layer tokens, where no model runs today?

## Where this came from

- myNameJev's handoff, whose format this follows:
  https://github.com/MoogMan1073/myNameJev/blob/main/docs/HANDOFF.md
- Pathforward's register,
  https://github.com/DSI-codebase/Pathforward/blob/main/docs/jev/CANDIDATES.md,
  and the `/tuning-jev` skill (Pathforward PR #7); neither merged on 2026-10-03.
