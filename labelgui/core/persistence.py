"""BBO label I/O and serialized background saves of immutable snapshots."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from contextlib import contextmanager
from pathlib import Path
import os
import logging
import tempfile

import numpy as np
from bbo import label_lib

logger = logging.getLogger(__name__)


@contextmanager
def _temporary_file(path, suffixes=()):
    """Yield a unique hidden file next to path, removed with its suffix siblings on failure.

    Writing beside the target keeps os.replace atomic. Temporary directories are avoided:
    on Windows, Python 3.12.4+ restricts them to the current user, which on SMB shares can
    leave a directory nobody can write into.
    """
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=f'.{path.stem}-', suffix=path.suffix)
    os.close(fd)
    temporary = Path(name)
    try:
        yield temporary
    except BaseException:
        for leftover in {temporary, *(temporary.with_suffix(suffix) for suffix in suffixes)}:
            leftover.unlink(missing_ok=True)
        raise

class LabelRepository:
    def load(self, path):
        return label_lib.load(Path(path), v0_format=False)

    def save(self, path, labels):
        path = Path(path).with_suffix('.yml')
        path.parent.mkdir(parents=True, exist_ok=True)
        # BBO writes YAML and a legacy NPZ companion. Replace each completed file;
        # the canonical YAML is never exposed partially written.
        with _temporary_file(path, suffixes=('.npz',)) as temporary:
            label_lib.save(temporary, labels)
            for suffix in ('.npz', '.yml'):
                source = temporary.with_suffix(suffix)
                if source.exists():
                    os.replace(source, path.with_suffix(suffix))
        logger.info('Saved labels: %s', path.resolve())


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


def load_resume_state(folder):
    path = Path(folder) / 'exit_status.npy'
    if path.is_file():
        logger.info('Loading resume state: %s', path.resolve())
        return np.load(path, allow_pickle=True)[()]
    return {}


def load_resume_time(folder):
    return load_resume_state(folder).get('i_time')


def save_resume_time(folder, time, *, time_index=None):
    path = Path(folder) / 'exit_status.npy'
    status = np.load(path, allow_pickle=True)[()] if path.is_file() else {}
    status['i_time'] = time
    status['time_index'] = time_index
    with _temporary_file(path) as temporary:
        np.save(temporary, status)
        os.replace(temporary, path)
