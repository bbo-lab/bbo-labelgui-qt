"""Sketch assets and geometric landmark selection."""
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class Sketch:
    image: np.ndarray
    locations: dict[str, tuple[float, float]]

    @classmethod
    def load(cls, path: Path):
        data = np.load(path, allow_pickle=True)[()]
        image = np.asarray(data['sketch'], dtype=np.uint8)
        locations = {name: tuple(map(float, xy)) for name, xy in data['sketch_label_locations'].items()}
        if image.ndim not in (2, 3) or not image.size or not locations:
            raise ValueError(f"Sketch must contain an image and named landmarks: {path}")
        if any(len(xy) != 2 or not np.all(np.isfinite(xy)) for xy in locations.values()):
            raise ValueError(f"Invalid sketch landmark coordinates: {path}")
        return cls(image, locations)

    def nearest_label(self, x, y):
        return min(self.locations, key=lambda name: np.linalg.norm(np.asarray(self.locations[name]) - (x, y)))
