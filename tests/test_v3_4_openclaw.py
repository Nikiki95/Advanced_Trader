from __future__ import annotations

import json
from pathlib import Path

from trading_bot.integrations.openclaw.approval_bridge import export_operator_queue
from trading_bot.integrations.openclaw.decision_tiers import classify_decision_tier
from trading_bot.integrations.openclaw.guardrails import generate_guardrail_report_from_config, summarize_portfolio_guardrails
from trading_bot.integrations.openclaw.session_policies import generate_session_policy_report_from_config
from trading_bot.integrations.openclaw.snapshot_schema import ingest_openclaw_bundle
from trading_bot.live.runner import build_live_runtime
from tests.test_v3_3_openclaw import _sandbox_config


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
        payload={'qty': 10, 'price_reference': 100.0, 'decision_tier': 'critical'},
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


def test_generate_session_policy_report_marks_bbb_blocked(tmp_path: Path):
    cfg = _prepare_runtime(tmp_path)
    out = tmp_path / 'reports'
    result = generate_session_policy_report_from_config(cfg, out, label='demo')
    payload = json.loads(Path(result['json_path']).read_text(encoding='utf-8'))
    assert 'BBB' in payload['blocked_symbols']
    md = Path(result['markdown_path']).read_text(encoding='utf-8')
    assert 'Session Policy Report' in md
    assert 'BBB' in md
    assert 'mode=block' in md


def test_guardrail_summary_escalates_with_active_alerts(tmp_path: Path):
    cfg = _prepare_runtime(tmp_path)
    runtime = build_live_runtime(cfg)
    summary = summarize_portfolio_guardrails(runtime)
    assert summary['severity'] == 'critical'
    assert 'operator_only' in summary['directives']
    report = generate_guardrail_report_from_config(cfg, tmp_path / 'guardrails', label='demo')
    md = Path(report['markdown_path']).read_text(encoding='utf-8')
    assert 'Portfolio Guardrail Report' in md
    assert 'operator_only' in md


def test_classify_decision_tier_respects_session_and_guardrails():
    contract = {
        'approval_policy': 'review_shorts',
        'event_regime': 'headline_fragile',
        'headline_risk': 'high',
        'event_risk_score': 0.82,
        'contradiction_score': 0.2,
    }
    session_policy = {'session_name': 'open', 'entry_mode': 'review', 'approval_tier_floor': 'elevated'}
    guardrails = {'directives': ['review_all_shorts']}
    tier, reasons = classify_decision_tier(
        action_type='OPEN_SHORT',
        notional=7500.0,
        contract=contract,
        session_policy=session_policy,
        portfolio_guardrails=guardrails,
    )
    assert tier == 'critical'
    assert any('review for all shorts' in item for item in reasons)


def test_export_operator_queue_includes_decision_tier_and_session_mode(tmp_path: Path):
    cfg = _prepare_runtime(tmp_path)
    runtime = build_live_runtime(cfg)
    out = tmp_path / 'operator_queue'
    export_operator_queue(runtime, out)
    approvals = sorted((out / 'approvals').glob('*.md'))
    assert approvals
    text = approvals[0].read_text(encoding='utf-8')
    assert 'Decision tier:' in text
    assert 'Session mode:' in text
