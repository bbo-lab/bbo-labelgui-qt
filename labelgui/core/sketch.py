"""Sketch assets and geometric landmark selection."""
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml


@dataclass(frozen=True)
class Sketch:
    image: np.ndarray
    locations: dict[str, tuple[float, float]]

    @classmethod
    def load(cls, path: Path):
        path = Path(path)
        if path.suffix.lower() in ('.yml', '.yaml'):
            from imageio.v3 import imread

            try:
                with path.open(encoding='utf-8') as file:
                    data = yaml.safe_load(file)
            except yaml.YAMLError as error:
                raise ValueError(f"Invalid sketch YAML: {path}") from error
            if not isinstance(data, dict):
                raise ValueError(f"Sketch YAML must contain a mapping: {path}")
            if str(data.get('version')) != '1.0':
                raise ValueError(f"Unsupported sketch version {data.get('version')!r}; expected '1.0': {path}")
            image_file = data.get('sketch')
            if not isinstance(image_file, str) or not image_file.strip():
                raise ValueError(f"Sketch must reference an image filename: {path}")
            image_path = Path(image_file).expanduser()
            if not image_path.is_absolute():
                image_path = path.parent / image_path
            image = np.asarray(imread(image_path), dtype=np.uint8)
        elif path.suffix.lower() == '.npy':
            data = np.load(path, allow_pickle=True)[()]
            image = np.asarray(data['sketch'], dtype=np.uint8)
        else:
            raise ValueError(f"Unsupported sketch file type: {path}")

        raw_locations = data.get('sketch_label_locations')
        if not isinstance(raw_locations, dict) or not raw_locations:
            raise ValueError(f"Sketch must contain named landmarks: {path}")
        locations = {}
        for name, xy in raw_locations.items():
            if not isinstance(name, str) or not name.strip():
                raise ValueError(f"Invalid sketch landmark name: {path}")
            try:
                coords = np.asarray(xy, dtype=float)
            except (TypeError, ValueError) as error:
                raise ValueError(f"Invalid sketch landmark coordinates for {name!r}: {path}") from error
            if coords.shape != (2,) or not np.all(np.isfinite(coords)):
                raise ValueError(f"Invalid sketch landmark coordinates for {name!r}: {path}")
            locations[name] = tuple(map(float, coords))
        if image.ndim not in (2, 3) or not image.size or not locations:
            raise ValueError(f"Sketch must contain an image and named landmarks: {path}")
        return cls(image, locations)

    def nearest_label(self, x, y):
        return min(self.locations, key=lambda name: np.linalg.norm(np.asarray(self.locations[name]) - (x, y)))
