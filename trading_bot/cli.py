from __future__ import annotations

import argparse
import json
from pathlib import Path

from trading_bot.backtest.engine import BacktestEngine
from trading_bot.backtest.report import summarize
from trading_bot.compat.original_repo import migrate_original_repo
from trading_bot.config import load_config
from trading_bot.live.runner import build_live_runtime, decide_operator_request, monitor_live_state, process_retry_queue, reconcile_live_state, recover_live_state, resolve_operator_alert, resume_live_state, run_live_cycle, sync_live_state
from trading_bot.integrations.openclaw.approval_bridge import export_operator_queue, import_operator_decisions
from trading_bot.integrations.openclaw.handoff import generate_shift_handoff_from_config
from trading_bot.integrations.openclaw.guardrails import generate_guardrail_report_from_config
from trading_bot.integrations.openclaw.session_policies import generate_session_policy_report_from_config
from trading_bot.integrations.openclaw.playbooks import export_review_playbooks_from_config
from trading_bot.integrations.openclaw.portfolio import generate_portfolio_regime_report_from_config
from trading_bot.integrations.openclaw.reports import generate_daily_ops_report_from_config
from trading_bot.integrations.openclaw.snapshot_schema import ingest_openclaw_bundle
from trading_bot.live.status import collect_health_snapshot, format_health_snapshot
from trading_bot.sentiment.pipeline import run_sentiment_scan
from trading_bot.utils.logging import configure_logging


def cmd_backtest(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    engine = BacktestEngine(cfg)
    result = engine.run()
    summary = summarize(result.ledger)
    print('Backtest finished')
    print(f'Trades:           {summary.trades}')
    print(f'Win rate:         {summary.win_rate_pct:.2f}%')
    print(f'Profit factor:    {summary.profit_factor:.2f}')
    print(f'Average trade:    {summary.avg_trade:.2f}')
    print(f'Max drawdown:     {summary.max_drawdown_pct:.2f}%')
    print(f'Total return:     {summary.total_return_pct:.2f}%')
    print(f'Ending equity:    {summary.ending_equity:,.2f}')
    return 0


def cmd_migrate_original(args: argparse.Namespace) -> int:
    manifest = migrate_original_repo(Path(args.source), Path(args.output))
    print(json.dumps(manifest, indent=2))
    return 0


def cmd_sentiment_scan(args: argparse.Namespace) -> int:
    result = run_sentiment_scan(Path(args.config), symbols=args.symbols or None)
    print(json.dumps(result, indent=2))
    return 0


def cmd_health(args: argparse.Namespace) -> int:
    snap = collect_health_snapshot(Path(args.config))
    print(format_health_snapshot(snap))
    return 0


def cmd_run_live(args: argparse.Namespace) -> int:
    runtime = build_live_runtime(Path(args.config))
    result = run_live_cycle(runtime, execute=args.execute)
    print(json.dumps(result, indent=2, default=str))
    return 0


def cmd_sync_state(args: argparse.Namespace) -> int:
    runtime = build_live_runtime(Path(args.config))
    result = sync_live_state(runtime)
    print(json.dumps(result, indent=2, default=str))
    return 0


def cmd_reconcile_live(args: argparse.Namespace) -> int:
    runtime = build_live_runtime(Path(args.config))
    result = reconcile_live_state(runtime, execute=args.execute)
    print(json.dumps(result, indent=2, default=str))
    return 0


def cmd_recover_live(args: argparse.Namespace) -> int:
    runtime = build_live_runtime(Path(args.config))
    result = recover_live_state(runtime, execute=args.execute)
    print(json.dumps(result, indent=2, default=str))
    return 0


def cmd_process_retries(args: argparse.Namespace) -> int:
    runtime = build_live_runtime(Path(args.config))
    result = process_retry_queue(runtime, execute=args.execute)
    print(json.dumps(result, indent=2, default=str))
    return 0


def cmd_resume_live(args: argparse.Namespace) -> int:
    runtime = build_live_runtime(Path(args.config))
    result = resume_live_state(runtime)
    print(json.dumps(result, indent=2, default=str))
    return 0


def cmd_monitor_live(args: argparse.Namespace) -> int:
    runtime = build_live_runtime(Path(args.config))
    result = monitor_live_state(runtime)
    print(result['operator_board'])
    print(json.dumps(result, indent=2, default=str))
    return 0


def cmd_decide_approval(args: argparse.Namespace) -> int:
    runtime = build_live_runtime(Path(args.config))
    result = decide_operator_request(runtime, approval_id=args.approval_id, approve=not args.reject, operator=args.operator, note=args.note)
    print(json.dumps(result, indent=2, default=str))
    return 0


def cmd_resolve_alert(args: argparse.Namespace) -> int:
    runtime = build_live_runtime(Path(args.config))
    result = resolve_operator_alert(runtime, alert_id=args.alert_id, operator=args.operator, note=args.note, acknowledge_only=args.ack_only)
    print(json.dumps(result, indent=2, default=str))
    return 0



def cmd_ingest_openclaw(args: argparse.Namespace) -> int:
    result = ingest_openclaw_bundle(Path(args.config), Path(args.bundle), label=args.label)
    print(json.dumps(result, indent=2, default=str))
    return 0


def cmd_export_operator_queue(args: argparse.Namespace) -> int:
    runtime = build_live_runtime(Path(args.config))
    result = export_operator_queue(runtime, Path(args.output_dir))
    print(json.dumps(result, indent=2, default=str))
    return 0


def cmd_import_operator_decisions(args: argparse.Namespace) -> int:
    runtime = build_live_runtime(Path(args.config))
    result = import_operator_decisions(runtime, Path(args.input_dir))
    print(json.dumps(result, indent=2, default=str))
    return 0


def cmd_generate_ops_report(args: argparse.Namespace) -> int:
    result = generate_daily_ops_report_from_config(Path(args.config), Path(args.output_dir), label=args.label)
    print(json.dumps(result, indent=2, default=str))
    return 0


def cmd_generate_portfolio_regime_report(args: argparse.Namespace) -> int:
    result = generate_portfolio_regime_report_from_config(Path(args.config), Path(args.output_dir), label=args.label)
    print(json.dumps(result, indent=2, default=str))
    return 0


def cmd_export_review_playbooks(args: argparse.Namespace) -> int:
    result = export_review_playbooks_from_config(Path(args.config), Path(args.output_dir), symbols=args.symbols or None)
    print(json.dumps(result, indent=2, default=str))
    return 0


def cmd_generate_shift_handoff(args: argparse.Namespace) -> int:
    result = generate_shift_handoff_from_config(Path(args.config), Path(args.output_dir), label=args.label)
    print(json.dumps(result, indent=2, default=str))
    return 0


def cmd_generate_session_policy_report(args: argparse.Namespace) -> int:
    result = generate_session_policy_report_from_config(Path(args.config), Path(args.output_dir), label=args.label)
    print(json.dumps(result, indent=2, default=str))
    return 0


def cmd_generate_guardrail_report(args: argparse.Namespace) -> int:
    result = generate_guardrail_report_from_config(Path(args.config), Path(args.output_dir), label=args.label)
    print(json.dumps(result, indent=2, default=str))
    return 0

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='AI Trading Bot V3.4')
    parser.add_argument('--log-level', default='INFO')
    sub = parser.add_subparsers(dest='command', required=True)

    p_backtest = sub.add_parser('backtest', help='Run the event-driven backtest')
    p_backtest.add_argument('--config', required=True)
    p_backtest.set_defaults(func=cmd_backtest)

    p_migrate = sub.add_parser('migrate-original', help='Convert the original repo layout into V2 files')
    p_migrate.add_argument('--source', required=True, help='Path to the original repository directory')
    p_migrate.add_argument('--output', required=True, help='Directory to write converted config/data into')
    p_migrate.set_defaults(func=cmd_migrate_original)

    p_sent = sub.add_parser('sentiment-scan', help='Fetch RSS headlines and append historical sentiment snapshots')
    p_sent.add_argument('--config', required=True)
    p_sent.add_argument('symbols', nargs='*')
    p_sent.set_defaults(func=cmd_sentiment_scan)

    p_ingest = sub.add_parser('ingest-openclaw', help='Ingest an OpenClaw article bundle into the bot sentiment stores')
    p_ingest.add_argument('--config', required=True)
    p_ingest.add_argument('--bundle', required=True)
    p_ingest.add_argument('--label', default='openclaw')
    p_ingest.set_defaults(func=cmd_ingest_openclaw)

    p_health = sub.add_parser('health', help='Show session-aware system health')
    p_health.add_argument('--config', required=True)
    p_health.set_defaults(func=cmd_health)

    p_live = sub.add_parser('run-live', help='Run one supervised live-trading decision cycle')
    p_live.add_argument('--config', required=True)
    p_live.add_argument('--execute', action='store_true', help='Actually send orders via IBKR when configured')
    p_live.set_defaults(func=cmd_run_live)

    p_sync = sub.add_parser('sync-state', help='Synchronize runtime state from IBKR open positions and orders')
    p_sync.add_argument('--config', required=True)
    p_sync.set_defaults(func=cmd_sync_state)

    p_reconcile = sub.add_parser('reconcile-live', help='Sync broker state and reconcile protective stops / orphan orders')
    p_reconcile.add_argument('--config', required=True)
    p_reconcile.add_argument('--execute', action='store_true', help='Actually apply reconciliation actions against IBKR')
    p_reconcile.set_defaults(func=cmd_reconcile_live)

    p_recover = sub.add_parser('recover-live', help='Recover pending order lifecycle and bracket state after restarts')
    p_recover.add_argument('--config', required=True)
    p_recover.add_argument('--execute', action='store_true', help='Also apply any reconciliation actions after recovery')
    p_recover.set_defaults(func=cmd_recover_live)

    p_retry = sub.add_parser('process-retries', help='Retry queued reconciliation actions')
    p_retry.add_argument('--config', required=True)
    p_retry.add_argument('--execute', action='store_true', help='Actually replay retry actions against IBKR')
    p_retry.set_defaults(func=cmd_process_retries)

    p_resume = sub.add_parser('resume-live', help='Review restart-resume workflows for working orders and missing protection')
    p_resume.add_argument('--config', required=True)
    p_resume.set_defaults(func=cmd_resume_live)

    p_monitor = sub.add_parser('monitor-live', help='Show operator-facing monitoring board with alerts and approvals')
    p_monitor.add_argument('--config', required=True)
    p_monitor.set_defaults(func=cmd_monitor_live)

    p_export = sub.add_parser('export-operator-queue', help='Export current alerts and approvals for an OpenClaw operator workflow')
    p_export.add_argument('--config', required=True)
    p_export.add_argument('--output-dir', required=True)
    p_export.set_defaults(func=cmd_export_operator_queue)

    p_import = sub.add_parser('import-operator-decisions', help='Apply operator decisions exported from OpenClaw back into runtime state')
    p_import.add_argument('--config', required=True)
    p_import.add_argument('--input-dir', required=True)
    p_import.set_defaults(func=cmd_import_operator_decisions)

    p_report = sub.add_parser('generate-ops-report', help='Generate an operator-facing daily OpenClaw report')
    p_report.add_argument('--config', required=True)
    p_report.add_argument('--output-dir', required=True)
    p_report.add_argument('--label')
    p_report.set_defaults(func=cmd_generate_ops_report)

    p_portfolio = sub.add_parser('generate-portfolio-regime-report', help='Generate a portfolio-wide OpenClaw regime summary')
    p_portfolio.add_argument('--config', required=True)
    p_portfolio.add_argument('--output-dir', required=True)
    p_portfolio.add_argument('--label')
    p_portfolio.set_defaults(func=cmd_generate_portfolio_regime_report)

    p_playbooks = sub.add_parser('export-review-playbooks', help='Export symbol-level review playbooks for elevated or blocked names')
    p_playbooks.add_argument('--config', required=True)
    p_playbooks.add_argument('--output-dir', required=True)
    p_playbooks.add_argument('symbols', nargs='*')
    p_playbooks.set_defaults(func=cmd_export_review_playbooks)

    p_handoff = sub.add_parser('generate-shift-handoff', help='Generate an operator shift handoff packet')
    p_handoff.add_argument('--config', required=True)
    p_handoff.add_argument('--output-dir', required=True)
    p_handoff.add_argument('--label')
    p_handoff.set_defaults(func=cmd_generate_shift_handoff)

    p_session = sub.add_parser('generate-session-policy-report', help='Generate a session-aware OpenClaw policy report')
    p_session.add_argument('--config', required=True)
    p_session.add_argument('--output-dir', required=True)
    p_session.add_argument('--label')
    p_session.set_defaults(func=cmd_generate_session_policy_report)

    p_guardrails = sub.add_parser('generate-guardrail-report', help='Generate portfolio-wide OpenClaw guardrails')
    p_guardrails.add_argument('--config', required=True)
    p_guardrails.add_argument('--output-dir', required=True)
    p_guardrails.add_argument('--label')
    p_guardrails.set_defaults(func=cmd_generate_guardrail_report)

    p_approve = sub.add_parser('decide-approval', help='Approve or reject a pending operator approval request')
    p_approve.add_argument('--config', required=True)
    p_approve.add_argument('--approval-id', required=True)
    p_approve.add_argument('--operator', default='operator')
    p_approve.add_argument('--note')
    p_approve.add_argument('--reject', action='store_true', help='Reject instead of approve')
    p_approve.set_defaults(func=cmd_decide_approval)

    p_alert = sub.add_parser('resolve-alert', help='Acknowledge or resolve an operator alert')
    p_alert.add_argument('--config', required=True)
    p_alert.add_argument('--alert-id', required=True)
    p_alert.add_argument('--operator', default='operator')
    p_alert.add_argument('--note')
    p_alert.add_argument('--ack-only', action='store_true', help='Only acknowledge the alert')
    p_alert.set_defaults(func=cmd_resolve_alert)
    return parser


def main() -> int:

    parser = build_parser()
    args = parser.parse_args()
    configure_logging(args.log_level)
    return args.func(args)


if __name__ == '__main__':
    raise SystemExit(main())
