# -*- coding: utf-8 -*-
"""稳定 ID 派生（提示词 §5）：source_id / work_id / episode_id / channel_id / route_id。

铁律：绝不用动态媒体 URL 当作品或频道 ID。
- work_id    由 规范化片名+年份 派生（确定性，跨构建稳定）
- episode_id 由 work_id+集号+规范化集名 派生（不依赖播放 URL）
- channel_id 由 tvg-id（优先）或规范化频道名 派生
- route_id   由 URL 身份（scheme+host+path+排序后的 query）派生；鉴权参数保留在
  实际 URL 中不参与 ID，指纹与播放地址分离
全部纯函数、无网络、可离线复现。
"""
import hashlib, re, unicodedata
from urllib.parse import urlsplit, parse_qsl, urlencode


def _norm(s: str) -> str:
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", str(s))).lower()


def _h(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def work_id(title: str, year: str) -> str:
    """同一片名+同年 = 同一作品；不同年/不同季/剪辑版必须用不同 title 输入消歧，
    由调用方保证（如『剧名 第2季』），本函数不做合并猜测。"""
    return "wkc_w_" + _h(f"{_norm(title)}|{str(year).strip()}")[:12]


def episode_id(wid: str, ep_index: int, ep_title: str) -> str:
    return "wkc_e_" + _h(f"{wid}|{int(ep_index)}|{_norm(ep_title)}")[:12]


def channel_id(name: str, tvg_id: str = "") -> str:
    """有 tvg-id 用 tvg-id（频道身份稳定），否则用规范化名。
    HD/SD 收敛到同一 channel_id（清晰度是线路属性）；CCTV+ 与 CCTV-N 天然不同名不同 ID。"""
    basis = str(tvg_id).strip() if str(tvg_id).strip() else _norm(name)
    return "wkc_c_" + _h(basis)[:12]


def route_id(url: str) -> str:
    """线路指纹：scheme 小写 + host 小写 + path + 排序后 query。
    实际播放 URL（含鉴权参数）单独保存，不因指纹需要而删参数。"""
    p = urlsplit(str(url))
    q = urlencode(sorted(parse_qsl(p.query)))
    identity = f"{p.scheme.lower()}|{p.netloc.lower()}|{p.path}|{q}"
    return "wkc_r_" + _h(identity)[:12]
