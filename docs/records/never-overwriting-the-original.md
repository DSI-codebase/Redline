# The original file WAS overwritten, and two dead gates preceded the live ones

Carved out of `CLAUDE.md` on 2026-09-22. A closed defect narrative is a
**record**, not an instruction: it keeps its measurements and its dates, and
nothing here is loaded on every turn. The standing rule it produced stays in
`CLAUDE.md`.

### ...and until 1.5.2 it was a sentence, not a rule

The boundary was stated in five documents and enforced nowhere. `save()`'s own
docstring said *"The original PDF is never overwritten"* directly above the line
that did it: `export_annotated_pdf` forwarded a save dialog's path straight into
`save(marked_path=...)`, and every write in the app took its destination on
trust. Measured, not argued:

| aimed at | result |
|---|---|
| `export_annotated_pdf(the open drawing)` | replaced, **no `.marked.pdf` written at all** |
| ...and every save after that | wrote **two** copies of every mark, for ever |
| `export_annotated_pdf(a neighbouring drawing)` | 3 pages → 1, replaced by the acting document |
| `export_flattened_pdf(a neighbouring drawing)` | same, and **unrecoverable** — baked into page content |
| `extract_pages(src, src, merge=True)` | 4 pages → 1 |
| `split_ranges(src, src, merge=True)` | 5 pages → 2 |
| `combine_pdfs([src, other], src)` | 4 pages → 6 |
| `rotate_pdf(a, an unrelated drawing)` | 4 pages → a 3-page rotated copy of `a` |

**PyMuPDF refuses some of this itself** — `save to original must be
incremental` — and the two things that get past it are worth knowing, because
they are what made a stated boundary a false one:

* **The library's check only sees a save from the document that opened the
  file.** Every page tool builds a *new* `fitz.Document` from the pages it read,
  so the check never fires and the write lands.
* **`save()`'s own atomicity machinery defeats it.** The `out_is_open`
  temp-and-`os.replace` branch exists so an open `.marked.pdf` can be re-saved
  on Windows; aimed at the original it turns a refusal the library would have
  issued into a successful destruction. The safety net was there and the app
  routed around it.

**The doubling is the part a user could not undo.** Once the original carries a
mark, `original_pdf_path` still resolves to it and `is_marked_pdf` says False,
so the `strip_annotations` branch that exists to stop re-saving doubling the
marks is unreachable — and the `.marked.pdf` carries every mark twice from then
on, whatever you do.

**What is enforced now, and where.** One guard, in `app/model/storage.py` beside
the path helpers, called from every write:

1. `refuse_protected(out, doc_path)` — never write **this document's original**.
   Refused even when that file is absent, because writing it would *create* the
   pristine base every later open reads from.
2. the same rule for **another drawing that holds marks here** — a reviewer works
   on a folder, and a save dialog opened in it puts every drawing one click away.
3. `refuse_overwriting_input(out, *inputs)` — a page tool may not eat its own
   input.

`app/tools/pdf_ops.py` routes all eleven of its writers through one `_guard_out`,
and `tests/test_never_overwrite_original.py` walks the module's AST and fails on
a writer that has none — a gate over the artifact rather than over a list of the
functions that existed when it was written.

**Two things the rules deliberately do NOT do**, because measuring said so:

* **Rule 2 asks whether the sidecar holds ANNOTATIONS, not whether it exists.**
  Opening a PDF creates its `.markup.db` unconditionally, so "a sidecar is
  present" means "seen here" and nothing more. The existence test refused an
  ordinary second export and broke two of this repo's own regression tests,
  which fork onto a name whose sidecar was pre-seeded with wires and waivers.
* **A PDF this app has never opened is not protected.** It is indistinguishable
  from a stale export, and the save dialog has already asked about replacing it.
  Redline protects what it can identify; saying which is the point.

### Two dead gates were written before the live ones

Both passed on the exact defect they were written for, and both were found by
injecting it rather than by reading them:

* the AST sweep counted only `.save(`, so `pdf_to_docx` — which writes through
  pdf2docx's `convert()` — was **not counted as a writer at all**, and removing
  its guard changed nothing. It now takes a set of write calls and asserts the
  scan is still *finding* at least ten writers, so a rename cannot make it match
  nothing and go green.
* the `same_path` test used a **symlink**, which `os.path.realpath` resolves —
  so the fallback answered it alone and deleting the `os.path.samefile` branch
  kept the test green. A **hard link** has two real names `realpath` does not
  collapse, and the fixture asserts that before it asserts anything else.

And the falsification loop itself was dead first: `2>/dev/null` on a
`python -m unittest` run discards the results, so eight injections in a row
reported *nothing fired*. **If a falsification says the gate did not fire,
suspect the reading before the gate.**
