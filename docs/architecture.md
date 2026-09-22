# Application architecture

`labelgui.core` contains the application logic and does not import Qt, Matplotlib,
or pyqtgraph. Importing `labelgui` does not load its UI. The CLI imports Qt only
when starting an interactive session.

## Ownership and dependencies

```text
CLI / Qt widgets
       |
       v
LabelingSession ----> Timeline
       |------------> AnnotationStore (editable and reference labels)
       |------------> Sketch / Camera
       |------------> SaveService ----> LabelRepository ----> bbo.label_lib

SelectUserWindow ---> JobRepository
MainWindow ---------> TimeSynchronizer (MQTT transport)
```

- `configuration.py` resolves job configuration paths and loads/validates YAML or
  legacy Python configurations through the existing BBO configuration loader.
- `session.py` owns the current time, sketch, landmark, cameras, annotations,
  navigation mode, reference filter, and autosave cadence. `open()` assembles a
  job; its reader factory and label repository can be substituted in tests.
- `timeline.py` maps the shared timeline to camera-local frame indices. It handles
  timestamp snapping, bounds, and all three `d_time` modes.
- `annotations.py` owns edits, deletion metadata, suggestions, nearest-point
  selection, and reference filtering. Frame overlays are plain data objects.
- `sketch.py` loads sketch files and selects landmarks by sketch coordinates.
- `persistence.py` wraps the existing BBO label format and handles background
  saves, failures, and resume state.
- `jobs.py` discovers users/jobs, stores selection defaults, and archives completed
  jobs. Dialogs do not perform these filesystem operations themselves.
- `synchronization.py` transports time values over MQTT without knowing about Qt.

`MainWindow` translates widget signals into session operations, then renders the
resulting state. `SketchDock` emits selections and click coordinates.
`ViewerSubWindow` translates mouse coordinates and paints frames/overlays. Video
rotation, contrast, zoom, and layout remain presentation concerns.

A session can be used without a QApplication:

```python
from pathlib import Path
from labelgui.core.session import LabelingSession

session = LabelingSession.open(Path('/data/labeling'), 'alice', Path('/data/job.yml'))
try:
    session.select_label('nose')
    session.seek(1.25)
    frame = session.frame_index(0)
    session.handle_video_action(0, frame, (120.0, 80.0), 'create_label')
    session.save()
    session.saver.check(wait=True)
finally:
    session.close()
```

For GUI tests or alternative startup flows, pass a prepared session to
`MainWindow(session=session, sync=False)`.

## Data compatibility

Jobs retain the existing keys, BBO YAML includes/path placeholders, and legacy
`.py` configuration conversion. Sketch `.npy` files still contain `sketch` and
`sketch_label_locations`. YAML sketches (`.yml`/`.yaml`) use `version: "1.0"`,
an image filename in `sketch`, and the same `sketch_label_locations` mapping.
Relative image filenames resolve against the sketch YAML's directory. Image I/O
uses imageio without importing the GUI. SVG images are rasterized through CairoSVG
at their intrinsic size (96 DPI), preserving transparency; landmark coordinates
remain rendered image pixels. See `example/sketch.yml` and `example/sketch_svg.yml`.
Labels use BBO's versioned format unchanged:

```text
labels[landmark_name][camera_local_frame_index]
    coords       (number_of_cameras, 2)
    point_times  (number_of_cameras,)  # edit wall-clock timestamps
    labeler      (number_of_cameras,) # indices into labeler_list
```

Camera order is the job recording order. Camera-local frame indices must not be
confused with shared recording times. Missing/deleted coordinates remain NaN, and
deletions retain the editing user and time. Guesses are never stored as labels.
Reference filtering retains the previous "annotated in any camera at this frame"
semantics. User attribution displayed in a camera window is now camera-specific.

Outputs remain under `<base>/user/<user>/<dataset>/`, with `labels.yml`, the
legacy NPZ companion, `backup/`, `autosave/`, and `exit_status.npy`. Autosave
continues to count navigation/selection events, not elapsed time or every edit.
Incidental GUI redraws no longer count as autosave events.
Label files are only written after annotation edits (including attribution/time
updates); navigation, selection, and deleting an absent point do not dirty labels.
`session.labels_changed` stays true until the current edits have been successfully
saved to the regular label file. Revision tracking preserves edits made during a
background save and allows failed saves to be retried. The regular and autosave
files track changes independently. Unchanged labels are also skipped on exit;
resume time is still written. Save As explicitly forces a write (`save(path,
force=True)`), even without edits.

## Threading and lifetime

The session is owned by one thread (the GUI thread in the desktop application).
SaveService copies the complete label data before submitting work to its single
worker. BBO's serializer can mutate that snapshot without racing with edits.
Files are written to a temporary directory on the destination filesystem and
replaced after serialization; YAML and NPZ replacements are individually atomic,
not a two-file transaction.

The GUI polls save results and reports errors. Closing waits for pending saves
and writes resume state before releasing readers and the executor. If saving
fails, the session remains open and usable for retry. MQTT callbacks emit a Qt
signal; session changes are made on the GUI thread. The synchronizer uses the
configured topic for both incoming and outgoing times, ignores malformed payloads,
and does not republish received updates.

## Intentional corrections during extraction

- Backward navigation at the first frame clamps instead of wrapping.
- Fractional time limits are preserved; empty/invalid timelines fail explicitly.
- Incoming MQTT times snap to the shared timeline.
- Guesses skip neighbors lacking a point in the current camera.
- Label edits refresh reference correspondence lines immediately.
- Empty user lists and canceled selection do not select the last user implicitly.
- `--merge` exits after merging instead of opening the GUI.
- Grayscale images without sensor metadata have a valid inferred sensor size.

## Tests

Run from the repository root with the configured project interpreter:

```sh
python -m unittest discover -s tests -p 'test_core.py' -v
QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -p 'test_gui.py' -v
```

Core tests cover timeline mapping, editing/deletion metadata, suggestions,
reference filtering, BBO file round trips, save snapshot isolation and failures,
configuration/startup/resume, autosave, MQTT, jobs, and GUI-free imports. GUI tests
use synthetic frames and an injected session, without opening real jobs or
connecting to a broker.
