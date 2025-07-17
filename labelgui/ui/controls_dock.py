from PyQt5.QtGui import QIntValidator
from PyQt5.QtWidgets import (QWidget, QGridLayout, QLabel, QLineEdit,
                             QPushButton, QDockWidget)


class ControlsDock(QDockWidget):

    def __init__(self):
        # Setup widget
        super().__init__("Controls")
        self.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)

        main_widget = QWidget()
        self.widgets = {
            'labels': {},
            'buttons': {},
            'fields': {},
            'lists': {}
        }
        self.layout_grid = QGridLayout(main_widget)

        row = 0
        self.add_label("dTime:", row, 0, "d_time")
        self.add_field(row, 1, "d_time")

        row += 1
        self.add_label("current time:", row, 0, "current_time")
        self.add_field(row, 1, "current_time")

        row += 1
        self.add_button("Previous Timepoint (A)", row, 0, "previous_time")
        self.add_button("Next Timepoint (D)", row, 1, "next_time")

        row += 1
        self.add_button("Save Labels (S)", row, 0, "save_labels")
        self.add_button("Zoom Out (O)", row, 1, "zoom_out")

        row += 1
        self.add_button("Single Label Mode", row, 0, "single_label_mode")
        self.widgets['buttons']['single_label_mode'].setCheckable(True)

        self.setWidget(main_widget)

    def add_label(self, label_text: str, row_idx: int, col_idx: int, label_key=None):
        label_widget = QLabel(label_text, self)
        self.layout_grid.setColumnStretch(col_idx, 1)
        self.layout_grid.setRowStretch(row_idx, 1)
        self.layout_grid.addWidget(label_widget, row_idx, col_idx)
        if label_key is None:
            label_key = label_text
        self.widgets['labels'][label_key] = label_widget

    def add_field(self, row_idx: int, col_idx: int, field_key: str, fill_int=False):
        field_widget = QLineEdit(self, enabled=False)
        if fill_int:
            field_widget.setValidator(QIntValidator())
        self.layout_grid.setColumnStretch(col_idx, 1)
        self.layout_grid.setRowStretch(row_idx, 1)
        self.layout_grid.addWidget(field_widget, row_idx, col_idx, 1, 1)
        self.widgets['fields'][field_key] = field_widget

    def add_button(self, button_text: str, row_idx: int, col_idx: int, button_key=None):
        button_widget = QPushButton(button_text, self, enabled=False)
        self.layout_grid.setColumnStretch(col_idx, 1)
        self.layout_grid.setRowStretch(row_idx, 1)
        self.layout_grid.addWidget(button_widget, row_idx, col_idx, 1, 1)
        if button_key is None:
            button_key = button_text
        self.widgets['buttons'][button_key] = button_widget

