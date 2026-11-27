"""Entry point of the frozen labelgui application (PyInstaller).

With LABELGUI_SMOKE_TEST=1, the bundle picks the first user of INPUT_PATH instead of
showing the user dialog, opens the main window and quits after a few seconds, so CI
can check that the bundle reads videos and renders SVG sketches.
"""

import os
import sys

if os.environ.get("LABELGUI_SMOKE_TEST"):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from labelgui.core.jobs import JobRepository
    from labelgui.select_user import SelectUserWindow
    from labelgui.ui.main_window import MainWindow

    def first_user(drive, parent=None):
        return JobRepository(drive).users()[0], None, True

    show = MainWindow.show

    def show_and_quit(window):
        show(window)
        QTimer.singleShot(3000, QApplication.quit)

    SelectUserWindow.start = staticmethod(first_user)
    MainWindow.show = show_and_quit

from labelgui.__main__ import main

sys.exit(main())
