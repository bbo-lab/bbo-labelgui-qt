"""Saves replace files atomically without creating directories in the labels folder."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from labelgui.core.annotations import AnnotationStore
from labelgui.core.persistence import LabelRepository, load_resume_state, save_resume_time


def refuse_new_directories():
    """Fail like a temporary directory that its creator cannot write into (Windows on SMB shares)."""
    mkdir = os.mkdir

    def guarded(path, *args, **kwargs):
        if not Path(path).exists():
            raise PermissionError(13, 'Permission denied', str(path))
        return mkdir(path, *args, **kwargs)  # Raises FileExistsError, as callers with exist_ok expect.

    return patch('os.mkdir', guarded)


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.folder = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def assert_only(self, *names):
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()), sorted(names))

    def test_saves_need_no_new_directories_and_leave_no_temporary_files(self):
        store = AnnotationStore(1)
        store.set_point('nose', 0, 0, (2, 3), 'alice')
        with refuse_new_directories():
            LabelRepository().save(self.folder / 'labels.yml', store.data)
            save_resume_time(self.folder, 1.5, time_index=3)
            save_resume_time(self.folder, 2.5, time_index=4)
        self.assert_only('labels.yml', 'labels.npz', 'exit_status.npy')
        loaded = LabelRepository().load(self.folder / 'labels.yml')
        np.testing.assert_array_equal(loaded['labels']['nose'][0]['coords'][0], [2, 3])
        self.assertEqual(load_resume_state(self.folder), {'i_time': 2.5, 'time_index': 4})

    def test_failed_label_save_keeps_files_and_removes_partial_temporaries(self):
        (self.folder / 'labels.yml').write_text('original')

        def partial_save(path, labels):
            np.savez(path.with_suffix('.npz'), labels)
            path.with_suffix('.yml').write_text('partial')
            raise OSError('disk full')

        with patch('labelgui.core.persistence.label_lib.save', partial_save):
            with self.assertRaisesRegex(OSError, 'disk full'):
                LabelRepository().save(self.folder / 'labels.yml', AnnotationStore(1).data)
        self.assertEqual((self.folder / 'labels.yml').read_text(), 'original')
        self.assert_only('labels.yml')

    def test_failed_resume_save_keeps_previous_state_and_removes_temporary(self):
        save_resume_time(self.folder, 1., time_index=2)
        with patch('labelgui.core.persistence.np.save', side_effect=OSError('disk full')):
            with self.assertRaisesRegex(OSError, 'disk full'):
                save_resume_time(self.folder, 5., time_index=9)
        self.assertEqual(load_resume_state(self.folder), {'i_time': 1., 'time_index': 2})
        self.assert_only('exit_status.npy')


if __name__ == '__main__':
    unittest.main()
