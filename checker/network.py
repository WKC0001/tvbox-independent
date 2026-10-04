"""Bounded media checks: manifest, variant, key, initialization and media bytes."""
import json
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit, urljoin, urlencode, parse_qsl, urlunsplit
from urllib.request import Request, urlopen


def iri(url):
    """IRI → URI：非 ASCII 路径必须先百分号编码。

    实测：部分上游的播放地址带中文，例如 `https://.../20221102期/index.m3u8`。
    urllib 只接受 ASCII，会把这类地址抛成
    `'ascii' codec can't encode character '\\u671f'`，看起来像"源坏了"，
    实际是探测端的问题——而且据此外推会把一个健康源从下一版里踢掉。
    safe 里保留 % 是为了不二次编码已经转义过的地址。
    """
    return quote(str(url), safe=":/?#[]@!$&'()*+,;=%~")


def fetch(url, headers=None, limit=4_000_000, timeout=10):
    if urlsplit(url).scheme not in ('http', 'https'):
        raise ValueError('network-specific transport; not tested by HTTP checker')
    started = time.monotonic()
    req = Request(iri(url), headers={'User-Agent': 'okhttp/4.12.0', **(headers or {})})
    for attempt in range(2):
        try:
            with urlopen(req, timeout=timeout) as response:
                data = response.read(limit)
                return data, response.geturl(), round((time.monotonic() - started) * 1000)
        except HTTPError as error:
            if attempt or error.code not in (429,500,502,503,504):raise
        except (URLError, TimeoutError, OSError):
            if attempt:raise
        time.sleep(0.5)


def query(url, **params):
    p = urlsplit(url)
    values = dict(parse_qsl(p.query, keep_blank_values=True))
    values.update({k: str(v) for k, v in params.items()})
    return urlunsplit((p.scheme, p.netloc, p.path, urlencode(values), ''))


def cms(url, **params):
    """CMS 接口必须返回 JSON；瞬时失败要重试，不能一次就把健康源判死。

    实测：一次并发 27 个源、8 线程的批量探测里，多个源返回了 200 + 非 JSON
    （上游 WAF / 限流的错误页），而随后单独请求同一个 URL 立刻返回正常数据。
    这条路径不重试的话，一次突发会把健康源记成 down（连续 2 次失败即降级），
    于是下一版发布就把它踢掉——把探测端的抖动误判成了源的问题。
    """
    target = query(url, **params)
    last = None
    for attempt in range(3):
        data, _, ms = fetch(target)
        try:
            result = json.loads(data)
        except ValueError as error:
            last = error
            time.sleep(0.8 * (attempt + 1))
            continue
        if not isinstance(result, dict) or not isinstance(result.get('list'), list):
            raise ValueError('CMS response must contain a list')
        return result, ms
    raise ValueError('CMS response was not JSON after 3 attempts: ' + str(last)[:120])


def media_bytes(data):
    return len(data) > 32 and ((data[0] == 71 and len(data) > 188 and data[188] == 71)
        or data[4:8] in (b'ftyp', b'styp', b'moof', b'sidx') or data[:3] in (b'FLV', b'ID3')
        or data[:2] in (b'\xff\xf1', b'\xff\xf9', b'\xff\xfb'))


def media(url, headers=None):
    started = time.monotonic()
    try:
        current, steps, encrypted = url, [], False
        for depth in range(4):
            data, final, _ = fetch(current, headers, limit=131072, timeout=7)
            text = data.decode('utf-8', errors='replace').lstrip('\ufeff\r\n ')
            if not text.startswith('#EXTM3U'):
                if not media_bytes(data):
                    raise ValueError('HTTP success without recognizable media bytes')
                steps.append('media-bytes')
                return {'ok': True, 'level': steps, 'ms': round((time.monotonic()-started)*1000), 'decode_tested': False}
            lines = [x.strip() for x in text.splitlines() if x.strip() and not x.startswith('#')]
            if not lines:
                raise ValueError('empty HLS playlist')
            if '#EXT-X-STREAM-INF:' in text:
                steps.append('master')
                current = urljoin(final, lines[0])
                continue
            for key in re.findall(r'#EXT-X-KEY:([^\r\n]+)', text):
                if 'METHOD=NONE' in key:
                    encrypted = False
                    continue
                uri = re.search(r'URI="([^"]+)"', key)
                if 'METHOD=AES-128' not in key or not uri:
                    raise ValueError('unsupported/DRM key; requires client review')
                key_data, _, _ = fetch(urljoin(final, uri[1]), headers, limit=33, timeout=6)
                if len(key_data) != 16:
                    raise ValueError('invalid AES-128 key response')
                encrypted = True
                steps.append('aes128-key')
            init = re.search(r'#EXT-X-MAP:.*?URI="([^"]+)"', text)
            if init:
                blob, _, _ = fetch(urljoin(final, init[1]), headers, limit=4096, timeout=6)
                if not media_bytes(blob):
                    raise ValueError('invalid initialization segment')
                steps.append('initialization')
            segment, _, _ = fetch(urljoin(final, lines[0]), headers, limit=16384, timeout=7)
            if encrypted:
                if len(segment) < 188 or len(segment) % 16 or segment.lstrip().startswith((b'<', b'{')):
                    raise ValueError('invalid encrypted segment response')
            elif not media_bytes(segment):
                raise ValueError('invalid HLS media segment')
            steps.append('encrypted-segment' if encrypted else 'media-segment')
            return {'ok': True, 'level': steps, 'ms': round((time.monotonic()-started)*1000), 'decode_tested': False}
        raise ValueError('too many nested manifests')
    except Exception as error:
        return {'ok': False, 'reason': str(error)[:200], 'decode_tested': False}
