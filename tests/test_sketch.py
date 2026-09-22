import tempfile
import unittest
from pathlib import Path

import numpy as np
import yaml
from imageio.v3 import imwrite

from labelgui.core.sketch import Sketch


class SketchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.folder = self.root / 'sketches'
        self.folder.mkdir()
        self.image_path = self.root / 'bird.png'
        self.image = np.arange(60, dtype=np.uint8).reshape(4, 5, 3)
        imwrite(self.image_path, self.image)
        self.locations = {'eye': [1.5, 2], 'beak': [4, 3]}
        self.data = {'version': '1.0', 'sketch': '../bird.png',
                     'sketch_label_locations': self.locations}

    def write_yaml(self, data, suffix='.yml'):
        path = self.folder / f'sketch{suffix}'
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding='utf-8')
        return path

    def test_relative_image_paths_and_yaml_extensions(self):
        # The YAML lives outside the working directory and refers to its parent.
        for suffix in ('.yml', '.yaml'):
            with self.subTest(suffix=suffix):
                sketch = Sketch.load(self.write_yaml(self.data, suffix))
                np.testing.assert_array_equal(sketch.image, self.image)
                self.assertEqual(sketch.locations, {'eye': (1.5, 2.), 'beak': (4., 3.)})
                self.assertEqual(list(sketch.locations), ['eye', 'beak'])
                self.assertEqual(sketch.nearest_label(4, 3), 'beak')

    def test_absolute_image_path_and_numeric_version(self):
        self.data.update(sketch=str(self.image_path), version=1.0)
        sketch = Sketch.load(self.write_yaml(self.data))
        np.testing.assert_array_equal(sketch.image, self.image)

    def test_legacy_numpy_sketch(self):
        path = self.folder / 'sketch.npy'
        np.save(path, {'sketch': self.image, 'sketch_label_locations': self.locations})
        sketch = Sketch.load(path)
        np.testing.assert_array_equal(sketch.image, self.image)
        self.assertEqual(sketch.locations['eye'], (1.5, 2.))

    def test_missing_or_unsupported_version(self):
        for version in (None, '2.0', True):
            with self.subTest(version=version):
                data = dict(self.data)
                if version is None:
                    del data['version']
                else:
                    data['version'] = version
                with self.assertRaisesRegex(ValueError, 'Unsupported sketch version'):
                    Sketch.load(self.write_yaml(data))

    def test_invalid_yaml_and_document_structure(self):
        for data in (None, [], 'not a mapping'):
            with self.subTest(data=data):
                with self.assertRaisesRegex(ValueError, 'must contain a mapping'):
                    Sketch.load(self.write_yaml(data))
        path = self.folder / 'broken.yml'
        path.write_text('version: [', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Invalid sketch YAML'):
            Sketch.load(path)

    def test_invalid_image_reference(self):
        for image_file in (None, '', [], 42):
            with self.subTest(image_file=image_file):
                self.data['sketch'] = image_file
                with self.assertRaisesRegex(ValueError, 'image filename'):
                    Sketch.load(self.write_yaml(self.data))
        self.data['sketch'] = 'missing.png'
        with self.assertRaises(FileNotFoundError):
            Sketch.load(self.write_yaml(self.data))

    def test_invalid_landmarks(self):
        for locations in (None, {}, [], {'eye': [1]}, {'eye': [1, 2, 3]},
                          {'eye': [float('nan'), 2]}, {'eye': [1, float('inf')]},
                          {'eye': 'bad'}, {'eye': [[1, 2]]}, {'eye': [None, 1]},
                          {'eye': ['bad', 2]}, {'': [1, 2]}, {1: [1, 2]}):
            with self.subTest(locations=locations):
                self.data['sketch_label_locations'] = locations
                with self.assertRaisesRegex(ValueError, 'landmark'):
                    Sketch.load(self.write_yaml(self.data))

    def test_bundled_example(self):
        path = Path(__file__).resolve().parents[1] / 'example' / 'sketch.yml'
        sketch = Sketch.load(path)
        self.assertEqual(sketch.image.shape, (16, 24))
        self.assertEqual(sketch.nearest_label(22, 8), 'beak_tip')
        for x, y in sketch.locations.values():
            self.assertTrue(0 <= x < sketch.image.shape[1])
            self.assertTrue(0 <= y < sketch.image.shape[0])
