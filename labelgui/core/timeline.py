"""Map a shared recording time to camera-local frame indices."""
import math

import numpy as np


class Timeline:
    def __init__(self, camera_times, minimum=-math.inf, maximum=math.inf, *, labeling_times=None):
        self.camera_times = tuple(np.asarray(t, dtype=float).copy() for t in camera_times)
        if not self.camera_times:
            raise ValueError("At least one recording is required")
        for times in self.camera_times:
            if times.ndim != 1 or not len(times) or not np.all(np.isfinite(times)):
                raise ValueError("Each recording needs a nonempty array of finite timestamps")
            if np.any(np.diff(times) < 0):
                raise ValueError("Camera timestamps must be ordered")
        self.labeling_times = None
        if labeling_times is not None:
            times = np.asarray(labeling_times, dtype=float)
            if times.ndim != 1 or not len(times) or not np.all(np.isfinite(times)):
                raise ValueError('labeling_times must be a nonempty list of finite times')
            self.labeling_times = times.copy()
        times = (np.unique(np.concatenate(self.camera_times)) if self.labeling_times is None
                 else self.labeling_times)
        self.times = times[(times >= minimum) & (times < maximum)]
        if not len(self.times):
            if self.labeling_times is not None:
                raise ValueError('No labeling_times fall within the configured time range')
            raise ValueError("No video frames fall within the configured time range")
        # The workflow sequence and chronological lookup serve different purposes.
        self.sorted_times = np.unique(self.times)
        self._sequence_index = 0
        self.current_time = float(self.times[0])

    @property
    def current_index(self):
        return self._sequence_index if self.current_time == self.times[self._sequence_index] else None

    def _occurrence(self, time):
        indices = np.flatnonzero(self.times == time)
        return int(indices[np.argmin(abs(indices - self._sequence_index))])

    def seek_index(self, index):
        """Select an occurrence, including consecutive entries with equal times."""
        if not 0 <= index < len(self.times):
            raise IndexError('Time selection index is out of range')
        self._sequence_index = int(index)
        self.current_time = float(self.times[index])
        return self.current_time

    def nearest(self, value):
        value = float(value)
        if not math.isfinite(value):
            raise ValueError("Time must be finite")
        # Preserve the old direction-dependent tie breaking.
        candidates = self.sorted_times if value >= self.current_time else self.sorted_times[::-1]
        return float(candidates[np.argmin(np.abs(candidates - value))])

    def seek(self, value, *, allow_outside_selection=False, sequence_index=None):
        value = float(value)
        if not math.isfinite(value):
            raise ValueError("Time must be finite")
        target = value if allow_outside_selection else self.nearest(value)
        if target not in self.sorted_times:
            self.current_time = target
            return target
        if (isinstance(sequence_index, (int, np.integer)) and 0 <= sequence_index < len(self.times)
                and self.times[sequence_index] == target):
            return self.seek_index(sequence_index)
        return self.seek_index(self._occurrence(target))

    def frame_index(self, camera, time=None):
        time = self.current_time if time is None else time
        times = self.camera_times[camera]
        right = min(int(np.searchsorted(times, time)), len(times) - 1)
        left = max(0, right - 1)
        index = left if abs(times[left] - time) <= abs(times[right] - time) else right
        # As with argmin, ties and duplicate timestamps choose the first frame.
        return int(np.searchsorted(times, times[index]))

    def time_for_frame(self, camera, frame):
        """Allowed shared time displaying this frame, or None if it is excluded."""
        times = self.camera_times[camera]
        if not 0 <= frame < len(times):
            return None
        time = times[frame]
        index = np.searchsorted(self.sorted_times, time)
        if self.labeling_times is None:
            if index == len(self.sorted_times) or self.sorted_times[index] != time:
                return None
            candidates = [time]
        else:
            # With irregular intervals, the farther side may be the only match.
            candidates = sorted(self.sorted_times[max(0, index - 1):index + 1],
                                key=lambda candidate: abs(candidate - time))
        return next((float(candidate) for candidate in candidates
                     if self.frame_index(camera, candidate) == frame), None)

    def navigation_indices(self, direction):
        """Remaining sequence entries, or a chronological re-entry after an outside visit."""
        if self.current_index is not None:
            start = self.current_index + direction
        else:
            index = int(np.searchsorted(self.sorted_times, self.current_time))
            if direction < 0:
                index -= 1
            index = int(np.clip(index, 0, len(self.sorted_times) - 1))
            start = self._occurrence(self.sorted_times[index])
        return range(start, len(self.times) if direction > 0 else -1, direction)

    def step(self, count, interval):
        if not math.isfinite(interval):
            raise ValueError("Time step must be finite")
        if interval == 0:
            if count == 0:
                return self.current_time
            direction = 1 if count > 0 else -1
            index = self.navigation_indices(direction).start + count - direction
            return self.seek_index(int(np.clip(index, 0, len(self.times) - 1)))
        if interval < 0:
            camera = min(len(self.camera_times) - 1, max(0, round(-interval - 1)))
            times = self.camera_times[camera]
            index = self.frame_index(camera)
            target = int(np.clip(index + count, 0, len(times) - 1))
            return self.seek(self.current_time + times[target] - times[index])
        return self.seek(self.current_time + count * interval)
