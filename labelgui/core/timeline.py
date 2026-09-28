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
            self.labeling_times = np.unique(times)
        times = (np.unique(np.concatenate(self.camera_times)) if self.labeling_times is None
                 else self.labeling_times)
        self.times = times[(times >= minimum) & (times < maximum)]
        if not len(self.times):
            if self.labeling_times is not None:
                raise ValueError('No labeling_times fall within the configured time range')
            raise ValueError("No video frames fall within the configured time range")
        self.current_time = float(self.times[0])

    def nearest(self, value):
        value = float(value)
        if not math.isfinite(value):
            raise ValueError("Time must be finite")
        # Preserve the old direction-dependent tie breaking.
        candidates = self.times if value >= self.current_time else self.times[::-1]
        return float(candidates[np.argmin(np.abs(candidates - value))])

    def seek(self, value):
        self.current_time = self.nearest(value)
        return self.current_time

    def frame_index(self, camera, time=None):
        time = self.current_time if time is None else time
        return int(np.argmin(np.abs(self.camera_times[camera] - time)))

    def step(self, count, interval):
        if not math.isfinite(interval):
            raise ValueError("Time step must be finite")
        if interval == 0:
            index = int(np.searchsorted(self.times, self.current_time))
            index = int(np.clip(index + count, 0, len(self.times) - 1))
            return self.seek(self.times[index])
        if interval < 0:
            camera = min(len(self.camera_times) - 1, max(0, round(-interval - 1)))
            times = self.camera_times[camera]
            index = self.frame_index(camera)
            target = int(np.clip(index + count, 0, len(times) - 1))
            return self.seek(self.current_time + times[target] - times[index])
        return self.seek(self.current_time + count * interval)
