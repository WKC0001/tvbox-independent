#!/usr/bin/env python3
"""Stage-6 release admin: promote / quarantine / rollback (one-command).

Actions:
  promote <version>        把已验证候选版提升为 latest（npm dist-tag add）
  rollback <version>       把 latest 指回指定旧版（npm dist-tag add）+ deprecate 新版
  quarantine <route_id>    内容污染紧急隔离：state/health.json 标记 isolated，
                           立即从 live.m3u/api.json 生成层剔除该线路（重建产物）

铁律：REPO 固定 WKC0001/tvbox-independent；任何 source-monitor 目标直接拒绝。
"""
import base64,json,os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
REPO="WKC0001/tvbox-independent"
if "source-monitor" in " ".join(sys.argv):
    sys.exit("REFUSED: 目标只能是 tvbox-independent")
PKG="wkc0001-tvbox-independent"

def npm(*args):
    r=subprocess.run(["npm",*args],capture_output=True,text=True,
                     env={**os.environ,"NODE_AUTH_TOKEN":os.environ.get("NPM_TOKEN","")})
    print(r.stdout[-800:] or r.stderr[-800:])
    return r.returncode==0

def main():
    if len(sys.argv)<2:sys.exit(__doc__)
    act=sys.argv[1]
    if act=="promote" and len(sys.argv)==3:
        v=sys.argv[2]
        sys.exit(0 if npm("dist-tag","add",f"{PKG}@{v}","latest","--registry=https://registry.npmjs.org/") else 1)
    if act=="rollback" and len(sys.argv)==3:
        v=sys.argv[2]
        # 回滚核心：latest 指回指定旧版（新版可选再 deprecate，由人工决定）
        sys.exit(0 if npm("dist-tag","add",f"{PKG}@{v}","latest","--registry=https://registry.npmjs.org/") else 1)
    if act=="quarantine" and len(sys.argv)==3:
        from checker import health
        from catalog.ids import route_id as rid_of
        st_path=ROOT/'state/health.json'
        state=health.load_state(st_path)
        target=sys.argv[2]
        # 允许传 route_id 或 URL
        rid=target if target.startswith('wkc_r_') else rid_of(target)
        rec=health.update(state,rid,'default',False,pollution=True,reason='quarantined: content pollution reported')
        health.save_state(st_path,state)
        print(f"[quarantine] {rid} → isolated/down")
        print("下一步：运行 scripts/assemble.py 重建产物（污染线路将因健康状态被剔除）并发布新候选版")
        sys.exit(0)
    sys.exit(__doc__)
if __name__=='__main__':main()
