from __future__ import annotations

import argparse
import json
from pathlib import Path

from trading_bot.integrations.openclaw.snapshot_schema import ingest_openclaw_bundle


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--bundle', required=True)
    parser.add_argument('--label', default='intraday_refresh')
    ns = parser.parse_args()
    result = ingest_openclaw_bundle(Path(ns.config), Path(ns.bundle), label=ns.label)
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
