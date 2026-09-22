"""Job configuration and user/job discovery, with no UI dependencies."""
from pathlib import Path
import math

from labelgui.misc import load_cfg


def job_config_path(drive, user, job=None):
    folder = Path(drive) / 'data' / 'user' / user
    if job is not None:
        for extension in ('yml', 'py'):
            candidate = folder / 'jobs' / f'{job}.{extension}'
            if candidate.is_file():
                return candidate
    return folder / 'labelgui_cfg.yml'


def load_configuration(path):
    cfg = load_cfg(Path(path))
    required = ('recording_folder', 'recording_filenames', 'sketch_files', 'allowed_cams',
                'min_time', 'max_time', 'd_time', 'controls')
    missing = [key for key in required if key not in cfg]
    if missing:
        raise ValueError(f"Missing job configuration fields: {', '.join(missing)}")
    if not cfg['recording_filenames'] or not cfg['sketch_files']:
        raise ValueError("A job needs recordings and at least one sketch")
    cfg = dict(cfg)
    cfg['d_time'] = float(cfg['d_time'])
    if not math.isfinite(cfg['d_time']):
        raise ValueError("Time step must be finite")
    for key, value in {'dataset_name': '', 'video_times': {}, 'load_labels_file': None,
                       'reference_labels_file': False, 'exit_save_labels': True,
                       'auto_save': False, 'auto_save_N0': 10, 'auto_save_N1': 100,
                       'sketch_zoom_scale': 0.1}.items():
        cfg.setdefault(key, value)
    for key in ('auto_save_N0', 'auto_save_N1'):
        value = cfg[key]
        if cfg['auto_save'] and (int(value) != value or value <= 0):
            raise ValueError("Autosave intervals must be positive integers")
    return cfg
