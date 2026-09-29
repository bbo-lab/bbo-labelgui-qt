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
from PySide6.QtWidgets import QApplication, QDockWidget, QTabBar

from labelgui.ui.main_window import MainWindow
from labelgui.ui.video_filters_dialog import VideoFiltersDialog
from labelgui.select_user import SelectUserWindow
from labelgui.core.jobs import JobRepository
from labelgui.core.annotations import AnnotationStore, FrameAnnotations, Point
from labelgui.core.timeline import Timeline
from test_core import FilteredReader, make_session
from test_local_search import PeakReader


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_alt_click_and_to_next_share_radius_and_camera_selection(self):
        with tempfile.TemporaryDirectory() as folder:
            session = make_session(folder)
            for camera in session.cameras:
                camera.reader = PeakReader()
            window = MainWindow(session=session, sync=False)
            first, second = window.subwindows.values()
            radius = window.dock_controls.widgets['fields']['search_radius']
            button = window.dock_controls.widgets['buttons']['track_next']
            try:
                first.setFloating(True)
                first.resize(640, 480)
                first.show()
                self.app.processEvents()
                self.assertFalse(button.isEnabled())
                radius.setText('2')
                self.assertEqual(session.search_radius, 2)
                first.box_vmax.setValue(30)  # Display clipping must not affect the search.
                scene_pos = first.view_box.mapViewToScene(QPointF(3, 5))
                point = first.plot_wget.mapFromScene(scene_pos)
                QTest.mouseClick(first.plot_wget.viewport(), Qt.MouseButton.LeftButton,
                                 Qt.KeyboardModifier.AltModifier, pos=point)
                self.assertEqual(session.annotations.point('nose', 0, 0), (4, 5))
                self.assertTrue(button.isEnabled())
                with patch.object(window.synchronizer, 'publish') as publish:
                    button.click()
                    publish.assert_called_once_with(.5)
                self.assertEqual(session.annotations.point('nose', 1, 0), (5, 5))
                self.assertEqual(session.current_time, .5)
                first.setFloating(False)
                window.arrange_cameras('tab_view')
                self.app.processEvents()
                tabs = next(bar for bar in window.camera_workspace.findChildren(QTabBar) if bar.count() == 2)
                index = next(i for i in range(tabs.count()) if tabs.tabText(i) == second.windowTitle())
                QTest.mouseClick(tabs, Qt.MouseButton.LeftButton, pos=tabs.tabRect(index).center())
                self.app.processEvents()
                self.assertEqual(window.active_camera, 1)
                self.assertFalse(button.isEnabled())
                window.viewer_click(5, 5, 1, 1)
                self.assertTrue(button.isEnabled())
                button.click()
                self.assertEqual(session.current_time, 1.1)
                self.assertEqual(session.annotations.point('nose', 2, 1), (6, 5))
                window.set_current_label('tail')
                self.assertFalse(button.isEnabled())
                window.set_current_label('nose')
                for text in ('', '-1', '0', 'abc', '1.5'):
                    radius.setText(text)
                    self.assertFalse(radius.hasAcceptableInput())
                    self.assertFalse(button.isEnabled())
                revision = session.annotations.revision
                window.viewer_click(5, 5, 2, 1, 'auto_label')
                self.assertEqual(session.annotations.revision, revision)
                radius.setText('3')
                self.assertTrue(button.isEnabled())
                window.viewer_click(6, 5, 2, 1, 'delete_label')
                self.assertFalse(button.isEnabled())
                # Focusing a floated camera changes the target without placing a label.
                first.setFloating(True)
                first.show()
                first.activateWindow()
                first.plot_wget.setFocus()
                self.app.processEvents()
                self.assertEqual(window.active_camera, 0)
                self.assertIn('cam0.avi', window.dock_controls.widgets['labels']['tracking_camera'].text())
            finally:
                window.close()
                window.deleteLater()
                self.app.processEvents()

    def test_reference_symbols_share_one_plot_and_survive_filtering_and_frame_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            session = make_session(folder)
            session.references = [AnnotationStore(2), AnnotationStore(2)]
            session.reference_markers = ['s', 'd']
            session.annotations.set_point('nose', 0, 0, (1, 2), 'alice')
            session.references[0].set_point('nose', 0, 0, (2, 3), 'ref')
            session.references[1].set_point('nose', 0, 0, (3, 4), 'ref')
            session.references[1].set_point('tail', 0, 0, (4, 5), 'ref')
            window = MainWindow(session=session, sync=False)
            camera = window.subwindows[0]
            item = camera.marker_items['ref_label']
            try:
                self.assertEqual([p.symbol() for p in item.points()], ['s', 'd'])
                self.assertEqual([p.data() for p in item.points()], ['nose', 'nose'])
                self.assertEqual(camera.marker_items['label'].points()[0].symbol(), 'o')
                self.assertEqual(len(camera.error_lines.getData()[0]), 4)
                window.checkbox_disp_ref_annotated.setChecked(False)
                self.assertEqual([p.symbol() for p in item.points()], ['s', 'd', 'd'])
                window.viewer_click(4, 5, 0, 0, 'select_ref_label')
                self.assertEqual(session.current_label, 'tail')
                self.assertEqual([p.symbol() for p in item.points()], ['s', 'd', 'd'])
                window.set_time(.5, mqtt_publish=False)
                self.assertFalse(item.isVisible())
                window.set_time(0, mqtt_publish=False)
                self.assertIs(camera.marker_items['ref_label'], item)
                self.assertEqual([p.symbol() for p in item.points()], ['s', 'd', 'd'])
                self.app.processEvents()
            finally:
                window.close()
                window.deleteLater()
                self.app.processEvents()

    def test_video_filters_refresh_existing_views_and_dialog(self):
        with tempfile.TemporaryDirectory() as folder:
            session = make_session(folder)
            session.cameras[0].filter_string = 'old_filter'
            session.seek(2.1)
            session.annotations.set_point('nose', 2, 0, (1, 2), 'alice')
            window = MainWindow(session=session, sync=False)
            first, second = window.subwindows.values()
            image = first.img_item
            try:
                self.app.processEvents()
                second.setFloating(True)
                self.app.processEvents()
                dialog = VideoFiltersDialog(session.cameras, window)
                self.assertEqual(dialog.filters, ['old_filter', ''])
                dialog.fields[0].setText('crop=size=8x6')
                self.assertEqual(dialog.filters, ['crop=size=8x6', ''])
                dialog.deleteLater()
                with patch.object(session, 'reader_factory', side_effect=lambda _: FilteredReader()), \
                        patch.object(window.synchronizer, 'publish') as publish:
                    self.assertTrue(window.apply_video_filters(['crop=size=8x6', 'crop=size=8x6']))
                    publish.assert_called_once_with(.5)
                self.assertIs(window.subwindows[0], first)
                self.assertIs(first.img_item, image)
                self.assertTrue(second.isFloating())
                self.assertIs(first.camera, session.cameras[0])
                self.assertEqual(first.frame_idx, 2)
                self.assertEqual(first.img_item.image.shape, (6, 8))
                self.assertEqual(first.box_vmax.maximum(), 1.)
                self.assertEqual(first.box_vmin.decimals(), 6)
                self.assertEqual(first.view_box.state['limits']['xLimits'], [0., 8.])
                self.assertEqual(first.view_box.state['limits']['yLimits'], [-1., 7.])
                self.assertEqual(window.dock_controls.widgets['fields']['current_time'].text(), '0.5')
                self.assertEqual(len(first.marker_items['label'].points()), 1)
                first.box_vmin.setValue(.25)
                self.assertEqual(first.box_vmin.value(), .25)
                original_camera = first.camera
                with patch.object(session, 'reader_factory', side_effect=ValueError('invalid filter')), \
                        patch('labelgui.ui.main_window.QMessageBox.critical') as error, \
                        self.assertLogs('labelgui.ui.main_window', level='ERROR'):
                    self.assertFalse(window.apply_video_filters(['invalid', 'crop=size=8x6']))
                    error.assert_called_once()
                self.assertIs(first.camera, original_camera)
                self.assertFalse(original_camera.reader.closed)
                with patch('labelgui.ui.main_window.VideoFiltersDialog') as dialog_type, \
                        patch.object(window, 'apply_video_filters', return_value=True) as apply:
                    dialog_type.return_value.exec.return_value = VideoFiltersDialog.DialogCode.Accepted
                    dialog_type.DialogCode.Accepted = VideoFiltersDialog.DialogCode.Accepted
                    dialog_type.return_value.filters = ['', '']
                    window.edit_video_filters()
                    apply.assert_called_once_with(['', ''])
                with patch.object(VideoFiltersDialog, 'exec', return_value=VideoFiltersDialog.DialogCode.Rejected), \
                        patch.object(session, 'set_video_filters') as change:
                    window.edit_video_filters()
                    change.assert_not_called()
            finally:
                window.close()
                window.deleteLater()
                self.app.processEvents()

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
                self.assertIn('nose', [p.name for p in camera.labels['label']])
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
                self.assertIn('nose', [p.name for p in camera.labels['label']])
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
                self.assertIn('tail', [p.name for p in window.subwindows[1].labels['label']])
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

    def test_next_previous_buttons_follow_ordered_selection_with_duplicates(self):
        with tempfile.TemporaryDirectory() as folder:
            session = make_session(folder)
            session.timeline = Timeline(session.timeline.camera_times, labeling_times=[1.5, .5, .5, 1])
            window = MainWindow(session=session, sync=False)
            buttons = window.dock_controls.widgets['buttons']
            try:
                self.assertEqual(session.current_time, 1.5)
                buttons['next_time'].click()
                self.assertEqual((session.current_time, session.timeline.current_index), (.5, 1))
                buttons['next_time'].click()
                self.assertEqual((session.current_time, session.timeline.current_index), (.5, 2))
                buttons['next_time'].click()
                self.assertEqual((session.current_time, session.timeline.current_index), (1, 3))
                buttons['previous_time'].click()
                self.assertEqual((session.current_time, session.timeline.current_index), (.5, 2))
                buttons['single_label_mode'].click()
                window.viewer_click(3, 4, session.frame_index(0), 0)
                self.assertEqual((session.current_time, session.timeline.current_index), (1, 3))
            finally:
                window.close()
                window.deleteLater()
                self.app.processEvents()

    def test_single_label_mode_mouse_toggle_off_stops_advancing(self):
        with tempfile.TemporaryDirectory() as folder:
            session = make_session(folder)
            session.cameras[0].reader = PeakReader()
            window = MainWindow(session=session, sync=False)
            camera = window.subwindows[0]
            camera.setFloating(True)
            camera.resize(640, 480)
            camera.show()
            window.dock_controls.setFloating(True)
            window.dock_controls.resize(420, 620)
            window.dock_controls.show()
            self.app.processEvents()
            button = window.dock_controls.widgets['buttons']['single_label_mode']

            def place(modifier=Qt.KeyboardModifier.NoModifier, mouse_button=Qt.MouseButton.LeftButton):
                point = camera.plot_wget.mapFromScene(camera.view_box.mapViewToScene(QPointF(6, 5)))
                QTest.mouseClick(camera.plot_wget.viewport(), mouse_button, modifier, pos=point)

            try:
                self.assertFalse(button.isChecked())
                self.assertFalse(session.single_label_mode)
                for _ in range(3):
                    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
                    self.assertTrue(button.isChecked())
                    self.assertTrue(session.single_label_mode)
                    time = session.current_time
                    place()
                    self.assertGreater(session.current_time, time)
                    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
                    self.assertFalse(button.isChecked())
                    self.assertFalse(session.single_label_mode)
                    time = session.current_time
                    with patch.object(window.synchronizer, 'publish') as publish:
                        place()
                        self.assertEqual(session.current_time, time)
                        place(Qt.KeyboardModifier.AltModifier)
                        self.assertEqual(session.current_time, time)
                        place(mouse_button=Qt.MouseButton.RightButton)
                        self.assertEqual(session.current_time, time)
                        publish.assert_not_called()
                    self.assertFalse(button.isChecked())
                    self.assertFalse(session.single_label_mode)
                # Trajectory navigation remains independent of auto-advance.
                session.annotations.set_point('tail', 3, 0, (9, 8), 'alice')
                revision = session.annotations.revision
                actions = {action.data(): action for action in window.trajectory_actions.actions()}
                actions['all'].trigger()
                point = camera.plot_wget.mapFromScene(camera.view_box.mapViewToScene(QPointF(9, 8)))
                QTest.mouseClick(camera.plot_wget.viewport(), Qt.MouseButton.LeftButton,
                                 Qt.KeyboardModifier.ShiftModifier, pos=point)
                self.assertEqual(session.current_time, 1.5)
                self.assertEqual(session.current_label, 'tail')
                self.assertEqual(session.annotations.revision, revision)
                self.assertFalse(button.isChecked())
                self.assertFalse(session.single_label_mode)
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
                self.assertIn('nose', [p.name for p in window.subwindows[0].labels['label']])
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
            reference = AnnotationStore(2)
            reference.set_point('nose', 0, 0, (5, 6), 'ref')
            reference.set_point('tail', 0, 0, (7, 8), 'ref')
            session.references.append(reference)
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

    def test_reference_lines_connect_adjacent_files_without_bridging_missing_markers(self):
        with tempfile.TemporaryDirectory() as folder:
            session = make_session(folder)
            session.annotations.set_point('nose', 0, 0, (1, 2), 'alice')
            for index in range(3):
                reference = AnnotationStore(2)
                reference.set_point('nose', 0, 0, (3 + index, 4 + index), 'ref')
                # A missing marker in the middle file must break the chain.
                if index != 1:
                    reference.set_point('tail', 0, 0, (10 + index, 11 + index), 'ref')
                session.references.append(reference)
            window = MainWindow(session=session, sync=False)
            camera = window.subwindows[0]
            lines = camera.reference_lines
            scene_items = tuple(camera.plot_wget.items())
            try:
                self.assertEqual(lines.opts['pen'].color(), QColor('red'))
                self.assertLess(lines.opts['pen'].widthF(), camera.error_lines.opts['pen'].widthF())
                self.assertEqual(lines.opts['connect'], 'pairs')
                self.assertLess(lines.zValue(), camera.marker_items['ref_label'].zValue())
                self.assertTrue(lines.isVisible())
                np.testing.assert_array_equal(lines.getData(), [[3, 4, 4, 5], [4, 5, 5, 6]])
                self.assertEqual(len(camera.error_lines.getData()[0]), 6)
                self.assertFalse(window.subwindows[1].reference_lines.isVisible())

                window.checkbox_disp_ref_annotated.setChecked(False)
                self.assertEqual(len(camera.marker_items['ref_label'].points()), 5)
                np.testing.assert_array_equal(lines.getData(), [[3, 4, 4, 5], [4, 5, 5, 6]])
                # Reference connections also work when there is no user label.
                window.viewer_click(1, 2, 0, 0, 'delete_label')
                self.assertFalse(camera.error_lines.isVisible())
                self.assertTrue(lines.isVisible())
                window.checkbox_disp_ref_annotated.setChecked(True)
                self.assertFalse(lines.isVisible())
                self.assertEqual(len(lines.getData()[0]), 0)
                window.checkbox_disp_ref_annotated.setChecked(False)
                self.assertTrue(lines.isVisible())

                window.set_time(.5)
                self.assertFalse(lines.isVisible())
                self.assertEqual(len(lines.getData()[0]), 0)
                window.set_time(0)
                self.assertTrue(lines.isVisible())
                self.assertIs(camera.reference_lines, lines)
                self.assertEqual(tuple(camera.plot_wget.items()), scene_items)
            finally:
                window.close()
                window.deleteLater()
                self.app.processEvents()

    def test_multiple_references_preserve_duplicate_names_and_selection(self):
        with tempfile.TemporaryDirectory() as folder:
            session = make_session(folder)
            session.annotations.set_point('nose', 0, 0, (1, 2), 'alice')
            for coords in ((5, 6), (9, 10)):
                reference = AnnotationStore(2)
                reference.set_point('nose', 0, 0, coords, 'ref')
                session.references.append(reference)
            session.references[1].set_point('tail', 0, 0, (7, 8), 'ref')
            window = MainWindow(session=session, sync=False)
            camera = window.subwindows[0]
            try:
                refs = camera.marker_items['ref_label']
                np.testing.assert_array_equal(refs.getData(), [[5, 9], [6, 10]])
                for point in refs.points():
                    self.assertEqual(point.data(), 'nose')
                    self.assertEqual(point.brush().color(), QColor('red'))
                    self.assertEqual(point.symbol(), 'x')
                    self.assertEqual(point.size(), 6)
                np.testing.assert_array_equal(camera.error_lines.getData(),
                                              [[1, 5, 1, 9], [2, 6, 2, 10]])
                for x, y in ((5, 6), (9, 10)):
                    window.set_current_label('tail')
                    window.viewer_click(x, y, 0, 0, 'select_ref_label')
                    self.assertEqual(session.current_label, 'nose')
                window.checkbox_disp_ref_annotated.setChecked(False)
                self.assertEqual(len(refs.points()), 3)
                window.viewer_click(7, 8, 0, 0, 'select_ref_label')
                self.assertEqual(session.current_label, 'tail')
                window.checkbox_disp_ref_annotated.setChecked(True)
                self.assertEqual(len(refs.points()), 2)
                window.set_time(.5)
                self.assertFalse(refs.isVisible())
                self.assertEqual(len(refs.points()), 0)
                self.assertFalse(camera.error_lines.isVisible())
            finally:
                window.close()
                window.deleteLater()
                self.app.processEvents()

    def test_shift_click_selects_nearest_visible_label_or_trajectory_and_plain_click_places(self):
        with tempfile.TemporaryDirectory() as folder:
            session = make_session(folder)
            session.annotations.set_point('nose', 0, 0, (2, 2), 'alice')
            session.annotations.set_point('tail', 0, 0, (4, 2), 'alice')
            session.annotations.set_point('tail', 2, 0, (10, 8), 'alice')
            revision = session.annotations.revision
            window = MainWindow(session=session, sync=False)
            camera = window.subwindows[0]
            camera.setFloating(True)
            camera.resize(640, 480)
            camera.show()
            actions = {action.data(): action for action in window.trajectory_actions.actions()}
            actions['all'].trigger()
            self.app.processEvents()

            def click(x, y, modifier=Qt.KeyboardModifier.ShiftModifier):
                point = camera.plot_wget.mapFromScene(camera.view_box.mapViewToScene(QPointF(x, y)))
                QTest.mouseClick(camera.plot_wget.viewport(), Qt.MouseButton.LeftButton, modifier, pos=point)

            try:
                # Clicks are well outside the tiny symbols; nearest selection still works.
                with patch.object(window.synchronizer, 'publish') as publish:
                    click(5, 2)
                    self.assertEqual((session.current_time, session.current_label), (0, 'tail'))
                    publish.assert_not_called()
                    click(9, 7)
                    self.assertEqual((session.current_time, session.current_label), (1, 'tail'))
                    publish.assert_called_once_with(1)
                window.set_time(0, mqtt_publish=False)
                window.set_current_label('nose')
                actions['off'].trigger()
                click(9, 7)
                self.assertEqual((session.current_time, session.current_label), (0, 'tail'))
                self.assertEqual(session.annotations.revision, revision)

                actions['all'].trigger()
                window.set_current_label('nose')
                with patch.object(window.synchronizer, 'publish') as publish:
                    click(10, 8, Qt.KeyboardModifier.NoModifier)
                    self.assertEqual((session.current_time, session.current_label), (0, 'nose'))
                    publish.assert_not_called()
                np.testing.assert_allclose(session.annotations.point('nose', 0, 0), (10, 8), atol=.05)
                self.assertGreater(session.annotations.revision, revision)
                # Exact overlapping coordinates prefer the current label, not a future frame.
                session.annotations.set_point('nose', 0, 0, (10, 8), 'alice')
                window._render_frame(images=False)
                window.set_current_label('tail')
                camera.rotate_view(90)
                self.app.processEvents()
                revision = session.annotations.revision
                click(10.5, 8.5)
                self.assertEqual((session.current_time, session.current_label), (0, 'nose'))
                self.assertEqual(session.annotations.revision, revision)
            finally:
                window.close()
                window.deleteLater()
                self.app.processEvents()

    def test_trajectory_clicks_navigate_or_log_without_creating_labels(self):
        with tempfile.TemporaryDirectory() as folder:
            session = make_session(folder)
            session.timeline = Timeline(session.timeline.camera_times, labeling_times=[.1, .6])
            session.annotations.set_point('nose', 0, 1, (2, 2), 'alice')
            session.annotations.set_point('tail', 1, 1, (7, 5), 'alice')
            session.annotations.set_point('tail', 3, 1, (9, 8), 'alice')
            revision = session.annotations.revision
            window = MainWindow(session=session, sync=False)
            camera = window.subwindows[1]
            camera.setFloating(True)
            camera.resize(640, 480)
            camera.show()
            actions = {action.data(): action for action in window.trajectory_actions.actions()}
            actions['all'].trigger()
            self.app.processEvents()

            def click(x, y, modifiers=Qt.KeyboardModifier.ShiftModifier):
                scene_pos = camera.view_box.mapViewToScene(QPointF(x, y))
                point = camera.plot_wget.mapFromScene(scene_pos)
                QTest.mouseClick(camera.plot_wget.viewport(), Qt.MouseButton.LeftButton,
                                 modifiers, pos=point)

            try:
                self.assertEqual([p.data() for p in camera.trajectory_item.scatter.points()],
                                 [('nose', 0), ('tail', 1), ('tail', 3)])
                with patch.object(window.synchronizer, 'publish') as publish:
                    with self.assertLogs('labelgui.core.session', level='INFO') as logs:
                        click(9, 8)
                    self.assertIn('outside the allowed time selection', logs.output[0])
                    publish.assert_not_called()
                    self.assertEqual((session.current_time, session.current_label), (.1, 'nose'))
                    click(7, 5)
                    publish.assert_called_once_with(.6)
                    self.assertEqual((session.current_time, session.current_label), (.6, 'tail'))
                    self.assertEqual(camera.frame_idx, 1)
                    self.assertEqual(window.active_camera, 1)
                    self.assertEqual(window.dock_sketch.list_labels.currentItem().text(), 'tail')
                click(2, 2, Qt.KeyboardModifier.ShiftModifier)
                self.assertEqual((session.current_time, session.current_label), (.1, 'nose'))
                self.assertEqual(session.annotations.revision, revision)
                # Active-only trajectories use the same click metadata after a rotated view.
                window.set_current_label('tail')
                actions['active'].trigger()
                camera.rotate_view(90)
                self.app.processEvents()
                click(7, 5)
                self.assertEqual((session.current_time, session.current_label), (.6, 'tail'))
                self.assertEqual(session.annotations.revision, revision)
                # Hidden trajectories must not intercept normal label placement.
                actions['off'].trigger()
                click(9, 8, Qt.KeyboardModifier.NoModifier)
                self.assertGreater(session.annotations.revision, revision)
                self.assertEqual(session.current_time, .6)
            finally:
                window.close()
                window.deleteLater()
                self.app.processEvents()

    def test_trajectory_time_filter_menu_preserves_metadata_and_plot_items(self):
        with tempfile.TemporaryDirectory() as folder:
            session = make_session(folder, trajectory_only_allowed_times=True)
            session.timeline = Timeline(session.timeline.camera_times, labeling_times=[0, 1])
            for frame in range(3):
                session.annotations.set_point('nose', frame, 0, (frame + 2, 3), 'alice')
            session.annotations.set_point('tail', 1, 0, (7, 8), 'alice')
            window = MainWindow(session=session, sync=False)
            camera = window.subwindows[0]
            item = camera.trajectory_item
            scene_items = tuple(camera.plot_wget.items())
            actions = {action.data(): action for action in window.trajectory_actions.actions()}
            try:
                self.assertTrue(window.trajectory_time_filter.isChecked())
                actions['all'].trigger()
                self.assertEqual([p.data() for p in item.scatter.points()], [('nose', 0), ('nose', 2)])
                np.testing.assert_array_equal(item.getData(), [[2, 4], [3, 3]])
                with patch.object(camera, 'redraw_frame') as redraw:
                    window.trajectory_time_filter.setChecked(False)
                    self.assertEqual(len(item.scatter.points()), 4)
                    window.trajectory_time_filter.setChecked(True)
                    redraw.assert_not_called()
                window.set_current_label('tail')
                actions['active'].trigger()
                self.assertFalse(item.isVisible())
                actions['off'].trigger()
                window.trajectory_time_filter.setChecked(False)
                self.assertFalse(item.isVisible())
                actions['active'].trigger()
                self.assertEqual([p.data() for p in item.scatter.points()], [('tail', 1)])
                window.trajectory_time_filter.setChecked(True)
                # Timeline replacement (e.g. video filters) invalidates the cached paths.
                session.timeline = Timeline(session.timeline.camera_times, labeling_times=[.5])
                window._render_frame()
                self.assertTrue(item.isVisible())
                self.assertIs(camera.trajectory_item, item)
                self.assertEqual(tuple(camera.plot_wget.items()), scene_items)
            finally:
                window.close()
                window.deleteLater()
                self.app.processEvents()

    def test_trajectory_click_override_menu_and_yaml_default(self):
        with tempfile.TemporaryDirectory() as folder:
            session = make_session(folder, trajectory_allow_outside_times=True)
            session.timeline = Timeline(session.timeline.camera_times, labeling_times=[0, 1])
            session.annotations.set_point('tail', 1, 0, (7, 5), 'alice')
            revision = session.annotations.revision
            window = MainWindow(session=session, sync=False)
            camera = window.subwindows[0]
            camera.setFloating(True)
            camera.resize(640, 480)
            camera.show()
            actions = {action.data(): action for action in window.trajectory_actions.actions()}
            actions['all'].trigger()
            self.app.processEvents()

            def click():
                point = camera.plot_wget.mapFromScene(camera.view_box.mapViewToScene(QPointF(7, 5)))
                QTest.mouseClick(camera.plot_wget.viewport(), Qt.MouseButton.LeftButton,
                                 Qt.KeyboardModifier.ShiftModifier, pos=point)

            try:
                self.assertTrue(window.trajectory_allow_outside.isChecked())
                with patch.object(window.synchronizer, 'publish') as publish:
                    click()
                    self.assertEqual((session.current_time, session.current_label), (.5, 'tail'))
                    self.assertEqual(camera.frame_idx, 1)
                    publish.assert_called_once_with(.5)
                window.goto_next_time()
                self.assertEqual(session.current_time, 1)
                click()
                window.goto_previous_time()
                self.assertEqual(session.current_time, 0)
                window.set_current_label('nose')
                window.trajectory_allow_outside.setChecked(False)
                with self.assertLogs('labelgui.core.session', level='INFO'):
                    click()
                self.assertEqual((session.current_time, session.current_label), (0, 'nose'))
                self.assertEqual(session.annotations.revision, revision)
                np.testing.assert_array_equal(session.timeline.times, [0, 1])
            finally:
                window.close()
                window.deleteLater()
                self.app.processEvents()

    def test_reference_trajectory_menu_batches_files_and_filters_independently(self):
        with tempfile.TemporaryDirectory() as folder:
            session = make_session(folder)
            session.annotations.set_point('nose', 0, 0, (1, 1), 'alice')
            session.references = [AnnotationStore(2), AnnotationStore(2)]
            session.reference_markers = ['o', 's']
            for frame, coords in ((0, (2, 3)), (2, (4, 5))):
                session.references[0].set_point('nose', frame, 0, coords, 'ref0')
            for frame, coords in ((1, (8, 5)), (3, (10, 8))):
                session.references[1].set_point('nose', frame, 0, coords, 'ref1')
            session.references[1].set_point('tail', 2, 0, (6, 6), 'ref1')
            session.timeline = Timeline(session.timeline.camera_times, labeling_times=[0, 1])
            window = MainWindow(session=session, sync=False)
            camera = window.subwindows[0]
            item = camera.reference_trajectory_item
            scene_items = tuple(camera.plot_wget.items())
            actions = {action.data(): action for action in window.reference_trajectory_actions.actions()}
            label_actions = {action.data(): action for action in window.trajectory_actions.actions()}
            try:
                self.assertTrue(actions['off'].isChecked())
                self.assertFalse(item.isVisible())
                actions['all'].trigger()
                self.assertFalse(camera.trajectory_item.isVisible())
                self.assertFalse(window.subwindows[1].reference_trajectory_item.isVisible())
                self.assertEqual([p.data() for p in item.scatter.points()],
                                 [('nose', 0, 0), ('nose', 2, 0), ('nose', 1, 1), ('nose', 3, 1), ('tail', 2, 1)])
                self.assertEqual([p.symbol() for p in item.scatter.points()], ['o', 'o', 's', 's', 's'])
                np.testing.assert_array_equal(item.opts['connect'], [True, False, True, False, False])
                self.assertEqual(item.opts['pen'].color().getRgb()[:3], (255, 0, 0))
                window.reference_trajectory_time_filter.setChecked(True)
                self.assertFalse(window.trajectory_time_filter.isChecked())
                self.assertEqual([p.data() for p in item.scatter.points()],
                                 [('nose', 0, 0), ('nose', 2, 0), ('tail', 2, 1)])
                actions['active'].trigger()
                window.set_current_label('tail')
                self.assertEqual([p.data() for p in item.scatter.points()], [('tail', 2, 1)])
                with patch.object(session.references[1], 'trajectories') as build:
                    window.set_time(1, mqtt_publish=False)
                    build.assert_not_called()
                session.references[1].delete_point('tail', 2, 0, 'ref1')
                window._render_frame(images=False)
                self.assertFalse(item.isVisible())
                window.set_current_label('nose')
                label_actions['all'].trigger()
                self.assertTrue(camera.trajectory_item.isVisible())
                actions['off'].trigger()
                self.assertTrue(camera.trajectory_item.isVisible())
                self.assertFalse(item.isVisible())
                self.assertIs(camera.reference_trajectory_item, item)
                self.assertEqual(tuple(camera.plot_wget.items()), scene_items)
            finally:
                window.close()
                window.deleteLater()
                self.app.processEvents()

    def test_control_click_reference_trajectories_respects_independent_time_options(self):
        with tempfile.TemporaryDirectory() as folder:
            session = make_session(folder, trajectory_allow_outside_times=True,
                                   reference_trajectory_only_allowed_times=False,
                                   reference_trajectory_allow_outside_times=False)
            session.timeline = Timeline(session.timeline.camera_times, labeling_times=[.1, .6])
            session.annotations.set_point('nose', 0, 1, (2, 2), 'alice')
            session.annotations.set_point('nose', 3, 1, (9, 8), 'alice')
            session.references = [AnnotationStore(2), AnnotationStore(2)]
            session.references[0].set_point('tail', 1, 1, (7, 5), 'ref0')
            session.references[0].set_point('tail', 3, 1, (9, 8), 'ref0')
            session.references[1].set_point('tail', 2, 1, (12, 3), 'ref1')
            revisions = [store.revision for store in [session.annotations, *session.references]]
            window = MainWindow(session=session, sync=False)
            camera = window.subwindows[1]
            camera.setFloating(True)
            camera.resize(640, 480)
            camera.show()
            for group in (window.trajectory_actions, window.reference_trajectory_actions):
                next(action for action in group.actions() if action.data() == 'all').trigger()
            self.app.processEvents()

            def click(x, y, modifier=Qt.KeyboardModifier.ControlModifier):
                point = camera.plot_wget.mapFromScene(camera.view_box.mapViewToScene(QPointF(x, y)))
                QTest.mouseClick(camera.plot_wget.viewport(), Qt.MouseButton.LeftButton, modifier, pos=point)

            try:
                self.assertFalse(window.reference_trajectory_allow_outside.isChecked())
                self.assertFalse(window.reference_trajectory_time_filter.isChecked())
                with self.assertLogs('labelgui.core.session', level='INFO') as logs:
                    click(11.5, 3.5)
                self.assertIn('reference[1]', logs.output[0])
                self.assertEqual((session.current_time, session.current_label), (.1, 'nose'))
                window.reference_trajectory_allow_outside.setChecked(True)
                with patch.object(window.synchronizer, 'publish') as publish:
                    click(11.5, 3.5)
                    publish.assert_called_once_with(1.1)
                self.assertEqual((session.current_time, session.current_label), (1.1, 'tail'))
                self.assertEqual(camera.frame_idx, 2)
                window.reference_trajectory_time_filter.setChecked(True)
                click(9, 8)  # The nearer excluded samples are hidden.
                self.assertEqual(session.current_time, .6)
                window.reference_trajectory_time_filter.setChecked(False)
                window.reference_trajectory_allow_outside.setChecked(False)
                window.set_current_label('nose')
                window.checkbox_disp_ref_annotated.setChecked(False)
                with patch.object(window.synchronizer, 'publish') as publish:
                    click(7, 5)  # Current reference marker wins the tie and only selects.
                    publish.assert_not_called()
                self.assertEqual((session.current_time, session.current_label), (.6, 'tail'))
                click(9, 8, Qt.KeyboardModifier.ShiftModifier)
                self.assertEqual((session.current_time, session.current_label), (1.6, 'nose'))
                self.assertEqual([store.revision for store in [session.annotations, *session.references]], revisions)
                click(12, 3, Qt.KeyboardModifier.NoModifier)
                self.assertEqual(session.current_time, 1.6)
                self.assertGreater(session.annotations.revision, revisions[0])
                self.assertEqual([store.revision for store in session.references], revisions[1:])
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
