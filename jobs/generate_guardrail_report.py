from __future__ import annotations

import argparse
from pathlib import Path

from trading_bot.integrations.openclaw.guardrails import generate_guardrail_report_from_config


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Generate a V3.4 portfolio guardrail report')
    parser.add_argument('--config', required=True)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--label')
    args = parser.parse_args()
    result = generate_guardrail_report_from_config(Path(args.config), Path(args.output_dir), label=args.label)
    print(result)
