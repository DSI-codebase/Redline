---
tags: [wire, reference]
---

# Wire Encoding

A wire label is a self-describing numeric string:

```
[ S S S ][ R R ][ W ]
  sheet    rung   wire-index-on-rung (0-based)
```

Default field widths are **sheet = 3, rung = 2, wire = 1** (6 digits total),
all configurable in [[Settings]].

## Worked example

The **second** wire on **rung 14** of **sheet 432** → `432141`
(the index is 0-based, so the **first** wire is `432140`).

This matches real drawing legends, e.g. *"261201 = 1st additional wire,
261202 = 2nd additional wire"* → wire index `0` is the base wire, `1` the first
additional, and so on.

## Sheet number

The sheet always comes from the label's own first digits — never from the PDF
page order (a single page can carry wires from several sheets). Optionally,
DSI Redline can cross-check against a title-block sheet number and **flag**
mismatches without discarding them (enable in [[Settings]]).

Used by [[Wire Numbers]] and [[Wire Export]].

#wire #reference
