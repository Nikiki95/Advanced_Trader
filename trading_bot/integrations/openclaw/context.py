from __future__ import annotations

from pathlib import Path
from typing import Any, TYPE_CHECKING
import json

from trading_bot.config import resolve_relative_path

if TYPE_CHECKING:
    from trading_bot.live.runner import LiveRuntime


def load_latest_contracts(runtime: LiveRuntime) -> dict[str, dict[str, Any]]:
    bridge_cfg = runtime.raw.get('openclaw_bridge') or {}
    runtime_dir = Path(resolve_relative_path(runtime.config_path, bridge_cfg.get('runtime_dir', 'runtime/openclaw')))
    latest_file = runtime_dir / 'latest' / 'current.json'
    if not latest_file.exists():
        return {}
    payload = json.loads(latest_file.read_text(encoding='utf-8'))
    return {str(row.get('symbol') or '').upper(): row for row in payload.get('contracts', []) if row.get('symbol')}


def load_current_sentiment_json(runtime: LiveRuntime) -> dict[str, Any]:
    sent_cfg = runtime.raw.get('sentiment') or {}
    current_path = sent_cfg.get('current_json_path')
    if not current_path:
        return {}
    path = Path(resolve_relative_path(runtime.config_path, current_path))
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding='utf-8'))
