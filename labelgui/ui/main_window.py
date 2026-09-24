"""Qt presentation and event bindings for a headless LabelingSession."""
import logging
import math
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QActionGroup
from PySide6.QtWidgets import QApplication, QFileDialog, QMainWindow, QMessageBox

from labelgui.core.configuration import job_config_path
from labelgui.core.session import LabelingSession
from labelgui.core.synchronization import TimeSynchronizer
from labelgui.select_user import SelectUserWindow
from .controls_dock import ControlsDock
from .sketch_dock import SketchDock
from .viewer_sub_window import ViewerSubWindow
from .video_filters_dialog import VideoFiltersDialog

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    mqtt_message_signal = Signal(float)

    def __init__(self, drive: Path = None, file_config=None, parent=None,
                 sync: str | bool = False, *, session=None):
        super().__init__(parent)
        if session is None:
            if drive is None or not Path(drive).is_dir():
                raise ValueError('The base data directory does not exist')
            user, job, accepted = SelectUserWindow.start(Path(drive))
            if not accepted:
                raise SystemExit(0)
            config_path = Path(file_config) if file_config else job_config_path(drive, user, job)
            session = LabelingSession.open(drive, user, config_path)
        self.session = session
        self.subwindows = {}
        self.active_camera = None
        self.camera_workspace = QMainWindow(self)
        self.camera_workspace.setWindowFlags(Qt.WindowType.Widget)
        self.camera_workspace.setDockOptions(QMainWindow.DockOption.AllowNestedDocks
                                            | QMainWindow.DockOption.AllowTabbedDocks
                                            | QMainWindow.DockOption.AnimatedDocks)
        self._camera_layout = 'tab_view'
        self.trajectory_mode = 'off'
        self._trajectory_key = None
        self.dock_sketch = SketchDock()
        self.dock_controls = ControlsDock()
        self.synchronizer = TimeSynchronizer(sync, self.mqtt_message_signal.emit)
        self.mqtt_message_signal.connect(lambda t: self.set_time(t, mqtt_publish=False))
        self._build_menus()
        self._build_viewers()
        self._connect_controls()
        self.camera_workspace.tabifiedDockWidgetActivated.connect(
            lambda dock: self._set_active_camera(dock.index))
        QApplication.instance().focusChanged.connect(self._camera_focus_changed)
        self._set_active_camera(next(iter(self.subwindows), None))
        self.setCentralWidget(self.camera_workspace)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock_sketch)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock_controls)
        self.resizeDocks([self.dock_sketch, self.dock_controls], [600, 600], Qt.Orientation.Horizontal)
        self.setWindowTitle(f'Labeling GUI - {session.dataset_name}')
        self._render_sketch()
        self._render_frame()
        self.synchronizer.connect()
        self.save_timer = QTimer(self)
        self.save_timer.timeout.connect(self._check_saves)
        self.save_timer.start(500)
        self.showMaximized()
        self.setFocus()

    def _build_menus(self):
        self.menuBar().addMenu('&File').addAction('Save Labels As...', self.save_labels_as)
        menu = self.menuBar().addMenu('&View')
        menu.addAction('&Tab (single cam view)', lambda: self.arrange_cameras('tab_view'))
        menu.addAction('&Tile', lambda: self.arrange_cameras('tile_view'))
        menu.addAction('&Dock All Cameras', self.dock_all_cameras)
        menu.addAction('Video &Filters...', self.edit_video_filters)
        trajectories = menu.addMenu('&Trajectories')
        self.trajectory_actions = QActionGroup(self)
        self.trajectory_actions.setExclusive(True)
        for mode, text in (('off', '&Hidden'), ('active', '&Active marker'), ('all', '&All markers')):
            action = trajectories.addAction(text)
            action.setCheckable(True)
            action.setData(mode)
            action.setChecked(mode == self.trajectory_mode)
            self.trajectory_actions.addAction(action)
        self.trajectory_actions.triggered.connect(self._trajectory_mode_changed)
        menu.addSection('Reference labels')
        self.checkbox_disp_ref_annotated = menu.addAction('&Only Display Annotated')
        self.checkbox_disp_ref_annotated.setCheckable(True)
        self.checkbox_disp_ref_annotated.setChecked(self.session.only_annotated_references)
        self.checkbox_disp_ref_annotated.toggled.connect(self._reference_filter_changed)

    def _build_viewers(self):
        for index, camera in enumerate(self.session.cameras):
            if index in self.session.config['allowed_cams']:
                window = ViewerSubWindow(index=index, camera=camera, parent=self.camera_workspace)
                window.setWindowTitle(f'{camera.path.name} ({index})')
                window.connect_controls()
                window.mouse_clicked_signal.connect(self.viewer_click)
                window.view_box.mouse_wheel_signal.connect(
                    lambda delta, camera=index: self.viewer_wheel_event(delta, camera))
                window.key_pressed_signal.connect(self._handle_shortcut)
                self.subwindows[index] = window
                self.camera_workspace.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, window)
        self.arrange_cameras(self._camera_layout)

    def _connect_controls(self):
        cfg = self.session.config['controls']
        sketch = self.dock_sketch
        sketch.sketch_zoom_scale = self.session.config.get('sketch_zoom_scale', 0.1)
        sketch.set_sketch_names([f'Sketch {i:03d}' for i in range(len(self.session.sketches))])
        sketch.connect_label_buttons(cfg)
        sketch.label_selected.connect(self.set_current_label)
        sketch.sketch_selected.connect(self.sketch_select)
        sketch.point_selected.connect(self._sketch_point_selected)
        actions = {'save_labels': self.save_labels, 'zoom_out': self.viewer_zoom_reset,
                   'rotate': self.viewer_rotate, 'previous_time': self.goto_previous_time,
                   'next_time': self.goto_next_time,
                   'previous_labeled_time': self.goto_previous_labeled_time,
                   'next_labeled_time': self.goto_next_labeled_time}
        for name, callback in actions.items():
            button = self.dock_controls.widgets['buttons'][name]
            button.setEnabled(cfg['buttons'].get(name, name in (
                'rotate', 'previous_labeled_time', 'next_labeled_time')))
            button.clicked.connect(lambda checked=False, action=callback: action())
        single = self.dock_controls.widgets['buttons']['single_label_mode']
        single.setEnabled(cfg['buttons'].get('single_label_mode', True))
        single.setChecked(self.session.single_label_mode)
        single.toggled.connect(self._single_label_mode_changed)
        for name, callback in (('current_time', self.field_current_time_changed),
                               ('d_time', self.set_d_time)):
            field = self.dock_controls.widgets['fields'][name]
            field.setEnabled(cfg['fields'].get(name, True))
            field.editingFinished.connect(callback)
        self.dock_controls.widgets['fields']['d_time'].setText(str(self.session.d_time))
        radius = self.dock_controls.widgets['fields']['search_radius']
        radius.setEnabled(True)
        radius.setText(str(self.session.search_radius))
        radius.textChanged.connect(self._search_radius_changed)
        self.dock_controls.widgets['buttons']['track_next'].clicked.connect(self.track_next)

    def _camera_focus_changed(self, previous, current):
        for camera, window in self.subwindows.items():
            if current is window or (current is not None and window.isAncestorOf(current)):
                self._set_active_camera(camera)
                break

    def _set_active_camera(self, camera):
        if camera not in self.subwindows:
            return
        self.active_camera = camera
        self.dock_controls.widgets['labels']['tracking_camera'].setText(
            f'Camera: {self.session.cameras[camera].path.name} ({camera})')
        self._update_tracking_controls()

    def _search_radius_changed(self):
        field = self.dock_controls.widgets['fields']['search_radius']
        if field.hasAcceptableInput():
            self.session.search_radius = field.validator().locale().toInt(field.text())[0]
        self._update_tracking_controls()

    def _update_tracking_controls(self):
        valid_radius = self.dock_controls.widgets['fields']['search_radius'].hasAcceptableInput()
        self.dock_controls.widgets['buttons']['track_next'].setEnabled(
            valid_radius and self.active_camera is not None
            and self.session.can_track_next(self.active_camera))

    def track_next(self):
        self._update_tracking_controls()
        if not self.dock_controls.widgets['buttons']['track_next'].isEnabled():
            return
        try:
            changed = self.session.track_next(self.active_camera)
        except Exception as error:
            QMessageBox.critical(self, 'Could not track marker', str(error))
            return
        if changed:
            self._render_frame()
            self.synchronizer.publish(self.session.current_time)

    def _render_sketch(self):
        self.dock_sketch.display_sketch(self.session.sketch, self.session.current_sketch_index,
                                       self.session.current_label)

    def _render_selection(self):
        self.dock_sketch.display_selection(self.session.current_label)
        for window in self.subwindows.values():
            window.set_current_label(self.session.current_label)
        self._render_trajectories()
        self._update_tracking_controls()

    def _trajectory_mode_changed(self, action):
        self.trajectory_mode = action.data()
        self._render_trajectories()

    def _render_trajectories(self):
        annotations = self.session.annotations
        name = self.session.current_label if self.trajectory_mode == 'active' else None
        key = (annotations.revision, self.trajectory_mode, name)
        if key == self._trajectory_key:
            return
        for camera, window in self.subwindows.items():
            if self.trajectory_mode == 'off':
                window.trajectory_item.hide()
            else:
                names = (name,) if self.trajectory_mode == 'active' else None
                window.set_trajectories(annotations.trajectories(camera, names))
        self._trajectory_key = key

    def _render_frame(self, images=True):
        for camera, window in self.subwindows.items():
            window.frame_idx = self.session.frame_index(camera)
            if images:
                window.redraw_frame()
            view = self.session.frame_annotations(camera)
            window.label_labeler.setText(', '.join(view.labelers))
            window.set_annotations(view, self.session.current_label)
        self.dock_controls.widgets['fields']['current_time'].setText(str(round(self.session.current_time, 6)))
        self._render_selection()

    def _reference_filter_changed(self, checked):
        self.session.only_annotated_references = checked
        self._render_frame(images=False)

    def _single_label_mode_changed(self, checked):
        self.session.single_label_mode = checked

    def viewer_click(self, x, y, cam_frame_idx, cam_idx, action='create_label'):
        self._set_active_camera(cam_idx)
        if action == 'auto_label' and not self.dock_controls.widgets['fields']['search_radius'].hasAcceptableInput():
            return
        previous_time = self.session.current_time
        try:
            changed = self.session.handle_video_action(cam_idx, cam_frame_idx, (x, y), action)
        except Exception as error:
            QMessageBox.critical(self, 'Could not place marker', str(error))
            return
        if changed:
            changed_time = previous_time != self.session.current_time
            self._render_frame(images=changed_time)
            if changed_time:
                self.synchronizer.publish(self.session.current_time)

    def set_current_label(self, name):
        if self.session.select_label(name):
            self._render_selection()

    def _sketch_point_selected(self, x, y):
        self.session.select_sketch_point(x, y)
        self._render_selection()

    def sketch_select(self, index):
        self.session.select_sketch(index)
        self._render_sketch()
        self._render_selection()

    def set_time(self, time, mqtt_publish=True):
        self.session.seek(time)
        self._render_frame()
        if mqtt_publish:
            self.synchronizer.publish(self.session.current_time)

    def move_num_timepoints(self, count):
        self.session.step(count)
        self._render_frame()
        self.synchronizer.publish(self.session.current_time)

    def goto_next_time(self):
        self.move_num_timepoints(1)

    def goto_previous_time(self):
        self.move_num_timepoints(-1)

    def move_labeled_timepoint(self, direction):
        if self.session.step_labeled(direction):
            self._render_frame()
            self.synchronizer.publish(self.session.current_time)

    def goto_next_labeled_time(self):
        self.move_labeled_timepoint(1)

    def goto_previous_labeled_time(self):
        self.move_labeled_timepoint(-1)

    def viewer_wheel_event(self, delta, camera=None):
        if camera is not None:
            self._set_active_camera(camera)
        self.move_num_timepoints(int(round(delta / 120)))

    def field_current_time_changed(self):
        field = self.dock_controls.widgets['fields']['current_time']
        try:
            self.set_time(float(field.text()))
        except ValueError:
            field.setText(str(round(self.session.current_time, 6)))

    def set_d_time(self):
        field = self.dock_controls.widgets['fields']['d_time']
        try:
            self.session.set_time_step(field.text())
        except ValueError:
            field.setText(str(self.session.d_time))
        field.clearFocus()

    def save_labels(self, file=None):
        self.session.save(file, force=file is not None)

    def save_labels_as(self):
        file = QFileDialog.getSaveFileName(self, 'Save Labels As...', '', 'Session File (*.yml)')[0]
        if file:
            self.save_labels(Path(file))

    def _check_saves(self):
        try:
            self.session.saver.check()
        except RuntimeError as error:
            QMessageBox.critical(self, 'Could not save labels', str(error))

    def viewer_rotate(self):
        for window in self.subwindows.values():
            window.rotate_view((window.rot_angle + 90) % 360)

    def viewer_zoom_reset(self):
        for window in self.subwindows.values():
            angle = window.rot_angle
            window.rotate_view(0)
            window.rotate_view(angle)
            window.plot_wget.autoRange()

    def edit_video_filters(self):
        dialog = VideoFiltersDialog(self.session.cameras, self)
        try:
            while dialog.exec() == VideoFiltersDialog.DialogCode.Accepted:
                if self.apply_video_filters(dialog.filters):
                    break
        finally:
            dialog.deleteLater()

    def apply_video_filters(self, filters):
        previous_time = self.session.current_time
        try:
            changed = self.session.set_video_filters(filters)
        except Exception as error:
            logger.exception('Could not apply video filters')
            QMessageBox.critical(self, 'Could not apply video filters', str(error))
            return False
        if changed:
            for index, window in self.subwindows.items():
                camera = self.session.cameras[index]
                if window.camera is not camera:
                    window.set_camera(camera, self.session.frame_index(index))
            self._trajectory_key = None
            self._render_frame()
            if self.session.current_time != previous_time:
                self.synchronizer.publish(self.session.current_time)
        return True

    def arrange_cameras(self, mode):
        """Arrange docked cameras without disturbing floating windows."""
        self._camera_layout = mode
        docks = [dock for dock in self.subwindows.values() if not dock.isFloating()]
        if not docks:
            return
        workspace = self.camera_workspace
        for dock in docks:
            workspace.removeDockWidget(dock)
        for dock in docks:
            workspace.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)
            dock.show()
        if mode == 'tab_view':
            for dock in docks[1:]:
                workspace.tabifyDockWidget(docks[0], dock)
            docks[0].raise_()
            self._set_active_camera(docks[0].index)
        else:
            columns = math.ceil(math.sqrt(len(docks)))
            row_heads = docks[::columns]
            # Create full-width rows before subdividing each row into columns.
            for above, below in zip(row_heads, row_heads[1:]):
                workspace.splitDockWidget(above, below, Qt.Orientation.Vertical)
            for start in range(0, len(docks), columns):
                row = docks[start:start + columns]
                for left, right in zip(row, row[1:]):
                    workspace.splitDockWidget(left, right, Qt.Orientation.Horizontal)
                workspace.resizeDocks(row, [1] * len(row), Qt.Orientation.Horizontal)
            workspace.resizeDocks(row_heads, [1] * len(row_heads), Qt.Orientation.Vertical)

    def dock_all_cameras(self):
        for dock in self.subwindows.values():
            dock.setFloating(False)
            dock.show()
        self.arrange_cameras(self._camera_layout)

    def keyPressEvent(self, event):
        if not self._handle_shortcut(event):
            super().keyPressEvent(event)

    def _handle_shortcut(self, event):
        cfg = self.session.config['controls']['buttons']
        actions = {
            Qt.Key.Key_D: ('next_time', self.goto_next_time),
            Qt.Key.Key_A: ('previous_time', self.goto_previous_time),
            Qt.Key.Key_S: ('save_labels', self.save_labels),
            Qt.Key.Key_O: ('zoom_out', self.viewer_zoom_reset),
            Qt.Key.Key_R: ('rotate', self.viewer_rotate),
            Qt.Key.Key_N: ('next_label', self.dock_sketch.widgets['buttons']['next_label'].click),
            Qt.Key.Key_P: ('previous_label', self.dock_sketch.widgets['buttons']['previous_label'].click),
        }
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            actions[Qt.Key.Key_A] = ('previous_labeled_time', self.goto_previous_labeled_time)
            actions[Qt.Key.Key_D] = ('next_labeled_time', self.goto_next_labeled_time)
        action = actions.get(event.key())
        if action and cfg.get(action[0], action[0] in (
                'rotate', 'previous_labeled_time', 'next_labeled_time')):
            if not event.isAutoRepeat() or action[0] in (
                    'next_time', 'previous_time', 'next_labeled_time', 'previous_labeled_time'):
                action[1]()
            event.accept()
            return True
        return False

    def closeEvent(self, event):
        try:
            self.session.close()
        except Exception as error:
            logger.exception('Could not close labeling session')
            QMessageBox.critical(self, 'Could not save session', f'{error}\nThe session remains open; please retry saving.')
            event.ignore()
            return
        self.save_timer.stop()
        self.synchronizer.close()
        for dock in self.subwindows.values():
            dock.hide()
        event.accept()
