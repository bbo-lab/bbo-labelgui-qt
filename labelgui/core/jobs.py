"""Filesystem operations used by the user/job selection dialog."""
from datetime import datetime
from pathlib import Path
import shutil

import yaml

from .configuration import CONFIG_EXTENSIONS


class JobRepository:
    def __init__(self, drive, defaults_file=None):
        self.drive = Path(drive)
        self.defaults_file = Path(defaults_file or '~/.bbo_labelgui/defaults.yml').expanduser()

    def users(self):
        return sorted(p.name for p in (self.drive / 'data' / 'user').iterdir() if p.is_dir())

    def jobs(self, user):
        folder = self.drive / 'data' / 'user' / user / 'jobs'
        return sorted({p.stem for extension in CONFIG_EXTENSIONS
                       for p in folder.glob(f'*{extension}') if p.is_file()})

    def read_defaults(self):
        if self.defaults_file.is_file():
            with self.defaults_file.open() as file:
                defaults = yaml.safe_load(file)
            if isinstance(defaults, dict) and 'user' in defaults and 'job' in defaults:
                return defaults
        return {'user': None, 'job': None}

    def write_defaults(self, user, job):
        self.defaults_file.parent.mkdir(parents=True, exist_ok=True)
        with self.defaults_file.open('w') as file:
            yaml.safe_dump({'user': user, 'job': job}, file)

    def complete_job(self, user, job):
        if not user or not job:
            return
        folder = self.drive / 'data' / 'user' / user / 'jobs'
        done = folder / 'done'
        done.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        for extension in CONFIG_EXTENSIONS:
            source = folder / f'{job}{extension}'
            if source.is_file():
                shutil.move(source, done / f'{timestamp}_{source.name}')
