#!/usr/bin/env python3
"""tvbox-independent 专用 GitHub API 直推脚本（模式沿用原项目 api_push.py）。

铁律：REPO 固定为 WKC0001/tvbox-independent。任何指向 source-monitor 的改动
在此脚本层直接拒绝（提示词 §13）。不 force push；远端更新时以预期 HEAD 条件检查。
"""
import base64, hashlib, json, subprocess, sys, time
from pathlib import Path

REPO = "WKC0001/tvbox-independent"
ROOT = Path(__file__).resolve().parents[1]

if "source-monitor" in REPO or "wkc0001-tvbox@" in sys.argv:
    sys.exit("REFUSED: 本脚本只允许推送 WKC0001/tvbox-independent")

# Read the reviewable local push manifest; every added/removed path is explicit.
plan_path=ROOT / '.push-plan.json'
FILES=json.loads(plan_path.read_text()).get('files',[]) if plan_path.exists() else []
DELETE=json.loads(plan_path.read_text()).get('delete',[]) if plan_path.exists() else []
for name in FILES+DELETE:
    if Path(name).is_absolute() or '..' in Path(name).parts or name.startswith('.git/'):
        sys.exit('Unsafe push path: '+name)



def gh(method, path, data=None):
    cmd = ["gh", "api", "-X", method, f"repos/{REPO}/{path}"]
    payload = None
    if data is not None:
        cmd += ["--input", "-"]
        payload = json.dumps(data).encode()
    # These Git object requests are content-addressed; repeating the same ref
    # update is also safe. Never retry authentication or non-fast-forward errors.
    for attempt in range(4):
        try:
            r = subprocess.run(cmd, input=payload, capture_output=True, timeout=60)
        except subprocess.TimeoutExpired:
            if attempt == 3:
                sys.exit(f"gh {method} {path} timed out after retries")
            print(f"[retry] {method} {path}: timeout ({attempt + 1}/3)", flush=True)
            time.sleep(2 ** (attempt + 1))
            continue
        if r.returncode == 0:
            return json.loads(r.stdout or b"{}")
        error = r.stderr.decode(errors="replace")
        transient = any(x in error.lower() for x in (
            "eof", "connection reset", "connection refused", "timed out",
            "timeout", "tls handshake", "http 429", "http 500", "http 502",
            "http 503", "http 504",
        ))
        if not transient or attempt == 3:
            sys.exit(f"gh {method} {path} 失败: {error[:500]}")
        print(f"[retry] {method} {path}: transient network error ({attempt + 1}/3)", flush=True)
        time.sleep(2 ** (attempt + 1))


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

    base_tree = ref["commit"]["commit"]["tree"]["sha"]
    remote_tree = gh("GET", f"git/trees/{base_tree}?recursive=1")
    if remote_tree.get("truncated"):
        sys.exit("Remote tree is truncated; refuse an incomplete comparison")
    existing = {item["path"]: item for item in remote_tree["tree"]}
    tree = []
    for f in FILES:
        content = (ROOT / f).read_bytes()
        blob_sha = hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()
        if existing.get(f, {}).get("sha") == blob_sha:
            continue
        print(f"[upload] {f}", flush=True)
        blob = gh("POST", "git/blobs",
                  {"content": base64.b64encode(content).decode(),
                   "encoding": "base64"})
        tree.append({"path": f, "mode": "100644", "type": "blob", "sha": blob["sha"]})
    for f in DELETE:
        if f in existing:
            tree.append({"path": f, "mode": existing[f].get("mode", "100644"), "type": "blob", "sha": None})
    if not tree:
        print("[i] No file changes; nothing to push")
        return
    new_tree = gh("POST", "git/trees", {"base_tree": base_tree, "tree": tree})
    commit = gh("POST", "git/commits", {"message": msg, "tree": new_tree["sha"], "parents": [parent]})
    gh("PATCH", "git/refs/heads/main", {"sha": commit["sha"], "force": False})
    print(f"[✓] pushed {commit['sha'][:10]}")
    (ROOT / ".commit-expected-head").write_text(commit["sha"])


if __name__ == "__main__":
    main()
