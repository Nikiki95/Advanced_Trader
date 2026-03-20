from __future__ import annotations

from datetime import datetime
from pathlib import Path
import csv
import json
from typing import Any
import yaml


def _read_json(path: Path) -> dict[str, Any]:
    with open(path, 'r', encoding='utf-8') as fh:
        return json.load(fh)


def _all_symbols(config: dict[str, Any]) -> list[str]:
    symbols: list[str] = []
    for session in config.get('sessions', {}).values():
        for symbol in session.get('watchlist', []):
            symbol = str(symbol).upper()
            if symbol not in symbols:
                symbols.append(symbol)
    return symbols


def _convert_sentiment(current_file: Path, out_csv: Path, out_json: Path) -> int:
    if not current_file.exists():
        out_csv.parent.mkdir(parents=True, exist_ok=True)
        out_csv.write_text('timestamp,symbol,score,confidence,source,summary\n', encoding='utf-8')
        out_json.write_text('{}\n', encoding='utf-8')
        return 0
    payload = _read_json(current_file)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(out_csv, 'w', encoding='utf-8', newline='') as fh:
        writer = csv.DictWriter(fh, fieldnames=['timestamp', 'symbol', 'score', 'confidence', 'source', 'summary'])
        writer.writeheader()
        for symbol, row in sorted(payload.items()):
            writer.writerow({
                'timestamp': row.get('timestamp') or datetime.utcnow().isoformat(),
                'symbol': str(symbol).upper(),
                'score': row.get('sentiment_score', 0.0),
                'confidence': row.get('confidence', 0.5),
                'source': row.get('provider') or row.get('source') or 'legacy',
                'summary': row.get('summary', ''),
            })
    out_json.write_text(json.dumps(payload, indent=2), encoding='utf-8')
    return len(payload)


def migrate_original_repo(source_dir: Path, output_dir: Path) -> dict[str, Any]:
    source_dir = Path(source_dir)
    output_dir = Path(output_dir)
    config_path = source_dir / 'config.json'
    sentiment_path = source_dir / 'sentiment_signals.json'
    if not config_path.exists():
        raise FileNotFoundError(f'Missing config.json in {source_dir}')

    legacy_cfg = _read_json(config_path)
    symbols = _all_symbols(legacy_cfg)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / 'config').mkdir(exist_ok=True)
    (output_dir / 'data').mkdir(exist_ok=True)
    (output_dir / 'legacy_snapshot').mkdir(exist_ok=True)

    starting_cash = 100_000.0
    max_position_usd = float(legacy_cfg.get('position_sizing', {}).get('max_position_usd', 1000))
    max_symbol_weight = min(max_position_usd / starting_cash, 0.35)
    yaml_payload = {
        'universe': {'symbols': symbols},
        'market_data': {
            'source': 'csv',
            'csv_dir': '../data/prices',
        },
        'sentiment': {
            'path': '../data/sentiment_history.csv',
            'current_json_path': '../data/current_sentiment.json',
        },
        'strategy': {
            'warmup_bars': 30,
            'long_entry_threshold': 0.35,
            'short_entry_threshold': -0.35,
            'long_exit_threshold': -0.05,
            'short_exit_threshold': 0.05,
            'weights': {
                'trend': 0.35,
                'momentum': 0.25,
                'mean_reversion': 0.10,
                'sentiment': 0.30,
            },
        },
        'risk': {
            'starting_cash': starting_cash,
            'risk_per_trade': float(legacy_cfg.get('risk', {}).get('max_risk_per_trade', 0.02)),
            'max_positions': 4,
            'max_gross_exposure': max(float(legacy_cfg.get('position_sizing', {}).get('max_total_exposure', 0.3)), 0.5),
            'min_cash_buffer_pct': 0.10,
            'stop_atr_multiple': float(legacy_cfg.get('stop_loss', {}).get('atr_multiplier', 2.0)),
            'daily_loss_limit_pct': 0.03,
            'max_symbol_weight': max_symbol_weight,
        },
        'backtest': {
            'start': '2024-01-01',
            'end': '2025-12-31',
            'slippage_bps': 5.0,
            'fee_bps': 1.0,
            'allow_shorting': bool(legacy_cfg.get('risk', {}).get('short_enabled', False)),
        },
        'compatibility': {
            'timezone': 'Europe/Berlin',
            'sessions': legacy_cfg.get('sessions', {}),
            'holidays': legacy_cfg.get('holidays', {}),
            'ibkr': {
                'host': legacy_cfg.get('ib_gateway', {}).get('host', '127.0.0.1'),
                'port': int(legacy_cfg.get('ib_gateway', {}).get('port', 4002)),
                'client_id': int(legacy_cfg.get('ib_gateway', {}).get('client_id', 1)),
                'paper_trading': bool(legacy_cfg.get('risk', {}).get('paper_trading', True)),
            },
            'legacy_paths': {
                'tracking_db': legacy_cfg.get('tracking', {}).get('db_file', 'performance.json'),
                'runtime_state': 'runtime/live_state.json',
            },
            'sentiment_runtime': {
                'feed_map': {name: session.get('news_feeds', []) for name, session in legacy_cfg.get('sessions', {}).items()},
            },
        },
        'live': {
            'sync_on_start': True,
            'state_path': '../runtime/live_state.json',
            'execution_journal_path': '../runtime/execution_journal.jsonl',
            'broker': {
                'host': legacy_cfg.get('ib_gateway', {}).get('host', '127.0.0.1'),
                'port': int(legacy_cfg.get('ib_gateway', {}).get('port', 4002)),
                'client_id': int(legacy_cfg.get('ib_gateway', {}).get('client_id', 1)),
                'exchange': 'SMART',
                'currency': 'USD',
                'order_timeout_seconds': 20,
            },
        },
    }

    converted = output_dir / 'config' / 'original_v2.yaml'
    with open(converted, 'w', encoding='utf-8') as fh:
        yaml.safe_dump(yaml_payload, fh, sort_keys=False, allow_unicode=True)

    count = _convert_sentiment(sentiment_path, output_dir / 'data' / 'sentiment_history.csv', output_dir / 'data' / 'current_sentiment.json')

    for name in ['config.json', 'sentiment_signals.json', 'README.md', 'README_CRON_FIX.md']:
        src = source_dir / name
        if src.exists():
            target = output_dir / 'legacy_snapshot' / name
            target.write_text(src.read_text(encoding='utf-8'), encoding='utf-8')

    manifest = {
        'source': str(source_dir),
        'output': str(output_dir),
        'symbols': symbols,
        'symbol_count': len(symbols),
        'sentiment_rows_written': count,
        'generated_files': [
            str(converted),
            str(output_dir / 'data' / 'sentiment_history.csv'),
            str(output_dir / 'data' / 'current_sentiment.json'),
        ],
    }
    with open(output_dir / 'migration_manifest.json', 'w', encoding='utf-8') as fh:
        json.dump(manifest, fh, indent=2)
    return manifest
