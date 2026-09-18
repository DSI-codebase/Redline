---
tags: [audit, drc, extraction]
---

# Design Rule Check

The **Audit** tab checks a drawing set against its own conventions and lists
what to confirm: tags whose number disagrees with the sheet they sit on, wire
numbers that reference a sheet they never appear on, sections the drawing index
promises but the set does not contain, and family codes nobody has registered.

Run it with **Tools ▸ Run design rule check…** (or `F7`, or the **Run check**
button on the Audit tab).

> **It is a review, not a verdict.** Findings say *confirm this*, with the
> convention or clause they rest on. The authority having jurisdiction and the
> listing agency decide compliance — this tool never does.

## Reading the results

The line above the list is the important one:

    451 of 506 checked — 55 not checked (55 missing catalog).

**A skipped item is not a passing item.** A plotted drawing simply does not
carry some of what a rule needs, and the header says so rather than letting an
empty list look like a clean drawing. Findings come in three levels:

| Level | Means |
|---|---|
| **Definite violation** | The rule was broken and the evidence is unambiguous |
| **Potential issue** | Worth your eye; the tool may be missing context |
| **Informational** | An observation, usually a setting to adjust |

Double-click a finding to jump to it on the drawing. Each one is outlined on
the sheet, **underneath** your own markup — an audit mark can never cover
something you drew, and the eraser will not touch it.

## One finding, several places

Panels are drawn from templates, so one mistake usually appears everywhere the
template was pasted. The rule library reports that as **one finding naming
every place**, rather than as eighteen identical rows: it is one decision, and
one waiver.

The Sheet column shows how far it reaches — `232 +8` means the finding also
stands on eight other sheets. Group the list **by sheet** and it appears under
every one of them, so working sheet by sheet still meets it; double-clicking a
row lands on *that* row's sheet, not on the first. Every place is outlined on
its own sheet, and the exported report names them all.

This matters more than it sounds. On a real 41-sheet set the check reports 92
findings covering 379 distinct places — so a list that showed only the first
place of each would leave five sixths of the work invisible, on sixteen sheets
that would look clean.

## Cross-references between sheets

A signal leaving one sheet is marked with a connector — `to 70004`, `from
30014`, sometimes `to 70004 PG.700`. The number is a sheet-and-line reference:
`70004` is sheet 700, line 04. These come in pairs, and the pairing is what
gets checked: if sheet 300 line 14 goes **to** sheet 700 line 04, then sheet 700
line 04 should come **from** sheet 300 line 14.

Two things are reported. A connector pointing at a sheet or line that is not in
the set is the more definite of the two — it compares printed text against the
sheets you have, with nothing inferred. A connector whose counterpart is missing
or names a different line is worth confirming: the line a connector sits on is
read from the line-number gutter down the side of the sheet, and different
connector symbols place their text either side of it, so the check allows one
line of slack before it says anything.

Only ladder sheets take part. A network topology or panel layout references
other sheets by different conventions, and expecting a connector back from one
would report correct drafting as an error.

## Importing the source drawings

**Tools ▸ Import project drawings…** points at the AutoCAD Electrical project
folder. Drawings that already have a DXF beside them are read directly; DWGs
are converted through the **ODA File Converter** if it is installed (a free
download — set its location under [[Settings]] ▸ Design rules, or let the app
find it). Conversions land in a cache folder, never beside your drawings.

The import reads what the plot cannot carry: component ratings, catalog and
manufacturer assignments, the declared wire layers — whose names carry each
conductor's gauge — the ladder definitions, and the wire connectivity itself,
derived the same way AutoCAD Electrical derives it. The audit then re-runs with
both views merged, and electrical rules light up wherever the source data
supports them: a fuse rated above what its conductor allows is reported with
the clause and the arithmetic.

The import also checks the source against itself. Stale terminal attributes
that reference wire numbers no drawing contains, signal arrows with no
cross-reference filled in, protective devices with no part assigned, and tags
drawn as plain text where an intelligent symbol belongs — each becomes a
finding a drafter can act on, which is how the source data gets better over
time.

> [!warning] When the stored import can't be read
> The imported drawings are kept in the markup database. If that copy is
> damaged and won't load, the check still runs — on the PDF alone — and says
> so at the top of the panel and of every exported report: *"The imported
> source drawings could not be read, so this check ran on the PDF alone."*
> Every rule that needs the source is then listed as having had nothing to
> check against. Re-import the drawings and run the check again to get those
> rules back.
>
> The findings you do get are real; they are the same ones you would get
> having never imported anything. What you are missing is the electrical half
> — so read the notice before treating the result as the whole picture.

## What the title block claims

A title block states its own sheet number and the number of the sheet after it.
Both are claims, and both are checked against the set: a sheet whose title block
disagrees with its drawing number, or whose **next** pointer steps over the sheet
that actually follows, usually means a title block was copied from a neighbour
and only half updated.

## Waiving a finding

Every real panel has justified exceptions. Right-click a finding ▸ **Waive…**,
give a reason and your name, and it stays on the list struck through, so the
decision stays visible to the next reviewer.

Waivers are stored per project and **survive re-running the check**. They are
keyed to the finding itself rather than to where it sits, so re-extracting the
drawing or nudging a tag in a revision does not lose them.

A waiver covers **every place** the finding names, and the dialog lists the
sheets so you are answering the question you are actually being asked. It is
also keyed to the *set* of symbols involved, not to how many there are: if a
later revision swaps one of them for another, the finding reopens rather than
quietly extending your decision to something nobody looked at.

## Where a finding is drawn

A finding is outlined around the text it is about, found by looking its subject
up among the page's printed words. Some subjects are not printed anywhere — a
cross-reference arrow is identified by its sheet and rung, which is a label the
report uses, not something drawn on the drawing.

When the subject cannot be found on the page, the finding is filed against its
sheet with no outline, and the row still names the sheet and rung. That is
deliberate: a box in the wrong place is worse than no box, because it looks
just as authoritative.

This matters most with source drawings imported. A drawing's own coordinates
measure the drawing, not the page, and the two are indistinguishable as bare
numbers — so a coordinate that did not come from the page is discarded rather
than trusted.

### Which page a finding opens on

A finding always names its sheet, and that is what decides the page it opens
on. Some kinds of finding — a protective device, a terminal, an index entry —
carry no page of their own, and for those the sheet is the only answer there
is.

Where a plot binds the same sheet number twice, the first one wins, matching
how the rest of the extraction dedupes.

### Turning a rule off

Turning a rule off hides its findings rather than deleting them, so turning it
back on restores them without another run — and *hidden* means everywhere: the
list, the boxes on the drawing, and all three exported reports.

The report still says which rules were turned off. Dropping the rows silently
would make "this rule found nothing" and "you switched this rule off" the same
sentence, and they are not the same fact. The coverage table still lists a rule
that ran before you turned it off, which is the honest record of what was
examined.

### Changing a rule's severity

Severity is a setting, not a property of the finding, so changing it applies to
the findings already on screen without re-running the check — and **withdrawing
it puts them back**. Set a rule to informational, decide against it, and the
findings return to whatever the rule itself declares.

The one case where nothing is restored is a finding whose rule is no longer
loaded. There is no declared severity to go back to, so it keeps what it has
rather than being given a guessed one.

## A rule that ran against nothing

The coverage header separates three states, not two. A rule can have **checked
everything**, **skipped some of it with a reason**, or **had nothing to check
against at all** — and the third is the one worth watching for, because it
looks like the first.

It happens when the model is missing a whole kind of thing the rule applies to.
Import a drawing set without its source DWGs and the motor rules have no motor
circuits to read, so they skip nothing and report nothing. That is not a clean
bill; it is four rules that never ran.

The header says so — "788 of 788 checked — 2 rules had nothing to check
against" — and every exported report names them.

## What the rules need

Some rules depend on data a plot does not contain — a device's catalog number,
a conductor's size. Those report as *not checked* rather than as clean, and the
coverage table in the exported report names them one by one.

Two pieces of per-sheet information do most of the work, and both are editable:

- **Sheet number** — read from the drawing number in the title block. Where the
  drawing does not say, the Sheet column stays blank and location rules skip
  that page rather than guess.
- **Sheet role** — whether a page is a schematic, a PLC I/O sheet, a panel
  layout, a terminal-block detail, and so on. This matters more than it sounds:
  a panel layout labels every device with the schematic sheet it comes from, so
  *every* tag on it is legitimately "off-sheet". Location rules only apply where
  the comparison means something.

## Settings

**[[Settings]] ▸ Design rules** lists every rule, with a checkbox to turn one
off and a severity you can override. Changes apply to the findings already on
screen — no need to run the check again to see the effect.

## Which rules produced a report

Every exported report names the rule pack and its version — *Rule packs:
drc-base@1.32.0* — at the foot of the HTML, beside the coverage line in
Markdown, and as a row in CSV. The version moves with every rule change, so
two reports that disagree about a finding can be told apart: if one says
`1.29.0` and the other `1.32.0`, the rules changed between them.

Worth checking after you update the rule library, because a `pip` install of
a git-pinned package will happily report success without fetching anything
new.

## Exporting

**Export report…** writes HTML, Markdown or CSV. All three carry the findings,
the clause each rests on, the evidence behind it, and the coverage statement.

## Related

- [[Component Labels]] — the tags the audit checks
- [[Wire Numbers]] — the conductors the audit checks
- [[Settings]] — rule selection and severities
- [[Storage and Files]] — where findings and waivers are kept

#audit
