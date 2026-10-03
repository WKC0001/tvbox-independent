# -*- coding: utf-8 -*-
"""统一内容门禁（阶段 2 核心）。

两个独立维度，绝不互相越权：
- 内容维度: pending / approved / blocked / review_required  （本模块管理）
- 健康维度: healthy / degraded / down / unverified           （checker/health.py 管理）

准入规则（提示词 §6）：
- 只有内容 approved 且审核覆盖适用、健康达标的资源可进入正式目录
- blocked 来源不因探活成功自动恢复；换名/换域名不得绕过（域名后缀+规范化名双重匹配）
- 分类/标题命中不安全模式（含"里番"等变体）一律拒绝；正常分类（电影/动作/爱情/科幻/战争）不受影响
- 本模块只做决策，不发网络请求；证据由调用方传入
"""
import json, re, unicodedata
from pathlib import Path

CONTENT_STATES = ("pending", "approved", "blocked", "review_required")
HEALTH_STATES = ("healthy", "degraded", "down", "unverified")

# 不安全分类模式：命中即拒（副闸门——分类级）
UNSAFE_CATEGORY = re.compile(
    r"伦理|倫理|理论片|理論片|成人|色情|三级|三級|福利|擦边|擦邊|写真|寫真|热舞|熱舞|"
    r"两性|兩性|无码|無碼|有码|有碼|传媒|傳媒|自拍|主播|萝莉|蘿莉|AV明星|巨乳|人妻|熟女|"
    r"性爱|性愛|SM调教|调教|調教|里番|裏番|18禁|R18|"
    r"强奸|乱伦|偷拍|丝袜|巨臀|翘臀|换脸|黑料|麻豆|精东|糖心|蜜桃|天美|"
    r"探花|国产精品|情色|激情|诱惑|群交|口交|自慰|淫|女优|東京热|东京热|一本道|"
    r"fc2|FC2|H漫|h漫|黑丝|偷情|换妻|空姐|技师|会所|门事件|大秀|视讯|秀色",
    re.I,
)

# 不安全标题/简介模式：命中即拒（标题级——分类伪装的第二道防线）
UNSAFE_TITLE = re.compile(
    r"里番|裏番|18禁|R18|无码|無碼|有码|有碼|人妻的|av女优|AV女优|"
    r"淫|强暴|性奴|援交|卖淫|嫖|妓|痴女|调教",
    re.I,
)


def norm(s: str) -> str:
    """规范化：NFKC + 去全部非字母数字 + 小写。用于换名防护与 ID 派生。"""
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", str(s))).lower()


def host_of(api: str) -> str:
    m = re.match(r"https?://([^/?#]+)", str(api))
    return (m.group(1) if m else "").lower().split(":")[0]


class ContentPolicy:
    """内容门禁。blocked/unverified 注册表来自 policy/blocked-sources.json。"""

    def __init__(self, blocked_path=None):
        p = Path(blocked_path) if blocked_path else Path(__file__).parent / "blocked-sources.json"
        data = json.loads(p.read_text(encoding="utf-8"))
        self.blocked_domains = set()      # 后缀匹配
        self.blocked_name_norms = set()   # 换名防护：规范化后的提供方名
        self.unverified_domains = set()
        self.unverified_name_norms = set()
        self.blocked_reasons = {}
        for e in data.get("blocked_providers", []):
            for d in e.get("domains", []):
                self.blocked_domains.add(d.lower())
                self.blocked_reasons[d.lower()] = e["reason"]
            for a in [e["name"]] + e.get("name_aliases", []):
                self.blocked_name_norms.add(norm(a))
        for e in data.get("unverified_providers", []):
            for d in e.get("domains", []):
                self.unverified_domains.add(d.lower())
            for a in [e["name"]] + e.get("name_aliases", []):
                self.unverified_name_norms.add(norm(a))

    # ---- 域名后缀匹配（防换子域/换 TLD 绕过）----
    def _match_domain(self, host, table):
        host = (host or "").lower()
        return any(host == d or host.endswith("." + d) for d in table)

    # ---- 提供方（来源站）判定 ----
    def _name_hit(self, name: str, table: set) -> tuple:
        """规范化名匹配 + 子串防护（换名/加前后缀绕不过）。
        子串双向：别名出现在候选名里，或候选名是某别名的变体缩写。"""
        n = norm(name)
        if not n:
            return False
        if n in table:
            return True
        for b in table:
            if len(b) >= 2 and (b in n or n in b):
                return True
        return False

    def provider_state(self, name: str, api: str):
        """返回 (state, reason)。state ∈ blocked / review_required / pending"""
        host = host_of(api)
        for d in self.blocked_domains:
            if host == d or host.endswith("." + d):
                return "blocked", f"域名命中封禁注册表 {d}"
        if self._name_hit(name, self.blocked_name_norms):
            return "blocked", f"提供方名命中封禁注册表（含别名防护）: {name}"
        if self._match_domain(host, self.unverified_domains):
            return "review_required", "域名命中未验证注册表（fail-closed）"
        if self._name_hit(name, self.unverified_name_norms):
            return "review_required", f"提供方名命中未验证注册表: {name}"
        return "pending", ""

    # ---- 分类判定 ----
    def category_state(self, category_name: str):
        """正常分类返回 pending（交由上游白名单逻辑），不安全分类返回 blocked。
        注意：电影/动作/爱情/科幻/战争/剧情 等正常词不受影响（模式不含这些词）。"""
        if UNSAFE_CATEGORY.search(str(category_name)):
            return "blocked", f"分类命中不安全模式: {category_name}"
        return "pending", ""

    # ---- 标题判定 ----
    def title_state(self, title: str, content: str = ""):
        blob = f"{title} {content or ''}"
        if UNSAFE_TITLE.search(blob):
            return "blocked", "标题/简介命中不安全标题模式"
        return "pending", ""

    # ---- 候选条目综合判定 ----
    def admit(self, candidate: dict):
        """candidate: {name/api 或 provider, category/type_name, title/vod_name, vod_content?}
        返回 (state, reason)。state ∈ blocked / review_required / pending。
        绝不在此处直接给 approved——approved 只能来自有人工证据的批准目录。"""
        name = str(candidate.get("name") or candidate.get("provider") or "")
        api = str(candidate.get("api") or "")
        st, why = self.provider_state(name, api)
        if st == "blocked":
            return "blocked", why
        st2, why2 = self.category_state(candidate.get("category") or candidate.get("type_name") or "")
        if st2 == "blocked":
            return "blocked", why2
        st3, why3 = self.title_state(candidate.get("title") or candidate.get("vod_name") or "",
                                     candidate.get("vod_content") or "")
        if st3 == "blocked":
            return "blocked", why3
        if st == "review_required":
            return "review_required", why
        return "pending", ""
