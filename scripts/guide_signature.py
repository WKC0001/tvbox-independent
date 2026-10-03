"""Print a stable digest of the guide state users actually receive.

`registry/channels.json` also stores the time each mapping was last confirmed, and every
rotating refresh rewrites those timestamps. A timestamp refresh renews the evidence and is
worth committing, but it changes no published byte, so it must not be mistaken for a
content change and used to justify a new release. This digest covers only the mapping
itself. Reads a path, or stdin when given "-".
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def digest(channels):
    rows = [f"{c['id']}\t{c.get('epg_id', '')}\t{c.get('epg_source', '')}" for c in channels]
    return hashlib.sha256('\n'.join(rows).encode()).hexdigest()


def main():
    argument = sys.argv[1] if len(sys.argv) > 1 else str(ROOT / 'registry/channels.json')
    text = sys.stdin.read() if argument == '-' else Path(argument).read_text()
    print(digest(json.loads(text)))


if __name__ == '__main__':
    main()
