from __future__ import annotations

import argparse
import json
from pathlib import Path

from trading_bot.integrations.openclaw.playbooks import export_review_playbooks_from_config


def main() -> int:
    parser = argparse.ArgumentParser(description='Export symbol review playbooks from the current OpenClaw context')
    parser.add_argument('--config', required=True)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('symbols', nargs='*')
    args = parser.parse_args()
    result = export_review_playbooks_from_config(Path(args.config), Path(args.output_dir), symbols=args.symbols or None)
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
