import json
import unittest
from pathlib import Path
from checker.television import canonical,parse_m3u,import_registry,exclusion,playlist,group
from checker.content import genre,allowed_types,safe_item

ROOT=Path(__file__).resolve().parents[2]

class TelevisionTests(unittest.TestCase):
    def test_distinct_services(self):
        names=['CCTV-4','CCTV-4K HD (1080p)','CCTV-8','CCTV-8K HD (1080p)','CCTV-5','CCTV-5+']
        self.assertEqual(len(set(map(canonical,names))),6)
        self.assertNotEqual(canonical('CHC家庭影院'),canonical('NewTV家庭影院'))
    def test_real_aliases(self):
        self.assertEqual(canonical('CCTV16'),canonical('CCTV-16 HD (1080p)'))
        self.assertEqual(canonical('CCTV-1 (720p)'),canonical('CCTV-1'))
        self.assertEqual(canonical('苏州4k'),'苏州4K')
    def test_parser_preserves_headers_names(self):
        text='#EXTM3U\n#EXTINF:-1 tvg-id="actual" group-title="a,b",News, English\n#EXTVLCOPT:http-referrer=https://station.example/\n#EXTVLCOPT:http-user-agent=Custom\nhttps://station.example/a.m3u8?signature=abc|Origin=https%3A%2F%2Fstation.example\n'
        r=parse_m3u(text,'fixture')[0]
        self.assertEqual(r['name'],'News, English');self.assertEqual(r['attributes']['tvg-id'],'actual')
        self.assertEqual(r['headers']['Origin'],'https://station.example');self.assertIn('signature=abc',r['url'])
    def test_platform_domain_boundary(self):
        self.assertIsNone(exclusion({'name':'沭阳综合','url':'https://shuyang-tv-hls.cm.jstv.com/live/a.m3u8'}))
        self.assertEqual(exclusion({'name':'轮播','url':'https://proxy.example/huya/123'}),'platform-carousel')
    def test_same_host_backups_kept(self):
        s='#EXTM3U\n'+''.join('#EXTINF:-1 group-title="央视",CCTV-1\nhttps://example/a'+str(i)+'.m3u8\n' for i in range(3))
        c,r,m=import_registry(parse_m3u(s,'test'));self.assertEqual(len(c),1);self.assertEqual(len(r),3)
        text,gaps=playlist(c,r,{});self.assertEqual(text.count('#EXTINF'),3)
    def test_wrong_group_and_epg(self):
        self.assertEqual(group('第一财经','央视'),'地方·上海')
        self.assertEqual(group('苏州4K','卫视'),'地方·江苏')
        c,r,m=import_registry(parse_m3u('#EXTINF:-1 tvg-id="fake.fqzone.tv",CCTV-1\nhttps://x/a.m3u8','t'))
        self.assertEqual(c[0]['epg_id'],'')
    def test_complete_old_record_ledger(self):
        raw=parse_m3u((ROOT/'registry/baseline/live.m3u').read_text(),'source-monitor@0.1.26')
        ledger=json.loads((ROOT/'reports/live-migration.json').read_text())
        self.assertEqual(len(raw),1024);self.assertEqual(len(raw),len(ledger))
        self.assertEqual({x['record'] for x in ledger},set(range(1,1025)))
    def test_all_18_exclusions_registered(self):
        sites=json.loads((ROOT/'registry/sites.json').read_text())
        self.assertEqual(sum(s['status']=='excluded' for s in sites),18)
        self.assertEqual(sum(s['status']!='excluded' for s in sites),43)

class ContentTests(unittest.TestCase):
    def test_no_substring_category_admission(self):
        for s in ('里番动漫','伦理片','成人动漫','午夜福利电影','新闻资讯','体育赛事','预告片'):
            self.assertIsNone(genre(s),s)
        for s in ('动作片','国产剧','国产动漫','大陆综艺'):
            self.assertIsNotNone(genre(s),s)
    def test_details_cannot_bypass_type(self):
        types=allowed_types([{'type_id':1,'type_name':'电影'},{'type_id':2,'type_name':'伦理片'}])
        self.assertTrue(safe_item({'type_id':1,'vod_id':1,'vod_name':'正常影片'},types))
        self.assertFalse(safe_item({'type_id':2,'vod_id':1,'vod_name':'看似正常'},types))
        self.assertFalse(safe_item({'type_id':1,'vod_id':1,'vod_name':'看似正常','type_name':'伦理片'},types))

if __name__=='__main__':unittest.main()
