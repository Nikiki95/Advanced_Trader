from __future__ import annotations

import json
from pathlib import Path

from trading_bot.integrations.openclaw.approval_bridge import export_operator_queue, import_operator_decisions
from trading_bot.integrations.openclaw.event_flags import detect_event_flags, classify_headline_risk
from trading_bot.integrations.openclaw.snapshot_schema import ingest_openclaw_bundle
from trading_bot.live.runner import build_live_runtime



def _cfg_with_paths(tmp_path: Path, *, require_approval: bool = True) -> Path:
    root = Path(__file__).resolve().parents[1]
    prices_dir = (root / 'examples' / 'data' / 'prices').as_posix()
    sample_cfg = f"""
universe:
  symbols: [AAA, BBB]
market_data:
  source: csv
  csv_dir: {prices_dir}
sentiment:
  path: sentiment/history.csv
  current_json_path: sentiment/current.json
strategy:
  warmup_bars: 30
backtest:
  start: 2024-01-15
  end: 2024-06-28
compatibility:
  timezone: Europe/Berlin
  sessions:
    us:
      start_cet: '14:00'
      end_cet: '21:30'
      watchlist: [AAA, BBB]
live:
  state_path: runtime/live_state.json
  execution_journal_path: runtime/execution_journal.jsonl
  sync_on_start: false
  process_retry_queue: false
  reconcile_protection_on_start: false
  require_operator_approval: {'true' if require_approval else 'false'}
  approval_intents: [OPEN_SHORT]
  approval_ttl_minutes: 120
  broker:
    host: 127.0.0.1
    port: 4002
    client_id: 7
openclaw_bridge:
  runtime_dir: runtime/openclaw
  min_relevance: 0.55
  symbol_aliases_path: aliases.json
"""
    cfg_path = tmp_path / 'demo.yaml'
    cfg_path.write_text(sample_cfg, encoding='utf-8')
    (tmp_path / 'aliases.json').write_text(json.dumps({'AAA': ['Alpha Analytics'], 'BBB': ['Beta Biotech']}), encoding='utf-8')
    return cfg_path



def test_openclaw_ingest_writes_current_history_and_snapshot(tmp_path: Path):
    cfg_path = _cfg_with_paths(tmp_path)
    bundle = Path(__file__).resolve().parents[1] / 'examples' / 'data' / 'openclaw' / 'sample_bundle.json'
    result = ingest_openclaw_bundle(cfg_path, bundle, label='overnight')

    current_payload = json.loads((tmp_path / 'sentiment' / 'current.json').read_text(encoding='utf-8'))
    latest_snapshot = json.loads((tmp_path / 'runtime' / 'openclaw' / 'latest' / 'current.json').read_text(encoding='utf-8'))
    history_csv = (tmp_path / 'sentiment' / 'history.csv').read_text(encoding='utf-8')

    assert result['contracts_written'] == 2
    assert set(current_payload) == {'AAA', 'BBB'}
    assert current_payload['BBB']['headline_risk'] == 'high'
    assert current_payload['AAA']['action_bias'] == 'bullish'
    assert current_payload['BBB']['event_risk_score'] >= 0.85
    assert 'thesis' in current_payload['AAA']
    assert 'contradiction_score' in history_csv
    assert latest_snapshot['provider'] == 'openclaw_v3'



def test_export_and_import_operator_queue_roundtrip(tmp_path: Path):
    cfg_path = _cfg_with_paths(tmp_path, require_approval=True)
    bundle = Path(__file__).resolve().parents[1] / 'examples' / 'data' / 'openclaw' / 'sample_bundle.json'
    ingest_openclaw_bundle(cfg_path, bundle, label='overnight')
    runtime = build_live_runtime(cfg_path)
    alert = runtime.state.create_operator_alert(category='manual_review', severity='critical', message='AAA requires review', symbol='AAA')
    approval = runtime.state.request_operator_approval(action_type='OPEN_SHORT', symbol='BBB', reason='short needs supervision', payload={'qty': 3, 'price_reference': 11.0})

    output_dir = tmp_path / 'operator_queue'
    export_result = export_operator_queue(runtime, output_dir)
    assert export_result['approvals_exported'] == 1
    assert export_result['alerts_exported'] == 1
    assert export_result['review_packets'] == 2
    stem = str(approval['approval_id']).replace(':', '_')
    assert (output_dir / 'approvals' / f"{stem}.md").exists()
    md = (output_dir / 'approvals' / f"{stem}.md").read_text(encoding='utf-8')
    assert 'Event risk score' in md
    assert 'Trading stance' in md

    decisions_dir = output_dir / 'decisions'
    decisions_dir.mkdir(exist_ok=True)
    (decisions_dir / 'approve.json').write_text(json.dumps({
        'kind': 'approval',
        'approval_id': approval['approval_id'],
        'decision': 'approve',
        'operator': 'alice',
        'note': 'approved',
    }), encoding='utf-8')
    (decisions_dir / 'resolve.json').write_text(json.dumps({
        'kind': 'alert',
        'alert_id': alert['alert_id'],
        'decision': 'resolve',
        'operator': 'alice',
        'note': 'handled',
    }), encoding='utf-8')

    imported = import_operator_decisions(runtime, output_dir)
    assert imported['count'] == 2
    assert runtime.state.active_approval_requests()[0]['status'] == 'approved'
    assert runtime.state.active_operator_alerts() == []



def test_event_flags_detect_high_risk_cases():
    flags = detect_event_flags(['Company faces lawsuit after earnings guidance cut'])
    risk = classify_headline_risk(flags, avg_confidence=0.9, abs_sentiment=0.8, event_risk_score=0.91)
    assert 'lawsuit' in flags
    assert 'earnings' in flags
    assert risk == 'high'
