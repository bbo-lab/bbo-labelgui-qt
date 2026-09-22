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

## Sketch files

The job's `sketch_files` list accepts legacy `.npy` sketches and versioned `.yml`
or `.yaml` sketches:

```yaml
version: "1.0"
sketch: images/bird.png
sketch_label_locations:
  beak_tip: [220, 80]
  eye: [140, 50]
```

`sketch` references an image file (for example PNG, JPEG, or SVG). Relative image paths
are resolved from the directory containing the sketch YAML file; absolute paths
are also supported. Coordinates are `[x, y]` in image pixels, with `[0, 0]` at the
top-left, x increasing to the right and y downwards. Landmark order follows the
YAML mapping order. The format version is required; currently `"1.0"` is supported.

See [example/sketch.yml](example/sketch.yml) for a complete example with an included
image. Existing `.npy` sketches continue to embed the image array and landmark
dictionary without requiring a version field.

SVG sketches are rasterized at their declared width and height, using 96 DPI for
physical units. If only a `viewBox` is specified, its width and height determine
the image size. Landmark coordinates refer to the rendered image's pixels, not
the SVG's internal coordinates when its `viewBox` uses a different scale or origin.
For a direct match, use `width="240" height="160" viewBox="0 0 240 160"`.
Transparency is preserved. See [example/sketch_svg.yml](example/sketch_svg.yml).
SVG rendering uses [CairoSVG](https://cairosvg.org/documentation/), included in the
project dependencies; its native Cairo library must also be available.

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
