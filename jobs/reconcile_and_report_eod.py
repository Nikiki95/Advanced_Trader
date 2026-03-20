from __future__ import annotations

import argparse
import json
from pathlib import Path

from trading_bot.live.runner import build_live_runtime, reconcile_live_state, monitor_live_state


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--report-path')
    ns = parser.parse_args()
    runtime = build_live_runtime(Path(ns.config))
    recon = reconcile_live_state(runtime, execute=ns.execute)
    monitor = monitor_live_state(runtime)
    report = {
        'reconciliation': recon,
        'monitor': monitor,
    }
    if ns.report_path:
        path = Path(ns.report_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2, default=str), encoding='utf-8')
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
