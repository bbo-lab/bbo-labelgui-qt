"""The application session: owns state and use cases, without Qt or plotting."""
from dataclasses import dataclass
import inspect
import logging
import math
from pathlib import Path

import numpy as np
from bbo import path_management

from labelgui import misc
from .annotations import AnnotationStore, nearest_point
from .configuration import archive_configuration, load_configuration
from .diagnostics import format_frame_report
from .persistence import LabelRepository, SaveService, load_resume_time, save_resume_time
from .sketch import Sketch
from .timeline import Timeline
from .local_search import brightness, find_local_peak

logger = logging.getLogger(__name__)


@dataclass
class Camera:
    path: Path
    reader: object
    metadata: dict
    filter_string: str = ''

    def frame(self, index):
        frame = self.reader.get_data(index).copy()
        if (frame.ndim not in (2, 3) or not all(frame.shape)
                or (frame.ndim == 3 and frame.shape[2] not in (1, 3, 4))):
            raise ValueError('Video filters must produce grayscale, RGB, or RGBA images')
        return frame

    def intensity_range(self):
        frame = self.frame(0)
        if np.issubdtype(frame.dtype, np.integer):
            limits = np.iinfo(frame.dtype)
            return int(limits.min), int(limits.max)
        if np.issubdtype(frame.dtype, np.bool_):
            return 0, 1
        if np.issubdtype(frame.dtype, np.floating):
            values = frame[np.isfinite(frame)]
            if len(values):
                low, high = float(values.min()), float(values.max())
                return low, high if high > low else low + 1
        raise ValueError('Video filters must produce images with finite numeric intensities')

    @classmethod
    def open(cls, path, filter_string, reader_factory):
        logger.info('Loading video: %s%s', Path(path).resolve(),
                    f' (filters: {filter_string})' if filter_string else '')
        source = f'{path}|{filter_string}' if filter_string else path
        camera = cls(path, reader_factory(source), {}, filter_string)
        try:
            camera.metadata = misc.read_video_meta(camera.reader)
            camera.intensity_range()
            return camera
        except Exception:
            camera.close()
            raise

    def close(self):
        close = getattr(self.reader, 'close', None)
        if close is not None:
            try:
                # svidreader caches need recursive closing to release the decoder.
                if 'recursive' in inspect.signature(close).parameters:
                    close(recursive=True)
                else:
                    close()
            except Exception:
                logger.exception('Could not close video reader %s', self.path)


def open_reader(path):
    import svidreader
    from svidreader.filtergraph import create_filtergraph_from_string
    filename, _, filter_string = str(path).partition('|')
    reader = svidreader.get_reader(filename, backend='iio', cache=True)
    if not filter_string:
        return reader
    try:
        return create_filtergraph_from_string([reader], filter_string)['out']
    except Exception:
        reader.close(recursive=True)
        raise


def camera_timestamps(reader, metadata, settings):
    if 'file' in settings:
        import pandas as pd
        logger.info('Loading camera timestamps: %s', Path(settings['file']).expanduser().resolve())
        times = pd.read_csv(settings['file'], comment='#').iloc[:, 0].to_numpy(dtype=float)
        if len(times) != len(reader):
            raise ValueError("Timestamp count does not match recording frame count")
    else:
        fps = float(settings.get('fps', metadata.get('fps', 0)))
        if not math.isfinite(fps) or fps <= 0:
            raise ValueError("Video frame rate must be positive and finite")
        times = np.arange(len(reader), dtype=float) / fps
    return times + float(settings.get('offset', 0))


class LabelingSession:
    """Own on one thread. Only SaveService workers and MQTT use background threads.

    Frame indices are camera-local; label files retain the existing camera order.
    Widgets receive frame/overlay data and never mutate annotation dictionaries.
    """
    def __init__(self, *, user, config, cameras, sketches, timeline, labels_folder,
                 annotations=None, references=None, reference_markers=None, saver=None, reader_factory=open_reader):
        self.user = user
        self.config = config
        self.cameras = cameras
        self.reader_factory = reader_factory
        self.sketches = sketches
        self.timeline = timeline
        self.labels_folder = Path(labels_folder)
        self.annotations = annotations if annotations is not None else AnnotationStore(len(cameras))
        self.references = references if references is not None else []
        self.reference_markers = reference_markers
        if reference_markers is not None and len(reference_markers) != len(self.references):
            raise ValueError('Each reference store must have a corresponding marker')
        self.saver = saver if saver is not None else SaveService()
        self.current_sketch_index = 0
        self.current_label = next(iter(self.sketch.locations))
        self.d_time = float(config['d_time'])
        self.single_label_mode = False
        self.only_annotated_references = True
        self.search_radius = 10
        self.pixel_metric = brightness
        self._autosave_counter = 0
        self._label_saves = {}
        self._closed = False
        self._last_logged_frame = None
        self.log_frame()

    @classmethod
    def open(cls, drive, user, config_path, *, reader_factory=open_reader, repository=None):
        drive, config_path = Path(drive), Path(config_path)
        cfg = load_configuration(config_path)
        repository = repository or LabelRepository()
        cameras = []
        try:
            for filename in cfg['recording_filenames']:
                filename, _, filter_string = filename.partition('|')
                path = path_management.decode_path(Path(cfg['recording_folder']) / filename).expanduser().resolve()
                cameras.append(Camera.open(path, filter_string, reader_factory))
            timeline = Timeline([camera_timestamps(c.reader, c.metadata, cfg['video_times'].get(i, {}))
                                 for i, c in enumerate(cameras)], float(cfg['min_time']), float(cfg['max_time']))
            sketches = []
            for filename in cfg['sketch_files']:
                path = Path(filename)
                if path.is_file():
                    sketches.append(Sketch.load(path))
                else:
                    logger.warning('Sketch file does not exist: %s', path)
            if not sketches:
                raise ValueError("No valid sketch files were loaded")
            if any(i < 0 or i >= len(cameras) for i in cfg['allowed_cams']):
                raise ValueError("An allowed camera index is outside the recording list")
            dataset = cfg['dataset_name'] or Path(cfg['recording_folder']).name
            folder = (drive / 'user' / user / dataset).expanduser().resolve()
            for subfolder in ('backup', 'autosave'):
                (folder / subfolder).mkdir(parents=True, exist_ok=True)
            archive_configuration(config_path, folder / 'backup', cfg)
            source = cfg['load_labels_file']
            source = Path(source) if isinstance(source, (str, Path)) else folder / 'labels.yml'
            if source.exists():
                logger.info('Loading editable labels: %s', source.resolve())
            labels = repository.load(source) if source.exists() else None
            if labels is not None:
                misc.copy_file(source, folder / 'backup')
            ref_source = cfg['reference_labels_file']
            if ref_source is True:
                ref_source = drive / 'data' / 'references' / f'{dataset}.yml'
            ref_sources = ref_source if isinstance(ref_source, list) else [ref_source]
            markers = cfg['reference_labels_marker']
            markers = markers if isinstance(markers, list) else [markers]
            references = []
            reference_markers = []
            for source, marker in zip(ref_sources, markers):
                if source is None or source is False:
                    continue
                if Path(source).is_file():
                    logger.info('Loading reference[%d]: %s', len(references), Path(source).resolve())
                    references.append(AnnotationStore(len(cameras), repository.load(source)))
                    reference_markers.append(marker)
                else:
                    logger.warning('Reference labels do not exist: %s', source)
            annotations = AnnotationStore(len(cameras), labels)
            resume_time = load_resume_time(folder)
            if resume_time in timeline.times:
                timeline.seek(resume_time)
            return cls(user=user, config=cfg, cameras=cameras, sketches=sketches,
                       timeline=timeline, labels_folder=folder, annotations=annotations,
                       references=references, reference_markers=reference_markers,
                       saver=SaveService(repository), reader_factory=reader_factory)
        except Exception:
            cls._close_cameras(cameras)
            raise

    @property
    def dataset_name(self):
        return self.config['dataset_name'] or Path(self.config['recording_folder']).name

    @property
    def current_time(self):
        return self.timeline.current_time

    @property
    def sketch(self):
        return self.sketches[self.current_sketch_index]

    def frame_index(self, camera):
        return self.timeline.frame_index(camera)

    def log_frame(self):
        """Log a report once per time/frame change, including the initial frame."""
        if not logger.isEnabledFor(logging.INFO):
            return
        frames = tuple(self.frame_index(camera) for camera in range(len(self.cameras)))
        state = (self.current_time, frames)
        if state == self._last_logged_frame:
            return
        logger.info('\n%s', format_frame_report(self.current_time, frames, self.annotations, self.references))
        self._last_logged_frame = state

    def frame_annotations(self, camera):
        return self.annotations.frame_annotations(self.frame_index(camera), camera, self.references,
                                                  self.only_annotated_references,
                                                  reference_markers=self.reference_markers)

    def select_label(self, name):
        if name not in self.sketch.locations:
            return False
        self.current_label = name
        self.autosave_event()
        return True

    def select_sketch(self, index):
        if not 0 <= index < len(self.sketches):
            raise ValueError("Invalid sketch index")
        self.current_sketch_index = index
        self.current_label = next(iter(self.sketch.locations))
        self.autosave_event()

    def select_sketch_point(self, x, y):
        self.select_label(self.sketch.nearest_label(x, y))

    def seek(self, time):
        self.timeline.seek(time)
        self.log_frame()
        self.autosave_event()

    def step(self, count):
        self.timeline.step(count, self.d_time)
        self.log_frame()
        self.autosave_event()

    def step_labeled(self, direction):
        """Jump to the nearest marked camera timestamp in the given direction."""
        times = (times[frame]
                 for camera, times in enumerate(self.timeline.camera_times)
                 for frame in self.annotations.labeled_frames(camera)
                 if 0 <= frame < len(times))
        candidates = (time for time in times
                      if self.timeline.times[0] <= time <= self.timeline.times[-1]
                      and (time - self.current_time) * direction > 0)
        target = (min if direction > 0 else max)(candidates, default=None)
        if target is None:
            return False
        self.seek(target)
        return True

    def set_time_step(self, value):
        value = float(value)
        if not math.isfinite(value):
            raise ValueError("Time step must be finite")
        self.d_time = value

    def set_video_filters(self, filters):
        """Replace changed readers only after all new readers and timestamps work."""
        if len(filters) != len(self.cameras) or any(not isinstance(value, str) for value in filters):
            raise ValueError('Provide one filter string per camera')
        changed = [i for i, camera in enumerate(self.cameras) if filters[i] != camera.filter_string]
        if not changed:
            return False
        replacements = {}
        try:
            for index in changed:
                replacements[index] = Camera.open(self.cameras[index].path, filters[index], self.reader_factory)
            cameras = [replacements.get(i, camera) for i, camera in enumerate(self.cameras)]
            timeline = Timeline([
                camera_timestamps(camera.reader, camera.metadata, self.config.get('video_times', {}).get(i, {}))
                if i in replacements else self.timeline.camera_times[i]
                for i, camera in enumerate(cameras)
            ], self.config.get('min_time', -math.inf), self.config.get('max_time', math.inf))
            timeline.seek(self.current_time)
            for index, camera in replacements.items():
                camera.frame(timeline.frame_index(index))
        except Exception:
            self._close_cameras(replacements.values())
            raise
        old_cameras = [self.cameras[index] for index in changed]
        self.cameras = cameras
        self.timeline = timeline
        filenames = self.config.get('recording_filenames', [str(camera.path) for camera in cameras])
        self.config['recording_filenames'] = [
            filename.partition('|')[0] + (f'|{value}' if value else '')
            for filename, value in zip(filenames, filters)
        ]
        self._close_cameras(old_cameras)
        self.log_frame()
        return True

    def refine_position(self, camera, frame, coords):
        """Shared neighborhood search for mouse placement and frame tracking."""
        return find_local_peak(self.cameras[camera].frame(frame), coords,
                               self.search_radius, self.pixel_metric)

    def next_tracking_frame(self, camera):
        """Next camera-local frame that can be displayed within the session."""
        frame = self.frame_index(camera) + 1
        times = self.timeline.camera_times[camera]
        if frame >= len(times):
            return None
        time = times[frame]
        if not self.timeline.times[0] <= time <= self.timeline.times[-1]:
            return None
        # Equal timestamps cannot identify a later frame in the shared timeline.
        if self.timeline.frame_index(camera, time) != frame:
            return None
        return frame

    def can_track_next(self, camera):
        return (self.current_label is not None
                and self.annotations.point(self.current_label, self.frame_index(camera), camera) is not None
                and self.next_tracking_frame(camera) is not None)

    def track_next(self, camera):
        """Place a marker in the next camera frame, then display that timestamp.

        Search before mutating state so a failed search leaves the session intact.
        This operation advances exactly once, regardless of single-label mode.
        """
        if not self.can_track_next(camera):
            return False
        frame = self.next_tracking_frame(camera)
        origin = self.annotations.point(self.current_label, self.frame_index(camera), camera)
        coords = self.refine_position(camera, frame, origin)
        if coords is None:
            return False
        self.annotations.set_point(self.current_label, frame, camera, coords, self.user)
        self.seek(self.timeline.camera_times[camera][frame])
        return True

    def handle_video_action(self, camera, frame, coords, action):
        # Ignore stale mouse events after a frame change.
        if frame != self.frame_index(camera):
            return False
        if action in ('select_label', 'select_ref_label'):
            view = self.frame_annotations(camera)
            points = view.references if action == 'select_ref_label' else view.points
            point = nearest_point(points, coords)
            return self.select_label(point.name) if point else False
        if action == 'create_label':
            self.annotations.set_point(self.current_label, frame, camera, coords, self.user)
        elif action == 'delete_label':
            self.annotations.delete_point(self.current_label, frame, camera, self.user)
        elif action == 'auto_label':
            coords = self.refine_position(camera, frame, coords)
            if coords is None:
                return False
            self.annotations.set_point(self.current_label, frame, camera, coords, self.user)
        else:
            raise ValueError(f"Unknown video action: {action}")
        if self.single_label_mode:
            self.step(1)
        return True

    @property
    def labels_changed(self):
        """Whether edits remain unsaved to the regular label file."""
        return self._labels_changed(self._label_path())

    def _label_path(self, path=None):
        return Path(path or self.labels_folder / 'labels.yml').with_suffix('.yml').resolve()

    def _labels_changed(self, path):
        revision, future = self._label_saves.get(path, (0, None))
        saved_revision = 0
        if (future is not None and future.done() and not future.cancelled()
                and future.exception() is None):
            saved_revision = revision
        return self.annotations.revision != saved_revision

    def save(self, path=None, *, force=False):
        path = self._label_path(path)
        revision = self.annotations.revision
        if not force:
            pending_revision, future = self._label_saves.get(path, (0, None))
            # Do not queue the same snapshot again while its write is pending.
            if future is not None and not future.done() and pending_revision == revision:
                return future
            if not self._labels_changed(path):
                return None
        future = self.saver.save(path, self.annotations.data)
        self._label_saves[path] = (revision, future)
        return future

    def autosave_event(self):
        if not self.config.get('auto_save', False):
            return
        self._autosave_counter += 1
        if self._autosave_counter % self.config['auto_save_N0'] == 0:
            self.save()
        if self._autosave_counter % self.config['auto_save_N1'] == 0:
            self.save(self.labels_folder / 'autosave' / 'labels.yml')
            self._autosave_counter = 0

    def close(self):
        if self._closed:
            return
        if self.config.get('exit_save_labels', True):
            self.save()
        # A failed save leaves the session usable so the UI can offer a retry.
        self.saver.check(wait=True)
        save_resume_time(self.labels_folder, self.current_time)
        self.saver.close()
        self._close_cameras(self.cameras)
        self._closed = True

    @staticmethod
    def _close_cameras(cameras):
        for camera in cameras:
            camera.close()
