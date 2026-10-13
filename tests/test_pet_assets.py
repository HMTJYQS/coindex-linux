import hashlib
import json
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent


class OriginalPetArtworkTests(unittest.TestCase):
    def test_bundled_artwork_matches_recorded_original_bytes(self):
        directory = ROOT / 'Resources/Pets'
        if not (directory / 'manifest.json').exists():
            self.skipTest('Optional original artwork has not been imported on this machine')
        manifest = json.loads((directory / 'manifest.json').read_text())
        self.assertEqual(len(manifest['pets']), 9)
        self.assertEqual((manifest['cell_width'], manifest['cell_height'], manifest['columns']), (192, 208, 8))
        for pet in manifest['pets']:
            with self.subTest(pet=pet['id']):
                self.assertEqual(hashlib.sha256((directory / pet['file']).read_bytes()).hexdigest(), pet['sha256'])
                self.assertEqual(pet['rows'], 11)
