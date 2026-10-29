---
tags: [calculators, drc]
---

# Calculators

The **Calculators** tab works out the electrical figures a review keeps
needing: voltage drop, wire and conduit sizes, motor currents, power
conversions and a few estimating figures. Every calculation is the design rule
library's (PyDRC), the same arithmetic the [[Design Rule Check]] runs, so a
number here and a finding there come from one table.

## Using it

1. Open the **Calculators** tab.
2. Pick a calculator in the list on the left. They are grouped on six pages:
   **Conductors**, **Voltage drop**, **Raceway**, **Motors**, **Power** and
   **Estimating**.
3. Fill in the fields. A field's unit is in its label, and a grey hint says
   what goes in it.
4. Press **Calculate**, or Enter in a field.
5. Press **Copy** to put the inputs and the whole result on the clipboard as
   plain text, ready to paste into a comment, an email or a quote.

What you type is kept while the app is open, so moving between calculators
loses nothing. Every field starts empty the next time the app starts, so a
figure from the last job cannot slip into this one. **Clear** empties the
calculator you are on.

## Reading a result

The first line says what kind of answer it is:

| Kind | Means |
|---|---|
| **code** | It cites a clause and a table of a published code |
| **method** | It follows a named engineering method, not a code table |
| **estimate** | A placeholder or an approximation. It never feeds a design rule finding |

Then come the figures, the arithmetic that produced them step by step, the
clauses they rest on, and one line for every table the calculation read.

> **A table nobody has signed says so.** The code tables carry NEC 2023 values
> until an engineer of record confirms them against NEC 2026, and every result
> that read one says that under **TABLES**. The result is advisory either way.
> Confirm it against the code book and the product listing. It is not a
> determination of compliance.

## When a field is empty

**An empty field is never filled in for you.** If the calculator needs it, the
result says so in place of an answer, for example *missing power factor*.

A few inputs have a stated default in the library: copper as the material, one
set of conductors in parallel, a breaker as the device. Left empty, those take
the default, and the result's arithmetic names it.

## When the tab is unavailable

The calculators need the design rule library. Without it the tab says the
calculators are unavailable and shows the command that installs the library,
the same as the Audit tab. The rest of the app is unaffected.

#calculators
