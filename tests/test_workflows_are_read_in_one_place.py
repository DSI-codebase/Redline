"""`tests/_workflow.py` is the one reader of the GitHub workflows in tests/.

That module's first line claims it, and until this module nothing held it. On
2026-11-01, with `tests/test_frozen_build.py::_steps` reading
`build-windows.yml` by hand again, that module still passed.

Every `tests/*.py` but `tests/_workflow.py` is parsed with `ast`, never searched
as text, because docstrings and comments name the workflows too, this one
included. A value is a workflow path when it is built from `.github` and then
`workflows`, as one string or as path parts, and the sweep follows it: through
assignments, module, class and `self.` attributes, the return value of a
function that builds one, into the parameter of a helper it is passed to,
across `from tests.x import NAME`, and across `from tests import x as R`
(`R.WORKFLOW`). Each call handed one, as an argument (`open(path)`) or as the
receiver (`BUILD.read_text()`), is judged as one of five things:

1. a top-level function of `tests/_workflow.py`, which is the reader;
2. a function defined in tests/, which is followed with that parameter as a
   workflow path;
3. a path operation (`os.path.join`, `pathlib`'s `/`, `glob.glob`, `str`),
   whose result is followed;
4. a call named in `NOT_A_READ`, which neither opens nor parses the file;
5. anything else, which is a raw read. A call the sweep does not recognize is
   counted as a read rather than passed, because a gate that waves through
   what it cannot name agrees with every reader nobody has written yet.

Two raw reads are allowed, both in `tests/test_requirements.py` and both named
in `tests/_workflow.py`'s docstring. `ALLOWED` is held in both directions: a
raw read anywhere else fails, and so does an allowance whose test was renamed
or no longer reads raw.

It sees a path it can spell. A sweep that globs the repository root and opens
whatever it finds builds no `.github` path, and only the `open` audit hook run
on 2026-11-01 measured that case.
"""

from __future__ import annotations

import ast
import builtins
import os
import re
import shutil
import tempfile
import textwrap
import unittest
import warnings

HERE = os.path.dirname(os.path.abspath(__file__))

#: The reader, by module stem. Every top-level function in it is `_workflow.*`.
READER = "_workflow"

#: The first line of `tests/_workflow.py`'s docstring, which this module holds.
CLAIM = ("Every step check in tests/ reads the GitHub workflows here, "
         "with PyYAML.")

#: The sentence that docstring retracts, quoted there since this landed.
RETRACTED = ("No test holds that, so a new hand reader would make the first "
             "line false without failing anything.")

#: The raw reads the claim's own docstring names, by file and qualname.
ALLOWED = {
    ("test_requirements.py",
     "TestTheRuleLibrarysAccountIsNotStale."
     "test_the_workflows_do_not_write_the_account_down_at_all"):
        "searches each whole file for a written-down account",
    ("test_requirements.py",
     "TestTheInterpreterClaimIsExercised."
     "test_the_frozen_build_stays_pinned_and_says_why"):
        "reads the pin's reason, which is a YAML comment the loader drops",
}

# --------------------------------------------------------------- the calls

#: Join path parts. The parts are folded, so `.github` then `workflows` is one.
PATH_JOIN = {
    "os.path.join", "posixpath.join", "ntpath.join", "pathlib.Path",
    "pathlib.PurePath", "pathlib.PosixPath", "pathlib.WindowsPath",
    "pathlib.PurePosixPath", "pathlib.PureWindowsPath",
}
#: Return what they were handed, or paths under it, and are followed.
PATH_KEEP = {
    "builtins.str", "os.fspath", "os.path.abspath", "os.path.normpath",
    "os.path.realpath", "os.path.expanduser", "os.path.dirname",
    "os.path.relpath", "os.scandir", "glob.glob", "glob.iglob",
    "builtins.sorted", "builtins.list", "builtins.tuple", "builtins.set",
    "builtins.frozenset", "builtins.reversed", "builtins.iter",
    "builtins.next", "builtins.enumerate", "builtins.zip",
}
PATH_KEEP_METHODS = {
    "resolve", "absolute", "as_posix", "expanduser", "with_name",
    "with_suffix", "with_stem", "relative_to", "glob", "rglob", "iterdir",
    "lower", "upper", "casefold", "strip", "rstrip", "lstrip", "replace",
    "split", "rsplit", "get", "pop", "copy", "values", "items",
}
PATH_KEEP_ATTRS = {"parent", "parents", "path"}
#: Handed a path, and neither open nor parse the file.
NOT_A_READ = {
    "os.path.exists", "os.path.isfile", "os.path.isdir", "os.path.basename",
    "os.path.splitext", "os.path.getsize", "os.path.getmtime", "os.stat",
    "os.listdir", "builtins.len", "builtins.print", "builtins.repr",
    "builtins.isinstance", "builtins.bool", "builtins.hash", "builtins.id",
}
NOT_A_READ_METHODS = {
    "exists", "is_file", "is_dir", "is_absolute", "stat", "samefile",
    "match", "is_relative_to", "as_uri", "endswith", "startswith", "count",
    "find", "rfind", "index",
}
#: A container these are called on holds what they were handed.
FILLS = {"append", "extend", "add", "insert", "update", "setdefault"}
#: The TestCase methods that only report, so a path in their message is not
#: a read. A method a test class defines itself is followed instead.
REPORTS = ("assert", "fail", "skipTest", "subTest")
#: Named as readers in a failure message. Anything unknown is a read anyway.
KNOWN_READERS = {
    "builtins.open", "io.open", "codecs.open", "tokenize.open", "json.load",
    "yaml.safe_load", "yaml.load", "yaml.full_load", "read_text",
    "read_bytes", "open",
}

# --------------------------------------------------------- the path states

WF, GH = "wf", "gh"   # under .github/workflows/, and .github itself
NONE = frozenset()
_WF = frozenset({WF})
_SEP = re.compile(r"[/\\]")


def _part(state: frozenset, part: str) -> frozenset:
    """The state of a path after one more literal component."""
    if part in ("", "."):
        return state
    out = set()
    if WF in state and part != "..":
        out.add(WF)
    if part == ".github":
        out.add(GH)
    if GH in state and part == "workflows":
        out.add(WF)
    return frozenset(out)


def _fold(pieces: list) -> frozenset:
    """The state of a path spelled by `pieces`, left to right.

    A piece is literal text, which separators split into components, or the
    state of a value the sweep cannot spell. A component that starts with such
    a value takes that value's state, so `f"{WORKFLOW}.bak"` is still one, and
    one that starts with text is a name under whatever came before it.
    """
    comps = [[]]
    for piece in pieces:
        if isinstance(piece, str):
            parts = _SEP.split(piece)
            comps[-1].append(parts[0])
            comps.extend([p] for p in parts[1:])
        else:
            comps[-1].append(piece)
    state = NONE
    for comp in comps:
        comp = [c for c in comp if c != ""]
        if not comp:
            continue
        if all(isinstance(c, str) for c in comp):
            state = _part(state, "".join(comp))
        elif not isinstance(comp[0], str):
            state = comp[0] | (state & _WF)
        else:
            state = state & _WF
    return state


# -------------------------------------------------------------- the sweep

_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef)
_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)


def _body_nodes(body):
    """The statements of `body`, through compound statements, not into defs."""
    for node in body:
        yield node
        if isinstance(node, _SCOPES):
            continue
        for field in ("body", "orelse", "finalbody"):
            yield from _body_nodes(getattr(node, field, None) or [])
        for handler in getattr(node, "handlers", None) or []:
            yield from _body_nodes(handler.body)
        for case in getattr(node, "cases", None) or []:
            yield from _body_nodes(case.body)


def _own(node):
    """Every node of a def, not into a def, class or lambda nested in it."""
    stack = list(ast.iter_child_nodes(node))
    while stack:
        sub = stack.pop()
        yield sub
        if not isinstance(sub, _SCOPES):
            stack.extend(ast.iter_child_nodes(sub))


def _params(fdef) -> list:
    a = fdef.args
    names = [p.arg for p in a.posonlyargs + a.args]
    if a.vararg:
        names.append(a.vararg.arg)
    names += [p.arg for p in a.kwonlyargs]
    if a.kwarg:
        names.append(a.kwarg.arg)
    return names


def _decorated(fdef, name: str) -> bool:
    return any(isinstance(d, ast.Name) and d.id == name for d in fdef.decorator_list)


def _is_exception(dotted: str) -> bool:
    if not dotted.startswith("builtins."):
        return False
    obj = getattr(builtins, dotted.split(".", 1)[1], None)
    return isinstance(obj, type) and issubclass(obj, BaseException)


def _texty(node) -> bool:
    return isinstance(node, ast.JoinedStr) or (
        isinstance(node, ast.Constant) and isinstance(node.value, str))


class _Module:
    def __init__(self, path: str):
        self.file = os.path.basename(path)
        self.name = self.file[:-3]
        with open(path, encoding="utf-8") as fh:
            self.source = fh.read()
        # A docstring holding `C:\Program Files` is an invalid escape, which
        # parse warns about and the suite's own import already did.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            self.tree = ast.parse(self.source, path)
        self.defs, self.classes, self.qual, self.owner = {}, {}, {}, {}
        self._index(self.tree.body, "", None)
        self.refs = self._refs(self.tree.body, None)
        self._bound = {}

    def _index(self, body, prefix, owner):
        for node in _body_nodes(body):
            if isinstance(node, (*_DEFS, ast.ClassDef)):
                q = prefix + node.name
                (self.classes if isinstance(node, ast.ClassDef) else self.defs)[q] = node
                self.qual[node], self.owner[node] = q, owner
                self._index(node.body, q + ".", node)

    def _refs(self, body, owner) -> dict:
        """What each name a body binds by import, def, class or alias names."""
        out = {}
        for node in _body_nodes(body):
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.asname:
                        out[a.asname] = ("import", a.name)
                    else:
                        out[a.name.split(".")[0]] = ("import", a.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                for a in node.names:
                    out[a.asname or a.name] = ("from", node.module or "", a.name,
                                               node.level)
            elif isinstance(node, (*_DEFS, ast.ClassDef)):
                out[node.name] = ("def", self.qual[node])
            elif (isinstance(node, ast.Assign) and len(node.targets) == 1
                  and isinstance(node.targets[0], ast.Name)
                  and isinstance(node.value, (ast.Name, ast.Attribute))):
                out[node.targets[0].id] = ("alias", node.value, owner)
        return out

    def bound(self, node) -> tuple:
        """A def's own local names, its `global` names, and its own refs."""
        if node not in self._bound:
            names, globs = set(_params(node)), set()
            for sub in _own(node):
                if isinstance(sub, (*_DEFS, ast.ClassDef)):
                    names.add(sub.name)
                elif isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
                    names.add(sub.id)
                elif isinstance(sub, ast.Global):
                    globs.update(sub.names)
                elif isinstance(sub, ast.ExceptHandler) and sub.name:
                    names.add(sub.name)
                elif isinstance(sub, (ast.Import, ast.ImportFrom)):
                    names.update((a.asname or a.name).split(".")[0] for a in sub.names)
            self._bound[node] = (names - globs, globs, self._refs(node.body, node))
        return self._bound[node]


class _Scope:
    """A module, class or function body, as the sweep walks it."""

    def __init__(self, module, node, kind):
        self.module, self.node, self.kind = module, node, kind
        self.qualname = module.qual.get(node, "<module>")
        self.env = {}
        self.cls = self.self_name = None
        self.names, self.globs, self.refs = set(), set(), {}
        if kind == "function":
            self.names, self.globs, self.refs = module.bound(node)
            owner = module.owner.get(node)
            if isinstance(owner, ast.ClassDef) and not _decorated(node, "staticmethod"):
                self.cls = module.qual[owner]
                params = _params(node)
                self.self_name = params[0] if params else None
        elif kind == "class":
            self.cls = self.qualname
            self.refs = module._refs(node.body, None)


class Sweep:
    """Every call in `directory`'s modules handed a workflow path, judged.

    Flow-insensitive and fixed-point: a name holds every state any assignment
    gives it, and the whole package is walked again until no fact grows.
    """

    def __init__(self, directory: str, package: str = "tests"):
        self.package = package
        names = sorted(n for n in os.listdir(directory)
                       if n.endswith(".py") and n != READER + ".py")
        self.modules = {m.name: m for m in
                        (_Module(os.path.join(directory, n)) for n in names)}
        with open(os.path.join(directory, READER + ".py"), encoding="utf-8") as fh:
            reader = ast.parse(fh.read())
        self.reader_defs = {n.name for n in reader.body if isinstance(n, _DEFS)}
        # Module globals, class attributes, return values, closure locals, and
        # parameter defaults: each a state, and each only ever grows.
        self.G, self.C, self.RET, self.CLO, self.DEF = {}, {}, {}, {}, {}
        self.contexts = {(m.name, q, (NONE,) * len(_params(f)))
                         for m in self.modules.values() for q, f in m.defs.items()}
        self.calls, self.sites, self._cache, self._resolving = set(), {}, {}, set()
        for self.rounds in range(1, 101):
            self.changed = False
            for m in self.modules.values():
                self._walk(_Scope(m, None, "module"), m.tree.body)
                for cdef in m.classes.values():
                    self._walk(_Scope(m, cdef, "class"), cdef.body)
            for key in list(self.contexts):
                self._run(*key)
            if not self.changed:
                break
        else:
            raise AssertionError("the sweep did not settle in 100 rounds")

    # ------------------------------------------------------------- results

    def by_kind(self, kind: str) -> list:
        return sorted((s for s in self.sites.values() if s["kind"] == kind),
                      key=lambda s: (s["file"], s["line"]))

    def raw_reads(self) -> dict:
        out = {}
        for s in self.by_kind("read"):
            out.setdefault((s["file"], s["qualname"]), []).append(s)
        return out

    # --------------------------------------------------------------- facts

    def _bump(self, facts: dict, key, state: frozenset) -> None:
        old = facts.get(key, NONE)
        if not state <= old:
            facts[key] = old | state
            self.changed = True

    def _global(self, mod: str, name: str, depth: int = 0) -> frozenset:
        state = self.G.get((mod, name), NONE)
        raw = self.modules[mod].refs.get(name)
        if raw and raw[0] == "from" and depth < 8:
            src = self._tests_module(raw[1], raw[3])
            if src in self.modules and src != mod:
                state |= self._global(src, raw[2], depth + 1)
        return state

    def _class_attr(self, mod: str, cls: str, attr: str, depth: int = 0) -> frozenset:
        state = self.C.get((mod, cls, attr), NONE)
        for base in self._bases(mod, cls) if depth < 8 else ():
            state |= self._class_attr(base[1], base[2], attr, depth + 1)
        return state

    def _bases(self, mod: str, cls: str) -> list:
        """The bases of a class that are classes in this package."""
        module = self.modules[mod]
        refs = [self._ref(_Scope(module, None, "module"), b)
                for b in module.classes[cls].bases]
        return [r for r in refs if r and r[0] == "class"]

    # ---------------------------------------------------------------- refs

    def _tests_module(self, module: str, level: int):
        """The stem a `from` import names inside the package, or None."""
        if level == 0 and module.startswith(self.package + "."):
            module = module[len(self.package) + 1:]
        elif level == 0 or (level == 1 and not module):
            return None
        return module if "." not in module else None

    def _resolve(self, mod: str, raw):
        key = (mod, raw)
        if key in self._cache:
            return self._cache[key]
        if key in self._resolving:
            return None
        self._resolving.add(key)
        try:
            self._cache[key] = found = self._resolve_raw(mod, raw)
        finally:
            self._resolving.discard(key)
        return found

    def _resolve_raw(self, mod: str, raw):
        kind = raw[0]
        if kind == "import":
            dotted = raw[1]
            if dotted == self.package:
                return ("package",)
            if dotted.startswith(self.package + "."):
                return ("module", dotted.split(".", 1)[1])
            return ("ext", dotted)
        if kind == "from":
            _, module, name, level = raw
            if (level == 0 and module == self.package) or (level == 1 and not module):
                return self._member(("package",), name)
            src = self._tests_module(module, level)
            if src is not None:
                return self._member(("module", src), name)
            return ("ext", f"{module}.{name}")
        if kind == "def":
            q = raw[1]
            return ("class" if q in self.modules[mod].classes else "func", mod, q)
        if kind == "alias":
            owner = raw[2]
            scope = _Scope(self.modules[mod], owner,
                           "function" if owner is not None else "module")
            return self._ref(scope, raw[1])
        return None

    def _member(self, base, attr):
        if base is None:
            return None
        if base[0] == "package":
            return ("module", attr) if attr in self.modules or attr == READER else None
        if base[0] == "module":
            if base[1] == READER:
                return ("reader", attr) if attr in self.reader_defs else None
            mod = self.modules.get(base[1])
            raw = mod.refs.get(attr) if mod else None
            return self._resolve(mod.name, raw) if raw else None
        if base[0] == "ext":
            return ("ext", f"{base[1]}.{attr}")
        if base[0] == "class":
            if f"{base[2]}.{attr}" in self.modules[base[1]].defs:
                return ("func", base[1], f"{base[2]}.{attr}")
            for b in self._bases(base[1], base[2]):
                found = self._member(b, attr)
                if found:
                    return found
        return None

    def _ref(self, sc, node):
        """What `node` names, if it is a module, function, class or reader."""
        if isinstance(node, ast.Attribute):
            return self._member(self._ref(sc, node.value), node.attr)
        if not isinstance(node, ast.Name):
            return None
        name, mod = node.id, sc.module
        fn = sc.node if sc.kind == "function" else None
        while fn is not None:
            names, globs, refs = mod.bound(fn)
            if name in refs:
                return self._resolve(mod.name, refs[name])
            if name in names:
                return None
            if name in globs:
                break
            fn = mod.owner.get(fn)
            while isinstance(fn, ast.ClassDef):
                fn = mod.owner.get(fn)
        if sc.kind == "class" and name in sc.refs:
            return self._resolve(mod.name, sc.refs[name])
        if name in mod.refs:
            return self._resolve(mod.name, mod.refs[name])
        if hasattr(builtins, name):
            return ("ext", f"builtins.{name}")
        return None

    # ------------------------------------------------------------ the walk

    def _run(self, mod_name, q, ctx):
        mod = self.modules[mod_name]
        fdef = mod.defs[q]
        sc = _Scope(mod, fdef, "function")
        for name, state in zip(_params(fdef), ctx):
            sc.env[name] = state | self.DEF.get((mod_name, q, name), NONE)
        while True:
            before = dict(sc.env)
            ret = self._walk(sc, fdef.body)
            if sc.env == before:
                break
        self._bump(self.RET, (mod_name, q, ctx), ret)
        for name, state in sc.env.items():
            self._bump(self.CLO, (mod_name, q, name), state)

    def _walk(self, sc, body) -> frozenset:
        """Walk statements, and return what their `return`s hand back."""
        ret = NONE
        for node in body:
            if isinstance(node, _DEFS):
                for d in node.decorator_list:
                    self._expr(sc, d)
                a, q = node.args, sc.module.qual[node]
                positional = a.posonlyargs + a.args
                pairs = list(zip(positional[len(positional) - len(a.defaults):], a.defaults))
                pairs += [(p, d) for p, d in zip(a.kwonlyargs, a.kw_defaults) if d]
                for p, d in pairs:
                    self._bump(self.DEF, (sc.module.name, q, p.arg), self._expr(sc, d))
            elif isinstance(node, ast.ClassDef):
                for e in node.bases + node.decorator_list:
                    self._expr(sc, e)
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    self._assign(sc, t, node.value)
            elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
                if node.value is not None:
                    self._assign(sc, node.target, node.value)
            elif isinstance(node, (ast.For, ast.AsyncFor)):
                self._assign(sc, node.target, None, self._expr(sc, node.iter))
                ret |= self._walk(sc, node.body) | self._walk(sc, node.orelse)
            elif isinstance(node, (ast.With, ast.AsyncWith)):
                for item in node.items:
                    state = self._expr(sc, item.context_expr)
                    if item.optional_vars is not None:
                        self._assign(sc, item.optional_vars, None, state)
                ret |= self._walk(sc, node.body)
            elif isinstance(node, (ast.If, ast.While)):
                self._expr(sc, node.test)
                ret |= self._walk(sc, node.body) | self._walk(sc, node.orelse)
            elif isinstance(node, ast.Try) or type(node).__name__ == "TryStar":
                ret |= self._walk(sc, node.body)
                for h in node.handlers:
                    self._expr(sc, h.type)
                    ret |= self._walk(sc, h.body)
                ret |= self._walk(sc, node.orelse) | self._walk(sc, node.finalbody)
            elif isinstance(node, ast.Match):
                self._expr(sc, node.subject)
                for case in node.cases:
                    self._expr(sc, case.guard)
                    ret |= self._walk(sc, case.body)
            elif isinstance(node, ast.Return):
                ret |= self._expr(sc, node.value)
            else:
                for child in ast.iter_child_nodes(node):
                    if isinstance(child, ast.expr):
                        self._expr(sc, child)
        return ret

    def _assign(self, sc, target, value, state=None):
        if state is None:
            state = self._expr(sc, value)
        if isinstance(target, ast.Name):
            mod = sc.module.name
            if sc.kind == "module" or target.id in sc.globs:
                self._bump(self.G, (mod, target.id), state)
            elif sc.kind == "class":
                self._bump(self.C, (mod, sc.cls, target.id), state)
            else:
                sc.env[target.id] = sc.env.get(target.id, NONE) | state
        elif isinstance(target, (ast.Tuple, ast.List)):
            pairwise = (isinstance(value, (ast.Tuple, ast.List))
                        and len(value.elts) == len(target.elts)
                        and not any(isinstance(e, ast.Starred)
                                    for e in value.elts + target.elts))
            for i, t in enumerate(target.elts):
                if pairwise:
                    self._assign(sc, t, value.elts[i])
                else:
                    self._assign(sc, t, None, state)
        elif isinstance(target, ast.Starred):
            self._assign(sc, target.value, None, state)
        elif isinstance(target, ast.Attribute):
            if (sc.cls and isinstance(target.value, ast.Name)
                    and target.value.id == sc.self_name):
                self._bump(self.C, (sc.module.name, sc.cls, target.attr), state)
            else:
                self._expr(sc, target.value)
        elif isinstance(target, ast.Subscript):
            self._expr(sc, target.slice)
            self._assign(sc, target.value, None, state)

    def _name(self, sc, name) -> frozenset:
        mod = sc.module
        if sc.kind == "function" and name in sc.globs:
            return self._global(mod.name, name)
        if sc.kind == "function" and name in sc.names:
            return sc.env.get(name, NONE)
        if sc.kind == "class" and (mod.name, sc.cls, name) in self.C:
            return self.C[(mod.name, sc.cls, name)]
        fn = mod.owner.get(sc.node) if sc.node is not None else None
        while fn is not None:
            if isinstance(fn, _DEFS):
                names, globs, _ = mod.bound(fn)
                if name in names:
                    return self.CLO.get((mod.name, mod.qual[fn], name), NONE)
                if name in globs:
                    break
            fn = mod.owner.get(fn)
        return self._global(mod.name, name)

    def _pieces(self, sc, node) -> list:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return [node.value]
        if isinstance(node, ast.JoinedStr):
            out = []
            for v in node.values:
                if isinstance(v, ast.Constant):
                    out.append(str(v.value))
                else:
                    out.append(self._expr(sc, v.value))
                    self._expr(sc, v.format_spec)
            return out
        return [self._expr(sc, node)]

    def _expr(self, sc, node) -> frozenset:
        if node is None:
            return NONE
        if isinstance(node, ast.Constant):
            return _fold([node.value]) if isinstance(node.value, str) else NONE
        if isinstance(node, ast.JoinedStr):
            return _fold(self._pieces(sc, node))
        if isinstance(node, ast.Name):
            return self._name(sc, node.id)
        if isinstance(node, ast.Attribute):
            return self._attribute(sc, node)
        if isinstance(node, ast.Call):
            return self._call(sc, node)
        if isinstance(node, ast.BinOp):
            if isinstance(node.op, ast.Div):
                return _fold([self._expr(sc, node.left), "/"] + self._pieces(sc, node.right))
            if isinstance(node.op, ast.Add) and (_texty(node.left) or _texty(node.right)):
                return _fold(self._pieces(sc, node.left) + self._pieces(sc, node.right))
            state = self._expr(sc, node.left) | self._expr(sc, node.right)
            return state if isinstance(node.op, ast.Add) else NONE
        if isinstance(node, ast.IfExp):
            self._expr(sc, node.test)
            return self._expr(sc, node.body) | self._expr(sc, node.orelse)
        if isinstance(node, (ast.BoolOp, ast.Tuple, ast.List, ast.Set)):
            elts = node.values if isinstance(node, ast.BoolOp) else node.elts
            return frozenset().union(*(self._expr(sc, e) for e in elts))
        if isinstance(node, ast.Dict):
            for k in node.keys:
                self._expr(sc, k)
            return frozenset().union(*(self._expr(sc, v) for v in node.values))
        if isinstance(node, (ast.Starred, ast.Await, ast.Yield, ast.YieldFrom)):
            return self._expr(sc, node.value)
        if isinstance(node, ast.Subscript):
            self._expr(sc, node.slice)
            return self._expr(sc, node.value)
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
            for gen in node.generators:
                self._assign(sc, gen.target, None, self._expr(sc, gen.iter))
                for cond in gen.ifs:
                    self._expr(sc, cond)
            if isinstance(node, ast.DictComp):
                self._expr(sc, node.key)
                return self._expr(sc, node.value)
            return self._expr(sc, node.elt)
        if isinstance(node, ast.NamedExpr):
            state = self._expr(sc, node.value)
            self._assign(sc, node.target, None, state)
            return state
        if isinstance(node, ast.Lambda):
            for d in node.args.defaults + [d for d in node.args.kw_defaults if d]:
                self._expr(sc, d)
            self._expr(sc, node.body)
            return NONE
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.expr):
                self._expr(sc, child)
        return NONE

    def _attribute(self, sc, node) -> frozenset:
        if (sc.cls and isinstance(node.value, ast.Name)
                and node.value.id == sc.self_name):
            return self._class_attr(sc.module.name, sc.cls, node.attr)
        ref = self._ref(sc, node.value)
        if ref and ref[0] == "module" and ref[1] in self.modules:
            return self._global(ref[1], node.attr)
        if ref and ref[0] == "class":
            return self._class_attr(ref[1], ref[2], node.attr)
        base = self._expr(sc, node.value)
        if WF in base and node.attr in ("read_text", "read_bytes", "open"):
            self._record(sc, node, "read", f"`.{node.attr}` taken off a workflow path")
        return base if node.attr in PATH_KEEP_ATTRS else NONE

    def _call(self, sc, node) -> frozenset:
        self.calls.add((sc.module.file, node.lineno, node.col_offset))
        func, bound, recv, callee = node.func, False, NONE, None
        attr = func.attr if isinstance(func, ast.Attribute) else None
        if attr is not None:
            if sc.cls and isinstance(func.value, ast.Name) and func.value.id == sc.self_name:
                callee = self._member(("class", sc.module.name, sc.cls), attr)
                bound = True
            else:
                base = self._ref(sc, func.value)
                if base is None:
                    recv = self._expr(sc, func.value)
                else:
                    callee = self._member(base, attr)
                    if callee and callee[0] == "func" and base[0] == "class":
                        fdef = self.modules[callee[1]].defs[callee[2]]
                        bound = _decorated(fdef, "classmethod")
        elif isinstance(func, ast.Name):
            callee = self._ref(sc, func)
        else:
            self._expr(sc, func)
        dotted = callee[1] if callee and callee[0] == "ext" else None
        joins = dotted in PATH_JOIN or (callee is None and attr == "joinpath")
        if joins:
            pieces = [] if dotted else [recv]
            for a in node.args:
                pieces += (["/"] if pieces else []) + self._pieces(sc, a)
            args = [p for p in pieces if not isinstance(p, str)]
        else:
            args = [self._expr(sc, a) for a in node.args]
        kws = [(k.arg, self._expr(sc, k.value)) for k in node.keywords]
        if joins:
            kind, result, why = "path", _fold(pieces), "joins path parts"
        else:
            kind, result, why = self._judge(sc, node, callee, bound, recv, args, kws)
        if WF in recv or any(WF in s for s in args) or any(WF in s for _, s in kws):
            self._record(sc, node, kind, why)
        return result

    def _judge(self, sc, node, callee, bound, recv, args, kws):
        """What a call does with what it is handed: a kind, a result, a reason."""
        func = node.func
        attr = func.attr if isinstance(func, ast.Attribute) else None
        every = frozenset().union(*args, *(s for _, s in kws))
        if callee and callee[0] == "reader":
            return "reader", NONE, f"`{READER}.{callee[1]}`"
        if callee and callee[0] == "class":
            init = self._member(callee, "__init__")
            if not init or init[0] != "func":
                return "read", NONE, f"constructs {callee[2]}, which has no __init__ here"
            callee, bound = init, True
        if callee and callee[0] == "func":
            fdef = self.modules[callee[1]].defs[callee[2]]
            ctx = self._ctx(fdef, node, args, kws,
                            bound and not _decorated(fdef, "staticmethod"))
            key = (callee[1], callee[2], ctx)
            if key not in self.contexts:
                self.contexts.add(key)
                self.changed = True
            return ("helper", self.RET.get(key, NONE),
                    f"followed into tests/{self.modules[callee[1]].file}::{callee[2]}")
        if callee and callee[0] == "ext":
            dotted = callee[1]
            if dotted in PATH_KEEP:
                return "path", every, f"`{dotted}` returns a path"
            if dotted in NOT_A_READ or _is_exception(dotted):
                return "not a read", NONE, f"`{dotted}`"
            known = "a reader" if dotted in KNOWN_READERS else "not known to this sweep"
            return "read", NONE, f"`{dotted}`, {known}"
        if callee is None and attr is not None:
            if WF in recv or not (args or kws):
                if attr in PATH_KEEP_METHODS:
                    return "path", recv, f"`.{attr}()` returns a path"
                if attr in NOT_A_READ_METHODS:
                    return "not a read", NONE, f"`.{attr}()`"
                known = "a reader" if attr in KNOWN_READERS else "not known to this sweep"
                return "read", NONE, f"`.{attr}()` on a workflow path, {known}"
            if (sc.cls and isinstance(func.value, ast.Name)
                    and func.value.id == sc.self_name and attr.startswith(REPORTS)):
                return "not a read", NONE, f"`self.{attr}` reports"
            if _texty(func.value):
                return "not a read", every if attr == "join" else NONE, f"`str.{attr}`"
            if attr in FILLS:
                self._assign(sc, func.value, None, every)
                return "not a read", NONE, f"`.{attr}()` fills a container"
        return "read", NONE, f"`{ast.unparse(func)}`, not known to this sweep"

    def _ctx(self, fdef, node, args, kws, bound) -> tuple:
        """The state of each parameter of `fdef` at this call."""
        names, a = _params(fdef), fdef.args
        positional = [p.arg for p in a.posonlyargs + a.args][1 if bound else 0:]
        state = dict.fromkeys(names, NONE)
        spread = NONE
        for i, (arg, s) in enumerate(zip(node.args, args)):
            if any(isinstance(x, ast.Starred) for x in node.args[:i + 1]):
                spread |= s
            elif i < len(positional):
                state[positional[i]] |= s
            elif a.vararg:
                state[a.vararg.arg] |= s
        for k, s in kws:
            if k is None:
                spread |= s
            elif k in state:
                state[k] |= s
            elif a.kwarg:
                state[a.kwarg.arg] |= s
        return tuple(state[n] | spread for n in names)

    def _record(self, sc, node, kind, why):
        site = (sc.module.file, node.lineno, node.col_offset)
        old = self.sites.get(site)
        if old is not None and (old["kind"] == "read" or kind != "read"):
            return
        self.sites[site] = {
            "file": sc.module.file, "line": node.lineno, "qualname": sc.qualname,
            "kind": kind, "why": why,
            "text": ast.get_source_segment(sc.module.source, node) or "",
        }


def _describe(sites) -> str:
    return "\n".join(f"  tests/{s['file']}:{s['line']} in {s['qualname']}: "
                     f"{' '.join(s['text'].split())[:100]} ({s['why']})" for s in sites)


_SWEEP = []


def _sweep() -> Sweep:
    if not _SWEEP:
        _SWEEP.append(Sweep(HERE))
    return _SWEEP[0]


class TestTheSweepReadTheSuite(unittest.TestCase):
    """Every check below this class is a "nothing else" assertion, and a sweep
    that parsed nothing, walked nothing or found no workflow path makes each
    one true. The floors are what an empty sweep cannot reach, set near half
    of what this found when it landed (2026-11-01): 86 modules, 13,065 calls
    walked, 30 handed a workflow path, 18 of them `_workflow.*`.
    """

    def test_every_module_in_tests_was_parsed(self):
        listed = sorted(n for n in os.listdir(HERE)
                        if n.endswith(".py") and n != READER + ".py")
        self.assertGreaterEqual(len(listed), 50, "the listing found almost no modules")
        self.assertEqual(sorted(m.file for m in _sweep().modules.values()), listed)
        self.assertIn(os.path.basename(__file__), listed, "this module sweeps itself too")

    def test_it_walked_calls_and_found_workflow_paths(self):
        sweep = _sweep()
        found, through = list(sweep.sites.values()), sweep.by_kind("reader")
        counts = (f"{len(sweep.modules)} modules, {len(sweep.calls)} calls walked, "
                  f"{len(found)} handed a workflow path, {len(through)} of them "
                  f"`{READER}.*`, {sweep.rounds} rounds")
        self.assertGreaterEqual(len(sweep.calls), 6000, counts)
        self.assertGreaterEqual(len(found), 15, counts)
        self.assertGreaterEqual(len(through), 9, counts)

    def test_every_module_that_imports_the_reader_was_seen_using_it(self):
        """A floor per module. One whose reader calls the sweep lost, to a
        helper it stopped following or an import it stopped resolving, fails
        here by name rather than shrinking a total."""
        sweep, importers = _sweep(), set()
        for m in sweep.modules.values():
            for node in ast.walk(m.tree):
                if isinstance(node, ast.ImportFrom) and (
                        node.module == f"tests.{READER}"
                        or any(a.name == READER for a in node.names)):
                    importers.add(m.file)
                elif isinstance(node, ast.Import) and any(
                        a.name == f"tests.{READER}" for a in node.names):
                    importers.add(m.file)
        self.assertGreaterEqual(len(importers), 3, f"importers: {sorted(importers)}")
        seen = {s["file"] for s in sweep.by_kind("reader")}
        self.assertEqual(sorted(importers - seen), [],
                         "these import tests/_workflow.py and the sweep saw no "
                         "workflow path reach it there")


class TestEveryWorkflowReadGoesThroughTheReader(unittest.TestCase):

    def test_nothing_else_reads_a_workflow_raw(self):
        stray = {k: v for k, v in _sweep().raw_reads().items() if k not in ALLOWED}
        self.assertEqual(
            stray, {},
            "a workflow is opened or parsed outside tests/_workflow.py:\n"
            + _describe(s for sites in stray.values() for s in sites)
            + "\nRead it through tests/_workflow.py. If the call neither opens "
            "nor parses the file, name it in NOT_A_READ with the reason.")

    def test_each_allowed_raw_read_is_still_there(self):
        sweep = _sweep()
        reads = sweep.raw_reads()
        for (file, qualname), reason in sorted(ALLOWED.items()):
            with self.subTest(qualname.rsplit(".", 1)[-1]):
                module = sweep.modules.get(file[:-3])
                self.assertIsNotNone(module, f"tests/{file} is gone")
                self.assertTrue(
                    qualname in module.defs,
                    f"tests/{file} has no {qualname}, so its allowance names "
                    f"nothing. Re-aim ALLOWED at the test that {reason}, or "
                    "drop it and the sentence naming it in tests/_workflow.py.")
                sites = reads.get((file, qualname), [])
                self.assertEqual(
                    len(sites), 1,
                    f"{qualname} is allowed one raw read because it {reason}, "
                    f"and the sweep found {len(sites)}:\n{_describe(sites)}\n"
                    "None means the allowance is dead, so drop it. More means "
                    "the test reads raw for a reason ALLOWED does not give.")


class TestTheClaimItHoldsIsTheOneStated(unittest.TestCase):
    """The gate and the line it holds move together, or either moves alone."""

    def _doc(self) -> str:
        with open(os.path.join(HERE, READER + ".py"), encoding="utf-8") as fh:
            return ast.get_docstring(ast.parse(fh.read())) or ""

    def test_the_first_line_is_the_claim(self):
        self.assertEqual(self._doc().splitlines()[0], CLAIM,
                         "tests/_workflow.py's first line moved. Re-aim CLAIM, "
                         "and this module if the claim changed with it.")

    def test_the_retraction_is_quoted_and_names_this_gate(self):
        doc = " ".join(self._doc().split())
        self.assertIn(f'"{RETRACTED}"', doc, "the retraction lost its quotation")
        self.assertNotIn("No test holds that", re.sub(r'"[^"]*"', "", doc),
                         "the docstring says again, outside a quotation, that "
                         "no test holds the line")
        self.assertIn(f"tests/{os.path.basename(__file__)}", doc,
                      "the docstring no longer names the test that holds it")


# ------------------------------------------------------ the gate can fire

_READER_STUB = '''
def load(path):
    return {}


def run_script(path, step_name, job=None):
    return ""
'''

_BUILD = '''
import os
import pathlib

from tests import _workflow

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOW = os.path.join(HERE, ".github", "workflows", "build-windows.yml")
BUILD = pathlib.Path(HERE) / ".github" / "workflows" / "build-windows.yml"
_run_script = _workflow.run_script


def _steps(path):
    return _workflow.load(str(path))["jobs"]


def test_steps():
    return _steps(BUILD)
'''

_USER = '''
"""Opens .github/workflows/build-windows.yml, this docstring says."""
import os

from tests import build as R
from tests.build import WORKFLOW, _run_script


def _drive():
    # open(".github/workflows/build-windows.yml") in a comment is not a call.
    return R._run_script(R.WORKFLOW, "Step") + _run_script(WORKFLOW, "Step")
'''


class TestTheSweepCanFire(unittest.TestCase):
    """Each shape the gate was falsified on, on a package written here.

    The clean package reads every workflow through the reader and shows no raw
    read. Each case puts one hand reader back and must show exactly that one,
    in the function it was put in.
    """

    CASES = {
        "a helper loads YAML from its parameter":
            ("build.py", '    return _workflow.load(str(path))["jobs"]',
             '    import yaml\n    return yaml.safe_load(open(path))["jobs"]',
             "_steps"),
        "pathlib reads the module's Path":
            ("build.py", "    return _steps(BUILD)", "    return BUILD.read_text()",
             "test_steps"),
        "setUp keeps the path on self, and a test opens it":
            ("build.py", "_run_script = _workflow.run_script\n",
             "_run_script = _workflow.run_script\n\n\nclass T:\n"
             "    def setUp(self):\n        self.path = WORKFLOW\n\n"
             "    def test(self):\n        return open(self.path).read()\n",
             "T.test"),
        "a local path, then open":
            ("user.py", "def _drive():\n",
             "def _drive():\n    path = os.path.join(os.sep, '.github', 'workflows', "
             "'tests.yml')\n    open(path)\n",
             "_drive"),
        "open(R.WORKFLOW) across `from tests import x as R`":
            ("user.py", "    return R._run_script(",
             "    open(R.WORKFLOW)\n    return R._run_script(", "_drive"),
        "open(NAME) across `from tests.x import NAME`":
            ("user.py", "    return R._run_script(",
             "    open(WORKFLOW)\n    return R._run_script(", "_drive"),
    }

    def _package(self, edit=None) -> Sweep:
        files = {"_workflow.py": _READER_STUB, "build.py": _BUILD, "user.py": _USER}
        if edit is not None:
            name, anchor, replacement = edit
            self.assertEqual(files[name].count(anchor), 1, f"the anchor {anchor!r}")
            files[name] = files[name].replace(anchor, replacement)
        root = tempfile.mkdtemp(prefix="workflow-sweep-")
        self.addCleanup(shutil.rmtree, root, True)
        for name, text in files.items():
            with open(os.path.join(root, name), "w", encoding="utf-8") as fh:
                fh.write(textwrap.dedent(text))
        return Sweep(root)

    def test_the_clean_package_reads_only_through_the_reader(self):
        sweep = self._package()
        self.assertEqual(sweep.raw_reads(), {})
        self.assertEqual({(s["file"], s["qualname"]) for s in sweep.by_kind("reader")},
                         {("build.py", "_steps"), ("user.py", "_drive")})

    def test_each_hand_reader_is_found_where_it_was_put(self):
        for case, (name, anchor, replacement, qualname) in self.CASES.items():
            with self.subTest(case):
                reads = self._package((name, anchor, replacement)).raw_reads()
                self.assertEqual(sorted(reads), [(name, qualname)], case)
                self.assertEqual(len(reads[(name, qualname)]), 1, case)


if __name__ == "__main__":
    unittest.main()
