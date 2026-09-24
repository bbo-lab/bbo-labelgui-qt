import logging

import numpy as np
from PySide6.QtCore import Qt, Signal, QTimer, QSignalBlocker
from PySide6.QtWidgets import QApplication, QDockWidget, QLabel, QDoubleSpinBox, QWidget, QVBoxLayout, QHBoxLayout, QCheckBox, QPushButton
import pyqtgraph as pg

logger = logging.getLogger(__name__)


class CustomViewBox(pg.ViewBox):
    mouse_wheel_signal = Signal(int)

    def __init__(self, parent=None, *args, **kwargs):
        super().__init__(parent=parent, *args, **kwargs)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self.mouse_wheel_signal.emit(event.delta())
            event.accept()
        else:
            super().wheelEvent(event)


class ViewerSubWindow(QDockWidget):
    """A camera view that can be docked, tabbed, or floated onto another screen."""
    mouse_clicked_signal = Signal(float, float, int, int, str)
    key_pressed_signal = Signal(object)
    marker_params = {
        'label': {'symbol': 'o', 'brush': 'cyan', 'size': 6},
        'guess_label': {'symbol': '+', 'brush': 'cyan', 'size': 6},
        'ref_label': {'symbol': 'x', 'brush': 'red', 'size': 6},
    }

    def __init__(self, index: int, camera, parent=None, img_item=None):

        super().__init__(parent)
        self.setObjectName(f'camera_{index}')
        self.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable
                         | QDockWidget.DockWidgetFeature.DockWidgetFloatable)
        self.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)

        self.index = index
        self.camera = camera
        self.img_item = img_item
        self.rot_angle = 0.0  # Clockwise angle in degrees
        self.frame_idx = None
        self.labels = {kind: [] for kind in self.marker_params}
        self.current_label_name = None

        main_widget = QWidget()
        main_layout = QVBoxLayout(main_widget)

        self.view_box = CustomViewBox(enableMenu=False)
        self.plot_wget = pg.PlotWidget(viewBox=self.view_box)
        self.plot_wget.invertY(True)
        self.plot_wget.showAxes(False)  # whether to frame it with a full set of axes
        self.plot_wget.scene().sigMouseClicked.connect(self.mouse_clicked)
        main_layout.addWidget(self.plot_wget)

        # Keep one scene item per marker type and reuse brushes for symbol caching.
        self.marker_brushes = {kind: pg.mkBrush(params['brush'])
                               for kind, params in self.marker_params.items()}
        self.current_label_brush = pg.mkBrush('darkgreen')
        self.marker_items = {}
        for kind, params in self.marker_params.items():
            item = pg.ScatterPlotItem(pen=None, pxMode=True, **params)
            item.setZValue(10)
            item.hide()
            self.plot_wget.addItem(item)
            self.marker_items[kind] = item
        self.error_lines = pg.PlotCurveItem(pen=pg.mkPen('red', width=2), connect='pairs')
        self.error_lines.setZValue(5)
        self.error_lines.hide()
        self.plot_wget.addItem(self.error_lines)

        self.trajectory_item = pg.PlotDataItem(
            pen=pg.mkPen((0, 255, 255, 130), width=1), symbol='o', symbolSize=3,
            symbolPen=None, symbolBrush=pg.mkBrush(0, 255, 255, 130),
        )
        self.trajectory_item.setZValue(2)
        self.trajectory_item.hide()
        self.plot_wget.addItem(self.trajectory_item)

        # Contrast options
        bottom_widget = QWidget()
        bottom_layout = QHBoxLayout(bottom_widget)
        bottom_layout.addWidget(QLabel("Intensity:"))

        self.checkbox_adjust_level = QCheckBox('Adjust')
        self.checkbox_adjust_level.setChecked(True)
        bottom_layout.addWidget(self.checkbox_adjust_level)

        self.label_vmin = QLabel("vmin")
        self.box_vmin = QDoubleSpinBox()
        self.box_vmin.setKeyboardTracking(False)
        bottom_layout.addWidget(self.label_vmin)
        bottom_layout.addWidget(self.box_vmin)

        self.label_vmax = QLabel("vmax")
        self.box_vmax = QDoubleSpinBox()
        self.box_vmax.setKeyboardTracking(False)
        bottom_layout.addWidget(self.label_vmax)
        bottom_layout.addWidget(self.box_vmax)
        bottom_layout.addStretch()

        self.label_labeler = QLabel("")
        bottom_layout.addWidget(self.label_labeler)

        self.dock_button = QPushButton('Dock')
        self.dock_button.setToolTip('Return this camera to the main window')
        self.dock_button.clicked.connect(lambda: self.setFloating(False))
        self.dock_button.hide()
        bottom_layout.addWidget(self.dock_button)

        self.set_intensity_range()
        main_layout.addWidget(bottom_widget)
        self.setWidget(main_widget)
        self._decoration_timer = QTimer(self)
        self._decoration_timer.setSingleShot(True)
        self._decoration_timer.timeout.connect(self._ensure_floating_window_flags)
        self.topLevelChanged.connect(self._floating_changed)

    def _floating_changed(self, floating):
        self.dock_button.setVisible(floating)
        if not floating:
            self._decoration_timer.stop()
            self.setWindowState(Qt.WindowState.WindowNoState)
            return
        self._ensure_floating_window_flags()

    def showEvent(self, event):
        super().showEvent(event)
        if self.isFloating():
            # Qt can reset flags again at the end of a dock drag, without another
            # topLevelChanged signal. Recheck after its show operation completes.
            self._decoration_timer.start(0)

    def _ensure_floating_window_flags(self):
        if not self.isFloating() or not self.isVisible():
            return
        # Recreating a native window during dragging would break its mouse grab.
        if QApplication.mouseButtons() != Qt.MouseButton.NoButton:
            self._decoration_timer.start(50)
            return

        # Qt assigns tool/frameless flags when a dock floats on some platforms.
        # Request a regular decorated window, including native resize and
        # minimize/maximize controls. Qt resets the flags when docking again.
        flags = (Qt.WindowType.Window | Qt.WindowType.CustomizeWindowHint
                 | Qt.WindowType.WindowTitleHint | Qt.WindowType.WindowSystemMenuHint
                 | Qt.WindowType.WindowMinimizeButtonHint | Qt.WindowType.WindowMaximizeButtonHint)
        if self.windowFlags() == flags:
            return
        geometry = self.geometry()
        visible = self.isVisible()
        self.setWindowFlags(flags)
        self.setGeometry(geometry)
        # Changing flags hides/recreates the native window.
        if visible:
            self.show()

    def keyPressEvent(self, event):
        # Floating docks are separate windows, so unhandled keys need an explicit
        # route to the session shortcuts. Editors still consume their own keys.
        event.ignore()
        self.key_pressed_signal.emit(event)
        if not event.isAccepted():
            super().keyPressEvent(event)

    def set_camera(self, camera, frame_index):
        self.camera = camera
        self.frame_idx = frame_index
        self.set_intensity_range()
        self.redraw_frame()
        self.plot_wget.autoRange()

    def redraw_frame(self):
        if self.frame_idx is None:
            if self.img_item is not None:
                self.img_item.clear()
            return

        img = self.camera.frame(self.frame_idx)
        levels = [self.box_vmin.value(), self.box_vmax.value()]
        if np.issubdtype(img.dtype, np.integer):
            levels = [int(value) for value in levels]
        img = np.clip(img, *levels)

        adjust_level = self.checkbox_adjust_level.isChecked()
        if not adjust_level:
            levels = [self.box_vmin.minimum(), self.box_vmax.maximum()]

        if self.img_item is None:
            self.img_item = pg.ImageItem(img, axisOrder='row-major', autoLevels=True)
            self.plot_wget.addItem(self.img_item)
            self.plot_wget.setAspectLocked(True)

        else:
            self.img_item.setImage(img, levels=levels)

        img_y, img_x = img.shape[:2]
        max_size = max(img_x, img_y)
        self.plot_wget.setLimits(xMin=(img_x - max_size) / 2,
                                 xMax=(img_x + max_size) / 2,
                                 yMin=(img_y - max_size) / 2,
                                 yMax=(img_y + max_size) / 2)

    def rotate_view(self, rot_angle: None | float = None):
        if rot_angle is not None:
            self.rot_angle = rot_angle % 360

        local_center = self.view_box.boundingRect().center()
        self.view_box.setTransformOriginPoint(local_center)
        self.view_box.setRotation(self.rot_angle)

    def set_trajectories(self, paths):
        """Batch all paths into one plot, without joining different markers."""
        coords = np.concatenate(paths) if paths else np.empty((0, 2))
        connect = np.ones(len(coords), dtype=bool)
        if paths:
            connect[np.cumsum([len(path) for path in paths]) - 1] = False
        self.trajectory_item.setData(coords[:, 0], coords[:, 1], connect=connect)
        self.trajectory_item.setVisible(bool(len(coords)))

    def set_annotations(self, view, current_label=None):
        """Replace a frame's coordinates without adding or removing scene items."""
        self.labels = {kind: [] for kind in self.marker_items}
        for point in (*view.points, *view.references):
            self.labels[point.kind].append(point)
        self.current_label_name = current_label
        for kind in self.marker_items:
            self._update_markers(kind)

        actual = {point.name: point.coords for point in self.labels['label']}
        segments = [(actual[point.name], point.coords) for point in self.labels['ref_label']
                    if point.name in actual]
        coords = np.asarray(segments, dtype=float).reshape(-1, 2)
        self.error_lines.setData(coords[:, 0], coords[:, 1])
        self.error_lines.setVisible(bool(segments))

    def _update_markers(self, kind):
        labels = self.labels[kind]
        selected = [kind != 'ref_label' and point.name == self.current_label_name for point in labels]
        item = self.marker_items[kind]
        item.setData(
            pos=[point.coords for point in labels], data=[point.name for point in labels],
            symbol=[point.marker or self.marker_params[kind]['symbol'] for point in labels],
            brush=[self.current_label_brush if active else self.marker_brushes[kind]
                   for active in selected],
            size=[8 if active else self.marker_params[kind]['size'] for active in selected],
        )
        item.setVisible(bool(labels))

    def set_current_label(self, label_name: str | None):
        if label_name == self.current_label_name:
            return
        previous = self.current_label_name
        self.current_label_name = label_name
        for kind in ('label', 'guess_label'):
            if any(point.name in (previous, label_name) for point in self.labels[kind]):
                self._update_markers(kind)

    def mouse_clicked(self, event):
        """
       Handle mouse click events on the plot widget.

        This method processes mouse click events on the plot widget, determining the type of action
        (e.g., create, select, or delete a label) based on the mouse button and keyboard modifiers used.
        It emits a signal with the coordinates of the click, the current frame index, the sub-window index,
        and the determined action string.

        Args:
            event: The mouse click event.

        Returns:
            None
        """
        if self.frame_idx is None:
            return

        scene_coords = event.scenePos()
        modifiers = QApplication.keyboardModifiers()

        if self.plot_wget.sceneBoundingRect().contains(scene_coords):
            mouse_point = self.view_box.mapSceneToView(scene_coords)

            # Left click
            if event.button() == Qt.MouseButton.LeftButton:
                if modifiers == Qt.KeyboardModifier.ShiftModifier:
                    action_str = 'select_label'
                elif modifiers == Qt.KeyboardModifier.ControlModifier:
                    action_str = 'select_ref_label'
                elif modifiers == Qt.KeyboardModifier.AltModifier:
                    action_str = 'auto_label'
                else:
                    action_str = 'create_label'
            # Right click
            elif event.button() == Qt.MouseButton.RightButton:
                action_str = 'delete_label'
            else:
                return

            self.mouse_clicked_signal.emit(mouse_point.x(), mouse_point.y(),
                                           self.frame_idx, self.index, action_str)
            logger.log(logging.DEBUG, f"Clicked on sub-window {self.index} at {mouse_point.x()}, {mouse_point.y()}")

    def set_intensity_range(self):
        min_int, max_int = self.camera.intensity_range()
        with QSignalBlocker(self.box_vmin), QSignalBlocker(self.box_vmax):
            for field in (self.box_vmin, self.box_vmax):
                field.setDecimals(0 if isinstance(min_int, int) else 6)
                field.setRange(min_int, max_int)
            self.box_vmin.setValue(min_int)
            self.box_vmax.setValue(max_int)

    def box_vmin_change(self, value: float):
        if value < self.box_vmax.value():
            self.redraw_frame()
        else:
            self.box_vmin.setValue(self.box_vmax.value() - 10 ** -self.box_vmin.decimals())

    def box_vmax_change(self, value: float):
        if value > self.box_vmin.value():
            self.redraw_frame()
        else:
            self.box_vmax.setValue(self.box_vmin.value() + 10 ** -self.box_vmax.decimals())

    def connect_controls(self):
        self.box_vmin.valueChanged.connect(self.box_vmin_change)
        self.box_vmax.valueChanged.connect(self.box_vmax_change)
        self.checkbox_adjust_level.stateChanged.connect(self.redraw_frame)
