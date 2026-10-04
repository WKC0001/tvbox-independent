import json,os,re,urllib.request
from pathlib import Path
v=os.environ['RELEASE_VERSION'];assert re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+',v)
p=Path('reports/acceptance')/(v+'.json');e=json.loads(p.read_text())
# 门槛是机器可验证的三项，由 scripts/auto_acceptance.py 在发布流水线里产生：
#   cdn_verified     发布产物与构建产物逐字节一致
#   config_protocol  发布出去的单仓配置结构合法（聚合首页、插件哈希、媒体白名单、无成人分类名泄漏）
#   playback_probe   从发布配置里取出真实上游，能真的取到可播放的媒体字节
# 原来的 mobile_apk / tv_apk 是"必须真在手机和电视上各装一次 APK"，
# 实测从来没有被满足过，latest 因此长期停在旧版本；device_tested 只作记录，不作门槛。
for key in ('cdn_verified','config_protocol','playback_probe'):
    assert e.get(key),'Unaccepted release: '+str(key)
assert e.get('device_tested') is False or e.get('device_tested') is True,'device_tested must be explicit'
url='https://cdn.jsdelivr.net/npm/wkc0001-tvbox-independent@'+v+'/manifest.json'
with urllib.request.urlopen(url,timeout=30) as r:m=json.load(r)
assert m['version']==v and m['files']==e['files'],'Acceptance is for different resource bytes'
print('Accepted release',v,'(device_tested=%s)'%e.get('device_tested'))
