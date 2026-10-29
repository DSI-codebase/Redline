---
tags: [calculators, drc]
---

# Calculators

The **Calculators** tab works out the electrical figures a review keeps
needing: voltage drop, wire and conduit sizes, motor currents, a panel's load
schedule, its short-circuit current rating (SCCR), the heat its enclosure must
shed, power conversions and a few estimating figures. Every calculation is the design rule
library's (PyDRC), the same arithmetic the [[Design Rule Check]] runs, so a
number here and a finding there come from one table.

## Using it

1. Open the **Calculators** tab.
2. Pick a calculator in the list on the left. They are grouped on seven pages:
   **Conductors**, **Voltage drop**, **Raceway**, **Motors**, **Panel**,
   **Power** and **Estimating**.
3. Fill in the fields. A field's unit is in its label, and a grey hint says
   what goes in it.
4. Press **Calculate**, or Enter in a field.
5. Press **Copy** to put the inputs and the whole result on the clipboard as
   plain text, ready to paste into a comment, an email or a quote.

What you type is kept while the app is open, so moving between calculators
loses nothing. Every field starts empty the next time the app starts, so a
figure from the last job cannot slip into this one. **Clear** empties the
calculator you are on.

## Calculators that take a list

Five calculators take a list: conduit fill (the conductors), cable pulling
tension (the run's segments, from the pulling end), the panel load schedule
(the loads), the panel SCCR (the power circuit components) and enclosure heat
(the parts that give off heat). Each holds its list in a table, one row per
item.

1. Type into a cell, or pick from its drop-down.
2. Press **Add row** for another item.
3. To take an item out, select its row and press **Remove row**. With no row
   selected, the last row goes.

A row left empty is not an entry, so a spare row at the bottom changes nothing.
A cell that holds something other than a number where a number belongs is named
by its row, for example *load 1, volts: 'four-eighty' is not a number*, and
nothing is calculated until it is put right.

A yes or no left blank is asked for, except where the library states the
answer. A load runs with the others, a supply device is not listed for 100%
operation, a component is in the power circuit, a part's watts are not checked
against a datasheet, and a part's quantity is one. Each column's hint says
which.

The three calculators on the **Panel** page each run several of the library's
calculations on one form and show every result under its own heading. The panel
SCCR, for example, shows **Panel SCCR**, **Against the target** and one
**Circuit** heading per power circuit. **Copy** takes every heading, with each
table row listed under the inputs.

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
