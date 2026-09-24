"""Offscreen integration tests using synthetic frames, with no broker or job dialog."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDockWidget

from labelgui.ui.main_window import MainWindow
from labelgui.select_user import SelectUserWindow
from labelgui.core.jobs import JobRepository
from labelgui.core.annotations import AnnotationStore, FrameAnnotations, Point
from labelgui.core.timeline import Timeline
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

    def test_labeled_timepoint_buttons_and_shortcuts(self):
        with tempfile.TemporaryDirectory() as folder:
            session = make_session(folder)
            session.annotations.set_point('tail', 1, 1, (3, 4), 'alice')
            session.annotations.set_point('nose', 3, 0, (5, 6), 'alice')
            window = MainWindow(session=session, sync=False)
            buttons = window.dock_controls.widgets['buttons']
            try:
                self.app.processEvents()
                buttons['next_labeled_time'].click()
                self.assertEqual(session.current_time, .6)
                self.assertEqual(window.subwindows[1].frame_idx, 1)
                self.assertIn('tail', window.subwindows[1].labels['label'])
                with patch.object(window.synchronizer, 'publish') as publish:
                    buttons['next_labeled_time'].click()
                    self.assertEqual(session.current_time, 1.5)
                    publish.assert_called_once_with(1.5)
                buttons['previous_labeled_time'].click()
                self.assertEqual(session.current_time, .6)
                QTest.keyClick(window, Qt.Key.Key_D, Qt.KeyboardModifier.ShiftModifier)
                self.assertEqual(session.current_time, 1.5)
                QTest.keyClick(window, Qt.Key.Key_A, Qt.KeyboardModifier.ShiftModifier)
                self.assertEqual(session.current_time, .6)
                camera = window.subwindows[0]
                camera.setFloating(True)
                camera.show()
                self.app.processEvents()
                QTest.keyClick(camera.plot_wget, Qt.Key.Key_D, Qt.KeyboardModifier.ShiftModifier)
                self.assertEqual(session.current_time, 1.5)
                QTest.keyClick(camera.plot_wget, Qt.Key.Key_A, Qt.KeyboardModifier.ShiftModifier)
                self.assertEqual(session.current_time, .6)
                QTest.keyClick(camera.plot_wget, Qt.Key.Key_D)
                self.assertEqual(session.current_time, 1.)
                QTest.keyClick(camera.plot_wget, Qt.Key.Key_A)
                self.assertEqual(session.current_time, .6)
                session.config['controls']['buttons']['next_labeled_time'] = False
                QTest.keyClick(window, Qt.Key.Key_D, Qt.KeyboardModifier.ShiftModifier)
                self.assertEqual(session.current_time, .6)
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

    def test_four_cameras_tile_into_equal_quarters(self):
        with tempfile.TemporaryDirectory() as folder:
            session = make_session(folder)
            session.cameras *= 2
            session.config['allowed_cams'] = list(range(4))
            session.timeline = Timeline(session.timeline.camera_times * 2)
            session.annotations = AnnotationStore(4)
            session.references = AnnotationStore(4)
            window = MainWindow(session=session, sync=False)
            try:
                window.showNormal()
                window.resize(1600, 1000)
                self.app.processEvents()
                for _ in range(2):
                    window.arrange_cameras('tile_view')
                    self.app.processEvents()
                    first, second, third, fourth = [dock.geometry()
                                                    for dock in window.subwindows.values()]
                    self.assertEqual(first.y(), second.y())
                    self.assertEqual(third.y(), fourth.y())
                    self.assertEqual(first.x(), third.x())
                    self.assertEqual(second.x(), fourth.x())
                    self.assertLess(first.right(), second.left())
                    self.assertLess(first.bottom(), third.top())
                    for rect in (second, third, fourth):
                        self.assertAlmostEqual(first.width(), rect.width(), delta=1)
                        self.assertAlmostEqual(first.height(), rect.height(), delta=1)
                    window.arrange_cameras('tab_view')
                    self.app.processEvents()
            finally:
                window.close()
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

    def test_marker_batches_reuse_items_and_clear_stale_coordinates(self):
        with tempfile.TemporaryDirectory() as folder:
            window = MainWindow(session=make_session(folder), sync=False)
            camera = window.subwindows[0]
            items = dict(camera.marker_items)
            lines = camera.error_lines
            scene_items = tuple(camera.plot_wget.items())
            points = tuple(Point(f'p{i}', (i, i + 1)) for i in range(100))
            refs = tuple(Point(p.name, (p.coords[0] + 2, p.coords[1] + 3), 'ref_label')
                         for p in points)
            try:
                for _ in range(3):
                    camera.set_annotations(FrameAnnotations(points, refs, ()), 'p0')
                    self.assertEqual(len(items['label'].points()), 100)
                    self.assertEqual(len(items['ref_label'].points()), 100)
                    self.assertFalse(items['guess_label'].isVisible())
                    x, y = lines.getData()
                    np.testing.assert_array_equal(np.column_stack((x, y)),
                                                  [xy for p, r in zip(points, refs)
                                                   for xy in (p.coords, r.coords)])
                    self.assertEqual(lines.opts['connect'], 'pairs')
                    self.assertTrue(lines.isVisible())
                    self.assertGreater(items['label'].zValue(), lines.zValue())
                    self.assertGreater(lines.zValue(), camera.img_item.zValue())

                    # A new frame moves a label into the guess layer. It must not
                    # retain its old marker or draw an error line to the guess.
                    guess = Point('p0', (8, 9), 'guess_label')
                    camera.set_annotations(FrameAnnotations((guess,), refs[:1], ()), 'p0')
                    self.assertFalse(items['label'].isVisible())
                    self.assertEqual(len(items['label'].points()), 0)
                    np.testing.assert_array_equal(items['guess_label'].getData(), [[8], [9]])
                    self.assertFalse(lines.isVisible())
                    self.assertEqual(len(lines.getData()[0]), 0)

                    camera.set_annotations(FrameAnnotations((), (), ()))
                    for kind, item in items.items():
                        self.assertIs(camera.marker_items[kind], item)
                        self.assertFalse(item.isVisible())
                        self.assertEqual(len(item.points()), 0)
                    self.assertIs(camera.error_lines, lines)
                    self.assertEqual(tuple(camera.plot_wget.items()), scene_items)
            finally:
                window.close()
                window.deleteLater()
                self.app.processEvents()

    def test_batched_selection_reference_filter_and_annotation_deletion(self):
        with tempfile.TemporaryDirectory() as folder:
            session = make_session(folder)
            session.annotations.set_point('nose', 0, 0, (1, 2), 'alice')
            session.annotations.set_point('tail', 1, 0, (3, 4), 'alice')
            session.references.set_point('nose', 0, 0, (5, 6), 'ref')
            session.references.set_point('tail', 0, 0, (7, 8), 'ref')
            window = MainWindow(session=session, sync=False)
            camera = window.subwindows[0]

            def assert_marker(kind, name, color, size):
                spot = next(p for p in camera.marker_items[kind].points() if p.data() == name)
                self.assertEqual(spot.brush().color(), QColor(color))
                self.assertEqual(spot.size(), size)

            try:
                assert_marker('label', 'nose', 'darkgreen', 8)
                assert_marker('guess_label', 'tail', 'cyan', 6)
                assert_marker('ref_label', 'nose', 'red', 6)
                window.set_current_label('tail')
                assert_marker('label', 'nose', 'cyan', 6)
                assert_marker('guess_label', 'tail', 'darkgreen', 8)
                window.checkbox_disp_ref_annotated.setChecked(False)
                self.assertEqual(len(camera.marker_items['ref_label'].points()), 2)
                assert_marker('ref_label', 'tail', 'red', 6)
                self.assertEqual(len(camera.error_lines.getData()[0]), 2)
                window.checkbox_disp_ref_annotated.setChecked(True)
                self.assertEqual(len(camera.marker_items['ref_label'].points()), 1)
                window.set_current_label('nose')
                window.viewer_click(1, 2, 0, 0, 'delete_label')
                self.assertFalse(camera.marker_items['label'].isVisible())
                self.assertFalse(camera.marker_items['ref_label'].isVisible())
                self.assertFalse(camera.error_lines.isVisible())
                camera.set_current_label(None)
                assert_marker('guess_label', 'tail', 'cyan', 6)
            finally:
                window.close()
                window.deleteLater()
                self.app.processEvents()

    def test_trajectory_menu_selection_batching_and_frame_navigation(self):
        with tempfile.TemporaryDirectory() as folder:
            session = make_session(folder)
            for camera in range(2):
                session.annotations.set_point('nose', 2, camera, (3 + camera, 4), 'alice')
                session.annotations.set_point('nose', 0, camera, (1 + camera, 2), 'alice')
            session.annotations.set_point('tail', 1, 0, (5, 6), 'alice')
            session.annotations.set_point('tail', 3, 0, (7, 8), 'alice')
            window = MainWindow(session=session, sync=False)
            first, second = window.subwindows.values()
            item = first.trajectory_item
            scene_items = tuple(first.plot_wget.items())
            actions = {action.data(): action for action in window.trajectory_actions.actions()}
            try:
                self.assertTrue(actions['off'].isChecked())
                self.assertFalse(item.isVisible())
                with patch.object(first, 'redraw_frame') as redraw:
                    actions['active'].trigger()
                    redraw.assert_not_called()
                self.assertTrue(item.isVisible())
                self.assertFalse(actions['off'].isChecked())
                np.testing.assert_array_equal(item.getData(), [[1, 3], [2, 4]])
                np.testing.assert_array_equal(second.trajectory_item.getData(), [[2, 4], [2, 4]])
                window.set_current_label('tail')
                np.testing.assert_array_equal(item.getData(), [[5, 7], [6, 8]])
                self.assertFalse(second.trajectory_item.isVisible())
                actions['all'].trigger()
                self.assertFalse(actions['active'].isChecked())
                np.testing.assert_array_equal(item.getData(), [[1, 3, 5, 7], [2, 4, 6, 8]])
                np.testing.assert_array_equal(item.opts['connect'], [True, False, True, False])
                self.assertTrue(second.trajectory_item.isVisible())
                with patch.object(session.annotations, 'trajectories') as build:
                    window.set_time(.5, mqtt_publish=False)
                    window.set_current_label('nose')
                    build.assert_not_called()
                self.assertIs(first.trajectory_item, item)
                self.assertEqual(tuple(first.plot_wget.items()), scene_items)
                self.assertGreater(item.zValue(), first.img_item.zValue())
                self.assertLess(item.zValue(), first.marker_items['label'].zValue())
                self.app.processEvents()
                actions['off'].trigger()
                self.assertFalse(item.isVisible())
                self.assertFalse(second.trajectory_item.isVisible())
            finally:
                window.close()
                window.deleteLater()
                self.app.processEvents()

    def test_trajectories_refresh_after_edits_and_deletion_while_hidden(self):
        with tempfile.TemporaryDirectory() as folder:
            session = make_session(folder)
            window = MainWindow(session=session, sync=False)
            item = window.subwindows[0].trajectory_item
            actions = {action.data(): action for action in window.trajectory_actions.actions()}
            try:
                actions['active'].trigger()
                self.assertFalse(item.isVisible())
                window.viewer_click(1, 2, 0, 0)
                self.assertTrue(item.isVisible())  # A single sample still has a dot.
                np.testing.assert_array_equal(item.getData(), [[1], [2]])
                window.set_time(1, mqtt_publish=False)
                window.viewer_click(3, 4, 2, 0)
                np.testing.assert_array_equal(item.getData(), [[1, 3], [2, 4]])
                window.viewer_click(5, 6, 2, 0)
                np.testing.assert_array_equal(item.getData(), [[1, 5], [2, 6]])
                window.viewer_click(5, 6, 2, 0, 'delete_label')
                np.testing.assert_array_equal(item.getData(), [[1], [2]])
                actions['off'].trigger()
                window.set_time(0, mqtt_publish=False)
                window.viewer_click(1, 2, 0, 0, 'delete_label')
                actions['active'].trigger()
                self.assertFalse(item.isVisible())
                self.assertEqual(item.getData(), (None, None))
                window.viewer_click(7, 8, 0, 0)
                self.assertTrue(item.isVisible())
                np.testing.assert_array_equal(item.getData(), [[7], [8]])
            finally:
                window.close()
                window.deleteLater()
                self.app.processEvents()

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
