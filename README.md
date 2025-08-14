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
└── users/
```
user1, user2,... will be presented in a selection dialog on startup. Currently, the jobs can be in .yml format or .py format.
The .py format is to be deprecated in the future.
#### Output
Marking results will be placed in `[base data directory]/users/`

### Others
To manipulate i.e. merge, add labels files, see `--help` for available options. 

## Compiling to exe
1. `conda activate bbo_labelgui_qt`.
2. Install pyinstaller: `pip install pyinstaller.
3. If present, empty `dist/` dirctory.
4. `pyinstaller --onefile labelgui.py --hidden-import numpy.core.multiarray`
5. Distribute exe file (or binary) in dist/ folder.

Note: it is necessary to add **numpy.core.multiarray** as a hidden import as it is necessary for loading .npy sketch files.