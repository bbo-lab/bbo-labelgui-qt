# Configuration and sketch examples

`labelgui_cfg.yml` is a documented two-camera job configuration. Its video paths
are placeholders; provide your recordings and adjust FPS or timestamp files.
It references the included `sketch_svg.yml` using a relative path.

To use it in the GUI, copy/adapt it to
`<base>/data/user/<user>/jobs/<job>.yml`, update its paths for the new location,
then run `python -m labelgui <base>` and select that user/job. Keep the sketches
and their `images/` directory together if you copy them alongside the config.

## Sketches

`sketch.yml` references `images/bird.pgm`, a small schematic bird head included
as a plain-text grayscale image. PNG or JPEG images can be used the same way.
Coordinates are `[x, y]` pixel positions from the top-left of the image.

`sketch_svg.yml` references `images/bird.svg`, a vector example rendered at
240 × 160 pixels. Its SVG viewBox matches the output dimensions, so SVG and
landmark coordinates match directly. SVGs with a different viewBox scale or
origin still use rendered pixel coordinates for landmarks.

Add the absolute path to `sketch.yml` to your job's `sketch_files` list. The image
path inside the sketch stays relative to `sketch.yml`, so the entire `example`
directory can be moved without changing it.
Use `sketch_svg.yml` instead to try the SVG example.

To load the example without starting the GUI, run from the repository root:

```python
from pathlib import Path
from labelgui.core.sketch import Sketch

sketch = Sketch.load(Path("example/sketch.yml"))
print(sketch.locations)
```
