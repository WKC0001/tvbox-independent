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

class GuideTests(unittest.TestCase):
    POLICY={'sources':['diyp:51zmt'],'max_age_days':21}
    def channel(self, **epg):
        channels,routes,_=import_registry(parse_m3u('#EXTINF:-1 group-title="卫视",湖南卫视\nhttps://example/a.m3u8','t'))
        channels[0].update(epg)
        return channels,routes
    def guide(self, channels, routes, now=1001):
        text,_=playlist(channels,routes,{},epg={**self.POLICY,'now':now})
        return text
    def test_import_never_invents_a_guide(self):
        channels,routes,_=import_registry(parse_m3u('#EXTINF:-1 tvg-id="湖南卫视",湖南卫视\nhttps://x/a.m3u8','t'))
        self.assertEqual(channels[0]['epg_id'],'')
        self.assertEqual(channels[0]['epg_checked_at'],0)
        self.assertNotIn('tvg-id',self.guide(channels,routes,now=10**9))
    def test_fresh_verified_mapping_is_emitted(self):
        self.assertIn('tvg-id="湖南卫视"',self.guide(*self.channel(epg_id='湖南卫视',epg_source='diyp:51zmt',epg_checked_at=1000)))
    def test_stale_confirmation_degrades_to_no_guide(self):
        channels,routes=self.channel(epg_id='湖南卫视',epg_source='diyp:51zmt',epg_checked_at=1000)
        self.assertNotIn('tvg-id',self.guide(channels,routes,now=1000+21*86400))
    def test_unknown_source_is_not_a_guide(self):
        self.assertNotIn('tvg-id',self.guide(*self.channel(epg_id='湖南卫视',epg_source='naming-rule',epg_checked_at=1000)))
    def test_missing_or_future_evidence_is_not_a_guide(self):
        self.assertNotIn('tvg-id',self.guide(*self.channel(epg_id='湖南卫视',epg_source='diyp:51zmt')))
        self.assertNotIn('tvg-id',self.guide(*self.channel(epg_id='湖南卫视',epg_source='diyp:51zmt',epg_checked_at=99999)))
    def test_without_a_source_policy_nothing_is_emitted(self):
        channels,routes=self.channel(epg_id='湖南卫视',epg_source='diyp:51zmt',epg_checked_at=1000)
        text,_=playlist(channels,routes,{})
        self.assertNotIn('tvg-id',text)

class RepositoryGuideStateTests(unittest.TestCase):
    """The shipped registry must stay auditable: an id is only ever stored with its source and date."""
    def setUp(self):
        self.channels=json.loads((ROOT/'registry/channels.json').read_text())
        self.sources=set(json.loads((ROOT/'policy/operations.json').read_text())['epg_sources'])
    def test_every_stored_id_carries_its_source_and_confirmation_time(self):
        for c in self.channels:
            if c.get('epg_id'):
                self.assertIn(c.get('epg_source'),self.sources,c['name'])
                self.assertGreater(c.get('epg_checked_at') or 0,0,c['name'])
            else:
                self.assertEqual(c.get('epg_source'),'',c['name'])
    def test_stored_ids_are_behless_api_handles_not_generated_names(self):
        for c in self.channels:
            self.assertNotIn('.fqzone.tv',c.get('epg_id') or '',c['name'])
    def test_match_report_agrees_with_the_registry(self):
        report=json.loads((ROOT/'reports/epg-match.json').read_text())
        self.assertEqual(report['channels_with_epg_id'],sum(1 for c in self.channels if c.get('epg_id')))
        # A rotating window probes one slice per run, so inspected is bounded by the registry
        # rather than equal to it, and every probe must land in exactly one verdict.
        self.assertGreater(report['inspected'],0)
        self.assertLessEqual(report['inspected'],len(self.channels))
        self.assertEqual(sum(report[k] for k in ('confirmed','retracted','unanswered','contaminated')),
                         report['inspected'])
    def test_timestamp_refresh_is_not_a_content_change(self):
        from scripts.guide_signature import digest
        refreshed=[{**c,'epg_checked_at':(c.get('epg_checked_at') or 0)+10**6} for c in self.channels]
        self.assertEqual(digest(refreshed),digest(self.channels))
        self.assertNotEqual(digest(self.channels[:-1]),digest(self.channels))
        changed=[{**c,'epg_id':''} if c.get('epg_id') else c for c in self.channels]
        if changed!=self.channels:self.assertNotEqual(digest(changed),digest(self.channels))

class RouteIdentityTests(unittest.TestCase):
    """A source that answers with a different channel must never reach the shipped playlist.

    The sampled aggregator serves a home-shopping feed for most requests and the real channel
    for the rest, so every byte it returns is valid HLS and reachability alone cannot tell the
    two apart. These assertions keep the identity evidence and the registry in step.
    """
    def setUp(self):
        self.channels=json.loads((ROOT/'registry/channels.json').read_text())
        self.routes=json.loads((ROOT/'registry/routes.json').read_text())
        self.policy=json.loads((ROOT/'policy/operations.json').read_text())
    def quarantined(self):
        return {r['id']:r for r in self.routes
                if r.get('review')=='quarantined' and 'identity' in (r.get('quarantine_reason') or '')}
    def test_quarantine_records_what_the_route_actually_served(self):
        for rid,route in self.quarantined().items():
            reason=route['quarantine_reason']
            served=reason.split('served ',1)[1].split(' (',1)[0] if 'served ' in reason else ''
            self.assertTrue(served and served!='unknown',reason)
            self.assertIn('requested ',reason,rid)
            self.assertIn('re-tests',reason,rid)
    def test_quarantined_routes_are_never_emitted(self):
        text,_=playlist(self.channels,self.routes,{},
                        network=self.policy['preferred_live_network'],
                        max_routes=self.policy['max_live_routes'])
        blocked={r['url'] for r in self.quarantined().values()}
        self.assertTrue(blocked,'no identity quarantine is recorded')
        for line in text.splitlines():
            if '://' in line:
                self.assertNotIn(line.split('|')[0],blocked,line)
    def test_report_agrees_with_the_registry(self):
        report=json.loads((ROOT/'reports/live-identity.json').read_text())
        self.assertEqual(set(report['quarantined']),set(self.quarantined()))
        self.assertEqual(report['routes_checked'],len(report['results']))
        # A withheld route is never re-screened for release, so its samples live under `reverified`;
        # either way everything the report condemns carries evidence from a sweep that measured it.
        evidence={r['id'] for r in report['results']}|{r['id'] for r in report['reverified']}
        self.assertTrue(set(report['quarantined']).issubset(evidence))
        self.assertTrue(set(report['quarantined']).issubset({c['id'] for c in report['confirmation']}))
        # A later sweep that only looks at admissible routes must not quietly drop the routes an
        # earlier one withheld: the ledger separates what was condemned today from what still stands.
        self.assertEqual(set(report['quarantined']),
                         set(report['newly_quarantined'])|set(report['carried_forward']))
        self.assertTrue(set(report['reverified_still_mismatching']).issubset(set(report['quarantined'])))
        for item in report['reverified']:
            self.assertTrue(item['samples'],'a re-probe recorded no samples: '+item['id'])
        # A sweep restricted to one known bad host must not be mistaken for an audit of everything
        # that ships: every registered http route has to be accounted for by the report.
        http={r['id'] for r in self.routes if r['url'].startswith(('http://','https://'))}
        seen=set(report['quarantined'])|{r['id'] for r in report['results']}
        seen|={r['id'] for r in self.routes if r.get('review')=='quarantined'}
        self.assertEqual(seen,http,'the identity report does not cover the whole registry')
    def test_only_opaque_names_are_unverifiable(self):
        from scripts.verify_live_identity import identity_tokens,judgeable,normalize,same_channel
        # The ad lineup serves bare numeric ids, so those must stay comparable.
        for value in ('107','102','mkt','dfws'):
            self.assertTrue(judgeable(value),value)
        for value in ('617290047','bc185d1ef1e52892','0b1b95c9-3543-4af9-9fdb-cf45f1602f17'):
            self.assertFalse(judgeable(value),value)
        self.assertEqual(normalize('dfwshd'),'dfws')
        self.assertEqual(normalize('cctv5hd'),'cctv5')
        self.assertFalse(same_channel('dfws','mkt'))
        self.assertTrue(same_channel('cctv5','cctv5md'))
        # A generic path with the channel in the query is still a named request.
        self.assertEqual(identity_tokens('http://h:82/gslb/zbdq5.m3u8?id=cctv8k'),['zbdq5','cctv8k'])

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
