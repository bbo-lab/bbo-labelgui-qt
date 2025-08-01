import logging

import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QApplication, QMdiSubWindow, QLabel, QSpinBox, QWidget, QVBoxLayout, QHBoxLayout, QCheckBox

logger = logging.getLogger(__name__)


class ViewerSubWindow(QMdiSubWindow):
    mouse_clicked_signal = pyqtSignal(float, float, int, int, str)
    # Necessary to follow camelCase for keys here, for compatibility with pyqtgraph
    plot_params = {
        'label': {'symbol': 'o', 'symbolBrush': 'cyan', 'symbolSize': 6, 'symbolPen': None},
        'guess_label': {'symbol': '+', 'symbolBrush': 'cyan', 'symbolSize': 6, 'symbolPen': None},
        'ref_label': {'symbol': 'x', 'symbolBrush': 'red', 'symbolSize': 6, 'symbolPen': None},

        'current_label': {'symbolBrush': 'darkgreen', 'symbolSize': 8},
        'error_line': {'color': 'red', 'width': 2}
    }

    def __init__(self, index: int, reader, parent=None, img_item=None):

        super().__init__(parent)
        # TODO: It will be ideal to have minimize and maximize buttons without close button
        self.setWindowFlags(Qt.CustomizeWindowHint | Qt.WindowTitleHint)

        self.index = index
        self.reader = reader
        self.img_item = img_item
        self.frame_idx = None
        self.labels = {label_key: {} for label_key in self.plot_params}
        self.current_label_name = None

        main_widget = QWidget()
        main_layout = QVBoxLayout(main_widget)

        self.plot_wget = pg.PlotWidget(enableMenu=False)
        self.plot_wget.invertY(True)
        self.plot_wget.showAxes(False)  # frame it with a full set of axes
        self.plot_wget.scene().sigMouseClicked.connect(self.mouse_clicked)
        main_layout.addWidget(self.plot_wget)

        # Contrast options
        bottom_widget = QWidget()
        bottom_layout = QHBoxLayout(bottom_widget)
        bottom_layout.addWidget(QLabel("Intensity:"))

        self.checkbox_adjust_level = QCheckBox('Adjust')
        self.checkbox_adjust_level.setChecked(True)
        bottom_layout.addWidget(self.checkbox_adjust_level)

        self.label_vmin = QLabel("vmin")
        self.box_vmin = QSpinBox()
        self.box_vmin.setKeyboardTracking(False)
        bottom_layout.addWidget(self.label_vmin)
        bottom_layout.addWidget(self.box_vmin)

        self.label_vmax = QLabel("vmax")
        self.box_vmax = QSpinBox()
        self.box_vmax.setKeyboardTracking(False)
        bottom_layout.addWidget(self.label_vmax)
        bottom_layout.addWidget(self.box_vmax)
        bottom_layout.addStretch()

        self.label_labeler = QLabel("")
        bottom_layout.addWidget(self.label_labeler)

        self.set_intensity_range()
        main_layout.addWidget(bottom_widget)
        self.setWidget(main_widget)

    def redraw_frame(self):
        if self.frame_idx is None:
            if self.img_item is not None:
                self.img_item.clear()
            return

        img = self.reader.get_data(self.frame_idx).copy()
        adjust_level = self.checkbox_adjust_level.isChecked()
        levels = [self.box_vmin.value(), self.box_vmax.value()]
        img = np.clip(img, *levels)
        if not adjust_level:
            levels = [self.box_vmin.minimum(), self.box_vmax.maximum()]

        if self.img_item is None:
            img_y, img_x = img.shape[:2]
            max_size = max(img.shape[:2])
            self.img_item = pg.ImageItem(img, axisOrder='row-major', autoLevels=True)
            self.plot_wget.addItem(self.img_item)
            self.plot_wget.setAspectLocked(True)
            self.plot_wget.setLimits(xMin= (img_x - max_size) / 2,
                                     xMax= (img_x + max_size) / 2,
                                     yMin= (img_y - max_size) / 2,
                                     yMax= (img_y + max_size) / 2)
        else:
            self.img_item.setImage(img, levels=levels)

    def draw_label(self, x: float, y: float, label_name: str, label_type='label', current_label=False):
        """
           Draw a label on the plot widget at the specified coordinates.

           This method adds a label to the plot widget at the given (x, y) coordinates. If the label already exists,
           it updates its position. Optionally, the label can be marked as the current label.

           Args:
               x (float): The x-coordinate of the label.
               y (float): The y-coordinate of the label.
               label_name (str): The name of the label.
               label_type (str, optional): The type of the label (default is 'label').
               current_label (bool, optional): Whether to mark this label as the current label (default is False).

           Returns:
               None
        """
        if label_name not in self.labels[label_type]:
            label_params = self.plot_params[label_type].copy()
            self.labels[label_type][label_name] = self.plot_wget.plot([x], [y], **label_params)
            # The only way is to set this explicitly; all the point labels are set with a Z value of 10
            self.labels[label_type][label_name].setZValue(10)
        else:
            self.labels[label_type][label_name].setData([x], [y])

        if current_label:
            self.set_current_label(label_name)

    def draw_line(self, xs, ys, line_name: str, line_type='error_line'):
        if line_name not in self.labels[line_type]:
            line_params = self.plot_params[line_type].copy()
            line_pen = pg.mkPen(**line_params)
            self.labels[line_type][line_name] = self.plot_wget.plot(xs, ys, pen=line_pen)

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

        vb = self.plot_wget.plotItem.vb
        scene_coords = event.scenePos()
        modifiers = QApplication.keyboardModifiers()

        if self.plot_wget.sceneBoundingRect().contains(scene_coords):
            mouse_point = vb.mapSceneToView(scene_coords)

            # Left click
            if event.button() == 1:
                if modifiers == Qt.ShiftModifier:
                    action_str = 'select_label'
                elif modifiers == Qt.AltModifier:
                    # TODO:
                    action_str = 'auto_label'
                    logger.log(logging.WARNING, "Not yet implemented")
                else:
                    action_str = 'create_label'
            # Right click
            elif event.button() == 2:
                action_str = 'delete_label'
            else:
                return

            self.mouse_clicked_signal.emit(mouse_point.x(), mouse_point.y(),
                                           self.frame_idx, self.index, action_str)
            logger.log(logging.DEBUG, f"Clicked on sub-window {self.index} at {mouse_point.x()}, {mouse_point.y()}")

    def set_current_label(self, label_name: str or None):
        """
        Update the given label as current label, and demote the old current label
        :param label_name: keyword
        :return: None
        """
        for label_type in ['label', 'guess_label']:
            # Change the status of the old 'current_label'
            if self.current_label_name in self.labels[label_type]:
                params = self.plot_params[label_type].copy()
                self.labels[label_type][self.current_label_name].setSymbolBrush(params['symbolBrush'])
                self.labels[label_type][self.current_label_name].setSymbolSize(params['symbolSize'])
            # Set new 'current_label'
            if label_name in self.labels[label_type]:
                params = self.plot_params['current_label'].copy()
                self.labels[label_type][label_name].setSymbolBrush(params['symbolBrush'])
                self.labels[label_type][label_name].setSymbolSize(params['symbolSize'])

        self.current_label_name = label_name

    def set_intensity_range(self):
        img_dtype = self.reader.get_data(0).dtype
        min_int = np.iinfo(img_dtype).min
        max_int = np.iinfo(img_dtype).max
        self.box_vmin.setRange(min_int, max_int)
        self.box_vmin.setValue(min_int)
        self.box_vmax.setRange(min_int, max_int)
        self.box_vmax.setValue(max_int)

    def box_vmin_change(self, value: int):
        if value < self.box_vmax.value():
            self.redraw_frame()
        else:
            self.box_vmin.setValue(self.box_vmax.value() - 1)

    def box_vmax_change(self, value: int):
        if value > self.box_vmin.value():
            self.redraw_frame()
        else:
            self.box_vmax.setValue(self.box_vmin.value() + 1)

    def connect_controls(self):
        self.box_vmin.valueChanged.connect(self.box_vmin_change)
        self.box_vmax.valueChanged.connect(self.box_vmax_change)
        self.checkbox_adjust_level.stateChanged.connect(self.redraw_frame)

    def clear_label(self, label_name: str, label_type='label'):
        # Remove the label from the dictionary and the view if it exists
        label_item = self.labels[label_type].pop(label_name, None)
        self.plot_wget.removeItem(label_item)

    def clear_all_labels(self):
        self.plot_wget.clearPlots()
        self.labels = {label_key: {} for label_key in self.plot_params}
        self.current_label_name = None
