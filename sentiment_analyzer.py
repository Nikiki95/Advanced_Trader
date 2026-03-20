#!/usr/bin/env python3
from pathlib import Path
import sys
from trading_bot.cli import main

if __name__ == '__main__':
    if len(sys.argv) == 1:
        cfg = Path('examples/config/demo.yaml')
        sys.argv.extend(['sentiment-scan', '--config', str(cfg)])
    elif 'sentiment-scan' not in sys.argv[1:2]:
        sys.argv.insert(1, 'sentiment-scan')
    raise SystemExit(main())
