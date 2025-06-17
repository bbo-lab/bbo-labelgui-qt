from PyQt5.QtWidgets import QDockWidget
import numpy as np

from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg


class SketchDock(QDockWidget):

    def __init__(self):

        super().__init__("Sketch")
        self.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)

        self.widgets = {
            'canvas': {},
            'figs': {},
            'axes': {},
            'highlight_dot': {},
            'highlight_circle': {}
        }
        self.sketch_zoom_scale = 0.1
        self.sketch = None
        self.sketch_zoom_dy = None
        self.sketch_zoom_dx = None

        self.widgets['figs']['sketch'] = Figure()
        self.widgets['canvas']['sketch'] = FigureCanvasQTAgg(self.widgets['figs']['sketch'])

        # full
        ax_sketch_dims = [0 / 3, 1 / 18, 1 / 3, 16 / 18]
        self.widgets['axes']['sketch'] = self.widgets['figs']['sketch'].add_axes(ax_sketch_dims)
        self.widgets['axes']['sketch'].axis('off')
        self.widgets['axes']['sketch'].set_title('Full:',
                                                  ha='center', va='center',
                                                  zorder=0)

        # zoom
        ax_sketch_zoom_dims = [1 / 3, 5 / 18, 2 / 3, 12 / 18]
        self.widgets['axes']['sketch_zoom'] = self.widgets['figs']['sketch'].add_axes(ax_sketch_zoom_dims)
        self.widgets['axes']['sketch_zoom'].axis('off')
        self.widgets['axes']['sketch_zoom'].set_title('Zoom:',
                                                       ha='center', va='center',
                                                       zorder=0)

        self.setWidget(self.widgets['canvas']['sketch'])

    def init_sketch(self):
        sketch = self.get_sketch_image()

        # full
        self.widgets['axes']['sketch'].imshow(sketch)
        self.widgets['axes']['sketch'].invert_yaxis()

        # zoom
        self.widgets['axes']['sketch_zoom'].imshow(sketch)
        self.widgets['axes']['sketch_zoom'].set_xlim(
            [np.shape(sketch)[1] / 2 - self.sketch_zoom_dx, np.shape(sketch)[1] / 2 + self.sketch_zoom_dx])
        self.widgets['axes']['sketch_zoom'].set_ylim(
            [np.shape(sketch)[0] / 2 - self.sketch_zoom_dy, np.shape(sketch)[0] / 2 + self.sketch_zoom_dy])
        self.widgets['axes']['sketch_zoom'].invert_yaxis()

        self.init_sketch_labels()
        self.update_sketch()

    def init_sketch_labels(self):
        # Plot all the labels
        for label_name, label_location in self.get_sketch_labels().items():
            self.widgets['axes']['sketch'].plot([label_location[0]], [label_location[1]],
                                                 marker='o',
                                                 color='orange',
                                                 markersize=3,
                                                 zorder=1)

            self.widgets['axes']['sketch_zoom'].plot([label_location[0]],
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
        self.widgets['highlight_dot']['sketch'] = self.widgets['axes']['sketch'].plot(
            [np.nan], [np.nan], **highlight_dot_params)[0]
        self.widgets['highlight_dot']['sketch_zoom'] = self.widgets['axes']['sketch_zoom'].plot(
            [np.nan], [np.nan], **highlight_dot_params)[0]
        self.widgets['highlight_circle']['sketch'] = self.widgets['axes']['sketch'].plot(
            [np.nan], [np.nan], **highlight_circle_params)[0]
        self.widgets['highlight_circle']['sketch_zoom'] = self.widgets['axes']['sketch_zoom'].plot(
            [np.nan], [np.nan], **highlight_circle_params)[0]

    def update_sketch(self, current_label_name=None):
        # Updates labels on the sketch
        sketch_labels = self.get_sketch_labels()

        if current_label_name is None:
            current_label_name = list(sketch_labels)[0]
        if current_label_name not in sketch_labels:
            return

        (x, y) = sketch_labels[current_label_name].astype(np.float32)
        self.widgets['highlight_dot']['sketch'].set_data([x], [y])
        self.widgets['highlight_circle']['sketch'].set_data([x], [y])
        # zoom
        self.widgets['highlight_dot']['sketch_zoom'].set_data([x], [y])
        self.widgets['highlight_circle']['sketch_zoom'].set_data([x], [y])
        self.widgets['axes']['sketch_zoom'].set_xlim([x - self.sketch_zoom_dx, x + self.sketch_zoom_dx])
        self.widgets['axes']['sketch_zoom'].set_ylim([y - self.sketch_zoom_dy, y + self.sketch_zoom_dy])
        self.widgets['axes']['sketch_zoom'].invert_yaxis()

        self.widgets['canvas']['sketch'].draw()

    def set_sketch_zoom(self):
        sketch = self.get_sketch_image()
        self.sketch_zoom_dx = np.max(np.shape(sketch)) * self.sketch_zoom_scale
        self.sketch_zoom_dy = np.max(np.shape(sketch)) * self.sketch_zoom_scale

    def get_sketch_image(self):
        return self.sketch['sketch'].astype(np.uint8)

    def get_sketch_labels(self):
        return self.sketch['sketch_label_locations']

    def get_sketch_label_coordinates(self):
        return np.array(list(self.get_sketch_labels().values()), dtype=np.float64)

