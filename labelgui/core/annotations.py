"""Annotation editing and suggestions in the existing BBO label format."""
from dataclasses import dataclass
import time

import numpy as np
from bbo import label_lib


@dataclass(frozen=True)
class Point:
    name: str
    coords: tuple[float, float]
    kind: str = "label"


@dataclass(frozen=True)
class FrameAnnotations:
    points: tuple[Point, ...]
    references: tuple[Point, ...]
    labelers: tuple[str, ...]


def nearest_point(points, coords):
    return min(points, key=lambda p: np.linalg.norm(np.asarray(p.coords) - coords), default=None)


class AnnotationStore:
    def __init__(self, camera_count, data=None, clock=time.time):
        self.camera_count = camera_count
        self.data = data if data is not None else label_lib.get_empty_labels()
        self.clock = clock
        for frames in self.data['labels'].values():
            for entry in frames.values():
                if np.shape(entry['coords']) != (camera_count, 2):
                    raise ValueError("Label camera count does not match the recordings")

    def point(self, name, frame, camera):
        entry = self.data['labels'].get(name, {}).get(frame)
        if entry is None:
            return None
        coords = entry['coords'][camera]
        return tuple(map(float, coords)) if np.all(np.isfinite(coords)) else None

    def _stamp(self, entry, camera, user):
        users = self.data['labeler_list']
        if user not in users:
            users.append(user)
        entry['labeler'][camera] = users.index(user)
        entry['point_times'][camera] = self.clock()

    def set_point(self, name, frame, camera, coords, user):
        if not name:
            raise ValueError("Select a landmark before placing a point")
        coords = np.asarray(coords, dtype=float)
        if coords.shape != (2,) or not np.all(np.isfinite(coords)):
            raise ValueError("Point coordinates must be two finite numbers")
        if frame < 0 or not 0 <= camera < self.camera_count:
            raise ValueError("Invalid frame or camera index")
        entry = self.data['labels'].setdefault(name, {}).setdefault(int(frame), {
            'coords': np.full((self.camera_count, 2), np.nan),
            'point_times': np.zeros(self.camera_count, dtype=float),
            'labeler': np.full(self.camera_count, self.data['labeler_list'].index('_unmarked'), dtype=np.uint16),
        })
        entry['coords'][camera] = coords
        self._stamp(entry, camera, user)

    def delete_point(self, name, frame, camera, user):
        if self.point(name, frame, camera) is None:
            return False
        entry = self.data['labels'][name][frame]
        entry['coords'][camera] = np.nan
        self._stamp(entry, camera, user)
        return True

    def guess(self, name, frame, camera):
        for offset in range(1, 4):
            before = self.point(name, frame - offset, camera)
            after = self.point(name, frame + offset, camera)
            if before is not None and after is not None:
                return tuple((np.asarray(before) + after) / 2)
        for offset in (-1, 1, -2, 2, -3, 3):
            point = self.point(name, frame + offset, camera)
            if point is not None:
                return point
        return None

    def points(self, frame, camera, include_guesses=True):
        points = []
        for name in self.data['labels']:
            coords = self.point(name, frame, camera)
            kind = 'label'
            if coords is None and include_guesses:
                coords = self.guess(name, frame, camera)
                kind = 'guess_label'
            if coords is not None:
                points.append(Point(name, coords, kind))
        return tuple(points)

    def frame_annotations(self, frame, camera, references, only_annotated=True):
        # Preserve the reference filter: annotated in any camera at this frame.
        names = label_lib.get_labels_from_frame(self.data, frame) if only_annotated else None
        refs = tuple(Point(p.name, p.coords, 'ref_label')
                     for p in references.points(frame, camera, include_guesses=False)
                     if names is None or p.name in names)
        return FrameAnnotations(self.points(frame, camera), refs,
                                tuple(label_lib.get_frame_labelers(self.data, frame, cam_idx=camera)))
