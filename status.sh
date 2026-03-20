#!/usr/bin/env bash
set -euo pipefail
CONFIG_PATH="${1:-examples/config/demo.yaml}"
python -m trading_bot.cli health --config "$CONFIG_PATH"
