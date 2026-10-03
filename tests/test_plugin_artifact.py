"""Regression: Java tests can pass while the shipped Android binary is stale."""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from verify_plugin import inspect_dex, verify_plugin


class PluginArtifactTest(unittest.TestCase):
    def test_shipped_dex_matches_actual_catalogue(self):
        self.assertTrue(verify_plugin(ROOT)['passed'])

    def test_previous_release_dex_rejected_even_with_current_java_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            for f in ('api.json', 'manifest.json'):
                shutil.copyfile(ROOT / f, tmp / f)
            shutil.copyfile(ROOT / 'tests/fixtures/stale-home.jpg', tmp / 'home.jpg')
            with self.assertRaisesRegex(ValueError, 'Shipped DEX catalogue mismatch'):
                verify_plugin(tmp)

    def test_non_dex_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Android DEX'):
            inspect_dex(b'fake plugin')

    def test_damaged_dex_rejected(self):
        with ZipFile(ROOT / 'home.jpg') as z:
            data = bytearray(z.read('classes.dex'))
        data[-1] ^= 1
        with self.assertRaisesRegex(ValueError, 'DEX signature mismatch'):
            inspect_dex(bytes(data))


if __name__ == '__main__':
    unittest.main()
