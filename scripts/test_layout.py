import unittest
from assemble import label,live_sort
from probe import parse_live
class LayoutTest(unittest.TestCase):
 def entry(self,name,url='https://live.ottiptv.cc/huya/100',group='其他'):
  return {'name':name,'id':'','url':url,'source_group':group}
 def test_ambiguous_program_and_scenery(self):
  self.assertEqual(label(self.entry('特种兵之火凤凰'))[0],'影视轮播')
  self.assertEqual(label(self.entry('福建漳州醉美沙滩翡翠湾'))[0],'风景慢直播')
  self.assertEqual(label(self.entry('1987年春晚'))[0],'综艺轮播')
 def test_aliases_and_wrong_upstream_group(self):
  self.assertEqual(label(self.entry('敦化一套',group='纪录频道'))[0],'地方')
  self.assertEqual(label(self.entry('TVBS-Asia'))[:2],label(self.entry('TVBS亚洲'))[:2])
  self.assertEqual(label(self.entry('CGTN记录'))[:2],label(self.entry('CGTN纪录'))[:2])
  self.assertIsNone(label(self.entry('2026-08-27 14:06:22')))
 def test_user_agent_with_comma(self):
  raw='#EXTM3U\n#EXTINF:-1 tvg-id="test" http-user-agent="Mozilla/5.0 (KHTML, like Gecko)" group-title="港澳台",Lotus TV\nhttps://example.com/stream.m3u8\n'
  entries=parse_live(raw,'fixture');self.assertEqual(entries[0]['name'],'Lotus TV');self.assertEqual(entries[0]['headers']['User-Agent'],'Mozilla/5.0 (KHTML, like Gecko)')
 def test_cctv_plus_and_order(self):
  five=label(self.entry('CCTV5体育'))[:2];plus=label(self.entry('CCTV5+体育赛事'))[:2];six=label(self.entry('CCTV6电影'))[:2]
  self.assertNotEqual(five,plus)
  self.assertEqual(sorted([six,plus,five],key=lambda k:live_sort((k,[]))),[five,plus,six])
if __name__=='__main__':unittest.main()
