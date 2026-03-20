# V3.0 upgrade notes

V3.0 is the first release that adds an explicit **OpenClaw bridge**.

## New functional capabilities

- ingest OpenClaw article bundles into historical + current sentiment stores
- detect article-level event flags such as earnings, guidance or lawsuits
- export operator-facing approvals and alerts into a file-based queue for OpenClaw
- import operator decisions back into the bot
- example Cron / Heartbeat configuration and job scripts

## What V3.0 does not change

- broker execution remains inside the trading bot
- unattended live trading is still **not** the target
- strategy alpha is still secondary to supervised operations and data quality
