from pathlib import Path
import json
import yaml

from trading_bot.compat.original_repo import migrate_original_repo


def test_migrate_original_repo_creates_v2_files(tmp_path: Path):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'config.json').write_text(json.dumps({
        'sessions': {
            'eu': {'watchlist': ['SAP'], 'news_feeds': ['https://example.com/{ticker}']},
            'us': {'watchlist': ['AAPL'], 'news_feeds': ['https://example.com/{ticker}']},
        },
        'holidays': {'eu': ['2026-01-01'], 'us': []},
        'ib_gateway': {'host': '127.0.0.1', 'port': 4002, 'client_id': 7},
        'risk': {'short_enabled': True, 'max_risk_per_trade': 0.02, 'paper_trading': True},
        'position_sizing': {'max_position_usd': 1000, 'max_total_exposure': 0.3},
        'stop_loss': {'atr_multiplier': 2.5},
    }))
    (source / 'sentiment_signals.json').write_text(json.dumps({
        'SAP': {'timestamp': '2026-01-01T10:00:00', 'sentiment_score': 0.4, 'confidence': 0.8, 'provider': 'legacy', 'summary': 'x'},
    }))

    out = tmp_path / 'out'
    manifest = migrate_original_repo(source, out)
    assert manifest['symbol_count'] == 2
    cfg = yaml.safe_load((out / 'config' / 'original_v2.yaml').read_text())
    assert cfg['universe']['symbols'] == ['SAP', 'AAPL']
    rows = (out / 'data' / 'sentiment_history.csv').read_text().strip().splitlines()
    assert len(rows) == 2
