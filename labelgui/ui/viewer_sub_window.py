import logging
import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import pyqtSignal
from PyQt5.Qt import Qt
from PyQt5.QtWidgets import QMdiSubWindow

logger = logging.getLogger(__name__)

class ViewerSubWindow(QMdiSubWindow):
    mouse_clicked_signal = pyqtSignal(float, float)
    plot_params = {
        'label': {'symbol':'o', 'symbolBrush': 'cyan', 'symbolSize': 5},
        'current_label': {'symbol':'o', 'symbolBrush': 'darkgreen', 'symbolSize': 8},
        'ref_label': {'symbol':'x', 'symbolBrush': 'red', 'symbolSize': 5},
        'error_line': {}
    }

    def __init__(self, reader, parent=None, img_item=None):

        super().__init__(parent)
        # TODO: It will be ideal to have minimize and maximize buttons without close button
        self.setWindowFlags(Qt.CustomizeWindowHint | Qt.WindowTitleHint)

        self.reader = reader
        self.img_item = img_item
        self.labels = {label_key: {} for label_key in self.plot_params}

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
            label_params = self.plot_params[label_type]
            if guess:
                label_params['symbol'] = '+'
            self.labels[label_type][label_name] = self.plot_wget.plot([x], [y], **label_params)
        else:
            self.labels[label_type][label_name].setData([x], [y])

    def mouse_clicked(self, event):
        vb = self.plot_wget.plotItem.vb
        scene_coords = event.scenePos()
        if self.plot_wget.sceneBoundingRect().contains(scene_coords):
            mouse_point = vb.mapSceneToView(scene_coords)
            self.mouse_clicked_signal.emit(mouse_point.x(), mouse_point.y())

    def clear_label(self, label_name:str, label_type='label'):
        label_item = self.labels[label_type].pop(label_name, None)
        self.plot_wget.removeItem(label_item)

    def clear_all_labels(self):
        self.plot_wget.clearPlots()
        self.labels = {label_key: {} for label_key in self.plot_params}
