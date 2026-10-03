# -*- coding: utf-8 -*-
"""健康状态机行为测试（实施提示词 §16.6/§16.7 离线可测子集）。
纯标准库，无网络。运行：python3 -m unittest discover -s tests -v
"""
import sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from checker import health as H  # noqa: E402

T0 = 1_700_000_000  # 任意基准时间戳


class TestHealthTransitions(unittest.TestCase):
    """§16.6 单次失败不批量删库；连续失败/恢复状态正确"""

    def test_first_success_is_healthy(self):
        s = {}
        r = H.update(s, "r1", "default", True, ts=T0)
        self.assertEqual(r["state"], "healthy")
        self.assertEqual(H.effective(r, now=T0), "healthy")

    def test_single_failure_degrades_not_down(self):
        s = {}
        H.update(s, "r1", "default", True, ts=T0)
        r = H.update(s, "r1", "default", False, ts=T0 + 60, reason="timeout")
        self.assertEqual(r["state"], "degraded")

    def test_two_consecutive_failures_down(self):
        s = {}
        H.update(s, "r1", "default", True, ts=T0)
        H.update(s, "r1", "default", False, ts=T0 + 60)
        r = H.update(s, "r1", "default", False, ts=T0 + 120)
        self.assertEqual(r["state"], "down")

    def test_restore_requires_two_successes_10min_apart(self):
        s = {}
        H.update(s, "r1", "default", True, ts=T0)
        H.update(s, "r1", "default", False, ts=T0 + 60)
        H.update(s, "r1", "default", False, ts=T0 + 120)   # down
        # 单次成功（间隔 <10min）不得复活
        r = H.update(s, "r1", "default", True, ts=T0 + 180)
        self.assertEqual(r["state"], "down")
        # 连续两次成功但间隔仍 <10min，不得复活
        r = H.update(s, "r1", "default", True, ts=T0 + 300)
        self.assertEqual(r["state"], "down")
        # 间隔 ≥10min 的第二次成功 → 恢复
        r = H.update(s, "r1", "default", True, ts=T0 + 300 + 601)
        self.assertEqual(r["state"], "healthy")

    def test_networks_independent(self):
        """§11 健康按线路×网络记录，境外失败不覆盖国内成功"""
        s = {}
        H.update(s, "r1", "cn-telecom", True, ts=T0)
        r = H.update(s, "r1", "gh-runner", False, ts=T0 + 30)
        self.assertEqual(H.effective(s["r1"]["cn-telecom"], now=T0), "healthy")
        self.assertEqual(r["state"], "degraded")


class TestPollutionIsolation(unittest.TestCase):
    """§16.6 内容污染立即隔离，不等健康阈值；健康维度不得越权解除"""

    def test_pollution_isolates_even_if_healthy(self):
        s = {}
        H.update(s, "r1", "default", True, ts=T0)
        r = H.update(s, "r1", "default", True, ts=T0 + 60, pollution=True, reason="博彩水印")
        self.assertEqual(r["state"], "down")
        self.assertTrue(r["isolated"])

    def test_isolated_survives_success_reports(self):
        s = {}
        H.update(s, "r1", "default", True, ts=T0, pollution=True)
        r = H.update(s, "r1", "default", True, ts=T0 + 3600)   # 即使探测成功
        self.assertTrue(r["isolated"])
        self.assertEqual(H.effective(r, now=T0 + 3600), "down")

    def test_stale_evidence_expires(self):
        """§11: 7 天无新证据 → unverified"""
        s = {}
        H.update(s, "r1", "default", True, ts=T0)
        rec = s["r1"]["default"]
        self.assertEqual(H.effective(rec, now=T0 + 6 * 86400), "healthy")
        self.assertEqual(H.effective(rec, now=T0 + 8 * 86400), "unverified")


class TestPersistenceAndBatch(unittest.TestCase):
    """§14 状态持久化恢复；§11 批量异常保护"""

    def test_state_roundtrip(self):
        import json
        s = {}
        H.update(s, "r1", "default", True, ts=T0)
        H.update(s, "r1", "default", False, ts=T0 + 60)
        blob = json.dumps(s)
        s2 = json.loads(blob)
        self.assertEqual(s2["r1"]["default"]["consecutive_fail"], 1)

    def test_merge_history_keeps_missing_routes(self):
        prev = {"old_route": {"default": H.new_record("default")}}
        prev["old_route"]["default"]["state"] = "healthy"
        cur = {"r1": {"default": H.new_record("default")}}
        merged = H.merge_history(prev, cur)
        self.assertIn("old_route", merged)
        self.assertIn("r1", merged)
        self.assertEqual(merged["old_route"]["default"]["state"], "healthy")

    def test_batch_anomaly_flag(self):
        prev = {f"r{i}": {"default": {"state": "healthy"}} for i in range(10)}
        cur = {f"r{i}": {"default": {"state": "healthy"}} for i in range(5)}  # 掉 50%
        out = H.batch_anomaly(cur, prev, threshold=0.30)
        self.assertTrue(out["flag"])
        cur_ok = {f"r{i}": {"default": {"state": "healthy"}} for i in range(9)}  # 掉 10%
        self.assertFalse(H.batch_anomaly(cur_ok, prev, threshold=0.30)["flag"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
