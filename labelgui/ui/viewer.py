import os
import sys

import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.Qt import Qt, QSizePolicy, QStyle
from PyQt5.QtGui import QImage, QPixmap, QPolygonF
from PyQt5.QtWidgets import QMainWindow, QMdiSubWindow, QGraphicsView, QApplication, QToolBar, QMessageBox, QRubberBand
from PyQt5.QtWidgets import QWidget, QLabel, QPushButton, QSpinBox, QComboBox, QDoubleSpinBox, QGraphicsLineItem, QGraphicsEllipseItem, \
    QGraphicsPolygonItem, QHBoxLayout, QFileDialog


class Viewer(QGraphicsView):
    scroll_opts = {}

    def __init__(self, context):

        super().__init__()

        self._zoom = 0
        self._empty = True
        self._scene = QtWidgets.QGraphicsScene(self)
        self._pxi = QtWidgets.QGraphicsPixmapItem()
        self._scene.addItem(self._pxi)

        self.setScene(self._scene)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setBackgroundBrush(QtGui.QBrush(QtGui.QColor(30, 100, 30)))
        self.setFrameShape(QtWidgets.QFrame.NoFrame)

        # Member variables
        self.frame = None
        self.image = None
        self.pixmap = None
        self.selectionband = QRubberBand(QRubberBand.Rectangle, self)
        self.selectionband_origin = None

        # Drawing symbol variables
        self.symbols_drawing_opts = {
            'calibration_diamond': {'thickness_fac': 0.004, 'size_fac': 0.015, 'type': 3, 'color': (0, 255, 255)},
            'ellipse_marker': {'thickness_fac': 0.002, 'size_fac': 0.005, 'type': 1, 'color': (0, 0, 255)},
            'ellipse_center_plus': {'thickness_fac': 0.003, 'size_fac': 0.003, 'type': 0, 'color': (0, 255, 255)},
            'ellipse': {'thickness_fac': 0.003, 'color_0': (0, 0, 255), 'color_1a': (0, 255, 255),
                        'color_1b': (255, 0, 255)},
            'landmark_dot': {'radius_fac_in': 0.004, 'radius_fac_out': 0.004, 'color_in': (0, 0, 200),
                             'color_1': (0, 0, 200),
                             'color_2': (0, 200, 0),
                             'color_3': (0, 200, 200),
                             'color_4': (0, 0, 0),
                             'color_out': (255, 255, 0)},
            'eyecenter_dot': {'radius_fac_in': 0.001, 'radius_fac_out': 0.005, 'color_in': (0, 0, 255),
                              'color_out': (0, 0, 255)},
            'tmark_dot': {'radius_fac_in': 0.003, 'radius_fac_out': 0.006, 'color_out': (0, 255, 0)}
        }
        self.symbol_size_fac = 1.0
        self.current_symbols = {}

    def fit_in_view(self) -> None:
        rect = QtCore.QRectF(self._pxi.pixmap().rect())
        if not rect.isNull():
            self.setSceneRect(rect)
            if not self._empty:
                unity = self.transform().mapRect(QtCore.QRectF(0, 0, 1, 1))
                self.scale(1 / unity.width(), 1 / unity.height())

                view_rect = self.viewport().rect()
                scene_rect = self.transform().mapRect(rect)
                factor = min(view_rect.width() / scene_rect.width(),
                             view_rect.height() / scene_rect.height())
                self.scale(factor, factor)
            self._zoom = 0