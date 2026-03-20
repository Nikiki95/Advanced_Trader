#!/usr/bin/env python3
from pathlib import Path
import argparse
import json

from trading_bot.compat.original_repo import migrate_original_repo


def main() -> int:
    parser = argparse.ArgumentParser(description='Migrate original AI Trading Bot repo into V2 layout')
    parser.add_argument('--source', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    manifest = migrate_original_repo(Path(args.source), Path(args.output))
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
