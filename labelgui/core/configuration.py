"""YAML job configuration: discovery, defaults, validation, and archiving."""
import math
import logging
from pathlib import Path
import shutil

import yaml
from bbo.yaml import load as yaml_load

logger = logging.getLogger(__name__)

CONFIG_EXTENSIONS = ('.yml', '.yaml')
BUTTONS = ('save_labels', 'single_label_mode', 'zoom_out', 'rotate',
           'previous_label', 'next_label', 'next_time', 'previous_time',
           'previous_labeled_time', 'next_labeled_time')
FIELDS = ('current_time', 'd_time')
# Built-in pyqtgraph symbols; keep validation usable without importing Qt.
REFERENCE_MARKERS = frozenset(('o', 's', 't', 't1', 't2', 't3', 'd', '+', 'x', 'p', 'h',
                               'star', '|', '_', 'arrow_up', 'arrow_right', 'arrow_down',
                               'arrow_left', 'crosshair'))


def job_config_path(drive, user, job=None):
    folder = Path(drive) / 'data' / 'user' / user
    stem = folder / 'jobs' / job if job is not None else folder / 'labelgui_cfg'
    for extension in CONFIG_EXTENSIONS:
        candidate = stem.parent / f'{stem.name}{extension}'
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"No YAML job configuration found for {stem}")


def _mapping(value, name):
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a mapping")
    return dict(value)


def _number(value, name, *, finite=True):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError(f"{name} must be a number") from error
    if isinstance(value, bool) or math.isnan(number) or (finite and not math.isfinite(number)):
        raise ValueError(f"Invalid number for {name}: {value!r}")
    return number


def _filename(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty path string")
    return value


def _path(value, name, directory):
    path = Path(_filename(value, name)).expanduser()
    return str((directory / path).resolve())


def load_configuration(path):
    path = Path(path).expanduser().resolve()
    if path.suffix.lower() not in CONFIG_EXTENSIONS:
        raise ValueError(f"Job configurations must be YAML (.yml or .yaml): {path}")
    try:
        # Preserve BBO includes/placeholders; check assets when opening the job.
        logger.info('Loading configuration: %s', path)
        cfg = _mapping(yaml_load(path, exist_required=False), 'Job configuration')
    except (yaml.YAMLError, AttributeError, TypeError) as error:
        raise ValueError(f"Invalid YAML job configuration: {path}") from error
    required = ('recording_folder', 'recording_filenames', 'sketch_files')
    missing = [key for key in required if key not in cfg]
    if missing:
        raise ValueError(f"Missing job configuration fields: {', '.join(missing)}")
    for key in ('recording_filenames', 'sketch_files'):
        if not isinstance(cfg[key], list) or not cfg[key]:
            raise ValueError(f"{key} must be a nonempty list of paths")
        cfg[key] = [_filename(value, key) for value in cfg[key]]
    camera_count = len(cfg['recording_filenames'])
    defaults = {'dataset_name': '', 'allowed_cams': list(range(camera_count)),
                'min_time': -math.inf, 'max_time': math.inf, 'd_time': 0,
                'video_times': {}, 'load_labels_file': None, 'reference_labels_file': False,
                'exit_save_labels': True, 'auto_save': False, 'auto_save_N0': 10,
                'auto_save_N1': 100, 'sketch_zoom_scale': 0.1, 'controls': {}}
    cfg = defaults | cfg
    if not isinstance(cfg['dataset_name'], str):
        raise ValueError("dataset_name must be a string")
    cameras = cfg['allowed_cams']
    if (not isinstance(cameras, list) or not cameras
            or any(type(i) is not int or not 0 <= i < camera_count for i in cameras)):
        raise ValueError("allowed_cams must be a nonempty list of valid camera indices")
    for key in ('min_time', 'max_time'):
        cfg[key] = _number(cfg[key], key, finite=False)
    if cfg['min_time'] >= cfg['max_time']:
        raise ValueError("min_time must be less than max_time")
    for key in ('d_time', 'sketch_zoom_scale'):
        cfg[key] = _number(cfg[key], key)
    if cfg['sketch_zoom_scale'] <= 0:
        raise ValueError("sketch_zoom_scale must be positive")
    for key in ('auto_save', 'exit_save_labels'):
        if type(cfg[key]) is not bool:
            raise ValueError(f"{key} must be true or false")
    for key in ('auto_save_N0', 'auto_save_N1'):
        if type(cfg[key]) is not int or cfg[key] <= 0:
            raise ValueError(f"{key} must be a positive integer")

    cfg['recording_folder'] = _path(cfg['recording_folder'], 'recording_folder', path.parent)
    cfg['sketch_files'] = [_path(value, 'sketch_files', path.parent) for value in cfg['sketch_files']]
    for key in ('load_labels_file', 'reference_labels_file'):
        value = cfg[key]
        if value is None or value is False:
            continue
        if key == 'reference_labels_file' and value is True:
            continue
        if key == 'reference_labels_file' and isinstance(value, list):
            cfg[key] = [_path(item, key, path.parent) for item in value]
            continue
        cfg[key] = _path(value, key, path.parent)

    references = cfg['reference_labels_file']
    markers = cfg.setdefault('reference_labels_marker',
                             ['x'] * len(references) if isinstance(references, list) else 'x')
    if isinstance(references, list):
        if not isinstance(markers, list) or len(markers) != len(references):
            raise ValueError('reference_labels_marker must be a list with the same length as reference_labels_file')
    elif isinstance(markers, list):
        raise ValueError('reference_labels_marker must be a single marker string for a scalar reference_labels_file')
    for marker in markers if isinstance(markers, list) else [markers]:
        if not isinstance(marker, str) or marker not in REFERENCE_MARKERS:
            raise ValueError(f'Invalid reference_labels_marker {marker!r}; '
                             f'choose from {", ".join(sorted(REFERENCE_MARKERS))}')

    cfg['video_times'] = _mapping(cfg['video_times'], 'video_times')
    for camera, settings in cfg['video_times'].items():
        if type(camera) is not int or not 0 <= camera < camera_count:
            raise ValueError("video_times keys must be valid integer camera indices")
        name = f'video_times[{camera}]'
        settings = _mapping(settings, name)
        if 'file' in settings:
            settings['file'] = _path(settings['file'], f'{name}.file', path.parent)
        if 'fps' in settings:
            settings['fps'] = _number(settings['fps'], f'{name}.fps')
            if settings['fps'] <= 0:
                raise ValueError(f"{name}.fps must be positive")
        settings['offset'] = _number(settings.get('offset', 0), f'{name}.offset')
        cfg['video_times'][camera] = settings

    controls = _mapping(cfg['controls'], 'controls')
    for group, names in (('buttons', BUTTONS), ('fields', FIELDS)):
        settings = _mapping(controls.get(group, {}), f'controls.{group}')
        if any(type(value) is not bool for value in settings.values()):
            raise ValueError(f"controls.{group} values must be true or false")
        controls[group] = dict.fromkeys(names, True) | settings
    cfg['controls'] = controls
    return cfg


def archive_configuration(source, target_dir, config):
    """Keep the original YAML and the normalized configuration used by this session."""
    target_dir = Path(target_dir)
    shutil.copy(source, target_dir)
    with (target_dir / 'labelgui_cfg_processed.yml').open('w', encoding='utf-8') as file:
        yaml.safe_dump(config, file, sort_keys=False)
