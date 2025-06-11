from PyQt5.QtWidgets import (QFrame, QGridLayout, QLabel, QPushButton, QDockWidget)
import numpy as np

from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg


class SketchDock(QDockWidget):

    def __init__(self):

        super().__init__("Sketch")

        self.widgets = {
            'figs': {},
            'axes': {},
        }
        self.widgets['figs']['sketch'] = Figure()
        self.widgets['canvases']['sketch'] = FigureCanvasQTAgg(self.widgets['figs']['sketch'])

        # full
        ax_sketch_dims = [0 / 3, 1 / 18, 1 / 3, 16 / 18]
        self.controls['axes']['sketch'] = self.controls['figs']['sketch'].add_axes(ax_sketch_dims)
        self.controls['axes']['sketch'].axis('off')
        self.controls['axes']['sketch'].set_title('Full:',
                                                  ha='center', va='center',
                                                  zorder=0)

        # zoom
        ax_sketch_zoom_dims = [1 / 3, 5 / 18, 2 / 3, 12 / 18]
        self.controls['axes']['sketch_zoom'] = self.controls['figs']['sketch'].add_axes(ax_sketch_zoom_dims)
        self.controls['axes']['sketch_zoom'].axis('off')
        self.controls['axes']['sketch_zoom'].set_title('Zoom:',
                                                       ha='center', va='center',
                                                       zorder=0)

        # text
        self.controls['texts']['sketch'] = self.controls['figs']['sketch'].text(
            ax_sketch_dims[0] + ax_sketch_dims[2] / 2,
            ax_sketch_dims[1] / 2,
            'Label {:02d}:\n{:s}'.format(0, ''),
            ha='center', va='center',
            fontsize=18,
            zorder=2)

        self.layout_grid = QGridLayout()
        self.layout_grid.addWidget(self.widgets['canvases']['sketch'])
        self.setLayout(self.layout_grid)

