from __future__ import annotations

import argparse
import json
from pathlib import Path

from trading_bot.integrations.openclaw.approval_bridge import export_operator_queue
from trading_bot.live.runner import build_live_runtime


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--output-dir', required=True)
    ns = parser.parse_args()
    result = export_operator_queue(build_live_runtime(Path(ns.config)), Path(ns.output_dir))
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
