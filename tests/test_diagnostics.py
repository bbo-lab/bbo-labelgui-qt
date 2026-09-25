from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import yaml

from labelgui.core.annotations import AnnotationStore
from labelgui.core.diagnostics import format_frame_report
from labelgui.core.jobs import JobRepository
from labelgui.core.persistence import LabelRepository
from labelgui.core.session import LabelingSession
from test_core import FakeReader, make_session
from test_local_search import PeakReader


class DiagnosticsTests(unittest.TestCase):
    def test_table_uses_each_camera_frame_and_stored_metadata(self):
        labels = AnnotationStore(2, clock=lambda: 123.25)
        labels.set_point('nose', 1, 0, (1.25, 2.5), 'alice')
        labels.set_point('nose', 0, 1, (3.5, 4.75), 'bob')
        labels.set_point('wrong_frame', 1, 1, (99, 99), 'bob')
        labels.set_point('guess_only', 0, 0, (8, 8), 'alice')
        labels.set_point('deleted', 1, 0, (5, 5), 'alice')
        labels.delete_point('deleted', 1, 0, 'alice')
        reference = AnnotationStore(2, clock=lambda: 456.5)
        reference.set_point('nose', 1, 0, (6, 7), 'reference author')
        unknown = AnnotationStore(2)
        unknown.set_point('nose', 0, 1, (8, 9), 'unknown')
        unknown.data['labels']['nose'][0].pop('labeler')
        unknown.data['labels']['nose'][0].pop('point_times')
        report = format_frame_report(.3, (1, 0), labels, [reference, unknown])
        self.assertIn('Time: 0.300000 s', report)
        self.assertIn('Frames: camera 0 = 1, camera 1 = 0', report)
        rows = [[value.strip() for value in line.split(' | ')] for line in report.splitlines()[4:]]
        self.assertEqual(rows, [
            ['0', '1', 'labels', 'nose', '1.25', '2.5', 'alice', '123.250000'],
            ['0', '1', 'reference[0]', 'nose', '6', '7', 'reference author', '456.500000'],
            ['1', '0', 'labels', 'nose', '3.5', '4.75', 'bob', '123.250000'],
            ['1', '0', 'reference[1]', 'nose', '8', '9', '-', '-'],
        ])

    def test_navigation_logs_once_per_time_change_and_can_be_silenced(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertLogs('labelgui.core.session', level='INFO') as logs:
                session = make_session(folder)
                session.seek(0)
                session.step(1)
                session.seek(.6)
                session.seek(.6)
                session.select_label('tail')
                session.handle_video_action(0, 1, (2, 3), 'create_label')
            try:
                self.assertEqual(len(logs.records), 3)
                self.assertIn('(no stored labels on these frames)', logs.records[0].getMessage())
                self.assertIn('Time: 0.100000 s', logs.records[1].getMessage())
                self.assertIn('camera 0 = 1, camera 1 = 1', logs.records[2].getMessage())
                with patch('labelgui.core.session.logger.isEnabledFor', return_value=False), \
                        patch('labelgui.core.session.format_frame_report') as render:
                    session.step(1)
                    render.assert_not_called()
            finally:
                session.close()

    def test_tracking_reports_the_newly_assigned_camera_frame(self):
        with tempfile.TemporaryDirectory() as folder:
            session = make_session(folder)
            session.cameras[0].reader = PeakReader()
            session.annotations.clock = lambda: 123.25
            session.annotations.set_point('nose', 0, 0, (4, 5), 'alice')
            session.search_radius = 2
            try:
                with self.assertLogs('labelgui.core.session', level='INFO') as logs:
                    self.assertTrue(session.track_next(0))
                self.assertEqual(len(logs.records), 1)
                report = logs.records[0].getMessage()
                self.assertIn('Time: 0.500000 s', report)
                self.assertIn('camera 0 = 1', report)
                self.assertIn('alice', report)
                self.assertIn('123.250000', report)
            finally:
                session.close()

    def test_startup_logs_each_direct_file_and_the_resumed_frame(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            defaults = root / 'defaults.yml'
            defaults.write_text('user: alice\njob: test\n')
            (root / 'cam.avi').touch()
            (root / 'times.csv').write_text('time\n0\n.5\n1\n1.5\n2\n')
            (root / 'image.pgm').write_bytes(b'P5\n4 4\n255\n' + bytes(16))
            (root / 'sketch.yml').write_text(yaml.safe_dump({
                'version': '1.0', 'sketch': 'image.pgm', 'sketch_label_locations': {'nose': [1, 2]}}))
            store = AnnotationStore(1, clock=lambda: 123.25)
            store.set_point('nose', 2, 0, (1, 2), 'alice')
            repository = LabelRepository()
            for name in ('labels.yml', 'reference_a.yml', 'reference_b.yml'):
                repository.save(root / name, store.data)
            output = root / 'user/alice/test'
            output.mkdir(parents=True)
            np.save(output / 'exit_status.npy', {'i_time': 1.})
            config = root / 'job.yml'
            config.write_text(yaml.safe_dump({
                'dataset_name': 'test', 'recording_folder': '.', 'recording_filenames': ['cam.avi'],
                'video_times': {0: {'file': 'times.csv'}}, 'sketch_files': ['sketch.yml'],
                'load_labels_file': 'labels.yml',
                'reference_labels_file': ['reference_a.yml', 'reference_b.yml'], 'exit_save_labels': False,
            }))
            with self.assertLogs('labelgui', level='INFO') as logs:
                JobRepository(root, defaults).read_defaults()
                session = LabelingSession.open(root, 'alice', config, reader_factory=lambda _: FakeReader())
            try:
                messages = [record.getMessage() for record in logs.records]
                expected = ('defaults.yml', 'job.yml', 'cam.avi', 'times.csv', 'sketch.yml', 'image.pgm',
                            'labels.yml', 'reference_a.yml', 'reference_b.yml', 'user/alice/test/exit_status.npy')
                for filename in expected:
                    with self.subTest(filename=filename):
                        matching = [record for record in logs.records
                                    if record.getMessage().startswith('Loading ')
                                    and str(root / filename) in record.getMessage()]
                        self.assertEqual(len(matching), 1)
                        self.assertEqual(matching[0].levelname, 'INFO')
                self.assertIn('Loading reference[1]:', '\n'.join(messages))
                report = messages[-1]
                self.assertIn('Time: 1.000000 s', report)
                self.assertIn('Frames: camera 0 = 2', report)
                self.assertIn('alice', report)
            finally:
                session.close()
