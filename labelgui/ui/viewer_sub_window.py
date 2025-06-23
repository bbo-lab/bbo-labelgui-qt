import logging
import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import pyqtSignal
from PyQt5.Qt import Qt
from PyQt5.QtWidgets import QMdiSubWindow

logger = logging.getLogger(__name__)

class LabelSubWindow(QMdiSubWindow):
    mouse_clicked_signal = pyqtSignal(float, float)
    plot_params = {
        'label': {'symbol':'o', 'symbolBrush': 'cyan', 'symbolSize': 4},
        'current_label': {'symbol':'o', 'symbolBrush': 'darkgreen', 'symbolSize': 6},
        'ref_label': {'symbol':'x', 'symbolBrush': 'red', 'symbolSize': 4},
        'error_line': {}
    }

    def __init__(self):

        super().__init__("LabelSubWindow")
        self.setWindowFlags(Qt.CustomizeWindowHint | Qt.WindowTitleHint)

        self.plot_wget = pg.PlotWidget(enableMenu=False)
        self.plot_wget_wget.invertY(True)
        self.plot_wget.showAxes(False)  # frame it with a full set of axes
        self.plot_wget.scene().sigMouseClicked.connect(self.mouse_clicked)
        self.setWidget(self.plot_wget)

        self.recording = None
        self.img_item = None


    def redraw(self, frame_idx):
        img = self.recording.get_data(frame_idx)

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

    def draw_label(self, x, y, label_type='label', guess=False):
        label_params = self.plot_params[label_type]
        if guess:
            label_params['symbol'] = '+'
        self.plot_wget.plot([x], [y], **label_params)

    def mouse_clicked(self, event):
        vb = self.plot_wget.plotItem.vb
        scene_coords = event.scenePos()
        if self.plot_wget.sceneBoundingRect().contains(scene_coords):
            mouse_point = vb.mapSceneToView(scene_coords)
            self.mouse_clicked_signal.emit(mouse_point.x(), mouse_point.y())

