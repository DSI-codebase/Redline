---
name: knowledge-index
description: >-
  Search the cross-repo knowledge index for past findings, pitfalls, fixes and
  abandoned approaches before designing or debugging something. Use when starting
  non-trivial work, when an error looks familiar, when choosing between
  approaches, or when the user asks whether something has been tried before.
---

# Cross-repo knowledge index

A searchable index of findings from every repository the user works on: pitfalls
already hit, fixes that worked, decisions and their reasoning, and approaches that
were tried and abandoned.

Index location: wherever Alvis is checked out on this machine. **Ask the tool
rather than assuming a path** — the directory carries whichever name it was
cloned under, and GitHub's redirect covers `git clone` and not a directory
somebody already has:

```
kb doctor
```

which prints the resolved index root, or `$KB_CONFIG` / `kb.config.local.toml`
if this machine names one.

## When to search it

Search **before** proposing a design or a fix, not after:

- Starting non-trivial work in an unfamiliar area
- An error message or symptom that feels familiar
- Choosing between two approaches
- The user asks "have we done this before?" or "didn't this break last time?"
- Before recommending a library, tool or pattern the user may have already rejected

Do **not** search for trivia, or for questions about the current file's contents.
A search costs a second; a search for something the index cannot know wastes the
turn.

## How to search

```
kb search <terms>                  # terms are ANDed, English-stemmed
kb search "exact phrase"           # quoted, not stemmed
kb search kind:pitfall topic:git   # structured filters
kb search outcome:failed <terms>   # dead ends only
kb search -outcome:failed <terms>  # exclude dead ends
kb search repo:<name> <terms>      # one repository
kb search --json <terms>           # structured output
```

Filters: `repo:` `kind:` `outcome:` `topic:` `corpus:`. Prefix with `-` to
exclude. `kind` is one of pitfall, resolution, pattern, decision, reference.
`outcome` is one of worked, failed, abandoned, unverified.

Exit code 1 means no matches. That is an ordinary answer -- report it plainly and
carry on; it does not mean the search failed.

Start broad and narrow. Terms are ANDed, so a five-word query usually returns
nothing; two or three words is the right first attempt.

## How to read a result

Every hit carries an outcome and an age, and **both change what it means**:

| Field | What it changes |
|---|---|
| `outcome: worked` | Confirmed fix. Safe to build on. |
| `outcome: failed` | A recorded dead end. Often the most valuable hit -- do not repeat it. |
| `outcome: abandoned` | Dropped before it was settled. Weak evidence either way. |
| `outcome: unverified` | The source never confirmed it. Treat as a lead, not an answer. |
| age | The source's last commit. A three-year-old fix for a library since rewritten may be actively wrong. |
| `also recorded in:` | The same claim came from several repos -- a trap hit repeatedly. |

Two sections come back. **Records** are distilled findings. **Documents** are raw
source material, including bulk-imported vendor reference. Document hits with no
record hits mean nobody has written this up yet -- the raw material exists but the
finding does not.

## Reporting what you find

Cite the source path so the user can read the original, and state the outcome and
age when either affects the advice. An index result is evidence, not authority:
if it contradicts what you can see in the current code, the current code wins and
the index is out of date.

Never present an `unverified` or `failed` record as an established fix.

## Fallback

If `kb` is not on PATH, the catalog is line-oriented JSON:

```
grep -i '<term>' <index root>/index/catalog.jsonl
```

`<index root>` is the Alvis checkout this page opens by naming -- the directory
holding `index/catalog.jsonl`. Do **not** go back to `kb doctor` for it: this
section is reached precisely when that command is absent, and a fallback whose
own instruction needs the thing it is a fallback for is no fallback.

That is why it is text rather than a database.
