from __future__ import annotations

import argparse
from pathlib import Path

from trading_bot.integrations.openclaw.session_policies import generate_session_policy_report_from_config


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Generate a V3.4 session policy report')
    parser.add_argument('--config', required=True)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--label')
    args = parser.parse_args()
    result = generate_session_policy_report_from_config(Path(args.config), Path(args.output_dir), label=args.label)
    print(result)
