"""User/job selection dialog; filesystem operations live in JobRepository."""
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QDialog, QGridLayout, QComboBox, QPushButton

from labelgui.core.jobs import JobRepository


class SelectUserWindow(QDialog):
    def __init__(self, drive, parent=None, *, repository=None):
        super().__init__(parent)
        self.repository = repository or JobRepository(drive)
        self.setGeometry(0, 0, 256, 128)
        rect = self.frameGeometry()
        rect.moveCenter(QGuiApplication.primaryScreen().geometry().center())
        self.move(rect.topLeft())
        self.setWindowTitle('Select User')
        layout = QGridLayout(self)
        self.user_combobox = QComboBox()
        self.user_combobox.addItems(self.repository.users())
        self.user_combobox.setCurrentIndex(-1)
        self.job_combobox = QComboBox()
        self.selecting_button = QPushButton('Ok')
        self.remove_button = QPushButton('Remove')
        for row, widget in enumerate((self.user_combobox, self.job_combobox,
                                      self.selecting_button, self.remove_button)):
            layout.addWidget(widget, row, 0)
        self.user_combobox.currentIndexChanged.connect(self.user_change)
        self.job_combobox.currentIndexChanged.connect(self._update_buttons)
        self.selecting_button.clicked.connect(self.accept)
        self.remove_button.clicked.connect(self.remove)
        self.user_change()
        defaults = self.repository.read_defaults()
        user_index = self.user_combobox.findText(defaults['user'] or '')
        self.user_combobox.setCurrentIndex(user_index)
        job_index = self.job_combobox.findText(defaults['job'] or '')
        if job_index >= 0:
            self.job_combobox.setCurrentIndex(job_index)

    def _update_buttons(self):
        self.selecting_button.setEnabled(self.get_user() is not None)
        self.remove_button.setEnabled(self.get_job() is not None)

    def user_change(self):
        self.job_combobox.clear()
        user = self.get_user()
        if user is not None:
            self.job_combobox.addItems(self.repository.jobs(user))
        self.job_combobox.setEnabled(self.job_combobox.count() > 0)
        self._update_buttons()

    def get_user(self):
        return self.user_combobox.currentText() if self.user_combobox.currentIndex() >= 0 else None

    def get_job(self):
        return self.job_combobox.currentText() if self.job_combobox.currentIndex() >= 0 else None

    def remove(self):
        self.repository.complete_job(self.get_user(), self.get_job())
        self.user_change()

    @staticmethod
    def start(drive, parent=None):
        dialog = SelectUserWindow(drive, parent)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        user, job = dialog.get_user(), dialog.get_job()
        if accepted:
            dialog.repository.write_defaults(user, job)
        return user, job, accepted
