"""Offscreen integration tests using synthetic frames, with no broker or job dialog."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import Qt, QPointF
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDockWidget

from labelgui.ui.main_window import MainWindow
from labelgui.select_user import SelectUserWindow
from labelgui.core.jobs import JobRepository
from test_core import make_session


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_floating_camera_keeps_annotation_and_keyboard_connections(self):
        with tempfile.TemporaryDirectory() as folder:
            session = make_session(folder)
            window = MainWindow(session=session, sync=False)
            camera = window.subwindows[0]
            try:
                self.app.processEvents()
                self.assertIsInstance(camera, QDockWidget)
                camera.setFloating(True)
                camera.resize(640, 480)
                camera.show()
                camera.activateWindow()
                self.app.processEvents()
                self.assertTrue(camera.isFloating())
                self.assertTrue(camera.isWindow())
                point = camera.plot_wget.mapFromScene(camera.view_box.mapViewToScene(QPointF(3, 4)))
                QTest.mouseClick(camera.plot_wget.viewport(), Qt.MouseButton.LeftButton, pos=point)
                self.assertIsNotNone(session.annotations.point('nose', 0, 0))
                self.assertIn('nose', camera.labels['label'])
                QTest.keyClick(camera.plot_wget, Qt.Key.Key_D)
                self.assertEqual(session.current_time, .1)
                self.assertEqual(window.subwindows[1].frame_idx, session.frame_index(1))
                QTest.keyClick(camera.plot_wget, Qt.Key.Key_A)
                self.assertEqual(session.current_time, 0)
                QTest.keyClick(camera.plot_wget, Qt.Key.Key_N)
                self.assertEqual(session.current_label, 'tail')
                with patch.object(session, 'save') as save:
                    QTest.keyClick(camera.plot_wget, Qt.Key.Key_S)
                    save.assert_called_once()
                camera.setFloating(False)
                self.app.processEvents()
                self.assertFalse(camera.isFloating())
                self.assertIs(window.subwindows[0], camera)
                self.assertIn('nose', camera.labels['label'])
                # A docked camera must dispatch each shortcut just once as well.
                QTest.keyClick(camera.plot_wget, Qt.Key.Key_D)
                self.assertEqual(session.current_time, .1)
            finally:
                window.close()
                window.deleteLater()
                self.app.processEvents()

    def test_camera_layouts_leave_floating_views_alone_and_recall_them(self):
        with tempfile.TemporaryDirectory() as folder:
            session = make_session(folder)
            window = MainWindow(session=session, sync=False)
            first, second = window.subwindows.values()
            workspace = window.camera_workspace
            try:
                self.app.processEvents()
                self.assertIn(second, workspace.tabifiedDockWidgets(first))
                window.arrange_cameras('tile_view')
                self.app.processEvents()
                self.assertNotIn(second, workspace.tabifiedDockWidgets(first))
                second.setFloating(True)
                window.arrange_cameras('tab_view')
                self.assertTrue(second.isFloating())
                first.setFloating(True)
                window.arrange_cameras('tile_view')
                self.assertTrue(first.isFloating())
                self.assertTrue(second.isFloating())
                window.dock_all_cameras()
                self.app.processEvents()
                self.assertFalse(first.isFloating())
                self.assertFalse(second.isFloating())
                self.assertNotIn(second, workspace.tabifiedDockWidgets(first))
                window.arrange_cameras('tab_view')
                self.assertIn(second, workspace.tabifiedDockWidgets(first))
                second.setFloating(True)
            finally:
                window.close()
                self.app.processEvents()
                self.assertFalse(second.isVisible())
                window.deleteLater()
                self.app.processEvents()

    def test_floating_camera_has_window_controls_and_can_dock_after_minimizing(self):
        with tempfile.TemporaryDirectory() as folder:
            window = MainWindow(session=make_session(folder), sync=False)
            camera = window.subwindows[0]
            try:
                self.app.processEvents()
                for _ in range(2):
                    camera.setFloating(True)
                    self.app.processEvents()
                    # Qt also resets flags when an already-floating dock finishes
                    # a drag; this does not emit topLevelChanged again.
                    camera.setFloating(True)
                    self.app.processEvents()
                    self.assertEqual(camera.windowType(), Qt.WindowType.Window)
                    self.assertFalse(camera.windowFlags() & Qt.WindowType.FramelessWindowHint)
                    self.assertTrue(camera.windowFlags() & Qt.WindowType.WindowMinimizeButtonHint)
                    self.assertTrue(camera.windowFlags() & Qt.WindowType.WindowMaximizeButtonHint)
                    self.assertTrue(camera.isVisible())
                    self.assertTrue(camera.dock_button.isVisible())
                    camera.showMaximized()
                    self.app.processEvents()
                    self.assertTrue(camera.isMaximized())
                    camera.dock_button.click()
                    self.app.processEvents()
                    self.assertFalse(camera.isFloating())
                    self.assertFalse(camera.isMaximized())
                    self.assertFalse(camera.dock_button.isVisible())
                camera.setFloating(True)
                camera.showMinimized()
                self.app.processEvents()
                self.assertTrue(camera.isMinimized())
                window.dock_all_cameras()
                self.app.processEvents()
                self.assertFalse(camera.isFloating())
                self.assertFalse(camera.isMinimized())
                self.assertTrue(camera.isVisible())
            finally:
                window.close()
                window.deleteLater()
                self.app.processEvents()

    def test_window_binds_session_and_renders_annotations(self):
        with tempfile.TemporaryDirectory() as folder:
            session = make_session(folder)
            window = MainWindow(session=session, sync=False)
            try:
                window.viewer_click(3, 4, 0, 0)
                self.assertEqual(session.annotations.point('nose', 0, 0), (3, 4))
                self.assertIn('nose', window.subwindows[0].labels['label'])
                window.dock_sketch.list_labels.setCurrentRow(1)
                self.assertEqual(session.current_label, 'tail')
                window.dock_controls.widgets['buttons']['single_label_mode'].click()
                window.viewer_click(5, 6, 0, 1)
                self.assertEqual(session.annotations.point('tail', 0, 1), (5, 6))
                self.assertEqual(session.current_time, .1)
                window.set_time(.61, mqtt_publish=False)
                self.assertEqual(window.subwindows[1].frame_idx, 1)
                window.dock_controls.widgets['fields']['d_time'].setText('')
                window.set_d_time()
                self.assertEqual(session.d_time, 0)
                window.viewer_rotate()
                window.viewer_zoom_reset()
                self.app.processEvents()
            finally:
                window.close()
                window.deleteLater()
                self.app.processEvents()
            self.assertTrue((Path(folder) / 'exit_status.npy').exists())

    def test_close_failure_keeps_window_and_session_open(self):
        with tempfile.TemporaryDirectory() as folder:
            session = make_session(folder)
            window = MainWindow(session=session, sync=False)
            camera = window.subwindows[0]
            camera.setFloating(True)
            with patch.object(session, 'close', side_effect=RuntimeError('disk full')), \
                    patch('labelgui.ui.main_window.QMessageBox.critical') as error:
                self.assertFalse(window.close())
                error.assert_called_once()
                self.assertTrue(camera.isVisible())
            self.assertTrue(window.close())
            window.deleteLater()
            self.app.processEvents()

    def test_empty_user_list_and_cancel_do_not_write_defaults(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'data' / 'user').mkdir(parents=True)
            repository = JobRepository(root, root / 'defaults.yml')
            dialog = SelectUserWindow(root, repository=repository)
            self.assertIsNone(dialog.get_user())
            self.assertFalse(dialog.selecting_button.isEnabled())
            dialog.reject()
            self.assertFalse(repository.defaults_file.exists())
            dialog.deleteLater()
            self.app.processEvents()
