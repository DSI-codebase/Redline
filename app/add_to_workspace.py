"""Add to workspace: copy a drawing into a workspace folder and work on the copy.

Reached two ways, with one menu: **File ▸ Add to workspace** for the open
drawing, and right-click ▸ **Add to workspace** on a row of the File view's
Recent page. The menu is rebuilt each time it opens, because a workspace's
folders change on disk:

* the current workspace's **quick subfolders** first (`drawings`,
  `documentation`, `notes` by default; created on first use), then its other
  top-level folders, then **New folder…**;
* **Other workspaces ▸**, each with the same list;
* "Already in <workspace>" instead of a list for the workspace the file is in;
* only **Add a workspace…** when none is declared.

What a copy writes, and the rule that it never replaces anything, is
`app/model/drawing_copy.py`. What happens around it is here: unsaved marks are
saved first (the sidecar copy reads what is committed), a byte-identical file
already there is offered to open instead, a name clash keeps both, and the
window switches to the copy when the drawing being copied is the one open --
otherwise the next marks would land on the original and the two would drift
apart without a word.
"""

from __future__ import annotations

import os

from PySide6.QtWidgets import QInputDialog, QMessageBox

from .model import drawing_copy as C
from .model import workspaces as W
from .model.recent import drawing_key, open_target
from .model.storage import ProtectedPathError


# -- the questions; module functions so tests can answer them ------------------

def _ask_save(win, name: str) -> bool:
    box = QMessageBox(win)
    box.setIcon(QMessageBox.Question)
    box.setWindowTitle("Add to workspace")
    box.setText(f"Save “{name}” before copying it?")
    box.setInformativeText(
        "The copy takes the marks as they are on disk, so unsaved marks would "
        "be left behind.")
    box.setStandardButtons(QMessageBox.Save | QMessageBox.Cancel)
    box.setDefaultButton(QMessageBox.Save)
    return box.exec() == QMessageBox.Save


def _ask_keep_both(win, name: str, new_name: str, where: str) -> bool:
    box = QMessageBox(win)
    box.setIcon(QMessageBox.Question)
    box.setWindowTitle("Add to workspace")
    box.setText(f"A different “{name}” is already in {where}.")
    box.setInformativeText(f"Keep both, adding this one as “{new_name}”? "
                           f"Nothing already there is replaced.")
    keep = box.addButton("Keep both", QMessageBox.AcceptRole)
    box.addButton(QMessageBox.Cancel)
    box.exec()
    return box.clickedButton() is keep


def _ask_open_existing(win, name: str, where: str) -> bool:
    box = QMessageBox(win)
    box.setIcon(QMessageBox.Information)
    box.setWindowTitle("Add to workspace")
    box.setText(f"“{name}” is already in {where}.")
    box.setInformativeText("The file there is identical. Open that one instead?")
    open_btn = box.addButton("Open it", QMessageBox.AcceptRole)
    box.addButton(QMessageBox.Cancel)
    box.exec()
    return box.clickedButton() is open_btn


def _ask_folder_name(win):
    return QInputDialog.getText(win, "New folder", "Folder name:")


def _warn(win, text: str) -> None:
    QMessageBox.warning(win, "Add to workspace", text)


# -- the menu ------------------------------------------------------------------

def populate(menu, win, source) -> None:
    """Fill ``menu`` with where the drawing ``source`` can be added."""
    menu.clear()
    cfg = win.config
    items = W.ordered(cfg.workspaces())
    if not items:
        menu.addAction("Add a workspace…", lambda: _show_workspaces(win))
        return
    if not source:
        menu.addAction("Open a drawing first").setEnabled(False)
        return
    home = cfg.workspace_for(source)
    current = cfg.current_workspace(source)
    others = [w for w in items if current is None or not _same(w, current)]
    target = menu
    if current is not None:
        menu.addAction(current.display_name).setEnabled(False)     # a heading
        _folder_actions(menu, win, source, current, home)
        if others:
            menu.addSeparator()
            target = menu.addMenu("Other workspaces")
    for ws in others:
        label = ws.display_name if ws.available else f"{ws.display_name}   (unavailable)"
        sub = target.addMenu(label)
        sub.setEnabled(ws.available)
        _folder_actions(sub, win, source, ws, home)


def _same(a, b) -> bool:
    return a is not None and b is not None and W._key(a.root) == W._key(b.root)


def _folder_actions(menu, win, source, ws, home) -> None:
    if _same(ws, home):
        menu.addAction(f"Already in {ws.display_name}").setEnabled(False)
        return
    if not ws.available:
        menu.addAction("Folder not found").setEnabled(False)
        return
    quick, others = W.destinations(ws, win.config.quick_folders())
    for rel in quick:
        menu.addAction(rel, lambda r=rel: add(win, source, ws.root, r))
    if others:
        menu.addSeparator()
        for rel in others:
            menu.addAction(rel, lambda r=rel: add(win, source, ws.root, r))
    menu.addSeparator()
    menu.addAction("New folder…", lambda: _new_folder(win, source, ws.root))


def _show_workspaces(win) -> None:
    win.show_file_view()
    win.file_view.show_workspaces()


def _new_folder(win, source, root) -> None:
    name, ok = _ask_folder_name(win)
    if not ok:
        return
    try:
        name = W.check_folder_name(name)
    except W.WorkspaceError as e:
        _warn(win, str(e))
        return
    add(win, source, root, name)       # the copy makes the folder


# -- adding --------------------------------------------------------------------

def add(win, source, root, rel_folder):
    """Copy the drawing ``source`` into ``rel_folder`` of the workspace at
    ``root``. Returns the plan that was carried out, or ``None``."""
    ws = win.config.find_workspace(root)
    if ws is None:
        return None
    doc = win.document
    is_open = doc is not None and drawing_key(doc.path) == drawing_key(source)
    if is_open and doc.dirty:
        if not _ask_save(win, os.path.basename(doc.path)) or not win.save_markup():
            return None
    where = f"{ws.display_name} ▸ {rel_folder}" if rel_folder else ws.display_name
    try:
        plan = C.plan_copy(source, W.absolute(ws.root, rel_folder))
    except C.CopyError as e:
        _warn(win, str(e))
        return None
    name = plan.natural_stem + ".pdf"
    if plan.identical:
        if _ask_open_existing(win, name, where):
            win.load_document(open_target(plan.identical))
        return None
    if plan.clash and not _ask_keep_both(win, name, plan.stem + ".pdf", where):
        return None
    try:
        C.copy_drawing(plan)
    except (C.CopyError, ProtectedPathError, OSError) as e:
        _warn(win, str(e))
        return None
    if is_open:
        # the next marks go on the copy, not the original
        win.load_document(plan.open_path)
        message = f"Copied to {where} and switched to the copy"
    else:
        message = f"Copied {os.path.basename(plan.open_path)} to {where}"
        fv = getattr(win, "file_view", None)
        if fv is not None and not fv.isHidden():
            fv.refresh_page()
    win.statusBar().showMessage(message, 8000)
    return plan
