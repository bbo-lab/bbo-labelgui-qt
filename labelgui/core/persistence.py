"""BBO label I/O and serialized background saves of immutable snapshots."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import os

import numpy as np
from bbo import label_lib


class LabelRepository:
    def load(self, path):
        return label_lib.load(Path(path), v0_format=False)

    def save(self, path, labels):
        path = Path(path).with_suffix('.yml')
        path.parent.mkdir(parents=True, exist_ok=True)
        # BBO writes YAML and a legacy NPZ companion. Replace each completed file;
        # the canonical YAML is never exposed partially written.
        with TemporaryDirectory(dir=path.parent, prefix='.labels-') as directory:
            temporary = Path(directory) / path.name
            label_lib.save(temporary, labels)
            for suffix in ('.npz', '.yml'):
                source = temporary.with_suffix(suffix)
                if source.exists():
                    os.replace(source, path.with_suffix(suffix))


class SaveService:
    """Call from the session's owning thread; workers only see copied data."""
    def __init__(self, repository=None):
        self.repository = repository or LabelRepository()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='label-save')
        self._pending = []

    def save(self, path, labels):
        snapshot = deepcopy(labels)
        future = self._executor.submit(self.repository.save, Path(path), snapshot)
        self._pending.append(future)
        return future

    def check(self, wait=False):
        pending, self._pending = self._pending, []
        errors = []
        for future in pending:
            if wait or future.done():
                try:
                    future.result()
                except Exception as error:
                    errors.append(error)
            else:
                self._pending.append(future)
        if errors:
            raise RuntimeError(f"Could not save labels: {errors[0]}") from errors[0]

    def close(self):
        try:
            self.check(wait=True)
        finally:
            self._executor.shutdown(wait=True)


def load_resume_time(folder):
    path = Path(folder) / 'exit_status.npy'
    return np.load(path, allow_pickle=True)[()].get('i_time') if path.is_file() else None


def save_resume_time(folder, time):
    path = Path(folder) / 'exit_status.npy'
    status = np.load(path, allow_pickle=True)[()] if path.is_file() else {}
    status['i_time'] = time
    with TemporaryDirectory(dir=path.parent, prefix='.resume-') as directory:
        temporary = Path(directory) / path.name
        np.save(temporary, status)
        os.replace(temporary, path)
