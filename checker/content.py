"""Provider admission and metadata filtering. No category-cache fail-open path."""
import re
import unicodedata

BLOCK = r"色情|成人|情色|伦理|倫理|三级|三態|三級|写真|寫真|里番|裏番|无码|無碼|有码|有碼|色情网|伦理片|福利姬|成人视频|成人视频|激情|淫|性爱|性愛|情色|AV女优|AV女優|麻豆传媒|麻豆傳媒|国产AV|日本AV|Hentai|Porn|XXX|18禁|18\+|R18|OnlyFans|成人动漫|成人動漫"
DENY = re.compile(BLOCK, re.I)
GENRES = {
    '电视剧': r'^(电视剧|電視劇|连续剧|連續劇|剧集|國產劇|国产剧|内地剧|大陆剧|香港剧|港澳剧|港台剧|港剧|台湾剧|台剧|欧美剧|美国剧|韩国剧|韩剧|日本剧|日剧|日韩剧|泰剧|泰国剧|马泰剧|海外剧|其他剧|Netflix自制剧)$',
    '电影': r'^(电影|電影|电影片|动作片|動作片|喜剧片|喜劇片|爱情片|愛情片|科幻片|恐怖片|惊悚片|悬疑片|剧情片|劇情片|战争片|犯罪片|历史片|奇幻片|冒险片|灾难片|武侠片|古装片|动画电影|动漫电影|网络电影|邵氏电影|邵氏大片|4K电影|Netflix电影|喜剧|剧情|动作|爱情|科幻|恐怖|惊悚|悬疑|战争|犯罪|历史|奇幻|冒险|灾难|武侠|古装)$',
    '综艺': r'^(综艺|綜藝|综艺片|大陆综艺|内地综艺|日韩综艺|港台综艺|欧美综艺|其他综艺)$',
    '动漫': r'^(动漫|動漫|动画|動畫|动漫片|国产动漫|中国动漫|日本动漫|日韩动漫|欧美动漫|港台动漫|海外动漫|少儿|少兒|动画片|番剧|剧场版|特摄)$',
    '纪录片': r'^(纪录片|紀錄片|记录片|纪录)$',
    '短剧': r'^(短剧|短劇|短剧大全|爽文短剧|反转爽剧)$',
}


def norm(value):
    return re.sub(r'\W+', '', unicodedata.normalize('NFKC', str(value))).casefold()


def genre(name):
    name = unicodedata.normalize('NFKC', str(name)).strip()
    if DENY.search(name):
        return None
    return next((k for k, pattern in GENRES.items() if re.fullmatch(pattern, name, re.I)), None)


def allowed_types(classes):
    return {str(c['type_id']): {'name': c['type_name'], 'genre': genre(c['type_name'])}
            for c in classes if c.get('type_id') is not None and genre(c.get('type_name', ''))}


def safe_item(item, types):
    type_id = str(item.get('type_id', ''))
    if type_id not in types:
        return False
    # Both id and current name must agree: a provider may reuse old category ids.
    if item.get('type_name') and not genre(item['type_name']):
        return False
    return bool(item.get('vod_id') and item.get('vod_name')) and not DENY.search(' '.join(
        str(item.get(k, '')) for k in ('vod_name', 'type_name', 'vod_class', 'vod_remarks', 'vod_tag')))


def episodes(item):
    for flag, line in zip(str(item.get('vod_play_from', '')).split('$$$'),
                          str(item.get('vod_play_url', '')).split('$$$')):
        for ep in line.split('#'):
            if '$' in ep:
                name, url = ep.split('$', 1)
                if url.startswith(('https://', 'http://')):
                    yield flag, name, url
