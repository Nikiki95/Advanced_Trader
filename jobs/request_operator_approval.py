from __future__ import annotations

import argparse
import json
from pathlib import Path

from trading_bot.integrations.openclaw.approval_bridge import import_operator_decisions
from trading_bot.live.runner import build_live_runtime


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--input-dir', required=True)
    ns = parser.parse_args()
    result = import_operator_decisions(build_live_runtime(Path(ns.config)), Path(ns.input_dir))
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
