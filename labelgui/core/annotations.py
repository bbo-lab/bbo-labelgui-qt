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
    marker: str | None = None
    reference_index: int | None = None


@dataclass(frozen=True)
class Trajectory:
    name: str
    frames: np.ndarray
    coords: np.ndarray
    reference_index: int | None = None
    marker: str | None = None


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
        self.revision = 0
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
        self.revision += 1

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
        self.revision += 1

    def delete_point(self, name, frame, camera, user):
        if self.point(name, frame, camera) is None:
            return False
        entry = self.data['labels'][name][frame]
        entry['coords'][camera] = np.nan
        self._stamp(entry, camera, user)
        self.revision += 1
        return True

    def labeled_frames(self, camera):
        """Camera-local frames with at least one marked point, excluding guesses."""
        return {frame for frames in self.data['labels'].values()
                for frame, entry in frames.items()
                if np.all(np.isfinite(entry['coords'][camera]))}

    def labeler(self, name, frame, camera):
        """Return the point's author, or None when author metadata is missing."""
        entry = self.data['labels'].get(name, {}).get(frame, {})
        indices = entry.get('labeler', ())
        users = self.data.get('labeler_list', ())
        if camera < len(indices):
            index = indices[camera]
            if np.isfinite(index) and index == int(index) and 0 <= index < len(users):
                return users[int(index)]
        return None

    def labelers(self):
        """Authors of recorded points across all frames and cameras."""
        return {self.labeler(name, frame, camera)
                for name, frames in self.data['labels'].items()
                for frame, entry in frames.items()
                for camera in range(self.camera_count)
                if np.all(np.isfinite(entry['coords'][camera]))}

    def _visible_point(self, name, frame, camera, hidden_labelers):
        if hidden_labelers and self.labeler(name, frame, camera) in hidden_labelers:
            return None
        return self.point(name, frame, camera)

    def trajectories(self, camera, names=None, *, hidden_labelers=()):
        """Recorded positions and camera frame indices, one trajectory per marker.

        Sparse annotations are connected across frame gaps; guesses and missing
        camera coordinates are excluded.
        """
        labels = self.data['labels']
        paths = []
        for name in labels if names is None else names:
            frames = labels.get(name, {})
            indices = np.asarray(sorted(frames), dtype=int)
            coords = np.asarray([frames[frame]['coords'][camera] for frame in indices],
                                dtype=float).reshape(-1, 2)
            valid = np.isfinite(coords).all(axis=1)
            if hidden_labelers:
                valid &= np.asarray([self.labeler(name, frame, camera) not in hidden_labelers
                                     for frame in indices], dtype=bool)
            if valid.any():
                paths.append(Trajectory(name, indices[valid], coords[valid]))
        return paths

    def guess(self, name, frame, camera, *, hidden_labelers=()):
        for offset in range(1, 4):
            before = self._visible_point(name, frame - offset, camera, hidden_labelers)
            after = self._visible_point(name, frame + offset, camera, hidden_labelers)
            if before is not None and after is not None:
                return tuple((np.asarray(before) + after) / 2)
        for offset in (-1, 1, -2, 2, -3, 3):
            point = self._visible_point(name, frame + offset, camera, hidden_labelers)
            if point is not None:
                return point
        return None

    def points(self, frame, camera, include_guesses=True, *, hidden_labelers=()):
        points = []
        for name in self.data['labels']:
            coords = self.point(name, frame, camera)
            kind = 'label'
            if coords is not None and hidden_labelers and self.labeler(name, frame, camera) in hidden_labelers:
                continue
            if coords is None and include_guesses:
                coords = self.guess(name, frame, camera, hidden_labelers=hidden_labelers)
                kind = 'guess_label'
            if coords is not None:
                points.append(Point(name, coords, kind))
        return tuple(points)

    def frame_annotations(self, frame, camera, references, only_annotated=True, *, reference_markers=None,
                          hidden_labelers=(), hidden_reference_labelers=()):
        # Preserve the reference filter: annotated in any camera at this frame.
        names = label_lib.get_labels_from_frame(self.data, frame) if only_annotated else None
        refs = tuple(Point(p.name, p.coords, 'ref_label',
                           reference_markers[index] if reference_markers is not None else 'x', index)
                     for index, reference in enumerate(references)
                     for p in reference.points(frame, camera, include_guesses=False,
                                               hidden_labelers=hidden_reference_labelers)
                     if names is None or p.name in names)
        points = self.points(frame, camera, hidden_labelers=hidden_labelers)
        users = {self.labeler(point.name, frame, camera) for point in points if point.kind == 'label'}
        labelers = tuple(sorted(user if user is not None else 'Unknown labeler'
                                for user in users if user != '_unmarked'))
        return FrameAnnotations(points, refs, labelers)
