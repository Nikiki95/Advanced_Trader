#!/usr/bin/env python3
from pathlib import Path
import sys
from trading_bot.cli import main

if __name__ == '__main__':
    if len(sys.argv) == 1:
        demo = Path('examples/config/demo.yaml')
        sys.argv.extend(['backtest', '--config', str(demo)])
    elif 'backtest' not in sys.argv[1:2]:
        sys.argv.insert(1, 'backtest')
    raise SystemExit(main())
