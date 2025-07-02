from PyQt5.QtWidgets import QWidget, QDockWidget, QVBoxLayout, QComboBox, QSizePolicy
from PyQt5.QtCore import pyqtSignal
import numpy as np
from typing import List, Dict, Optional
import logging
from pathlib import Path

from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg


logger = logging.getLogger(__name__)


class SketchDock(QDockWidget):
    sketch_clicked_signal = pyqtSignal(int)

    def __init__(self):

        super().__init__("Sketch")
        self.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)

        self.graph_widgets = {
            # Graphical widgets
            'canvas': {},
            'figs': {},
            'axes': {},
            'highlight_dot': {},
            'highlight_circle': {}
        }
        self.sketches = []
        self.current_sketch_idx = None
        self.sketches_loaded = False

        self.sketch_zoom_scale = 0.1
        self.sketch_zoom_dy = None
        self.sketch_zoom_dx = None

        main_widget = QWidget()
        layout = QVBoxLayout(main_widget)

        self.graph_widgets['figs']['sketch'] = Figure()
        self.graph_widgets['canvas']['sketch'] = FigureCanvasQTAgg(self.graph_widgets['figs']['sketch'])

        # full
        ax_sketch_dims = [0 / 3, 1 / 18, 1 / 3, 16 / 18]
        self.graph_widgets['axes']['sketch'] = self.graph_widgets['figs']['sketch'].add_axes(ax_sketch_dims)

        # zoom
        ax_sketch_zoom_dims = [1 / 3, 5 / 18, 2 / 3, 12 / 18]
        self.graph_widgets['axes']['sketch_zoom'] = self.graph_widgets['figs']['sketch'].add_axes(ax_sketch_zoom_dims)

        layout.addWidget(self.graph_widgets['canvas']['sketch'])

        # Sketch selection combo
        self.combobox_sketches = QComboBox()
        self.combobox_sketches.setDisabled(True)
        layout.addWidget(self.combobox_sketches)

        main_widget.setLayout(layout)
        self.setWidget(main_widget)

    def load_sketches(self, sketch_files: List[Path]):
        # load sketches
        sketches = []
        for sf in sketch_files:
            if sf.exists():
                sketches.append(np.load(sf.as_posix(), allow_pickle=True)[()])
            else:
                logger.log(logging.WARNING, f'Autoloading failed. Sketch file {sf} does not exist.')

        if len(sketches):
            self.sketches = sketches
            self.current_sketch_idx = 0
            self.sketches_loaded = True

    def init_sketch(self):
        sketch = self.get_sketch_image()
        self.set_sketch_zoom()

        # full
        self.graph_widgets['axes']['sketch'].imshow(sketch)
        self.graph_widgets['axes']['sketch'].axis('off')
        self.graph_widgets['axes']['sketch'].set_title('Full:',
                                                       ha='center', va='center',
                                                       zorder=0)

        # zoom
        self.graph_widgets['axes']['sketch_zoom'].imshow(sketch)
        self.graph_widgets['axes']['sketch_zoom'].set_xlim(
            [np.shape(sketch)[1] / 2 - self.sketch_zoom_dx, np.shape(sketch)[1] / 2 + self.sketch_zoom_dx])
        self.graph_widgets['axes']['sketch_zoom'].set_ylim(
            [np.shape(sketch)[0] / 2 - self.sketch_zoom_dy, np.shape(sketch)[0] / 2 + self.sketch_zoom_dy])
        self.graph_widgets['axes']['sketch_zoom'].axis('off')
        self.graph_widgets['axes']['sketch_zoom'].set_title('Zoom:',
                                                            ha='center', va='center',
                                                            zorder=0)

        self.init_sketch_labels()
        self.update_sketch()

    def init_sketch_labels(self):
        # Plot all the labels
        for label_name, label_location in self.get_sketch_labels().items():
            self.graph_widgets['axes']['sketch'].plot([label_location[0]], [label_location[1]],
                                                      marker='o',
                                                      color='orange',
                                                      markersize=3,
                                                      zorder=1)

            self.graph_widgets['axes']['sketch_zoom'].plot([label_location[0]],
                                                           [label_location[1]],
                                                           marker='o',
                                                           color='orange',
                                                           markersize=5,
                                                           zorder=1)
            
        # Init highlight markers
        highlight_dot_params = {
            'color': 'darkgreen',
            'marker': '.',
            'markersize': 2,
            'alpha': 1.0,
            'zorder': 2,
        }
        highlight_circle_params = {
            'color': 'darkgreen',
            'marker': 'o',
            'markersize': 40,
            'markeredgewidth': 4,
            'fillstyle': 'none',
            'alpha': 2 / 3,
            'zorder': 2,
        }
        self.graph_widgets['highlight_dot']['sketch'] = self.graph_widgets['axes']['sketch'].plot(
            [np.nan], [np.nan], **highlight_dot_params)[0]
        self.graph_widgets['highlight_dot']['sketch_zoom'] = self.graph_widgets['axes']['sketch_zoom'].plot(
            [np.nan], [np.nan], **highlight_dot_params)[0]
        self.graph_widgets['highlight_circle']['sketch'] = self.graph_widgets['axes']['sketch'].plot(
            [np.nan], [np.nan], **highlight_circle_params)[0]
        self.graph_widgets['highlight_circle']['sketch_zoom'] = self.graph_widgets['axes']['sketch_zoom'].plot(
            [np.nan], [np.nan], **highlight_circle_params)[0]

    def fill_sketches_combobox(self):
        self.combobox_sketches.setDisabled(False)
        self.combobox_sketches.addItems([f'Sketch {i:03d}'
                                         for i, _ in enumerate(self.sketches)])

    def connect_canvas(self):
        self.graph_widgets['canvas']['sketch'].mpl_connect('button_press_event', self.sketch_click)

    def update_sketch(self, current_label_name=None):
        # Updates labels on the sketch
        sketch_labels = self.get_sketch_labels()

        if current_label_name:
            (x, y) = sketch_labels[current_label_name].astype(np.float32)
        else:
            x, y = (np.nan, np.nan)

        self.graph_widgets['highlight_dot']['sketch'].set_data([x], [y])
        self.graph_widgets['highlight_circle']['sketch'].set_data([x], [y])
        # zoom
        self.graph_widgets['highlight_dot']['sketch_zoom'].set_data([x], [y])
        self.graph_widgets['highlight_circle']['sketch_zoom'].set_data([x], [y])
        if not np.any(np.isnan([x, y])):
            self.graph_widgets['axes']['sketch_zoom'].set_xlim([x - self.sketch_zoom_dx, x + self.sketch_zoom_dx])
            self.graph_widgets['axes']['sketch_zoom'].set_ylim([y - self.sketch_zoom_dy, y + self.sketch_zoom_dy])
        self.graph_widgets['axes']['sketch_zoom'].invert_yaxis()

        self.graph_widgets['canvas']['sketch'].draw()

    def set_sketch_zoom(self):
        sketch = self.get_sketch_image()
        self.sketch_zoom_dx = np.max(np.shape(sketch)) * self.sketch_zoom_scale
        self.sketch_zoom_dy = np.max(np.shape(sketch)) * self.sketch_zoom_scale

    def get_sketch_image(self):
        if self.sketches_loaded:
            return self.sketches[self.current_sketch_idx]['sketch'].astype(np.uint8)
        return None

    def get_sketch_labels(self):
        if self.sketches_loaded:
            return self.sketches[self.current_sketch_idx]['sketch_label_locations']
        return None

    def get_sketch_label_coordinates(self):
        return np.array(list(self.get_sketch_labels().values()), dtype=np.float64)

    def sketch_click(self, event):
        if event.button == 1:
            x = event.xdata
            y = event.ydata
            if (x is not None) & (y is not None):
                label_coordinates = self.get_sketch_label_coordinates()
                dists = ((x - label_coordinates[:, 0]) ** 2 + (y - label_coordinates[:, 1]) ** 2) ** 0.5
                label_index = np.argmin(dists)
                self.sketch_clicked_signal.emit(label_index)

    def clear_sketch(self):
        for ax_key in ['sketch', 'sketch_zoom']:
            self.graph_widgets['axes'][ax_key].clear()
