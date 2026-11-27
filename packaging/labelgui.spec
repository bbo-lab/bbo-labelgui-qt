# PyInstaller build of the labelgui application, one folder per platform:
#   pyinstaller packaging/labelgui.spec
# Gives dist/labelgui/ with the labelgui executable, run as `labelgui [options] INPUT_PATH`.
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

import labelgui
import svidreader

# Editable installs are invisible to PyInstaller's import analysis; search their source folders directly.
pathex = [str(Path(module.__file__).parents[1]) for module in (labelgui, svidreader)]

hiddenimports = [
    # Readers and video filters are imported inside functions, chosen by backend or filter string.
    *collect_submodules("labelgui"), *collect_submodules("svidreader"),
    "imageio.plugins.pyav", "imageio.plugins.pillow", "cairosvg", "paho.mqtt.client",
    "matplotlib.backends.backend_qtagg", "matplotlib.backends.backend_agg",
    # Unpickling .npy sketch files imports these by name.
    "numpy.core.multiarray", "numpy._core.multiarray",
]

# Optional packages that svidreader or pyqtgraph would pull in when installed, the ffmpeg executable
# of imageio-ffmpeg (about 165 MB; videos are read with PyAV), and unused Qt modules.
excludes = [
    "imageio_ffmpeg",
    "tkinter", "IPython", "cupy", "cupyx", "numba", "llvmlite", "jax", "torch", "torchvision",
    "PyQt5", "PyQt6", "pyqtgraph.opengl", "OpenGL",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DExtras", "PySide6.Qt3DInput", "PySide6.Qt3DLogic",
    "PySide6.Qt3DAnimation", "PySide6.QtQuick3D", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtGraphs", "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtPdf",
    "PySide6.QtPdfWidgets", "PySide6.QtBluetooth", "PySide6.QtPositioning", "PySide6.QtLocation",
    "PySide6.QtSensors", "PySide6.QtSerialPort", "PySide6.QtNfc", "PySide6.QtRemoteObjects",
    "PySide6.QtScxml", "PySide6.QtSpatialAudio", "PySide6.QtTextToSpeech", "PySide6.QtWebSockets",
    "PySide6.QtHttpServer", "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtUiTools",
]

a = Analysis(
    [str(Path(SPECPATH) / "labelgui_launcher.py")],
    pathex=pathex,
    hiddenimports=hiddenimports,
    excludes=excludes,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="labelgui",
    console=True,  # A command-line program: takes INPUT_PATH and logs the opened files and labels.
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="labelgui", upx=False)
