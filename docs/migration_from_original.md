# Migration from the original repository

The uploaded original repository used a prototype structure with `config.json`, a single `sentiment_signals.json`, direct IBKR calls inside `trading_bot.py`, and a simplified backtest.

## What the migration helper does

`trading-bot migrate-original` reads the original files and writes:

- `config/original_v2.yaml`
- `data/sentiment_history.csv`
- `data/current_sentiment.json`
- `legacy_snapshot/` copies of the original config and README files
- `migration_manifest.json`

## What the migration helper does not do

- it does not create historical price CSVs automatically
- it does not guarantee live-trading readiness
- it does not infer exact historical sentiment beyond the snapshots available in the legacy JSON file

## Why the old `sentiment_signals.json` is converted into CSV history

The original design overwrote a single JSON file. That is fine for one live cycle, but it breaks backtests because the same file gets reused for every historical date.
V2 converts it to a row-based snapshot store so the strategy can ask for the latest sentiment **known as of a specific timestamp**.

## V2.1 additions after migration

After migration you can now also:

```bash
trading-bot health --config migrated_original/config/original_v2.yaml
trading-bot run-live --config migrated_original/config/original_v2.yaml
trading-bot sync-state --config migrated_original/config/original_v2.yaml
```

For real broker rollout, set live-state and broker settings explicitly in the migrated YAML before using `--execute`.
