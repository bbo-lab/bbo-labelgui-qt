from PySide6.QtCore import Qt
from PySide6.QtGui import QDoubleValidator, QIntValidator
from PySide6.QtWidgets import (QWidget, QGridLayout, QVBoxLayout, QLabel, QLineEdit,
                               QPushButton, QDockWidget, QGroupBox, QSizePolicy,
                               QScrollArea, QFrame)


class ControlsDock(QDockWidget):
    def __init__(self):
        super().__init__('Controls')
        self.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable
                         | QDockWidget.DockWidgetFeature.DockWidgetFloatable)
        self.widgets = {'labels': {}, 'buttons': {}, 'fields': {}, 'lists': {}}

        content = QWidget()
        content.setObjectName('controlsContent')
        # Palette colors keep the sections compatible with light and dark themes.
        content.setStyleSheet('''
            QWidget#controlsContent QGroupBox {
                border: 1px solid palette(midlight);
                border-radius: 6px;
                margin-top: 10px;
                padding: 2px;
            }
            QWidget#controlsContent QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 10px;
                padding: 0 4px;
                color: palette(text);
                font-weight: 600;
            }
        ''')
        sections = QVBoxLayout(content)
        sections.setContentsMargins(6, 6, 6, 6)
        sections.setSpacing(6)

        navigation = self._group(sections, 'Navigation')
        time_validator = QDoubleValidator(self)
        time_validator.setDecimals(6)
        self._field(navigation, 0, 'Current time (s)', 'current_time', time_validator)
        step = self._field(navigation, 1, 'Time step', 'd_time', QDoubleValidator(self))
        step.setToolTip('Positive: step in seconds. Zero: next global timepoint. '
                        'Negative: camera-based step (-1 for camera 0, -2 for camera 1, …).')
        self._button(navigation, 2, 0, 'Previous (A)', 'previous_time')
        self._button(navigation, 2, 1, 'Next (D)', 'next_time')
        previous = self._button(navigation, 3, 0, 'Labeled ← (Shift+A)', 'previous_labeled_time')
        previous.setToolTip('Go to the previous labeled timepoint (Shift+A)')
        following = self._button(navigation, 3, 1, 'Labeled → (Shift+D)', 'next_labeled_time')
        following.setToolTip('Go to the next labeled timepoint (Shift+D)')

        labeling = self._group(sections, 'Labeling')
        single = self._button(labeling, 0, 0, 'Single label mode', 'single_label_mode')
        single.setCheckable(True)
        single.setToolTip('Advance after placing or deleting a label')
        self._button(labeling, 0, 1, 'Save labels (S)', 'save_labels')

        tracking = self._group(sections, 'Assisted labeling', columns=3)
        radius = self._field(tracking, 0, 'Radius (px)', 'search_radius',
                             QIntValidator(1, 2147483647, self))
        radius.setMaximumWidth(90)
        radius.setToolTip('Circular search radius for Alt+left-click and To next')
        next_button = self._button(tracking, 0, 2, 'To next', 'track_next')
        next_button.setToolTip('Find the marker near its current position in the next frame of this camera')
        camera = QLabel('Camera: —')
        camera.setWordWrap(True)
        tracking.addWidget(camera, 1, 0, 1, 3)
        self.widgets['labels']['tracking_camera'] = camera
        tracking.setColumnStretch(0, 1)
        tracking.setColumnStretch(1, 0)
        tracking.setColumnStretch(2, 0)

        view = self._group(sections, 'Image view')
        self._button(view, 0, 0, 'Rotate (R)', 'rotate')
        self._button(view, 0, 1, 'Reset zoom (O)', 'zoom_out')
        sections.addStretch()

        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        self.setWidget(scroll)

    @staticmethod
    def _group(sections, title, columns=2):
        group = QGroupBox(title)
        group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        layout = QGridLayout(group)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setHorizontalSpacing(6)
        layout.setVerticalSpacing(4)
        for column in range(columns):
            layout.setColumnStretch(column, 1)
        sections.addWidget(group)
        return layout

    def _field(self, layout, row, title, key, validator):
        label = QLabel(title)
        field = QLineEdit()
        field.setEnabled(False)
        field.setAlignment(Qt.AlignmentFlag.AlignRight)
        field.setValidator(validator)
        label.setBuddy(field)
        layout.addWidget(label, row, 0)
        layout.addWidget(field, row, 1)
        self.widgets['labels'][key] = label
        self.widgets['fields'][key] = field
        return field

    def _button(self, layout, row, column, title, key):
        button = QPushButton(title)
        button.setEnabled(False)
        layout.addWidget(button, row, column)
        self.widgets['buttons'][key] = button
        return button
