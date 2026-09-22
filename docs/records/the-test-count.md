# The test count that used to sit in `CLAUDE.md`

Carved out of `CLAUDE.md` on 2026-09-22. A closed defect narrative is a
**record**, not an instruction: it keeps its measurements and its dates, and
nothing here is loaded on every turn. The standing rule it produced stays in
`CLAUDE.md`.

### The count that used to sit here, and why it does not any more

Both of these documents said *"CI's last green run on `main` reports **682
tests across 53 modules; 0 skipped**"*. When somebody next ran it the answer
was **720 across 56**, and this file had by then accumulated **three
different numbers** — 682/53 in the header, 713/55 and 716/56 in two
narratives further down. A reader comparing their own run against the header
cannot tell which to believe.

The sentence merged two claims with opposite properties, which is what let it
rot unnoticed:

| permanent | volatile |
|---|---|
| CI skips nothing, because `--strict` / `--require-drc` turn a skip into a failure | how many tests there are |
| a local run without Qt reports far fewer, and says so | what that number is today |

The permanent half is gated and stays. The volatile half is **removed rather
than restamped** — a number merely updated is wrong again the week after, and
nothing reads it in between. `tools/run_tests.py` prints the current answer,
with the skips grouped by reason.

The two narrative counts below (713/55, 716/56) stay: each is a dated
before/after measurement that is the evidence for the paragraph it sits in,
not a claim about the suite today. That distinction is the whole rule —
**a snapshot cited as evidence keeps its date; a snapshot standing in for the
current answer gets deleted.**
