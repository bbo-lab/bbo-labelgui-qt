from PyQt5.QtGui import QIntValidator
from PyQt5.QtWidgets import (QFrame, QGridLayout, QLabel, QLineEdit,
                             QListWidget, QPushButton, QComboBox, QAbstractItemView, QDockWidget)


class ControlsDock(QDockWidget):

    def __init__(self):
        # Setup widget
        super().__init__("Controls")

        self.widgets = {
            'labels': {},
            'buttons': {},
            'fields': {}
        }
        self.layout_grid = QGridLayout()

        row = 0
        self.add_label_to_grid("dx:", row, 1, "dx")
        self.add_label_to_grid("dy:", row, 2, "dy")

        row += 1
        self.add_field(row, 1, "dx")
        self.add_field(row, 2, "dy")

        row += 1
        self.add_label_to_grid("vmin:", row, 1, "vmin")
        self.add_label_to_grid("vmax:", row, 2, "vmax")

        row += 1
        self.add_field(row, 1, "vmin")
        self.add_field(row, 2, "vmax")

        row += 1
        self.add_button("Save Labels (S)", row, 0, "save_labels")

        list_labels = QListWidget()
        list_labels.setSelectionMode(QAbstractItemView.SingleSelection)
        self.layout_grid.addWidget(list_labels, row, 1, 3, 2)
        self.widgets['lists']['labels'] = list_labels

        row += 1
        self.add_button("Previous Label (P)", row, 1, "previous_label")
        self.add_button("Next Label (N)", row, 2, "next_label")

        row += 1
        self.add_label("current frame:", row, 0, "current_pose")
        self.add_label("dFrame:", row, 1, "d_frame")

        row += 1
        self.add_field(row, 0, "current_pose")
        self.add_field(row, 0, "d_frame")

        row += 1
        self.add_button("Previous Frame (A)", row, 0, "previous")
        self.add_button("Next Frame (D)", row, 1, "next")
        self.add_button("Home (H)", row, 2, "home")

        row += 1
        self.add_label("", row, 0, "labeler")

        self.setLayout(self.layout_grid)
        self.setStyleSheet("background-color: white;")

    def add_label(self, label_text:str, row_idx: int, col_idx: int, label_key=None):
        label_widget = QLabel(label_text, self)
        self.layout_grid.addWidget(label_widget, row_idx, col_idx)
        if label_key is None:
            label_key = label_text
        self.widgets['labels'][label_key] = label_widget

    def add_field(self, row_idx: int, col_idx: int, field_key: str, fill_int=True):
        field_widget = QLineEdit()
        if fill_int:
            field_widget.setValidator(QIntValidator())
        self.layout_grid.addWidget(field_widget, row_idx, col_idx)
        self.widgets['fields'][field_key] = field_widget

    def add_button(self, button_text:str, row_idx:int, col_idx, button_key=None):
        button_widget = QPushButton(button_text, self)
        self.layout_grid.addWidget(button_widget, row_idx, col_idx)
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