# YAML sketch example

`sketch.yml` references `images/bird.pgm`, a small schematic bird head included
as a plain-text grayscale image. PNG or JPEG images can be used the same way.
Coordinates are `[x, y]` pixel positions from the top-left of the image.

Add the absolute path to `sketch.yml` to your job's `sketch_files` list. The image
path inside the sketch stays relative to `sketch.yml`, so the entire `example`
directory can be moved without changing it.

To load the example without starting the GUI, run from the repository root:

```python
from pathlib import Path
from labelgui.core.sketch import Sketch

sketch = Sketch.load(Path("example/sketch.yml"))
print(sketch.locations)
```
