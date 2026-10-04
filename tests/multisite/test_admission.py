import json,tempfile,unittest
from pathlib import Path
from checker import health
from checker.television import playlist
from scripts.build_multisite import select

class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.now=1800000000
        self.site={'id':'s','order':1,'kind':'cms','status':'candidate','review':{'admitted':True},'config':{'name':'Sample','api':'https://cms.example/api','key':'s'}}
        self.proof={'accepted':True,'checked_at':self.now-100,'media_hosts':['media.example']}
        self.state={'site:s':{'local':{'state':'healthy','last_ok_ts':self.now-100}}}
    def selected(self,a=None):
        return select([self.site],a or {'s':{'local':self.proof}},self.now,self.state,{},native_audit={})[0]
    def test_initial_review_is_required(self):
        self.assertEqual(len(self.selected()),1)
        self.site['review']={};self.assertFalse(self.selected())
    def test_one_failure_uses_recent_success_two_failures_remove(self):
        a={'s':{'local':{'accepted':False,'last_success':self.proof}}}
        self.state['site:s']['local']['state']='degraded';self.assertEqual(len(self.selected(a)),1)
        self.state['site:s']['local']['state']='down';self.assertFalse(self.selected(a))
    def test_isolation_overrides_other_network_success(self):
        self.state['site:s']['global']={'isolated':True};self.assertFalse(self.selected())
    def test_evidence_expires(self):
        self.proof['checked_at']=self.now-8*86400;self.assertFalse(self.selected())
    def test_corrupt_state_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'s.json';p.write_text('{broken')
            with self.assertRaises(json.JSONDecodeError):health.load_state(p)
    def test_down_route_keeps_identity_gap(self):
        ch=[{'id':'tv1','name':'CCTV-1','group':'央视及教育','routes':['r1']}]
        routes=[{'id':'r1','url':'https://example/live.m3u8'}]
        text,gaps=playlist(ch,routes,{'r1':{'local':{'state':'down'}}},network='local')
        self.assertNotIn('#EXTINF',text);self.assertEqual(gaps[0]['channel_id'],'tv1')
    def test_extra_headers_roundtrip(self):
        from checker.television import parse_m3u
        ch=[{'id':'tv1','name':'CCTV-1','group':'央视及教育','routes':['r1']}]
        routes=[{'id':'r1','url':'https://example/live.m3u8','headers':{'Authorization':'Bearer abc'}}]
        text,_=playlist(ch,routes,{})
        self.assertEqual(parse_m3u(text,'test')[0]['headers'],routes[0]['headers'])

    def test_blocked_host_is_removed_wholesale(self):
        # 广告填充标识集中来自少数几个 host，逐条隔离追不上同一 host 上的新线路。
        ch=[{'id':'tv1','name':'CCTV-1','group':'央视及教育','routes':['r1','r2']}]
        routes=[{'id':'r1','url':'http://ad.example:98/a.m3u8'},{'id':'r2','url':'https://good.example/a.m3u8'}]
        text,gaps=playlist(ch,routes,{},blocked_hosts=['ad.example:98'])
        self.assertNotIn('ad.example:98',text);self.assertIn('good.example',text)
        # 没有健康证据时本来就会有一条"未核实"缺口，这里只关心名单 host 确实不再出现。
        self.assertEqual([g for g in gaps if g['reason'].startswith('route host')],[])

    def test_priority_channel_loses_confirmed_ad_route(self):
        # 方案 C 的 A 档：重点频道宁可缺台也不播广告——最后一条线路是广告也不保留。
        ch=[{'id':'tv1','name':'CCTV-5','group':'央视及教育','routes':['r1']}]
        routes=[{'id':'r1','url':'https://ad.example/cctv5.m3u8'}]
        text,gaps=playlist(ch,routes,{},protected_ads=['r1'],priority_groups=['央视及教育'])
        self.assertNotIn('#EXTINF',text)
        self.assertEqual(gaps[0]['reason'],'only remaining route is a confirmed advertisement')

    def test_non_priority_channel_keeps_ad_route_but_marks_it(self):
        # 方案 C 的 B 档：其余频道保留播出，但那一行要标出来，tvg-name 保持原名以便对回登记表。
        ch=[{'id':'tv1','name':'都市剧场','group':'电影剧场','routes':['r1']}]
        routes=[{'id':'r1','url':'https://ad.example/dsjc.m3u8'}]
        text,gaps=playlist(ch,routes,{},protected_ads=['r1'],priority_groups=['央视及教育'],ad_tag='⚠未核验')
        self.assertIn('都市剧场 ⚠未核验',text)
        self.assertEqual([g for g in gaps if g['reason']=='only remaining route is a confirmed advertisement'],[])

    def test_guide_id_is_omitted_when_the_guide_has_no_such_channel(self):
        # 登记了 id 但节目单里没有，对用户就是"没有节目单"——这种 id 不能发出去。
        ch=[{'id':'tv1','name':'CCTV-1','group':'央视及教育','routes':['r1']},
            {'id':'tv2','name':'翡翠台','group':'港澳台','routes':['r2']}]
        ch[0]['epg_id']='CCTV1';ch[1]['epg_id']='JADE'
        ch[0]['epg_source']=ch[1]['epg_source']='diyp:51zmt'
        ch[0]['epg_checked_at']=ch[1]['epg_checked_at']=1800000000
        routes=[{'id':'r1','url':'https://a.example/1.m3u8'},{'id':'r2','url':'https://b.example/2.m3u8'}]
        epg={'now':1800000000,'sources':['diyp:51zmt'],'max_age_days':35}
        text,_=playlist(ch,routes,{},epg=epg,guide_channels=['CCTV1'])
        self.assertIn('tvg-name="CCTV-1"',text);self.assertIn('tvg-id="CCTV1"',text)
        self.assertIn('tvg-name="翡翠台"',text);self.assertNotIn('tvg-id="JADE"',text)
