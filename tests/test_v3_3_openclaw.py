from __future__ import annotations

import json
from pathlib import Path

from trading_bot.integrations.openclaw.handoff import generate_shift_handoff_from_config
from trading_bot.integrations.openclaw.playbooks import export_review_playbooks_from_config
from trading_bot.integrations.openclaw.portfolio import generate_portfolio_regime_report_from_config
from trading_bot.integrations.openclaw.snapshot_schema import ingest_openclaw_bundle
from trading_bot.live.runner import build_live_runtime


def _sandbox_config(tmp_path: Path, repo: Path) -> Path:
    runtime_root = (tmp_path / 'runtime').resolve().as_posix()
    data_root = (repo / 'examples' / 'data').resolve().as_posix()
    text = (repo / 'examples' / 'config' / 'demo.yaml').read_text(encoding='utf-8')
    text = text.replace('../runtime', runtime_root)
    text = text.replace('../data', data_root)
    cfg = tmp_path / 'demo.yaml'
    cfg.write_text(text, encoding='utf-8')
    return cfg


def _prepare_runtime(tmp_path: Path) -> Path:
    repo = Path(__file__).resolve().parents[1]
    cfg = _sandbox_config(tmp_path, repo)
    bundle = repo / 'examples' / 'data' / 'openclaw' / 'sample_bundle.json'
    ingest_openclaw_bundle(cfg, bundle, label='test')
    runtime = build_live_runtime(cfg)
    runtime.state.request_operator_approval(
        action_type='OPEN_SHORT',
        symbol='BBB',
        reason='review short candidate under elevated event regime',
        payload={'qty': 10, 'price_reference': 100.0},
        ttl_minutes=120,
    )
    runtime.state.create_operator_alert(
        category='headline_risk',
        severity='critical',
        message='BBB remains in a high-risk event regime',
        symbol='BBB',
        details={'event_regime': 'binary_event_lockdown'},
    )
    return cfg


def test_generate_portfolio_regime_report_writes_focus_symbols(tmp_path: Path):
    cfg = _prepare_runtime(tmp_path)
    out = tmp_path / 'reports'
    result = generate_portfolio_regime_report_from_config(cfg, out, label='demo')
    payload = json.loads(Path(result['json_path']).read_text(encoding='utf-8'))
    assert 'BBB' in payload['focus_symbols']
    assert payload['approval_policy_counts']['block_new_entries'] >= 1
    md = Path(result['markdown_path']).read_text(encoding='utf-8')
    assert 'Portfolio Regime Report' in md
    assert 'binary_event_lockdown' in md


def test_export_review_playbooks_writes_symbol_markdown_and_json(tmp_path: Path):
    cfg = _prepare_runtime(tmp_path)
    out = tmp_path / 'playbooks'
    result = export_review_playbooks_from_config(cfg, out)
    assert 'BBB' in result['symbols']
    md = (out / 'bbb.md').read_text(encoding='utf-8')
    payload = json.loads((out / 'bbb.json').read_text(encoding='utf-8'))
    assert 'Symbol Playbook: BBB' in md
    assert 'Block new entries' in md
    assert payload['review_level'] == 'manual review required'


def test_generate_shift_handoff_includes_blocked_and_pending_items(tmp_path: Path):
    cfg = _prepare_runtime(tmp_path)
    out = tmp_path / 'handoff'
    result = generate_shift_handoff_from_config(cfg, out, label='handoff')
    assert 'BBB' in result['blocked_symbols']
    md = Path(result['markdown_path']).read_text(encoding='utf-8')
    assert 'Operator Shift Handoff' in md
    assert 'OPEN_SHORT BBB' in md
    assert 'high-risk event regime' in md
