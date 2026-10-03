import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from assemble import is_isolated, without_isolated_media
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
