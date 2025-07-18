# BBO-labelgui-qt
GUI for guided data labeling

## Installation
(You do not need to clone this repository.)
1. [Install Anaconda](https://docs.anaconda.com/anaconda/install/)
2. Start Anaconda Prompt (Windows) / terminal (linux) and navigate into repository directory
3. Create conda environment `conda env create -f https://raw.githubusercontent.com/bbo-lab/bbo-labelgui-qt/main/environment.yml`

## Running
1. Start Anaconda Prompt (Windows) / terminal (linux) and navigate into repository directory
2. Switch to environment `conda activate bbo_labelgui_qt`
3. Run with `python -m labelgui [options ...]`

## Update 
1. Start Anaconda Prompt (Windows) / terminal (linux) and navigate into repository directory
2. Update with `conda env update -f https://raw.githubusercontent.com/bbo-lab/bbo-labelgui-qt/master/environment.yml --prune`.

## Options
### Labeling mode
Run with `python -m labelgui [base data directory]`.
This starts a GUI in drone mode, for the use by assistants with limited options to influence how the program runs 
and where it saves. This expects the following file structure:
```
[base data directory]/
├── data/
│   └── users/
│       ├── user1/
│       │   └── labelgui_cfg.yml
│       ├── user2/
│       │   └── labelgui_cfg.yml
│       └── ...
└── users/
```
user1, user2,... will be presented in a selection dialog on startup. Currently, the jobs can be in .yml format or .py format.
The .py format is to be deprecated in the future.
Marking results will be placed in `[base data directory]/users/`

### Others
`--help` shows all available options.

## Compiling to exe
1. `conda activate bbo_labelgui_qt`.
2. Install pyinstaller: `pip install pyinstaller.
3. If present, empty `dist/` dirctory.
4. `pyinstaller --onefile labelgui.py --hidden-import numpy.core.multiarray`
5. Distribute exe file (or binary) in dist/ folder.

Note: it is necessary to add **numpy.core.multiarray** as a hidden import as it is necessary for loading .npy sketch files.