"""Check the actual Android DEX being shipped, rather than freshly compiled Java tests."""
import hashlib
import json
import re
import struct
import sys
import zlib
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]


def uleb(data, offset):
    value = 0
    for shift in range(0, 35, 7):
        byte = data[offset]
        offset += 1
        value |= (byte & 127) << shift
        if byte < 128:
            return value, offset
    raise ValueError('Invalid DEX ULEB128')


def inspect_dex(data):
    if len(data) < 112 or data[:4] != b'dex\n' or data[7] != 0:
        raise ValueError('Plugin does not contain an Android DEX')
    def word(offset):
        return struct.unpack_from('<I', data, offset)[0]
    if word(32) != len(data) or word(36) != 112 or word(40) != 0x12345678:
        raise ValueError('Invalid DEX header')
    if data[12:32] != hashlib.sha1(data[32:]).digest():
        raise ValueError('DEX signature mismatch')
    if word(8) != zlib.adler32(data[12:]) & 0xffffffff:
        raise ValueError('DEX checksum mismatch')
    strings = []
    for i in range(word(56)):
        offset = word(word(60) + 4 * i)
        _, offset = uleb(data, offset)
        end = data.index(0, offset)
        strings.append(data[offset:end].decode('utf-8', errors='replace'))
    types = [strings[word(word(68) + 4 * i)] for i in range(word(64))]
    classes = set()
    embedded = None
    for i in range(word(96)):
        offset = word(100) + 32 * i
        name = types[word(offset)]
        classes.add(name)
        if name != 'Lcom/github/catvod/spider/ApprovedCatalogue;':
            continue
        cursor = word(offset + 24)
        sizes = []
        for _ in range(4):
            value, cursor = uleb(data, cursor)
            sizes.append(value)
        fields = []
        index = 0
        for _ in range(sizes[0]):
            delta, cursor = uleb(data, cursor)
            _, cursor = uleb(data, cursor)
            index += delta
            fields.append(strings[word(word(84) + 8 * index + 4)])
        cursor = word(offset + 28)
        if not cursor:
            raise ValueError('Catalogue hash is missing from compiled static fields')
        count, cursor = uleb(data, cursor)
        for index in range(count):
            encoded = data[cursor]
            cursor += 1
            kind, size = encoded & 31, (encoded >> 5) + 1
            if kind != 0x17:
                raise ValueError('Unexpected catalogue constant type')
            string_index = int.from_bytes(data[cursor:cursor + size], 'little')
            cursor += size
            if fields[index] == 'SHA256':
                embedded = strings[string_index]
    required = {'Lcom/github/catvod/spider/' + n + ';'
                for n in ('WkcHome', 'ApprovedCatalogue', 'Init', 'Proxy')}
    if not required <= classes:
        raise ValueError('Required plugin classes are absent')
    if 'Lcom/github/catvod/crawler/Spider;' in classes or 'Landroid/content/Context;' in classes:
        raise ValueError('Host APP stubs must not be shipped in the plugin')
    hashes = {s for s in strings if re.fullmatch(r'[0-9a-f]{64}', s)}
    return {'catalog_sha256': embedded, 'hash_constants': hashes, 'classes': sorted(classes)}


def verify_plugin(root=ROOT):
    root = Path(root)
    api = json.loads((root / 'api.json').read_text(encoding='utf-8'))
    manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    data = api['sites'][0]['ext']['catalog_json']
    expected = hashlib.sha256(data.encode('utf-8')).hexdigest()
    with ZipFile(root / 'home.jpg') as archive:
        if archive.namelist().count('classes.dex') != 1:
            raise ValueError('Plugin must have exactly one classes.dex')
        dex = archive.read('classes.dex')
    actual = inspect_dex(dex)
    if actual['catalog_sha256'] != expected or actual['hash_constants'] != {expected}:
        raise ValueError('Shipped DEX catalogue mismatch: expected ' + expected
                         + ', compiled ' + str(actual['catalog_sha256']))
    if manifest['catalog_sha256'] != expected:
        raise ValueError('Manifest catalogue hash mismatch')
    plugin = (root / 'home.jpg').read_bytes()
    if api['spider'].split(';md5;')[-1] != hashlib.md5(plugin).hexdigest():
        raise ValueError('APP plugin MD5 mismatch')
    if manifest['files']['home.jpg'] != hashlib.sha256(plugin).hexdigest():
        raise ValueError('Manifest plugin hash mismatch')
    return {'catalog_sha256': expected, 'plugin_sha256': hashlib.sha256(plugin).hexdigest(),
            'dex_bytes': len(dex), 'compiled_classes': actual['classes'], 'passed': True}


if __name__ == '__main__':
    try:
        print(json.dumps(verify_plugin(), ensure_ascii=False, indent=2))
    except Exception as error:
        print('PLUGIN_VERIFICATION_FAILED: ' + str(error), file=sys.stderr)
        sys.exit(1)
