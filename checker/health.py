# -*- coding: utf-8 -*-
"""健康状态机（提示词 §11）：按『线路 × 网络』记录，维度与内容审核严格分离。

状态: healthy / degraded / down / unverified
转移规则（全部可测试，无网络依赖）：
- 成功: unverified → healthy（首次实证）；healthy/degraded → healthy（记连续成功）
        down → 仅当间隔 ≥10 分钟的连续两次成功才恢复 healthy（防止抖动复活）
- 失败: 任何状态 → degraded（单次失败降级、降优先级，不删除）
        连续 ≥2 个检查周期失败 → down（移出正式线路池）
- 内容污染: isolated 标志立即置位，无视健康阈值，恢复只能由内容维度人工解除
- 过期: last_ok 超过 stale_after 秒（默认 7 天）→ 视为 unverified（证据过期）
状态持久化为 state/health.json，跨运行恢复（提示词 §14）。
"""
import json, time
from pathlib import Path

HEALTH_STATES = ("healthy", "degraded", "down", "unverified")
DEFAULT_STALE_AFTER = 7 * 86400
RESTORE_GAP_MIN = 600  # 恢复所需两次成功的最小间隔（秒）


def new_record(network: str = "default", ts: int = None) -> dict:
    return {"network": network, "state": "unverified", "consecutive_ok": 0,
            "consecutive_fail": 0, "last_ok_ts": None, "last_fail_ts": None,
            "last_ok_gap": None, "last_reason": "", "isolated": False}


def load_state(path) -> dict:
    p = Path(path)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_state(path, state: dict) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                          encoding="utf-8")


def _get(state: dict, route_id: str, network: str, ts: int) -> dict:
    rec = state.setdefault(route_id, {}).setdefault(network, new_record(network, ts))
    return rec


def update(state: dict, route_id: str, network: str, ok: bool, ts: int = None,
           reason: str = "", pollution: bool = False,
           stale_after: int = DEFAULT_STALE_AFTER) -> dict:
    """处理一次探测结果，就地更新 state，返回该线路的最新记录。
    ts 为探测时间戳（秒）；同一线路同一网络重复处理幂等。"""
    ts = int(ts if ts is not None else time.time())
    rec = _get(state, route_id, network, ts)

    if pollution:
        # 内容污染立即隔离，健康维度不得覆盖
        rec["isolated"] = True
        rec["state"] = "down"
        rec["last_reason"] = reason or "content pollution"
        return rec

    if rec.get("isolated"):
        rec["last_reason"] = reason or "isolated by content review; recovery requires manual review"
        return rec

    if ok:
        gap = None
        if rec.get("last_ok_ts"):
            gap = ts - rec["last_ok_ts"]
        rec["last_ok_ts"] = ts
        rec["last_ok_gap"] = gap
        rec["consecutive_fail"] = 0
        rec["consecutive_ok"] = int(rec.get("consecutive_ok", 0)) + 1
        if rec["state"] == "down":
            # 恢复需要：间隔 ≥10 分钟的连续两次成功
            if gap is not None and gap >= RESTORE_GAP_MIN and rec["consecutive_ok"] >= 2:
                rec["state"] = "healthy"
            else:
                rec["last_reason"] = "down: awaiting two successes ≥10min apart to restore"
        else:
            rec["state"] = "healthy"
        rec["last_reason"] = ""
    else:
        rec["last_fail_ts"] = ts
        rec["last_reason"] = reason or "probe failed"
        rec["consecutive_ok"] = 0
        rec["consecutive_fail"] = int(rec.get("consecutive_fail", 0)) + 1
        # 批量异常保护由调用方在汇总层执行；此处单线路语义：
        rec["state"] = "down" if rec["consecutive_fail"] >= 2 else "degraded"
    return rec


def effective(rec: dict, now: int = None, stale_after: int = DEFAULT_STALE_AFTER) -> str:
    """对外生效状态：隔离 > 过期(视为 unverified) > 记录状态。"""
    if rec.get("isolated"):
        return "down"
    now = int(now if now is not None else time.time())
    if rec.get("state") == "healthy" and rec.get("last_ok_ts") and now - rec["last_ok_ts"] > stale_after:
        return "unverified"
    return rec.get("state", "unverified")


def merge_history(prev: dict, cur: dict) -> dict:
    """恢复历史状态（提示词 §14）：以 cur 为主，prev 中 cur 缺失的线路原样保留，
    保证健康历史/连续失败计数跨运行不丢失。"""
    out = json.loads(json.dumps(cur))  # deep copy
    for rid, nets in (prev or {}).items():
        for net, rec in nets.items():
            slot = out.setdefault(rid, {})
            if net not in slot:
                slot[net] = rec
    return out


def batch_anomaly(state: dict, prev: dict, threshold: float = 0.30) -> dict:
    """批量异常检测（提示词 §11）：总线路较上次骤降超过阈值 → 触发标志。
    返回 {flag, healthy_now, healthy_prev}。触发后调用方应停止普通自动删除与发布。"""
    def count(s):
        n = 0
        for nets in (s or {}).values():
            for rec in nets.values():
                if rec.get("state") in ("healthy", "degraded"):
                    n += 1
        return n
    now_c, prev_c = count(state), count(prev)
    drop = (prev_c - now_c) / prev_c if prev_c else 0.0
    return {"flag": prev_c > 0 and drop > threshold, "healthy_now": now_c,
            "healthy_prev": prev_c, "drop": round(drop, 3)}
