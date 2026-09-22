"""Render sketch assets and emit user intent; selection belongs to the session."""
import numpy as np
from PySide6.QtCore import Signal, QSignalBlocker
from PySide6.QtWidgets import (QWidget, QDockWidget, QVBoxLayout, QComboBox,
                               QListWidget, QHBoxLayout, QAbstractItemView, QPushButton)
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure


class SketchDock(QDockWidget):
    label_selected = Signal(str)
    sketch_selected = Signal(int)
    point_selected = Signal(float, float)

    def __init__(self):
        super().__init__('Sketch')
        self.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable
                         | QDockWidget.DockWidgetFeature.DockWidgetFloatable)
        self.sketch_zoom_scale = 0.1
        self.sketch = None
        self.widgets = {'buttons': {}}
        main = QWidget()
        layout = QVBoxLayout(main)
        self.figure = Figure()
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.full_axes = self.figure.add_axes([0, 1 / 18, 1 / 3, 16 / 18])
        self.zoom_axes = self.figure.add_axes([1 / 3, 5 / 18, 2 / 3, 12 / 18])
        self.highlights = []
        layout.addWidget(self.canvas)
        self.combobox_sketches = QComboBox()
        layout.addWidget(self.combobox_sketches)
        self.list_labels = QListWidget()
        self.list_labels.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        layout.addWidget(self.list_labels)
        layout.setStretchFactor(self.list_labels, 5)
        buttons = QWidget()
        row = QHBoxLayout(buttons)
        for name, title in [('previous_label', 'Previous Label (P)'), ('next_label', 'Next Label (N)')]:
            button = QPushButton(title)
            self.widgets['buttons'][name] = button
            row.addWidget(button)
        layout.addWidget(buttons)
        self.setWidget(main)
        self.combobox_sketches.currentIndexChanged.connect(self._sketch_changed)
        self.list_labels.currentTextChanged.connect(self._label_changed)
        self.canvas.mpl_connect('button_press_event', self.sketch_click)

    def set_sketch_names(self, names):
        with QSignalBlocker(self.combobox_sketches):
            self.combobox_sketches.clear()
            self.combobox_sketches.addItems(names)

    def connect_label_buttons(self, controls_cfg):
        for name, direction in [('previous_label', -1), ('next_label', 1)]:
            button = self.widgets['buttons'][name]
            button.setEnabled(controls_cfg['buttons'].get(name, True))
            button.clicked.connect(lambda checked=False, step=direction: self._move_label(step))

    def _move_label(self, step):
        if self.list_labels.count():
            self.list_labels.setCurrentRow((self.list_labels.currentRow() + step) % self.list_labels.count())

    def _sketch_changed(self, index):
        if index >= 0:
            self.sketch_selected.emit(index)

    def _label_changed(self, name):
        if name:
            self.label_selected.emit(name)

    def display_sketch(self, sketch, index, selected_label):
        self.sketch = sketch
        with QSignalBlocker(self.combobox_sketches), QSignalBlocker(self.list_labels):
            self.combobox_sketches.setCurrentIndex(index)
            self.list_labels.clear()
            self.list_labels.addItems(list(sketch.locations))
        self.highlights = []
        coordinates = np.asarray(list(sketch.locations.values()))
        for axes, title in [(self.full_axes, 'Full:'), (self.zoom_axes, 'Zoom:')]:
            axes.clear()
            axes.imshow(sketch.image)
            axes.axis('off')
            axes.set_title(title)
            axes.plot(coordinates[:, 0], coordinates[:, 1], linestyle='none', marker='o',
                      color='orange', markersize=3)
            self.highlights.append(axes.plot([], [], marker='.', color='darkgreen', markersize=2)[0])
            self.highlights.append(axes.plot([], [], marker='o', color='darkgreen', markersize=40,
                                             markeredgewidth=4, fillstyle='none', alpha=2 / 3)[0])
        self.display_selection(selected_label)

    def display_selection(self, name):
        if self.sketch is None or name not in self.sketch.locations:
            return
        with QSignalBlocker(self.list_labels):
            self.list_labels.setCurrentRow(list(self.sketch.locations).index(name))
        x, y = self.sketch.locations[name]
        for highlight in self.highlights:
            highlight.set_data([x], [y])
        radius = max(self.sketch.image.shape[:2]) * self.sketch_zoom_scale
        self.zoom_axes.set_xlim(x - radius, x + radius)
        self.zoom_axes.set_ylim(y + radius, y - radius)
        self.canvas.draw_idle()
        self.list_labels.clearFocus()

    def sketch_click(self, event):
        if event.button == 1 and event.xdata is not None and event.ydata is not None:
            self.point_selected.emit(event.xdata, event.ydata)
