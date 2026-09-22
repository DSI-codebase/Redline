# Seven modules errored rather than skipping, and the gate for it failed on Windows

Carved out of `CLAUDE.md` on 2026-09-22. A closed defect narrative is a
**record**, not an instruction: it keeps its measurements and its dates, and
nothing here is loaded on every turn. The standing rule it produced stays in
`CLAUDE.md`.

## ...and seven modules ERRORED rather than skipping, which is the same failure louder

`CONTRIBUTING.md` calls a machine without Qt "not a failure" and the section
above is about skips being invisible. Seven modules did neither: they **errored**
— which is loud, and loud about the wrong thing. `No module named 'PySide6'` on
a checkout where nobody has installed the requirements reads as a broken repo,
and it makes a legitimately-degrading run look like a failing one. Same class as
`TestRolledUpFindingOnScreen`, and the same class this repo fixed in PyDRC for
`ezdxf` one repo over — *fixing a class of bug only where it was noticed.*

**The guard they were missing is not the one they had.** Three of the seven
already carried `try: from PySide6... except: _QT_OK = False` and still died,
because what they import at module scope is `app.config` or `app.help`, and Qt
arrives **through those**. A probe of the direct import cannot see a transitive
one. Two shapes, one cause:

| module | died at | through |
|---|---|---|
| `test_help` | module scope | `app/help.py:16` |
| `test_v12_recent`, `test_v14_search` | module scope | `app/config.py:14` |
| `test_cli_open` | inside the test | `main.py:9` |
| `test_crop_tags`, `test_region_export` | inside the test | `app/tools/wizards.py:11` |
| `test_v12_author` | inside the test | `app/viewer/command_stack.py:13` |

- **A decorator cannot save a module that never loads**, so the three
  module-scope cases needed their `app.*` import guarded as well. The other four
  load fine and only needed the decorator.
- **`tests/_qt.py` is one probe, not a twenty-ninth copy**, and it probes the
  thing rather than a proxy: whether `PySide6` imports at all. `except
  Exception`, not `except ImportError`, because the documented Linux failure is
  `libEGL.so.1` raised from inside the extension module.
- **A test that is semantically Qt-free can still need Qt to run.**
  `TestRecentConfig` says *"the stored list itself (no GUI)"* and builds
  `AppConfig`, which is `QSettings`. Skipping it is honest; erroring was not.
  Making `app.config` Qt-free is a product change and is deliberately not done
  here.

**Verified in BOTH directions, which is the only way to tell a fix from a
withdrawal.** A skip added where a test used to run is coverage lost, and it
looks identical to a fix in the without-Qt direction alone. So PySide6 was
installed and the suite measured before and after: **713 tests across 55
modules, 28 skipped, identical per-module results and identical skip reasons** —
the change is inert when Qt is present, by construction (`skipUnless(True)` is a
no-op and every new import guard is `if _QT_OK:`).

The first attempt was **not** inert: a scripted rewrite half-applied to
`test_v12_author`, adding the decorator without the import it referenced, and
the module died with `NameError`. 713 → **707**, and those 6 lost tests are that
one module exactly. Caught by comparing against the baseline rather than by
reading the diff — the third mechanical-rewrite defect this family has had, after
Canal's two.

`tests/test_qt_absent_degrades.py` is the gate, and it **sweeps the artifact**:
every `tests/test_*.py`, loaded and run with `PySide6` blocked, asserting zero
errors. A gate naming those seven covers what was broken the day it was written;
the eighth module to reach Qt through a new `app.*` import fails here instead.
6.4 s. Falsified nine ways — each of the seven guards stripped in turn (each
caught, each naming its own module), plus the blocker neutered, plus a
module-count floor so a sweep that finds nothing cannot read as a pass.

### ...and the gate itself was the only thing that failed on Windows

The fix landed green on all three Ubuntu legs and red on all three Windows ones.
The suite reported **716 tests across 56 modules, 16 skipped**, with every one of
the seven repaired modules reporting `ok` — and `FAILED MODULES:
tests.test_qt_absent_degrades`. The repair worked on Windows; the gate written to
prove it did not.

- **`/dev/null` does not exist on Windows.** The sweep gave its runner
  `stream=open("/dev/null", "w")`, which there resolves to a directory that is
  not present, so the subprocess died and the module failed. A latent platform
  failure of exactly the shape this file already records for a leaked PyMuPDF
  handle: **green locally, red only on `windows-latest`**, and unreachable from
  the local suite. `io.StringIO()` needs no filesystem at all.
- **The message written to explain a dead sweep explained nothing.** Its f-string
  carried `{{r.stderr[-3000:]}}` — doubled braces, correct inside the *generated
  subprocess source* one line above and wrong in the test's own f-string — so it
  printed that text literally instead of the traceback. The CI log therefore
  named no cause at all, which is why the fix had to be reproduced locally
  before it could be diagnosed.

`tests/test_suite_is_discoverable.py` gained the sweep, since this repo runs
Windows in CI and a POSIX device path in `tests/` is a Windows-only failure by
construction. **Two things stop it firing on itself, and neither is an
exemption** — its first draft flagged its own needle table and its own
docstring, which is the shape this repo keeps paying for, and the standing
answer is to tighten the check rather than waive the text explaining it:

- the needles are **assembled** (`"/" + "dev"`) rather than written, so the file
  contains no literal matching what it searches for;
- **a docstring is not code.** Bare string expressions are excluded
  structurally, which is a general statement about what counts rather than a
  carve-out for one module.

Both directions are asserted in the module itself — a docstring mentioning the
path is not a finding, a path passed to a call is. Falsified three ways: the
POSIX path restored (caught), Windows simulated by pointing at an absent
directory (the message fires *and now carries a real traceback*), and the
docstring exclusion removed (the gate fires on prose, proving the exclusion is
load-bearing).
