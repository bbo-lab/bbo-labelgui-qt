import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from labelgui.core.local_search import brightness, find_local_peak
from labelgui.core.timeline import Timeline
from test_core import FakeReader, make_session


class PeakReader(FakeReader):
    def __init__(self):
        super().__init__()
        self.frames = np.full((5, 12, 16), 20, dtype=np.uint8)
        for frame in range(5):
            self.frames[frame, 5, 4 + frame] = 200
            self.frames[frame, 0, 15] = 255  # Brighter, but outside the neighborhood.

    def get_data(self, frame):
        return self.frames[frame]


class LocalSearchTests(unittest.TestCase):
    def test_circle_edges_coordinates_and_ties(self):
        image = np.zeros((6, 8))
        image[2, 4] = 10
        image[4, 5] = 20  # Inside bounding square but outside radius 2.
        self.assertEqual(find_local_peak(image, (3, 2), 2), (4, 2))
        image[0, 0] = 30
        self.assertEqual(find_local_peak(image, (.2, .3), 2), (0, 0))
        self.assertIsNone(find_local_peak(image, (-10, -10), 1))
        self.assertEqual(find_local_peak(np.ones((6, 8)), (3.2, 2.3), 3), (3, 2))

    def test_color_nonfinite_values_and_custom_metric(self):
        rgba = np.zeros((3, 4, 4), dtype=np.uint8)
        rgba[0, 0, 3] = 255  # Alpha is not brightness.
        rgba[1, 2, :3] = [100, 200, 150]
        self.assertEqual(find_local_peak(rgba, (1, 1), 2), (2, 1))
        image = np.array([[np.nan, 3, np.inf], [4, -8, 2.]])
        self.assertEqual(find_local_peak(image, (1, 1), 2), (0, 1))
        self.assertEqual(find_local_peak(image, (1, 1), 2, lambda crop: -brightness(crop)), (1, 1))
        self.assertIsNone(find_local_peak(np.full((3, 3), np.nan), (1, 1), 2))
        with self.assertRaises(ValueError):
            find_local_peak(image, (1, 1), -1)
        with self.assertRaises(ValueError):
            find_local_peak(image, (1, 1), 2, lambda crop: 1)


class TrackingTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.session = make_session(self.folder.name)
        self.session.cameras[0].reader = PeakReader()
        self.session.cameras[1].reader = PeakReader()
        self.session.search_radius = 2

    def tearDown(self):
        self.session.close()
        self.folder.cleanup()

    def test_next_uses_camera_frame_not_global_step_or_single_label_mode(self):
        session = self.session
        session.annotations.set_point('nose', 0, 0, (4, 5), 'alice')
        session.single_label_mode = True
        session.d_time = 1.5
        self.assertTrue(session.track_next(0))
        self.assertEqual(session.current_time, .5)
        self.assertEqual(session.frame_index(0), 1)
        self.assertEqual(session.annotations.point('nose', 1, 0), (5, 5))
        self.assertIsNone(session.annotations.point('nose', 1, 1))
        # Camera 1 displays frame 1 at global time .5, though its timestamp is .6.
        session.annotations.set_point('nose', 1, 1, (5, 5), 'alice')
        self.assertTrue(session.track_next(1))
        self.assertEqual(session.current_time, 1.1)
        self.assertEqual(session.annotations.point('nose', 2, 1), (6, 5))

    def test_unassigned_guesses_last_frame_and_session_limits(self):
        session = self.session
        self.assertFalse(session.can_track_next(0))
        session.annotations.set_point('nose', 0, 0, (4, 5), 'alice')
        session.seek(.5)
        self.assertIsNotNone(session.annotations.guess('nose', 1, 0))
        self.assertFalse(session.track_next(0))
        session.seek(2)
        session.annotations.set_point('nose', 4, 0, (8, 5), 'alice')
        self.assertFalse(session.can_track_next(0))
        session.timeline = Timeline(session.timeline.camera_times, maximum=.5)
        self.assertFalse(session.track_next(0))

    def test_both_operations_use_the_same_replaceable_metric(self):
        session = self.session
        reader = session.cameras[0].reader
        reader.frames[0, 5, 3] = 0
        reader.frames[1, 5, 2] = 0
        session.pixel_metric = lambda crop: -brightness(crop)
        self.assertTrue(session.handle_video_action(0, 0, (4, 5), 'auto_label'))
        self.assertEqual(session.annotations.point('nose', 0, 0), (3, 5))
        self.assertTrue(session.track_next(0))
        self.assertEqual(session.annotations.point('nose', 1, 0), (2, 5))
        revision = session.annotations.revision
        self.assertFalse(session.handle_video_action(0, 0, (4, 5), 'auto_label'))
        self.assertEqual(session.annotations.revision, revision)

    def test_failed_search_does_not_advance_or_edit(self):
        session = self.session
        session.annotations.set_point('nose', 0, 0, (4, 5), 'alice')
        revision = session.annotations.revision
        session.pixel_metric = lambda crop: np.full(crop.shape[:2], np.nan)
        self.assertFalse(session.track_next(0))
        self.assertFalse(session.handle_video_action(0, 0, (4, 5), 'auto_label'))
        with patch.object(session.cameras[0], 'frame', side_effect=OSError('decode failed')):
            with self.assertRaises(OSError):
                session.track_next(0)
        self.assertEqual(session.current_time, 0)
        self.assertEqual(session.annotations.revision, revision)
