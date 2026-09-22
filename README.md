# BBO-labelgui-qt
GUI for guided data labeling

## Running
1. Run with `python -m labelgui [options ...]`

## Options
### Labeling mode
Run with `python -m labelgui [base data directory]`.
This starts a GUI in drone mode, for the use by assistants with limited options to influence how the program runs 
and where it saves. This expects the following file structure:
```
[base data directory]/
├── data/
│   └── user/
│       ├── user1/
│       │   └── jobs
│       │       └── labelgui_cfg.yml
│       ├── user2/
│       │   └── jobs
│       │       └── labelgui_cfg.yml
│       └── ...
└── user/
```
user1, user2,... will be presented in a selection dialog on startup. Currently, the jobs can be in .yml format or .py format.
The .py format is to be deprecated in the future.
#### Output
Marking results will be placed in `[base data directory]/user/[user]/[dataset]/`.

### Others
To manipulate i.e. merge, add labels files, see `--help` for available options. 

## Camera windows

Drag a camera's title bar out of the window, double-click it, or use its undock
button to float the camera view. Floating views request a normal window frame
for resizing, minimizing, and maximizing, and can be moved to another screen.
Use the floating camera's **Dock** button to return it to the main window.
Frame navigation, annotation, and keyboard shortcuts remain synchronized.

The View menu offers Tab and Tile arrangements for docked cameras, and
**Dock All Cameras** brings every floating camera back into the main window.

## Compiling to exe
1. `conda activate bbo_labelgui_qt`.
2. Install pyinstaller: `pip install pyinstaller.
3. If present, empty `dist/` dirctory.
4. `pyinstaller --onefile labelgui.py --hidden-import numpy.core.multiarray`
5. Distribute exe file (or binary) in dist/ folder.

Note: it is necessary to add **numpy.core.multiarray** as a hidden import as it is necessary for loading .npy sketch files.
## Development

Application logic lives in `labelgui/core`; Qt views bind to a `LabelingSession`.
See [architecture and testing](docs/architecture.md) for ownership, formats,
threading, and examples of using the session without a GUI.
