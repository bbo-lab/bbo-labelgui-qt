import os
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import Future
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
import yaml

from labelgui.core.annotations import AnnotationStore
from labelgui.core.configuration import job_config_path
from labelgui.core.jobs import JobRepository
from labelgui.core.persistence import LabelRepository, SaveService
from labelgui.core.session import Camera, LabelingSession, camera_timestamps
from labelgui.core.sketch import Sketch
from labelgui.core.synchronization import TimeSynchronizer
from labelgui.core.timeline import Timeline


class FakeReader:
    def __init__(self):
        self.closed = False

    def __len__(self):
        return 5

    def get_data(self, frame):
        return np.full((12, 16), frame, dtype=np.uint8)

    def get_meta_data(self):
        return {'fps': 2}

    def close(self):
        self.closed = True


def make_session(folder, **config):
    cfg = {'dataset_name': 'test', 'recording_folder': str(folder), 'd_time': 0,
           'allowed_cams': [0, 1], 'exit_save_labels': False, 'auto_save': False,
           'controls': {'buttons': dict.fromkeys(('save_labels', 'zoom_out', 'rotate', 'previous_time',
                       'next_time', 'single_label_mode', 'previous_label', 'next_label'), True),
                        'fields': {'current_time': True, 'd_time': True}}}
    cfg.update(config)
    sketch = Sketch(np.zeros((20, 20), dtype=np.uint8), {'nose': (2., 3.), 'tail': (15., 17.)})
    cameras = [Camera(Path(f'cam{i}.avi'), FakeReader(), {'fps': 2}) for i in range(2)]
    return LabelingSession(user='alice', config=cfg, cameras=cameras, sketches=[sketch],
                           timeline=Timeline([[0, .5, 1, 1.5, 2], [.1, .6, 1.1, 1.6, 2.1]]),
                           labels_folder=folder)


class TimelineTests(unittest.TestCase):
    def test_union_limits_offsets_and_nearest_camera_frames(self):
        timeline = Timeline([[0, .5, 1], [.1, .35, .6, .85]], .1, .9)
        np.testing.assert_allclose(timeline.times, [.1, .35, .5, .6, .85])
        timeline.seek(.6)
        self.assertEqual([timeline.frame_index(i) for i in range(2)], [1, 2])
        timeline.seek(-100)
        self.assertEqual(timeline.current_time, .1)
        timeline.seek(100)
        self.assertEqual(timeline.current_time, .85)

    def test_three_step_modes_and_boundaries(self):
        timeline = Timeline([[0, 1, 2], [.25, .75, 1.25, 1.75]])
        self.assertEqual(timeline.step(-1, 0), 0)
        self.assertEqual(timeline.step(1, 0), .25)
        self.assertEqual(timeline.step(1, .5), .75)
        timeline.seek(0)
        self.assertEqual(timeline.step(-1, -1), 0)
        self.assertEqual(timeline.step(1, -1), 1)
        self.assertEqual(timeline.step(100, -1), 2)
        self.assertEqual(timeline.step(1, 0), 2)

    def test_invalid_and_empty_times(self):
        for times in ([], [[]], [[np.nan]], [[1, 0]]):
            with self.assertRaises(ValueError):
                Timeline(times)
        with self.assertRaises(ValueError):
            Timeline([[0, 1]], 2, 3)
        with self.assertRaises(ValueError):
            Timeline([[0, 1]]).seek(float('nan'))

    def test_timestamp_generation_and_csv(self):
        reader = FakeReader()
        np.testing.assert_allclose(camera_timestamps(reader, {'fps': 2}, {'offset': 1}), [1, 1.5, 2, 2.5, 3])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'times.csv'
            path.write_text('time\n0\n0.2\n0.4\n0.6\n0.8\n')
            np.testing.assert_allclose(camera_timestamps(reader, {}, {'file': path}), [0, .2, .4, .6, .8])
            path.write_text('time\n0\n')
            with self.assertRaises(ValueError):
                camera_timestamps(reader, {}, {'file': path})


class AnnotationTests(unittest.TestCase):
    def test_edit_delete_metadata_and_camera_independence(self):
        store = AnnotationStore(2, clock=lambda: 123.)
        store.set_point('nose', 4, 1, (10, 20), 'alice')
        self.assertIsNone(store.point('nose', 4, 0))
        self.assertEqual(store.point('nose', 4, 1), (10, 20))
        store.clock = lambda: 124.
        self.assertTrue(store.delete_point('nose', 4, 1, 'bob'))
        entry = store.data['labels']['nose'][4]
        self.assertTrue(np.isnan(entry['coords'][1]).all())
        self.assertEqual(entry['point_times'][1], 124.)
        self.assertEqual(store.data['labeler_list'][entry['labeler'][1]], 'bob')
        self.assertFalse(store.delete_point('nose', 4, 1, 'bob'))

    def test_guesses_skip_missing_camera_and_do_not_create_annotations(self):
        store = AnnotationStore(2)
        store.set_point('nose', 0, 0, (0, 4), 'alice')
        store.set_point('nose', 2, 0, (4, 8), 'alice')
        self.assertEqual(store.guess('nose', 1, 0), (2, 6))
        self.assertIsNone(store.point('nose', 1, 0))
        store.delete_point('nose', 2, 0, 'alice')
        self.assertEqual(store.guess('nose', 3, 0), (0, 4))
        self.assertIsNone(store.guess('nose', 3, 1))

    def test_reference_filter_and_per_camera_labelers(self):
        store, refs = AnnotationStore(2), AnnotationStore(2)
        store.set_point('nose', 0, 0, (1, 2), 'alice')
        store.set_point('tail', 0, 1, (3, 4), 'bob')
        refs.set_point('nose', 0, 0, (2, 3), 'ref')
        refs.set_point('eye', 0, 0, (4, 5), 'ref')
        view = store.frame_annotations(0, 0, refs)
        self.assertEqual([p.name for p in view.references], ['nose'])
        self.assertEqual(view.labelers, ('alice',))
        self.assertEqual(len(store.frame_annotations(0, 0, refs, False).references), 2)


class PersistenceTests(unittest.TestCase):
    def test_snapshot_isolated_from_edits_and_worker_mutation(self):
        started, release = threading.Event(), threading.Event()
        received = []
        class Repository:
            def save(self, path, labels):
                started.set()
                if not release.wait(5):
                    raise RuntimeError('Test timed out')
                received.append(labels['labels']['nose'][0]['coords'][0].copy())
                labels['labels'].clear()
        store = AnnotationStore(1)
        store.set_point('nose', 0, 0, (1, 2), 'alice')
        saver = SaveService(Repository())
        try:
            saver.save('unused.yml', store.data)
            self.assertTrue(started.wait(5))
            store.set_point('nose', 0, 0, (3, 4), 'alice')
            release.set()
            saver.check(wait=True)
            np.testing.assert_array_equal(received[0], [1, 2])
            self.assertEqual(store.point('nose', 0, 0), (3, 4))
        finally:
            release.set()
            saver.close()

    def test_real_bbo_roundtrip_preserves_deletion_metadata(self):
        store = AnnotationStore(2, clock=lambda: 456.)
        store.set_point('nose', 0, 1, (2, 3), 'alice')
        store.delete_point('nose', 0, 1, 'bob')
        store.set_point('tail', 1, 0, (7, 8), 'alice')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'labels.yml'
            repository = LabelRepository()
            repository.save(path, store.data)
            loaded = repository.load(path)
            self.assertTrue(path.with_suffix('.npz').exists())
            self.assertTrue(np.isnan(loaded['labels']['nose'][0]['coords'][1]).all())
            self.assertEqual(loaded['labels']['nose'][0]['point_times'][1], 456.)
            np.testing.assert_array_equal(loaded['labels']['tail'][1]['coords'][0], [7, 8])

    def test_failed_write_keeps_canonical_file_and_reports_error(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'labels.yml'
            path.write_text('original')
            saver = SaveService()
            try:
                with patch('labelgui.core.persistence.label_lib.save', side_effect=OSError('disk full')):
                    saver.save(path, AnnotationStore(1).data)
                    with self.assertRaisesRegex(RuntimeError, 'disk full'):
                        saver.check(wait=True)
                self.assertEqual(path.read_text(), 'original')
            finally:
                saver.close()


class SessionTests(unittest.TestCase):
    def test_navigation_and_selection_do_not_save_unchanged_labels(self):
        with tempfile.TemporaryDirectory() as folder:
            session = make_session(folder, auto_save=True, auto_save_N0=1,
                                   auto_save_N1=2, exit_save_labels=True)
            with patch.object(session.saver.repository, 'save') as save:
                try:
                    session.step(1)
                    session.select_label('tail')
                    session.select_sketch(0)
                    session.seek(0)
                    session.handle_video_action(0, 0, (1, 2), 'delete_label')
                    self.assertFalse(session.labels_changed)
                    self.assertIsNone(session.save())
                finally:
                    session.close()
                save.assert_not_called()
            self.assertTrue((Path(folder) / 'exit_status.npy').exists())

    def test_edits_and_deletions_dirty_labels_until_saved(self):
        with tempfile.TemporaryDirectory() as folder:
            session = make_session(folder, auto_save=True, auto_save_N0=1, auto_save_N1=2)
            try:
                session.handle_video_action(0, 0, (1, 2), 'create_label')
                self.assertTrue(session.labels_changed)
                session.save().result()
                self.assertFalse(session.labels_changed)
                session.handle_video_action(0, 0, (1, 2), 'delete_label')
                self.assertTrue(session.labels_changed)
                session.save().result()
                self.assertFalse(session.labels_changed)
                session.handle_video_action(0, 0, (1, 2), 'delete_label')
                self.assertFalse(session.labels_changed)
                # Single-label mode must mark the edit before navigation autosaves.
                session.single_label_mode = True
                session.handle_video_action(0, 0, (3, 4), 'create_label')
                session.saver.check(wait=True)
                self.assertFalse(session.labels_changed)
                saved = LabelRepository().load(Path(folder) / 'labels.yml')
                np.testing.assert_array_equal(saved['labels']['nose'][0]['coords'][0], [3, 4])
            finally:
                session.close()

    def test_pending_save_does_not_clear_new_edits_or_queue_duplicates(self):
        with tempfile.TemporaryDirectory() as folder:
            session = make_session(folder)
            first, second = Future(), Future()
            try:
                with patch.object(session.saver, 'save', side_effect=[first, second]) as save:
                    session.handle_video_action(0, 0, (1, 2), 'create_label')
                    self.assertIs(session.save(), first)
                    self.assertTrue(session.labels_changed)
                    self.assertIs(session.save(), first)
                    save.assert_called_once()
                    session.handle_video_action(0, 0, (3, 4), 'create_label')
                    first.set_result(None)
                    self.assertTrue(session.labels_changed)
                    self.assertIs(session.save(), second)
                    second.set_result(None)
                    self.assertFalse(session.labels_changed)
                    self.assertIsNone(session.save())
                    self.assertEqual(save.call_count, 2)
            finally:
                session.close()

    def test_save_as_can_export_unchanged_labels_without_clearing_regular_dirty_state(self):
        with tempfile.TemporaryDirectory() as folder:
            session = make_session(folder)
            target = Path(folder) / 'export.yml'
            try:
                session.save(target, force=True).result()
                self.assertTrue(target.exists())
                self.assertFalse(session.labels_changed)
                session.handle_video_action(0, 0, (1, 2), 'create_label')
                session.save(target, force=True).result()
                self.assertTrue(session.labels_changed)
                session.save().result()
                self.assertFalse(session.labels_changed)
            finally:
                session.close()

    def test_workflow_uses_camera_local_frames_and_selection(self):
        with tempfile.TemporaryDirectory() as folder:
            session = make_session(folder)
            try:
                session.select_sketch_point(15, 16)
                self.assertEqual(session.current_label, 'tail')
                session.seek(.6)
                self.assertTrue(session.handle_video_action(1, 1, (3, 4), 'create_label'))
                self.assertEqual(session.annotations.point('tail', 1, 1), (3, 4))
                session.select_label('nose')
                session.handle_video_action(1, 1, (3, 4), 'select_label')
                self.assertEqual(session.current_label, 'tail')
                self.assertFalse(session.handle_video_action(1, 0, (9, 9), 'create_label'))
                session.single_label_mode = True
                session.handle_video_action(1, 1, (3, 4), 'delete_label')
                self.assertIsNone(session.annotations.point('tail', 1, 1))
                self.assertEqual(session.current_time, 1.)
            finally:
                session.close()
            self.assertTrue(all(c.reader.closed for c in session.cameras))

    def test_autosave_cadence_and_resume(self):
        with tempfile.TemporaryDirectory() as folder:
            session = make_session(folder, auto_save=True, auto_save_N0=2, auto_save_N1=4)
            try:
                session.annotations.set_point('nose', 0, 0, (1, 2), 'alice')
                for _ in range(4):
                    session.step(1)
                session.saver.check(wait=True)
                self.assertTrue((Path(folder) / 'labels.yml').is_file())
                self.assertTrue((Path(folder) / 'autosave' / 'labels.yml').is_file())
                self.assertFalse(session.labels_changed)
                with patch.object(session.saver.repository, 'save') as save:
                    for _ in range(4):
                        session.step(1)
                    session.saver.check(wait=True)
                    save.assert_not_called()
            finally:
                session.close()
            self.assertEqual(np.load(Path(folder) / 'exit_status.npy', allow_pickle=True)[()]['i_time'], 2.)

    def test_close_failure_allows_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            session = make_session(folder, exit_save_labels=True)
            session.handle_video_action(0, 0, (1, 2), 'create_label')
            repository = session.saver.repository
            original = repository.save
            repository.save = Mock(side_effect=OSError('disk full'))
            with self.assertRaises(RuntimeError):
                session.close()
            self.assertTrue(session.labels_changed)
            self.assertFalse(session.cameras[0].reader.closed)
            repository.save = original
            session.close()
            self.assertFalse(session.labels_changed)
            self.assertTrue(session.cameras[0].reader.closed)

    def test_open_config_sketch_recordings_and_restore(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            sketch = root / 'sketch.npy'
            np.save(sketch, {'sketch': np.zeros((10, 10), dtype=np.uint8),
                             'sketch_label_locations': {'nose': [2, 3]}})
            config = root / 'job.yml'
            config.write_text(yaml.safe_dump({'recording_folder': str(root), 'recording_filenames': ['cam.avi'],
                'sketch_files': [str(sketch)], 'allowed_cams': [0], 'min_time': .25, 'max_time': 2,
                'd_time': 0, 'dataset_name': 'job', 'controls': {'buttons': {}, 'fields': {}},
                'exit_save_labels': True}))
            # Path decoder checks existence before passing to the supplied reader.
            (root / 'cam.avi').touch()
            session = LabelingSession.open(root, 'alice', config, reader_factory=lambda path: FakeReader())
            self.assertEqual(session.current_time, .5)
            session.seek(1.5)
            session.handle_video_action(0, 3, (5, 6), 'create_label')
            session.close()
            # The same job can resume with a YAML sketch referencing an image.
            from imageio.v3 import imwrite
            imwrite(root / 'sketch.png', np.zeros((10, 10), dtype=np.uint8))
            yaml_sketch = root / 'sketch.yml'
            yaml_sketch.write_text(yaml.safe_dump({'version': '1.0', 'sketch': 'sketch.png',
                                                  'sketch_label_locations': {'nose': [2, 3]}}))
            cfg = yaml.safe_load(config.read_text())
            cfg['sketch_files'] = [str(yaml_sketch)]
            config.write_text(yaml.safe_dump(cfg))
            restored = LabelingSession.open(root, 'alice', config, reader_factory=lambda path: FakeReader())
            try:
                self.assertFalse(restored.labels_changed)
                self.assertEqual(restored.sketch.locations, {'nose': (2., 3.)})
                self.assertEqual(restored.current_time, 1.5)
                self.assertEqual(restored.annotations.point('nose', 3, 0), (5, 6))
            finally:
                restored.close()


class IntegrationTests(unittest.TestCase):
    def test_core_and_cli_import_without_gui(self):
        code = '''
import sys
import labelgui.core.session
import labelgui.__main__
from pathlib import Path
from labelgui.core.sketch import Sketch
Sketch.load(Path('example/sketch_svg.yml'))
assert not any(name.startswith(('PySide6', 'pyqtgraph', 'matplotlib')) for name in sys.modules)
'''
        subprocess.run([sys.executable, '-c', code], check=True)

    def test_cli_merge_does_not_start_gui(self):
        from labelgui.__main__ import main
        with patch.object(sys, 'argv', ['labelgui', 'target.yml', '--merge', 'source.yml']), \
                patch('labelgui.__main__.label_lib.merge') as merge:
            main()
        merge.assert_called_once_with(['source.yml'], target_file=Path('target.yml'), overwrite=True, yml_only=False)

    def test_mqtt_uses_configured_topic_and_rejects_bad_payload(self):
        received = []
        sync = TimeSynchronizer('custom/time', received.append)
        sync.client = Mock()
        sync.publish(1.25)
        sync.client.publish.assert_called_once_with('custom/time', payload='1.25')
        for topic, payload in [('custom/time', b'1.25'), ('custom/time', b'bad'),
                                ('custom/time', b'nan'), ('other', b'3')]:
            sync._on_message(None, None, Mock(topic=topic, payload=payload))
        self.assertEqual(received, [1.25])
        sync.close()
        self.assertIsNone(sync.client)

    def test_job_discovery_defaults_and_completion(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            jobs = root / 'data' / 'user' / 'alice' / 'jobs'
            jobs.mkdir(parents=True)
            (jobs / 'job.yml').write_text('{}')
            (jobs / 'job.yaml').write_text('{}')
            (jobs / 'job.py').write_text('{}')
            (jobs / 'python_only.py').write_text('{}')
            repository = JobRepository(root, root / 'defaults.yml')
            self.assertEqual(repository.users(), ['alice'])
            self.assertEqual(repository.jobs('alice'), ['job'])
            self.assertEqual(job_config_path(root, 'alice', 'job'), jobs / 'job.yml')
            repository.write_defaults('alice', 'job')
            self.assertEqual(repository.read_defaults(), {'user': 'alice', 'job': 'job'})
            repository.complete_job('alice', 'job')
            self.assertEqual(repository.jobs('alice'), [])
            self.assertEqual(len(list((jobs / 'done').iterdir())), 2)
            self.assertTrue((jobs / 'job.py').exists())
            self.assertTrue((jobs / 'python_only.py').exists())


if __name__ == '__main__':
    unittest.main()
