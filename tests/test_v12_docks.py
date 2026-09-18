"""Main panes (Viewer / TODO / Wire Numbers / Component Labels / PDF Tools)
live in tabified, floatable dock widgets instead of a QTabWidget, so any tab
can be pulled into its own window or docked elsewhere — like the Comments /
Navigation panels."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication, QDockWidget
    _QT_OK = True
except Exception:  # pragma: no cover
    _QT_OK = False


@unittest.skipUnless(_QT_OK, "PySide6 not available")
class TestMainDocks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _win(self):
        from app.main_window import MainWindow
        return MainWindow()

    def test_panes_are_floatable_docks(self):
        win = self._win()
        # every main pane is wrapped in its own QDockWidget…
        for panel in (win.view, win.todo_panel, win.wire_panel,
                      win.component_panel, win.tools_panel):
            dock = win.tabs.dock_for(panel)
            self.assertIsInstance(dock, QDockWidget)
            self.assertIs(dock.widget(), panel)
            # …and docks can float into their own window
            self.assertTrue(dock.features() & QDockWidget.DockWidgetFloatable)

    def test_docks_have_stable_object_names(self):
        win = self._win()
        names = {win.tabs.dock_for(w).objectName() for w in (
            win.view, win.todo_panel, win.wire_panel,
            win.component_panel, win.tools_panel)}
        self.assertEqual(names, {"ViewerDock", "TodoDock", "WireDock",
                                 "ComponentDock", "PdfToolsDock"})

    def test_tabs_facade_tracks_current(self):
        win = self._win()
        win.tabs.setCurrentWidget(win.tools_panel)
        self.assertIs(win.tabs.currentWidget(), win.tools_panel)
        win.tabs.setCurrentWidget(win.view)
        self.assertIs(win.tabs.currentWidget(), win.view)

    def test_viewer_is_the_default_pane(self):
        win = self._win()
        self.assertIs(win.tabs.currentWidget(), win.view)

    def test_pane_tabs_sit_on_top(self):
        from PySide6.QtWidgets import QTabWidget
        from PySide6.QtCore import Qt
        win = self._win()
        # tabs render on top (North), like the old QTabWidget — not Qt's default
        # bottom position for tabified docks
        self.assertEqual(win.tabPosition(Qt.LeftDockWidgetArea), QTabWidget.North)
        self.assertEqual(win.tabPosition(Qt.RightDockWidgetArea), QTabWidget.North)

    def test_default_layout_tabs_main_panes_only(self):
        # The five main panes tab together; the Navigation and Comments sidebars
        # stay as their own docks. Assert against the freshly-built default so a
        # restored session layout (QSettings) can't mask a regression.
        from app.main_window import _UI_STATE_VERSION
        win = self._win()
        win.restoreState(win._default_state, _UI_STATE_VERSION)
        group = win.tabifiedDockWidgets(win.tabs.dock_for(win.view))
        self.assertNotIn(win.comment_dock, group)
        self.assertNotIn(win.nav_dock, group)
        for panel in (win.todo_panel, win.wire_panel,
                      win.component_panel, win.tools_panel):
            self.assertIn(win.tabs.dock_for(panel), group)

    def test_float_then_reset_layout_redocks(self):
        win = self._win()
        todo_dock = win.tabs.dock_for(win.todo_panel)
        todo_dock.setFloating(True)
        self.assertTrue(todo_dock.isFloating())
        win.reset_layout()
        self.assertFalse(todo_dock.isFloating())
        # reset returns to the Viewer pane
        self.assertIs(win.tabs.currentWidget(), win.view)

    def test_current_skips_a_closed_pane(self):
        # If the tracked pane gets closed (e.g. a floated pane dismissed with
        # its ✕), currentWidget() must not keep reporting it — otherwise a
        # dropped PDF over the window could be silently swallowed.
        win = self._win()
        tools_dock = win.tabs.dock_for(win.tools_panel)
        win.tabs._current = win.tools_panel      # force the stale pointer
        tools_dock.close()                        # explicitly hidden
        self.assertTrue(tools_dock.isHidden())
        self.assertIsNot(win.tabs.currentWidget(), win.tools_panel)

    def test_each_pane_has_a_reopen_toggle(self):
        # A closed dock must be recoverable from a menu action.
        win = self._win()
        for panel in (win.view, win.todo_panel, win.wire_panel,
                      win.component_panel, win.tools_panel):
            act = win.tabs.dock_for(panel).toggleViewAction()
            self.assertIsNotNone(act)

    def test_layout_state_roundtrips_at_version(self):
        from app.main_window import _UI_STATE_VERSION
        win = self._win()
        state = win.saveState(_UI_STATE_VERSION)
        self.assertTrue(win.restoreState(state, _UI_STATE_VERSION))

    def test_old_unversioned_state_is_rejected(self):
        from app.main_window import _UI_STATE_VERSION
        win = self._win()
        # a layout blob from an older build (version 0) must not apply
        legacy = win.saveState(0)
        self.assertFalse(win.restoreState(legacy, _UI_STATE_VERSION))


if __name__ == "__main__":
    unittest.main()
