#!/usr/bin/env python3
"""tvbox-independent 专用 GitHub API 直推脚本（模式沿用原项目 api_push.py）。

铁律：REPO 固定为 WKC0001/tvbox-independent。任何指向 source-monitor 的改动
在此脚本层直接拒绝（提示词 §13）。不 force push；远端更新时以预期 HEAD 条件检查。
"""
import base64, json, subprocess, sys
from pathlib import Path

REPO = "WKC0001/tvbox-independent"
ROOT = Path(__file__).resolve().parents[1]

if "source-monitor" in REPO or "wkc0001-tvbox@" in sys.argv:
    sys.exit("REFUSED: 本脚本只允许推送 WKC0001/tvbox-independent")

FILES = [
    "package.json", "api.json", "live.m3u", "home.jpg", "manifest.json",
    "policy/blocked-sources.json", "policy/content_policy.py", "policy/__init__.py",
    "catalog/ids.py", "catalog/__init__.py",
    "checker/health.py", "checker/__init__.py",
    "scripts/assemble.py", "scripts/validate.cjs", "scripts/test_layout.py",
    "scripts/channel_layout.py", "scripts/probe.py", "scripts/review_catalog.py",
    "scripts/review_live.py", "scripts/review_assets.py", "scripts/verify-cdn.cjs",
    "scripts/cdn-diagnostic.cjs", "scripts/api_push.py",
    "scripts/live_harvest.py", "scripts/live_review_frames.py", "scripts/live_merge.py",
    "scripts/vod_harvest.py", "scripts/vod_review_frames.py", "scripts/vod_merge.py",
    "scripts/maintenance.py", "scripts/admin_release.py", "state/health.json",
    "tests/test_content_gate.py", "tests/test_health.py", "tests/__init__.py",
    "java/build.sh", "java/src/com/github/catvod/spider/ApprovedCatalogue.java",
    "java/src/com/github/catvod/spider/Init.java",
    "java/src/com/github/catvod/spider/Proxy.java",
    "java/src/com/github/catvod/spider/WkcHome.java",
    "java/test/HomeTest.java", "java/test/HomeIntegration.java",
     ".github/workflows/verify.yml",
    ".github/workflows/enrich.yml", ".github/workflows/vod-enrich.yml",
    ".github/workflows/review-content.yml", ".github/workflows/review-live.yml",
    ".github/workflows/review-assets.yml", ".github/workflows/cdn-diagnostic.yml",
    ".github/workflows/publish-release.yml", ".github/workflows/maintenance.yml",
    "input/approved-catalog.json", "input/approved-live.json",
    "input/channel-metadata.json", "input/reviewed-titles.json",
    "input/review-candidates.json", "input/review-live.json",
    "input/review-live-decisions.json", "input/live-allowed-hosts.json",
    "input/vod-candidates.json", "input/vod-review-decisions.json", "input/vod-enrich.json",
    "reports/content-review.json", "reports/route-registry.json",
    "reports/live-gaps.json", "reports/vod-gaps.json",
    ".gitignore", "README.md",
    "posters/wkc_149b66c9a4af14.jpg", "posters/wkc_35d92d7e622748.jpg", "posters/wkc_3bda296ad3d4b8.jpg", "posters/wkc_6fa37f485a4967.jpg", "posters/wkc_7e184d61d11e43.jpg", "posters/wkc_d157f17b39aeeb.jpg", "posters/wkc_d18b061d9e7b7b.jpg", "posters/wkc_da00b75fa9e263.jpg", "posters/wkc_wkc_w_006176.jpg", "posters/wkc_wkc_w_0e6616.jpg", "posters/wkc_wkc_w_2252ca.jpg", "posters/wkc_wkc_w_47a783.jpg", "posters/wkc_wkc_w_52997a.jpg", "posters/wkc_wkc_w_533547.jpg", "posters/wkc_wkc_w_6fa4f9.jpg", "posters/wkc_wkc_w_a0683e.jpg", "posters/wkc_wkc_w_b023fa.jpg", "posters/wkc_wkc_w_b62a10.jpg", "posters/wkc_wkc_w_b6b710.jpg", "posters/wkc_wkc_w_cc86e2.jpg", "posters/wkc_wkc_w_e1df19.jpg", "posters/wkc_wkc_w_e8b8e0.jpg", "posters/wkc_wkc_w_ff1524.jpg",
]


def gh(method, path, data=None):
    cmd = ["gh", "api", "-X", method, f"repos/{REPO}/{path}"]
    if data is not None:
        cmd += ["--input", "-"]
        r = subprocess.run(cmd, input=json.dumps(data).encode(), capture_output=True)
    else:
        r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        sys.exit(f"gh {method} {path} 失败: {r.stderr.decode()[:500]}")
    return json.loads(r.stdout or b"{}")


def main():
    msg_file = ROOT / ".commit-msg"
    if not msg_file.exists():
        sys.exit("缺少 .commit-msg（提交信息文件）。请先写入提交信息。")
    msg = msg_file.read_text(encoding="utf-8").strip()
    ref = gh("GET", "branches/main")
    parent = ref["commit"]["sha"]
    expected = (ROOT / ".commit-expected-head").read_text().strip() if (ROOT / ".commit-expected-head").exists() else None
    if expected and expected != parent:
        sys.exit(f"远端已前进（{parent[:10]} != 预期 {expected[:10]}），请先同步快照再推。")
    print(f"[i] remote main = {parent[:10]}")

    missing = [f for f in FILES if not (ROOT / f).exists()]
    if missing:
        sys.exit(f"FILES 中文件缺失，拒绝部分推送: {missing}")

    tree = []
    for f in FILES:
        blob = gh("POST", "git/blobs",
                  {"content": base64.b64encode((ROOT / f).read_bytes()).decode(),
                   "encoding": "base64"})
        tree.append({"path": f, "mode": "100644", "type": "blob", "sha": blob["sha"]})
    new_tree = gh("POST", "git/trees", {"base_tree": ref["commit"]["commit"]["tree"]["sha"], "tree": tree})
    commit = gh("POST", "git/commits", {"message": msg, "tree": new_tree["sha"], "parents": [parent]})
    gh("PATCH", "git/refs/heads/main", {"sha": commit["sha"], "force": False})
    print(f"[✓] pushed {commit['sha'][:10]}")
    (ROOT / ".commit-expected-head").write_text(commit["sha"])


if __name__ == "__main__":
    main()
