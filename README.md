# bbo-labelgui-qt
GUI for guided data labeling

## Compiling to exe
    pyinstaller --onefile labelgui.py --hidden-import numpy.core.multiarray
it is necessary to add **numpy.core.multiarray** as a hidden import as it is necessary for loading .npy sketch files.