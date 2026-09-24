"""Edit the svidreader pipeline for each recording."""
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QVBoxLayout


class VideoFiltersDialog(QDialog):
    def __init__(self, cameras, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Video Filters')
        self.resize(700, 200)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Enter the filter text after | for each video. Leave empty to remove filters.'))
        form = QFormLayout()
        self.fields = []
        for index, camera in enumerate(cameras):
            field = QLineEdit(camera.filter_string)
            field.setToolTip(str(camera.path))
            form.addRow(f'{camera.path.name} ({index})', field)
            self.fields.append(field)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def filters(self):
        return [field.text() for field in self.fields]
