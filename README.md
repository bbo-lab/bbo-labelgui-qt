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
user1, user2,... will be presented in a selection dialog on startup. Jobs use
`.yml` or `.yaml` configurations; Python (`.py`) configurations are no longer supported.
Each file in `data/user/<user>/jobs/` is a selectable job. Without a selected job,
the application uses `data/user/<user>/labelgui_cfg.yml` (or `.yaml`).
When both extensions exist for the same job, `.yml` takes precedence.
#### Output
Marking results will be placed in `[base data directory]/user/[user]/[dataset]/`.

### Others
To manipulate i.e. merge, add labels files, see `--help` for available options. 

## Job configuration

See [example/labelgui_cfg.yml](example/labelgui_cfg.yml) for a documented config
covering recordings, sketches, camera timestamps, reference labels, saving, and
controls. Supply your own videos and adjust its paths before opening the job.

Only `recording_folder`, `recording_filenames`, and `sketch_files` are required.
Defaults enable all cameras and controls, use the full recording time range and
frame-by-frame navigation, and save changed labels on exit. Autosave is disabled
unless enabled in the config.

Relative recording-folder, sketch, timestamp-CSV, and label-file paths resolve
from the job configuration's directory. Recording filenames resolve from
`recording_folder`. Absolute paths, BBO path placeholders (including `{file}`),
and BBO `!include:` directives remain supported. Plain relative paths supplied
by included files also resolve from the job config's directory; use `{file}` in
an included file for paths relative to that file.

Existing YAML field names are retained. Explicit settings override defaults;
omitted controls now default to enabled. Relative paths previously interpreted
from the working directory should be updated to be relative to the config file.

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

### Assisted marker placement

Set **Search radius (px)** in the Controls dock (positive integer, default 10).
**Alt + left-click** places the active marker on the brightest pixel within that
circular radius around the click. **To next** starts from the active marker's
recorded position, finds the brightest nearby pixel in the current camera's next
frame, labels it, and displays that frame. It advances one camera frame, regardless
of `dTime` or Single Label Mode. Alt-click otherwise follows normal placement's
Single Label Mode behavior.

The camera shown beside **To next** follows the selected camera tab or the last
camera clicked or focused. The button is disabled for an unassigned marker
(guesses do not count), an invalid radius, or the last available camera frame.
Searches use the filtered video before display contrast clipping, clip the circle
at image edges, and use mean RGB intensity for color images (ignoring alpha).
Equal maxima prefer the position closest to the search center. If no finite pixel
is found, the position and frame remain unchanged.

Use **View → Trajectories → Active marker** or **All markers** to overlay paths
from all annotated frames on each camera's current image. **Hidden** (the default)
turns them off. Paths connect recorded positions in frame order, including across
gaps in labeling; guesses and reference labels are excluded. Small dots show the
recorded positions, and paths update when annotations or the active marker change.

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
