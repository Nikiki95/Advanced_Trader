from __future__ import annotations

import argparse
import json
from pathlib import Path

from trading_bot.integrations.openclaw.handoff import generate_shift_handoff_from_config


def main() -> int:
    parser = argparse.ArgumentParser(description='Generate an operator shift handoff packet')
    parser.add_argument('--config', required=True)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--label')
    args = parser.parse_args()
    result = generate_shift_handoff_from_config(Path(args.config), Path(args.output_dir), label=args.label)
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
