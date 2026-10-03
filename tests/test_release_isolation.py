import copy
import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from assemble import is_isolated, without_isolated_media
import assemble
from catalog.ids import route_id


class ReleaseIsolationTest(unittest.TestCase):
    def test_isolation_cannot_be_overridden_by_another_network(self):
        url = 'https://example.com/live.m3u8'
        state = {route_id(url): {'cn': {'isolated': True}, 'gh': {'state': 'healthy'}}}
        self.assertTrue(is_isolated(state, url))

    def test_outage_does_not_automatically_become_content_block(self):
        url = 'https://example.com/live.m3u8'
        self.assertFalse(is_isolated({route_id(url): {'gh': {'state': 'down'}}}, url))

    def test_isolated_episode_removed_and_correct_alternative_retained(self):
        bad, good = 'https://example.com/bad.m3u8', 'https://example.org/ok.m3u8'
        row = {'vod_play_from': 'A$$$B', 'vod_play_url': '第1集$'+bad+'$$$第1集$'+good}
        result = without_isolated_media([copy.deepcopy(row)],
                                       {route_id(bad): {'default': {'isolated': True}}})
        self.assertEqual(result[0]['vod_play_from'], 'B')
        self.assertEqual(result[0]['vod_play_url'], '第1集$'+good)
        self.assertIn(bad, row['vod_play_url'])

    def test_fully_isolated_work_not_displayed(self):
        bad = 'https://example.com/bad.m3u8'
        rows = [{'vod_play_from': 'A', 'vod_play_url': '正片$'+bad}]
        self.assertEqual(without_isolated_media(rows,
                         {route_id(bad): {'default': {'isolated': True}}}), [])


class ReleaseReproducibilityTest(unittest.TestCase):
    def test_release_snapshot_survives_clock_changes_and_version_bump(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for folder in ('posters', 'state'):
                shutil.copytree(ROOT / folder, root / folder)
            (root / 'input').mkdir()
            for name in ('approved-catalog.json', 'approved-live.json', 'live-allowed-hosts.json'):
                shutil.copyfile(ROOT / 'input' / name, root / 'input' / name)
            for name in ('package.json', 'home.jpg', 'manifest.json'):
                shutil.copyfile(ROOT / name, root / name)
            (root / 'reports').mkdir()
            (root / 'java/src/com/github/catvod/spider').mkdir(parents=True)
            original = (root / 'manifest.json').read_bytes()
            def rebuild(clock):
                with patch.object(assemble, 'ROOT', root), \
                     patch('assemble.time.strftime', return_value=clock), \
                     contextlib.redirect_stdout(io.StringIO()):
                    assemble.main()
                return (root / 'manifest.json').read_bytes()
            self.assertEqual(rebuild('2030-01-01T00:00:00Z'), original)
            self.assertEqual(rebuild('2040-01-01T00:00:00Z'), original)
            package = json.loads((root / 'package.json').read_text())
            package['version'] = '99.0.0'
            (root / 'package.json').write_text(json.dumps(package))
            bumped = rebuild('2050-01-01T00:00:00Z')
            self.assertEqual(json.loads(bumped)['generated_at'], '2050-01-01T00:00:00Z')
            self.assertEqual(rebuild('2060-01-01T00:00:00Z'), bumped)
