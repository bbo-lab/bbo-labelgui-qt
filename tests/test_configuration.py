import math
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import Mock, patch

import yaml

from labelgui.core.configuration import load_configuration, job_config_path
from labelgui.core.jobs import JobRepository
from labelgui.core.annotations import AnnotationStore
from labelgui.core.persistence import LabelRepository
from labelgui.core.session import LabelingSession
from test_core import FakeReader


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.minimal = {'recording_folder': 'recordings',
                        'recording_filenames': ['cam0.mp4', 'cam1.mp4'],
                        'sketch_files': ['sketch.yml']}

    def write_config(self, data, suffix='.yml'):
        path = self.root / f'job{suffix}'
        path.write_text(yaml.safe_dump(data), encoding='utf-8')
        return path

    def test_yaml_extensions_defaults_and_relative_paths(self):
        for suffix in ('.yml', '.yaml'):
            with self.subTest(suffix=suffix):
                cfg = load_configuration(self.write_config(self.minimal, suffix))
                self.assertEqual(cfg['recording_folder'], str(self.root / 'recordings'))
                self.assertEqual(cfg['recording_filenames'], ['cam0.mp4', 'cam1.mp4'])
                self.assertEqual(cfg['sketch_files'], [str(self.root / 'sketch.yml')])
                self.assertEqual(cfg['allowed_cams'], [0, 1])
                self.assertEqual((cfg['min_time'], cfg['max_time']), (-math.inf, math.inf))
                self.assertEqual(cfg['d_time'], 0.)
                self.assertFalse(cfg['auto_save'])
                self.assertTrue(cfg['exit_save_labels'])
                self.assertTrue(all(cfg['controls']['buttons'].values()))
                self.assertTrue(all(cfg['controls']['fields'].values()))

    def test_optional_paths_and_partial_controls(self):
        cfg = load_configuration(self.write_config(self.minimal | {
            'recording_folder': str(self.root / 'absolute'),
            'load_labels_file': 'labels/start.yml',
            'reference_labels_file': 'labels/reference.yml',
            'video_times': {0: {'file': 'times/cam0.csv', 'offset': .25}, 1: {'fps': 30}},
            'controls': {'buttons': {'next_time': False}},
        }))
        self.assertEqual(cfg['recording_folder'], str(self.root / 'absolute'))
        self.assertEqual(cfg['load_labels_file'], str(self.root / 'labels/start.yml'))
        self.assertEqual(cfg['reference_labels_file'], str(self.root / 'labels/reference.yml'))
        self.assertEqual(cfg['video_times'][0]['file'], str(self.root / 'times/cam0.csv'))
        self.assertEqual(cfg['video_times'][0]['offset'], .25)
        self.assertEqual(cfg['video_times'][1], {'fps': 30., 'offset': 0.})
        self.assertFalse(cfg['controls']['buttons']['next_time'])
        self.assertTrue(cfg['controls']['buttons']['previous_time'])
        self.assertTrue(cfg['controls']['fields']['current_time'])

    def test_python_configuration_is_rejected_before_loading(self):
        path = self.root / 'job.py'
        path.write_text("{'standardRecordingFolder': 'recordings'}")
        with patch('labelgui.core.configuration.yaml_load') as loader:
            with self.assertRaisesRegex(ValueError, 'must be YAML'):
                load_configuration(path)
            loader.assert_not_called()

    def test_reference_file_lists_resolve_paths_and_validate_entries(self):
        paths = ['references/first.yml', str(self.root / 'second.yml')]
        cfg = load_configuration(self.write_config(self.minimal | {'reference_labels_file': paths}))
        self.assertEqual(cfg['reference_labels_file'],
                         [str(self.root / 'references/first.yml'), str(self.root / 'second.yml')])
        cfg = load_configuration(self.write_config(self.minimal | {'reference_labels_file': []}))
        self.assertEqual(cfg['reference_labels_file'], [])
        for value in ([None], [False], [True], [1], [' '], [['nested.yml']]):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'reference_labels_file'):
                load_configuration(self.write_config(self.minimal | {'reference_labels_file': value}))

    def test_session_loads_all_reference_files_and_legacy_options(self):
        sketch = Path(__file__).resolve().parents[1] / 'example/sketch.yml'
        repository = LabelRepository()
        for name, coords in [('first.yml', (1, 2)), ('second.yml', (3, 4))]:
            store = AnnotationStore(2)
            store.set_point('eye', 0, 0, coords, 'ref')
            repository.save(self.root / name, store.data)
        default = self.root / 'data/references/test.yml'
        default.parent.mkdir(parents=True)
        shutil.copy(self.root / 'first.yml', default)
        cases = [(['first.yml', 'second.yml'], [(1, 2), (3, 4)]),
                 ('first.yml', [(1, 2)]), (True, [(1, 2)]),
                 (False, []), (None, []), ([], [])]
        for source, expected in cases:
            with self.subTest(source=source):
                cfg = self.minimal | {'sketch_files': [str(sketch)], 'dataset_name': 'test',
                                      'exit_save_labels': False, 'reference_labels_file': source}
                session = LabelingSession.open(self.root, 'alice', self.write_config(cfg),
                                               reader_factory=lambda _: FakeReader())
                try:
                    session.only_annotated_references = False
                    self.assertEqual([p.coords for p in session.frame_annotations(0).references], expected)
                    self.assertEqual(session.frame_annotations(1).references, ())
                    processed = session.labels_folder / 'backup/labelgui_cfg_processed.yml'
                    self.assertEqual(load_configuration(processed), session.config)
                finally:
                    session.close()
        cfg['reference_labels_file'] = ['missing.yml', 'second.yml']
        with self.assertLogs('labelgui.core.session', level='WARNING') as logs:
            session = LabelingSession.open(self.root, 'alice', self.write_config(cfg),
                                           reader_factory=lambda _: FakeReader())
        try:
            self.assertIn('missing.yml', logs.output[0])
            session.only_annotated_references = False
            self.assertEqual([p.coords for p in session.frame_annotations(0).references], [(3, 4)])
        finally:
            session.close()

    def test_invalid_yaml_and_missing_fields(self):
        for data in (None, [], 'text', 42, {}, {'recording_folder': 'recordings'}):
            with self.subTest(data=data):
                with self.assertRaises(ValueError):
                    load_configuration(self.write_config(data))
        path = self.root / 'invalid.yaml'
        path.write_text('recording_folder: [')
        with self.assertRaisesRegex(ValueError, 'Invalid YAML job configuration'):
            load_configuration(path)

    def test_invalid_field_values(self):
        cases = [
            ('recording_folder', None), ('recording_filenames', 'cam.mp4'),
            ('recording_filenames', []), ('sketch_files', [1]),
            ('allowed_cams', []), ('allowed_cams', [2]), ('allowed_cams', [True]),
            ('min_time', float('nan')), ('max_time', None),
            ('d_time', float('inf')), ('d_time', 'bad'), ('d_time', True),
            ('sketch_zoom_scale', 0), ('auto_save', 'false'), ('exit_save_labels', 1),
            ('auto_save_N0', 0), ('auto_save_N1', 1.5), ('auto_save_N1', True),
            ('video_times', []), ('video_times', {'0': {'fps': 30}}),
            ('video_times', {2: {}}), ('video_times', {0: None}),
            ('video_times', {0: {'fps': 0}}), ('video_times', {0: {'offset': float('inf')}}),
            ('video_times', {0: {'file': None}}), ('controls', []),
            ('controls', {'buttons': None}), ('controls', {'fields': {'current_time': 'yes'}}),
            ('load_labels_file', True), ('reference_labels_file', 42), ('dataset_name', None),
        ]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                with self.assertRaisesRegex(ValueError, field):
                    load_configuration(self.write_config(self.minimal | {field: value}))
        with self.assertRaisesRegex(ValueError, 'min_time must be less than max_time'):
            load_configuration(self.write_config(self.minimal | {'min_time': 1, 'max_time': 1}))

    def test_bbo_includes_and_file_placeholders(self):
        assets = self.root / 'assets'
        assets.mkdir()
        (assets / 'recordings').mkdir()
        (assets / 'sketch.yml').touch()
        (assets / 'base.yml').write_text(yaml.safe_dump(self.minimal | {
            'recording_folder': '{file}/recordings', 'sketch_files': ['{file}/sketch.yml'],
        }))
        path = self.root / 'job.yaml'
        path.write_text('!include: assets/base.yml\nd_time: 0.5\n')
        cfg = load_configuration(path)
        self.assertEqual(cfg['recording_folder'], str(assets / 'recordings'))
        self.assertEqual(cfg['sketch_files'], [str(assets / 'sketch.yml')])
        self.assertEqual(cfg['d_time'], .5)

    def test_yaml_job_discovery_and_default_config(self):
        user = self.root / 'data/user/alice'
        jobs = user / 'jobs'
        jobs.mkdir(parents=True)
        (jobs / 'job.yaml').write_text('{}')
        (jobs / 'old.py').write_text('{}')
        (jobs / 'not_a_file.yml').mkdir()
        (user / 'labelgui_cfg.yaml').write_text('{}')
        repository = JobRepository(self.root, self.root / 'defaults.yml')
        self.assertEqual(repository.jobs('alice'), ['job'])
        self.assertEqual(job_config_path(self.root, 'alice', 'job'), jobs / 'job.yaml')
        self.assertEqual(job_config_path(self.root, 'alice'), user / 'labelgui_cfg.yaml')
        with self.assertRaises(FileNotFoundError):
            job_config_path(self.root, 'alice', 'old')
        repository.complete_job('alice', 'job')
        self.assertEqual(repository.jobs('alice'), [])
        self.assertEqual(len(list((jobs / 'done').iterdir())), 1)

    def test_recording_filter_is_saved_separately_from_resolved_path(self):
        sketch = Path(__file__).resolve().parents[1] / 'example/sketch.yml'
        pipeline = 'math=exp="out=i0/2";crop=size=8x6'
        cfg = self.minimal | {'sketch_files': [str(sketch)], 'exit_save_labels': False,
                              'recording_filenames': [f'cam0.mp4|{pipeline}', 'cam1.mp4']}
        factory = Mock(side_effect=lambda _: FakeReader())
        session = LabelingSession.open(self.root, 'alice', self.write_config(cfg), reader_factory=factory)
        try:
            path = self.root / 'recordings/cam0.mp4'
            self.assertEqual(session.cameras[0].path, path)
            self.assertEqual(session.cameras[0].filter_string, pipeline)
            self.assertEqual(session.cameras[1].filter_string, '')
            factory.assert_any_call(f'{path}|{pipeline}')
            factory.reset_mock()
            session.set_video_filters(['', ''])
            factory.assert_called_once_with(path)
        finally:
            session.close()

    def test_example_opens_and_archives_normalized_yaml(self):
        example = Path(__file__).resolve().parents[1] / 'example'
        target = self.root / 'example'
        shutil.copytree(example, target)
        (target / 'recordings').mkdir()
        for camera in ('camera_0.mp4', 'camera_1.mp4'):
            (target / 'recordings' / camera).touch()
        path = target / 'labelgui_cfg.yml'
        session = LabelingSession.open(self.root, 'alice', path, reader_factory=lambda _: FakeReader())
        try:
            self.assertEqual(session.dataset_name, 'example_bird')
            self.assertEqual(session.sketch.locations['eye'], (140., 50.))
            self.assertEqual(len(session.cameras), 2)
            self.assertEqual(session.cameras[0].path, target / 'recordings/camera_0.mp4')
            backup = session.labels_folder / 'backup'
            self.assertEqual((backup / path.name).read_text(), path.read_text())
            processed = backup / 'labelgui_cfg_processed.yml'
            self.assertEqual(yaml.safe_load(processed.read_text()), session.config)
            self.assertEqual(load_configuration(processed), session.config)
        finally:
            session.close()
