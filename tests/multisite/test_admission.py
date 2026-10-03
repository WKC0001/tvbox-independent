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
