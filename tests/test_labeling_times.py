from pathlib import Path
import tempfile
import unittest

import numpy as np
import yaml

from labelgui.core.configuration import load_configuration
from labelgui.core.session import LabelingSession
from labelgui.core.timeline import Timeline
from test_core import FakeReader, make_session
from test_local_search import PeakReader


class LabelingTimesTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.config = self.root / 'job.yml'
        self.minimal = {'recording_folder': '.', 'recording_filenames': ['cam.avi'],
                        'sketch_files': ['sketch.npy'], 'dataset_name': 'test',
                        'exit_save_labels': False}

    def configure(self, **options):
        self.config.write_text(yaml.safe_dump(self.minimal | options), encoding='utf-8')
        return load_configuration(self.config)

    def session(self, times):
        session = make_session(self.root, labeling_times=times)
        self.addCleanup(session.close)
        session.timeline = Timeline(session.timeline.camera_times, labeling_times=times)
        return session

    def test_inline_times_and_default(self):
        self.assertIsNone(self.configure()['labeling_times'])
        self.assertIsNone(self.configure(labeling_times=None)['labeling_times'])
        cfg = self.configure(labeling_times=[1.25, .5, 3, .5])
        self.assertEqual(cfg['labeling_times'], [1.25, .5, 3., .5])

    def test_relative_files_and_info_logging(self):
        for suffix, content in (('.yml', '[1.25, 0.5, 3.0]\n'),
                                ('.yaml', '- 1.25\n- 0.5\n- 3.0\n'),
                                ('.txt', '# seconds\n1.25\n0.5 3.0 # end\n'),
                                ('.csv', '1.25,0.5,3.0\n')):
            with self.subTest(suffix=suffix):
                path = self.root / f'times{suffix}'
                path.write_text(content, encoding='utf-8')
                with self.assertLogs('labelgui.core.configuration', level='INFO') as logs:
                    cfg = self.configure(labeling_times=path.name)
                self.assertEqual(cfg['labeling_times'], [1.25, .5, 3.])
                self.assertIn(f'Loading labeling times: {path}', logs.records[-1].getMessage())

    def test_invalid_lists_and_files(self):
        for value in ([], False, True, 1, {}, [True], [None], [[1]], ['bad'],
                      [float('nan')], [float('inf')]):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'labeling_times'):
                self.configure(labeling_times=value)
        for suffix, contents in (('.yml', 'null'), ('.yml', '[1,'),
                                  ('.yml', 'times: [1]'), ('.txt', '# empty\n'),
                                  ('.csv', 'time\n0.5'), ('.txt', '1 nan')):
            with self.subTest(suffix=suffix, contents=contents):
                path = self.root / f'bad{suffix}'
                path.write_text(contents)
                with self.assertRaisesRegex(ValueError, 'labeling_times'):
                    self.configure(labeling_times=path.name)
        with self.assertRaises(FileNotFoundError):
            self.configure(labeling_times='missing.txt')

    def test_preserve_order_and_duplicates_while_filtering_and_mapping_frames(self):
        timeline = Timeline([[0, 1, 2, 3], [.1, .6, 1.1, 1.6, 2.1, 2.6]],
                            minimum=.5, maximum=2.5,
                            labeling_times=[2.5, 1.2, .5, 1.2, 0])
        np.testing.assert_array_equal(timeline.times, [1.2, .5, 1.2])
        self.assertEqual(timeline.current_time, 1.2)
        self.assertEqual(timeline.current_index, 0)
        self.assertEqual(timeline.step(1, 0), .5)
        self.assertEqual(timeline.step(1, 0), 1.2)
        self.assertEqual(timeline.current_index, 2)
        self.assertEqual([timeline.frame_index(i) for i in range(2)], [1, 2])
        self.assertEqual(timeline.step(1, 0), 1.2)
        self.assertEqual(timeline.step(-1, 0), .5)
        self.assertEqual(timeline.seek(100), 1.2)
        self.assertEqual(timeline.seek(-100), .5)
        for interval in (1, -1, -2):
            self.assertEqual(timeline.step(1, interval), 1.2)
            timeline.seek(.5)

    def test_duplicate_occurrences_step_independently_in_both_directions(self):
        timeline = Timeline([[0, 1, 2, 3]], labeling_times=[3, 1, 1, 2])
        self.assertEqual(timeline.current_time, 3)
        for index, value in ((1, 1), (2, 1), (3, 2), (3, 2)):
            self.assertEqual(timeline.step(1, 0), value)
            self.assertEqual(timeline.current_index, index)
        for index, value in ((2, 1), (1, 1), (0, 3), (0, 3)):
            self.assertEqual(timeline.step(-1, 0), value)
            self.assertEqual(timeline.current_index, index)
        timeline.step(2, 0)
        self.assertEqual(timeline.current_index, 2)
        timeline.seek(1)
        self.assertEqual(timeline.current_index, 2)
        timeline.seek(2)
        timeline.seek(1)
        self.assertEqual(timeline.current_index, 2)
        self.assertEqual(timeline.step(1, 1), 2)
        timeline.seek(0)
        self.assertEqual(timeline.current_time, 1)
        self.assertEqual(timeline.time_for_frame(0, 1), 1)
        np.testing.assert_array_equal(timeline.times, [3, 1, 1, 2])

    def test_marked_navigation_and_single_label_mode_follow_sequence(self):
        session = self.session([1.5, .5, .5, 1, 0])
        session.annotations.set_point('nose', 1, 0, (1, 2), 'alice')
        session.annotations.set_point('tail', 0, 1, (3, 4), 'alice')
        for index in (1, 2, 4):
            self.assertTrue(session.step_labeled(1))
            self.assertEqual(session.timeline.current_index, index)
        self.assertFalse(session.step_labeled(1))
        self.assertTrue(session.step_labeled(-1))
        self.assertEqual(session.timeline.current_index, 2)
        session.single_label_mode = True
        session.handle_video_action(0, 1, (5, 6), 'create_label')
        self.assertEqual(session.current_time, 1)
        self.assertEqual(session.timeline.current_index, 3)

    def test_invalid_or_filtered_empty_selection(self):
        for times in ([], [[1]], [np.nan], [np.inf]):
            with self.subTest(times=times), self.assertRaisesRegex(ValueError, 'labeling_times'):
                Timeline([[0, 1]], labeling_times=times)
        with self.assertRaisesRegex(ValueError, 'No labeling_times'):
            Timeline([[0, 1, 2]], minimum=.5, maximum=1, labeling_times=[0, 1, 2])

    def test_marked_navigation_only_visits_selected_times(self):
        session = self.session([.1, .9, 1.7])
        session.annotations.set_point('nose', 1, 0, (1, 2), 'alice')  # Excluded frame.
        self.assertFalse(session.step_labeled(1))
        session.annotations.set_point('tail', 2, 0, (3, 4), 'alice')
        session.annotations.set_point('nose', 3, 1, (5, 6), 'alice')
        self.assertTrue(session.step_labeled(1))
        self.assertEqual(session.current_time, .9)
        self.assertTrue(session.step_labeled(1))
        self.assertEqual(session.current_time, 1.7)
        self.assertFalse(session.step_labeled(1))
        self.assertTrue(session.step_labeled(-1))
        self.assertEqual(session.current_time, .9)
        self.assertFalse(session.step_labeled(-1))

    def test_tracking_never_edits_an_excluded_frame(self):
        session = self.session([0, 1])
        session.cameras[0].reader = PeakReader()
        session.annotations.set_point('nose', 0, 0, (4, 5), 'alice')
        revision = session.annotations.revision
        self.assertFalse(session.can_track_next(0))
        self.assertFalse(session.track_next(0))
        self.assertEqual(session.current_time, 0)
        self.assertEqual(session.annotations.revision, revision)
        # An offset shared time may still display exactly the next camera frame.
        session.timeline = Timeline(session.timeline.camera_times, labeling_times=[.1, .4])
        session.search_radius = 2
        self.assertTrue(session.can_track_next(0))
        self.assertTrue(session.track_next(0))
        self.assertEqual(session.current_time, .4)
        self.assertEqual(session.frame_index(0), 1)
        self.assertEqual(session.annotations.point('nose', 1, 0), (5, 5))

    def test_filter_changes_preserve_selected_times_and_bounds(self):
        session = self.session([0, .9, .4, .9, 1.7])
        session.config.update(min_time=.4, max_time=1.7)
        session.timeline = Timeline(session.timeline.camera_times, .4, 1.7,
                                    labeling_times=[0, .9, .4, .9, 1.7])
        session.step(2)
        session.reader_factory = lambda *args, **kwargs: FakeReader()
        self.assertTrue(session.set_video_filters(['test-filter', '']))
        np.testing.assert_array_equal(session.timeline.times, [.9, .4, .9])
        self.assertEqual(session.current_time, .9)
        self.assertEqual(session.timeline.current_index, 2)

    def test_open_file_selection_resume_and_archive(self):
        (self.root / 'cam.avi').touch()
        np.save(self.root / 'sketch.npy', {'sketch': np.zeros((10, 10), dtype=np.uint8),
                                         'sketch_label_locations': {'nose': [2, 3]}})
        times = self.root / 'times.yml'
        times.write_text('[1.7, 0.4, 0, 0.9, 0.9]')
        self.configure(labeling_times=times.name, min_time=.4, max_time=1.7)

        def open_session():
            return LabelingSession.open(self.root, 'alice', self.config,
                                         reader_factory=lambda _: FakeReader())

        session = open_session()
        try:
            np.testing.assert_array_equal(session.timeline.times, [.4, .9, .9])
            self.assertEqual(session.current_time, .4)
            self.assertEqual(session.frame_index(0), 1)
            session.step(1)
            self.assertEqual(session.current_time, .9)
            session.step(1)
            self.assertEqual(session.current_time, .9)
            self.assertEqual(session.timeline.current_index, 2)
            processed = session.labels_folder / 'backup' / 'labelgui_cfg_processed.yml'
            self.assertEqual(load_configuration(processed)['labeling_times'], [1.7, .4, 0, .9, .9])
        finally:
            session.close()
        restored = open_session()
        try:
            self.assertEqual(restored.current_time, .9)
            self.assertEqual(restored.timeline.current_index, 2)
        finally:
            restored.close()
        times.write_text('[0.4, 1.2]')
        changed = open_session()
        try:
            self.assertEqual(changed.current_time, .4)  # Old resume time is no longer selected.
        finally:
            changed.close()


if __name__ == '__main__':
    unittest.main()
