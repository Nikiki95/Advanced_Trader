from __future__ import annotations

import argparse
import json
from pathlib import Path

from trading_bot.live.runner import build_live_runtime, run_live_cycle


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--execute', action='store_true')
    ns = parser.parse_args()
    result = run_live_cycle(build_live_runtime(Path(ns.config)), execute=ns.execute)
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
