from __future__ import annotations

import json
from pathlib import Path

from trading_bot.integrations.openclaw.regime import choose_approval_policy, classify_event_regime
from trading_bot.integrations.openclaw.reports import generate_daily_ops_report_from_config
from trading_bot.integrations.openclaw.snapshot_schema import ingest_openclaw_bundle
from trading_bot.live.runner import _approval_reasons, _execution_settings, build_live_runtime
from trading_bot.types import TradeIntent


def test_regime_and_policy_lock_down_high_risk_events():
    regime = classify_event_regime(
        event_flags=['guidance_change', 'lawsuit'],
        event_risk_score=0.91,
        contradiction_score=0.02,
        action_bias='bearish',
        headline_risk='high',
    )
    policy = choose_approval_policy(
        event_regime=regime,
        trading_stance='block_new_entries',
        event_risk_score=0.91,
        contradiction_score=0.02,
        action_bias='bearish',
    )
    assert regime == 'binary_event_lockdown'
    assert policy == 'block_new_entries'


def _sandbox_config(tmp_path: Path, repo: Path) -> Path:
    runtime_root = (tmp_path / 'runtime').resolve().as_posix()
    data_root = (repo / 'examples' / 'data').resolve().as_posix()
    text = (repo / 'examples' / 'config' / 'demo.yaml').read_text(encoding='utf-8')
    text = text.replace('../runtime', runtime_root)
    text = text.replace('../data', data_root)
    cfg = tmp_path / 'demo.yaml'
    cfg.write_text(text, encoding='utf-8')
    return cfg


def test_ingest_adds_event_regime_and_approval_policy(tmp_path: Path):
    repo = Path(__file__).resolve().parents[1]
    bundle = repo / 'examples' / 'data' / 'openclaw' / 'sample_bundle.json'
    temp_cfg = _sandbox_config(tmp_path, repo)
    ingest_openclaw_bundle(temp_cfg, bundle, label='test')
    latest = json.loads((tmp_path / 'runtime' / 'openclaw' / 'latest' / 'current.json').read_text(encoding='utf-8'))
    by_symbol = {row['symbol']: row for row in latest['contracts']}
    assert by_symbol['AAA']['event_regime'] == 'risk_on_supportive'
    assert by_symbol['AAA']['approval_policy'] == 'auto'
    assert by_symbol['BBB']['approval_policy'] == 'block_new_entries'


def test_openclaw_policy_adds_dynamic_approval_reason():
    repo = Path(__file__).resolve().parents[1]
    runtime = build_live_runtime(repo / 'examples' / 'config' / 'demo.yaml')
    reasons = _approval_reasons(runtime, _execution_settings(runtime.raw), intent=TradeIntent.OPEN_SHORT, symbol='BBB', qty=10, entry_price=100.0)
    assert any('openclaw policy' in reason for reason in reasons)


def test_generate_daily_ops_report_writes_markdown_and_json(tmp_path: Path):
    repo = Path(__file__).resolve().parents[1]
    result = generate_daily_ops_report_from_config(repo / 'examples' / 'config' / 'demo.yaml', tmp_path, label='demo')
    assert Path(result['json_path']).exists()
    md = Path(result['markdown_path']).read_text(encoding='utf-8')
    assert 'Operator Daily Report' in md
    assert 'BBB' in md
