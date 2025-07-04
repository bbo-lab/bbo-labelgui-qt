from PyQt5.QtGui import QIntValidator
from PyQt5.QtWidgets import (QWidget, QGridLayout, QLabel, QLineEdit,
                             QPushButton, QComboBox, QDockWidget)


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
        self.combobox_recordings = QComboBox()
        self.layout_grid.addWidget(self.combobox_recordings, row, 0, 1, 2)

        row += 1
        self.add_label("dFrame:", row, 0, "d_frame")
        self.add_field(row, 1, "d_frame")

        row += 1
        self.add_label("current frame:", row, 0, "current_frame")
        self.add_field(row, 1, "current_frame")

        row += 1
        self.add_button("Previous Frame (A)", row, 0, "previous_frame")
        self.add_button("Save Labels (S)", row, 1, "save_labels")

        row += 1
        self.add_button("Next Frame (D)", row, 0, "next_frame")
        self.add_button("Home (H)", row, 1, "home")

        row += 1
        self.add_label("", row, 0, "labeler")

        self.setWidget(main_widget)

    def add_label(self, label_text: str, row_idx: int, col_idx: int, label_key=None):
        label_widget = QLabel(label_text, self)
        self.layout_grid.addWidget(label_widget, row_idx, col_idx, 1, 1)
        if label_key is None:
            label_key = label_text
        self.widgets['labels'][label_key] = label_widget

    def add_field(self, row_idx: int, col_idx: int, field_key: str, fill_int=True):
        field_widget = QLineEdit()
        if fill_int:
            field_widget.setValidator(QIntValidator())
        self.layout_grid.addWidget(field_widget, row_idx, col_idx, 1, 1)
        self.widgets['fields'][field_key] = field_widget

    def add_button(self, button_text: str, row_idx: int, col_idx, button_key=None):
        button_widget = QPushButton(button_text, self)
        self.layout_grid.addWidget(button_widget, row_idx, col_idx, 1, 1)
        if button_key is None:
            button_key = button_text
        self.widgets['buttons'][button_key] = button_widget


def get_button_status(button: QPushButton):
    return button.isChecked()


def update_button_stylesheet(button: QPushButton):
    if get_button_status(button):
        button.setStyleSheet("background-color: green;")
    else:
        button.setStyleSheet("")


def toggle_button(button: QPushButton):
    button.setChecked(not get_button_status(button))
    update_button_stylesheet(button)


def disable_button(button: QPushButton):
    if get_button_status(button):
        toggle_button(button)


def enable_button(button: QPushButton):
    if not get_button_status(button):
        toggle_button(button)
