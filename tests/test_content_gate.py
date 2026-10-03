# -*- coding: utf-8 -*-
"""内容门禁行为测试（实施提示词 §16.1/§16.2/§16.3 的离线可测子集）。
纯标准库 unittest，无网络。运行：python3 -m unittest discover -s tests -v
"""
import json, sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from policy.content_policy import ContentPolicy, UNSAFE_CATEGORY, UNSAFE_TITLE  # noqa: E402
from catalog.ids import work_id, episode_id, channel_id, route_id              # noqa: E402


def make_policy():
    return ContentPolicy(ROOT / "policy" / "blocked-sources.json")


class TestCategoryGate(unittest.TestCase):
    """§16.1 正常题材被接受，成人类别及伪装条目被拒绝"""

    def test_normal_categories_pass(self):
        for c in ["电影", "动作片", "爱情片", "科幻片", "战争片", "剧情片",
                  "电视剧", "连续剧", "综艺", "动漫", "纪录片", "少儿", "短剧",
                  "国产剧", "香港剧", "欧美剧", "动漫电影", "体育", "音乐"]:
            st, _ = make_policy().category_state(c)
            self.assertEqual(st, "pending", f"正常分类被误杀: {c}")

    def test_adult_categories_rejected(self):
        for c in ["伦理片", "理论片", "写真", "福利", "无码", "有码", "三级",
                  "里番", "裏番", "18禁", "麻豆传媒", "激情动漫", "国产精品"]:
            st, _ = make_policy().category_state(c)
            self.assertEqual(st, "blocked", f"不安全分类漏杀: {c}")

    def test_disguised_category_blocked(self):
        """蹭安全词的黑话分类必须被副闸门拦下"""
        for c in ["激情动漫", "成人电影", "伦理剧", "写真电影"]:
            st, _ = make_policy().category_state(c)
            self.assertEqual(st, "blocked", f"伪装分类漏杀: {c}")

    def test_adult_title_blocked(self):
        st, _ = make_policy().title_state("某里番合集 第2季")
        self.assertEqual(st, "blocked")


class TestProviderBlocklist(unittest.TestCase):
    """§6.1 封禁来源维持封禁；换名/换域名不得自动重新录用"""

    def test_blocked_domains(self):
        p = make_policy()
        for host in ["apiyutu.com", "www.apiyutu.com", "apilj.com",
                     "api.ddapi.cc", "lbapi9.com", "api.huosuapi.cc",
                     "api.guangsuapi.com", "155api.com", "jkunzyapi.com",
                     "api.xiaojizy.live", "jipinvip1.com", "fqzy.me",
                     "bhziyuan.com"]:
            st, why = p.provider_state("随便什么名", f"https://{host}/api.php/provide/vod")
            self.assertEqual(st, "blocked", f"封禁域名漏放: {host}")

    def test_blocked_subdomain_trick(self):
        """换子域绕不过后缀匹配"""
        p = make_policy()
        st, _ = p.provider_state("新名字", "https://api2.apiyutu.com/provide/vod")
        self.assertEqual(st, "blocked")

    def test_renamed_provider_caught_by_alias(self):
        """换名字绕不过规范化名匹配"""
        p = make_policy()
        st, why = p.provider_state("玉兔资源站", "https://example-new-domain.com/api.php/provide/vod")
        self.assertEqual(st, "blocked", "换名后应被别名防护拦截")

    def test_unverified_not_admitted(self):
        """未验证来源 fail-closed：不能直接进目录"""
        p = make_policy()
        st, _ = p.provider_state("速播 | 采集", "https://subocj.com/api.php/provide/vod")
        self.assertEqual(st, "review_required")

    def test_unknown_provider_pending(self):
        p = make_policy()
        st, _ = p.provider_state("量子 | 采集", "https://cj.lziapi.com/api.php/provide/vod")
        self.assertEqual(st, "pending")


class TestApprovalBoundary(unittest.TestCase):
    """§16.2 待审内容不出现在任何入口；本模块绝不直接发放 approved"""

    def test_admit_never_returns_approved(self):
        p = make_policy()
        for cand in [
            {"name": "量子 | 采集", "api": "https://cj.lziapi.com/x", "category": "电影"},
            {"name": "某未知站", "api": "https://newsite.example.com/x", "category": "电视剧"},
        ]:
            st, _ = p.admit(cand)
            self.assertNotEqual(st, "approved")
            self.assertIn(st, ("pending", "review_required", "blocked"))

    def test_blocked_candidate_full_path(self):
        p = make_policy()
        st, why = p.admit({"name": "玉兔 | 采集", "api": "https://apiyutu.com/api.php/provide/vod",
                           "category": "电影"})
        self.assertEqual(st, "blocked")


class TestStableIDs(unittest.TestCase):
    """§16.3 同名不同季/年份不误合并；ID 不依赖播放 URL"""

    def test_same_work_same_id(self):
        self.assertEqual(work_id("甄嬛传", "2011"), work_id("甄嬛传", "2011"))

    def test_different_year_different_id(self):
        self.assertNotEqual(work_id("甄嬛传", "2011"), work_id("甄嬛传", "2022"))

    def test_season_disambiguation(self):
        """季通过标题消歧：不同季输入=不同作品 ID"""
        self.assertNotEqual(work_id("剧名 第1季", "2020"), work_id("剧名 第2季", "2020"))

    def test_episode_id_independent_of_url(self):
        w = work_id("剧名", "2024")
        a = episode_id(w, 1, "第01集")
        b = episode_id(w, 1, "第01集")
        self.assertEqual(a, b)
        self.assertNotEqual(a, episode_id(w, 2, "第02集"))
        # URL 变了 ID 不变
        self.assertEqual(episode_id(w, 1, "第01集"), episode_id(w, 1, "第01集"))

    def test_channel_id_cctv_plus_not_merged(self):
        """CCTV+ 与 CCTV-N 不误并；HD/SD 收敛"""
        self.assertNotEqual(channel_id("CCTV-1 综合"), channel_id("CCTV+ 体育赛事"))
        self.assertEqual(channel_id("CCTV-5 体育", "cctv-5.hn.cn"),
                         channel_id("CCTV-5 体育HD", "cctv-5.hn.cn"))

    def test_route_id_query_preserved_in_fingerprint(self):
        """不同鉴权参数 = 不同线路指纹；同 URL 幂等"""
        a = route_id("https://cdn.example.com/live/ch1.m3u8?token=AAA")
        b = route_id("https://cdn.example.com/live/ch1.m3u8?token=BBB")
        c = route_id("https://cdn.example.com/live/ch1.m3u8?token=AAA")
        self.assertNotEqual(a, b)
        self.assertEqual(a, c)


class TestApprovedCatalogIntegrity(unittest.TestCase):
    """现有批准目录必须 100% 通过门禁（防历史污点混入基线）"""

    def test_all_approved_rows_pass_gate(self):
        p = make_policy()
        cat = json.loads((ROOT / "input" / "approved-catalog.json").read_text())
        self.assertTrue(cat.get("visual_review_complete"))
        for row in cat["list"]:
            st, why = p.title_state(row["vod_name"], row.get("vod_content", ""))
            self.assertEqual(st, "pending", f"批准目录存在污点条目: {row['vod_name']} {why}")

    def test_approved_live_routes_not_blocked(self):
        p = make_policy()
        live = json.loads((ROOT / "input" / "approved-live.json").read_text())
        from urllib.parse import urlsplit
        for e in live:
            if e.get("frame_review_pass") and e.get("fresh_probe", {}).get("ok"):
                host = (urlsplit(e["url"]).hostname or "").lower()
                self.assertFalse(p._match_domain(host, p.blocked_domains),
                                 f"批准直播命中封禁域名: {e['url']}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
