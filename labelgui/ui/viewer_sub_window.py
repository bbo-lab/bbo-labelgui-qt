import logging
import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QApplication, QMdiSubWindow

logger = logging.getLogger(__name__)

class ViewerSubWindow(QMdiSubWindow):
    mouse_clicked_signal = pyqtSignal(int, float, float, str)
    plot_params = {
        'label': {'symbol':'o', 'symbolBrush': 'cyan', 'symbolSize': 6, 'symbolPen': None},
        'current_label': {'symbol':'o', 'symbolBrush': 'darkgreen', 'symbolSize': 8, 'symbolPen': None},
        'ref_label': {'symbol':'x', 'symbolBrush': 'red', 'symbolSize': 6, 'symbolPen': None},
        'error_line': {}
    }

    def __init__(self, index:int, reader, parent=None, img_item=None):

        super().__init__(parent)
        # TODO: It will be ideal to have minimize and maximize buttons without close button
        # self.setWindowFlags(Qt.CustomizeWindowHint | Qt.WindowTitleHint)

        self.index = index
        self.reader = reader
        self.img_item = img_item
        self.labels = {label_key: {} for label_key in self.plot_params}
        self.labels['current_label'] = SingleItemDict()

        self.plot_wget = pg.PlotWidget(enableMenu=False)
        self.plot_wget.invertY(True)
        self.plot_wget.showAxes(False)  # frame it with a full set of axes
        self.plot_wget.scene().sigMouseClicked.connect(self.mouse_clicked)
        self.setWidget(self.plot_wget)

    def redraw_frame(self, frame_idx):
        img = self.reader.get_data(frame_idx)

        if self.img_item is None:
            # img_size = np.max(img.shape[:2])
            img_y, img_x = img.shape[:2]
            self.img_item = pg.ImageItem(img, axisOrder='row-major',
                                         autoLevels=img.dtype != np.uint8)
            self.plot_wget.addItem(self.img_item)
            self.plot_wget.setLimits(xMin=0, yMin=0,
                                xMax=img_x, yMax=img_y)
        else:
            self.img_item.setImage(img, autoLevels=img.dtype != np.uint8)

    def draw_label(self, x:float, y:float, label_name:str, label_type='label', guess=False):
        if label_name not in self.labels[label_type]:
            label_params = self.plot_params[label_type].copy()
            if guess:
                label_params['symbol'] = '+'
            self.labels[label_type][label_name] = self.plot_wget.plot([x], [y], **label_params)
        else:
            self.labels[label_type][label_name].setData([x], [y])

    def mouse_clicked(self, event):
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
                    action_str = 'auto_label'
                else:
                    action_str = 'create_label'
            # Right click
            elif event.button() == 2:
                # TODO: should test
                action_str = 'delete_label'
            else:
                return

            self.mouse_clicked_signal.emit(self.index, mouse_point.x(), mouse_point.y(), action_str)
        # logger.log(logging.INFO, f"Click at  {mouse_point.x()}, {mouse_point.y()}")

    def set_current_label(self, label_name: str or None):
        label_type = 'current_label'
        if  len(self.labels[label_type]) and label_name not in self.labels[label_type]:
            old_label_name = list(self.labels[label_type].keys())[0]
            old_label_item = self.labels[label_type].pop(old_label_name)
            old_label_item.setData(*old_label_item.getData(),
                                   symbolBrush=self.plot_params['label']['symbolBrush'],
                                   symbolSize=self.plot_params['label']['symbolSize'])
            self.labels['label'][old_label_name] = old_label_item

        label_type = 'label'
        if label_name in self.labels[label_type]:
            label_item = self.labels[label_type].pop(label_name)
            label_item.setData(*label_item.getData(),
                               symbolBrush=self.plot_params['current_label']['symbolBrush'],
                               symbolSize=self.plot_params['current_label']['symbolSize'])
            self.labels['current_label'][label_name] = label_item

    def clear_label(self, label_name:str, label_type='label'):
        # Remove the label from the dictionary and the view if it exists
        label_item = self.labels[label_type].pop(label_name, None)
        self.plot_wget.removeItem(label_item)

    def clear_all_labels(self):
        self.plot_wget.clearPlots()
        self.labels = {label_key: {} for label_key in self.plot_params}


class SingleItemDict(dict):
    def __setitem__(self, key, value):
        # Allow if empty, or replacing existing key
        if len(self) == 0 or key in self:
            super().__setitem__(key, value)
        else:
            raise ValueError("SingleItemDict can only contain one item.")

    def update(self, *args, **kwargs):
        # Only allow update if result will have at most one unique key
        new_items = dict(*args, **kwargs)
        combined_keys = set(self.keys()) | set(new_items.keys())
        if len(combined_keys) > 1:
            raise ValueError("SingleItemDict can only contain one item.")
        super().update(new_items)