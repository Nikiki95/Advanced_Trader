# V3.0 Runbook

## Morning sequence

1. OpenClaw creates or refreshes an article bundle.
2. Run `jobs/build_overnight_sentiment.py`.
3. Run `jobs/pre_market_decision.py`.
4. Run `jobs/monitor_runtime.py` to export approvals / alerts for operator review.

## Intraday sequence

1. Run `jobs/intraday_sentiment_refresh.py` with new OpenClaw bundle input.
2. Run `jobs/intraday_decision_check.py`.
3. Export the operator queue again if approvals or alerts changed.

## End of day

1. Run `jobs/reconcile_and_report_eod.py`.
2. Archive the report.
3. Review unresolved alerts.

## Useful trading-bot commands

- `trading-bot health --config ...`
- `trading-bot monitor-live --config ...`
- `trading-bot export-operator-queue --config ... --output-dir ...`
- `trading-bot import-operator-decisions --config ... --input-dir ...`
- `trading-bot ingest-openclaw --config ... --bundle ...`
