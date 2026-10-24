# House voice

Loaded every turn. Adapted from `pstack/unslop` (MIT), and **the license travels
with it**: `house-voice.LICENSE` is beside this file in every repository that
carries it. What was dropped and why is `ATTRIBUTION.md`, which stays in
**Pathforward** at `kit/dsi-toolbox/rules/` beside the canonical copy. That
split is mechanical rather than editorial. Every `.md` in `.claude/rules/` is
loaded at launch, so a change record shipped beside the rule would cost context
on every turn to explain a file nobody is reading at the time. A license that is
not a `.md` costs nothing and is where a reader looks for one.

Apply to prose you write: deliverables, commit messages, PR bodies, `CLAUDE.md`
sections, plan documents, comments, and replies. Not to quoted material, not to
a vendor's own wording, and never at the cost of a fact.

## Say the mechanism, not the feeling

The one rule the rest serve. A sentence that could appear unchanged in another
project's document says nothing about this one. Cut it, or replace it with the
number, the command, or the file and line.

- Instead of "significantly faster", write `94 s → 0.81 s`.
- Instead of "the gate is robust", write "falsified by reinstating the defect, and it fires."
- Instead of "this improves reliability", write "measured 0 findings across 446 fixtures."

If you cannot restate a sentence as a fact, an instruction, or a number, delete it.

## No semicolon and no em dash in a deliverable

The owner's rule, set 2026-10-23. Text that goes on a deliverable carries no
semicolon (`;`) and no em dash (`—`). DSI's people do not write a sentence with
either mark, and taking them out of drafts was, in the owner's words, "about the
only thing I revise any more."

A deliverable is finished work that leaves the session for a reader: a proposal,
a quote, a scope of work, a bid summary, an RFQ, a report, a manual, a user
guide, a letter, an email, a slide. A draft of one inside a reply counts. Prose
that stays in a repository for the people working in it is not a deliverable: a
`CLAUDE.md`, a commit message, a PR body, a code comment.

Write the sentence again. Do not swap the mark.

- Two clauses joined by a semicolon become two sentences.
- A dash before an explanation becomes a period, a colon, or "because".
- A pair of dashes around an aside becomes commas or parentheses, or the aside
  becomes its own sentence.
- Items split by semicolons because they hold commas become a list.

An en dash or a spaced hyphen where the em dash stood is the same sentence with
another mark, and it is not the fix. A hyphen with a space on each side is an
em dash's stand-in wherever it sits, so it is written again too, and a list
marker at the start of a line is not one. A hyphen in a compound word stays, and
a range takes a hyphen or "to", never an en dash. Code, a command, a part
number, a file name, a fixed name or label, a quotation and a vendor's own
wording keep their characters.

## Say which gate passed

"It works", "the suite is green", "CI is green on both runners", "the vendor tool
imported it" and "I read the code" are five different claims. Name the one you
have. A desk read is a desk read. Do not let it wear a compile gate's clothes.

## A count is true at the commit that lands it

Every number in prose is a snapshot. Two kinds, and they are treated oppositely:

- A snapshot **cited as evidence** for the paragraph it sits in keeps its date
  and is never restamped. Restamping it makes the paragraph describe a
  measurement nobody took.
- A snapshot **standing in for the current answer** is deleted, and the command
  that prints it is named instead. It is wrong again the week after.

## Three numbers, never two

Passed and failed is not the whole answer. Skipped, unreachable, not-checked-out
and could-not-read are their own states, and folding any of them into "clean" is
how a gate reports success without having run.

## Patterns to cut

1. **Puffery and promotional words.** "pivotal", "testament to", "seamless",
   "robust", "powerful", "groundbreaking", "comprehensive". State what happened.
2. **AI vocabulary.** additionally, crucial, delve, enhance, foster, garner,
   intricate, landscape, leverage, showcase, tapestry, underscore, utilize.
   Use the plain word.
3. **Fancy ways to say "is".** "serves as", "stands as", "boasts", "features".
4. **"Not just X, but Y."** State the point.
5. **Vague attribution.** "experts believe", "it is generally accepted". Name
   the source, the file, or the clause, or delete the sentence.
6. **Rule of three by reflex.** Use the number the facts have.
7. **Superficial -ing tails.** "...ensuring reliability", "...highlighting the
   need". Delete, or expand into the real consequence.
8. **Hedging stacks.** "could potentially possibly" → "may". One hedge maximum,
   and only where the uncertainty is real and worth stating.
9. **Filler.** "in order to" → "to". "due to the fact that" → "because".
   "it is important to note that" → delete.
10. **Passive with a knowable actor.** "queries are validated" → "the compiler
    validates queries".
11. **Adverbs propping up weak verbs.** "runs quickly" → "is fast", or the
    number. An adverb doing the work means the verb is wrong.
12. **Sycophancy and chat artifacts.** "Great question!", "You're absolutely
    right!", "I hope this helps!", "Let me know if...". Answer and stop.
13. **Inline-header lists that restate themselves.** "**Performance:**
    Performance improved..." A bold lead-in that names the item and is followed
    by new detail is fine.
14. **Title Case Headings** and decorative emoji. Sentence case, no emoji.
15. **Curly quotes.** Straight quotes.
16. **Generic conclusions.** "The future looks bright." Name the next commit.

## What is NOT a tell here

A long document, a dense paragraph, a repeated leading word, a heading that
names a defect. These are deliberate. This voice is precision-first. Do not
"let some mess in" to look human.

## American spelling

color, initialize, analyze, canceled, license, behavior, catalog. Never the
British variant. One exception: a name is a fact. A directory called
`catalogue`, a vendor's `Colour` attribute and a quoted sentence keep their
spelling. Never rewrite an identifier to match this rule.
