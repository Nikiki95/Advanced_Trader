from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional
import csv
import pandas as pd

from trading_bot.types import SentimentSnapshot


@dataclass(slots=True)
class HistoricalSentimentStore:
    path: Path
    _df: pd.DataFrame | None = None

    def _load(self) -> pd.DataFrame:
        if self._df is not None:
            return self._df
        if not self.path.exists():
            self._df = pd.DataFrame(columns=[
                'timestamp', 'symbol', 'score', 'confidence', 'source', 'summary',
                'relevance_score', 'event_risk_score', 'contradiction_score',
                'headline_risk', 'action_bias', 'source_count', 'thesis', 'event_flags',
                'trading_stance', 'event_regime', 'approval_policy'
            ])
            return self._df
        rows = []
        with open(self.path, 'r', encoding='utf-8', newline='') as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                if not row:
                    continue
                rows.append({
                    'timestamp': row.get('timestamp'),
                    'symbol': str(row.get('symbol', '')).upper(),
                    'score': row.get('score', 0.0),
                    'confidence': row.get('confidence', 0.0),
                    'source': row.get('source', 'unknown'),
                    'summary': row.get('summary', ''),
                    'relevance_score': row.get('relevance_score', 1.0),
                    'event_risk_score': row.get('event_risk_score', 0.0),
                    'contradiction_score': row.get('contradiction_score', 0.0),
                    'headline_risk': row.get('headline_risk', 'low'),
                    'action_bias': row.get('action_bias', 'neutral'),
                    'source_count': row.get('source_count', 0),
                    'thesis': row.get('thesis', row.get('summary', '')),
                    'event_flags': row.get('event_flags', ''),
                    'trading_stance': row.get('trading_stance', 'neutral'),
                    'event_regime': row.get('event_regime', 'normal'),
                    'approval_policy': row.get('approval_policy', 'auto'),
                })
        df = pd.DataFrame(rows)
        expected = {'timestamp', 'symbol', 'score', 'confidence'}
        missing = expected - set(df.columns)
        if missing:
            raise ValueError(f'Sentiment file missing columns: {sorted(missing)}')
        for col, default in {
            'source': 'unknown',
            'summary': '',
            'relevance_score': 1.0,
            'event_risk_score': 0.0,
            'contradiction_score': 0.0,
            'headline_risk': 'low',
            'action_bias': 'neutral',
            'source_count': 0,
            'thesis': '',
            'event_flags': '',
            'trading_stance': 'neutral',
            'event_regime': 'normal',
            'approval_policy': 'auto',
        }.items():
            if col not in df.columns:
                df[col] = default
        df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True, format='mixed').dt.tz_localize(None)
        for col in ('score', 'confidence', 'relevance_score', 'event_risk_score', 'contradiction_score', 'source_count'):
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)
        self._df = df.sort_values('timestamp').reset_index(drop=True)
        return self._df

    def get_latest_asof(self, symbol: str, asof: datetime) -> Optional[SentimentSnapshot]:
        df = self._load()
        asof_ts = pd.Timestamp(asof)
        if asof_ts.tzinfo is not None:
            asof_ts = asof_ts.tz_convert(None)
        view = df[(df['symbol'] == symbol.upper()) & (df['timestamp'] <= asof_ts)]
        if view.empty:
            return None
        row = view.iloc[-1]
        flags_raw = str(row.get('event_flags', '') or '')
        flags = [part for part in flags_raw.split('|') if part]
        thesis = str(row.get('thesis') or row.get('summary') or '')
        return SentimentSnapshot(
            symbol=row['symbol'],
            timestamp=row['timestamp'].to_pydatetime(),
            score=float(row['score']),
            confidence=float(row['confidence']),
            source=str(row.get('source', 'unknown')),
            relevance_score=float(row.get('relevance_score', 1.0)),
            headline_risk=str(row.get('headline_risk', 'low')),
            event_flags=flags,
            event_risk_score=float(row.get('event_risk_score', 0.0)),
            contradiction_score=float(row.get('contradiction_score', 0.0)),
            action_bias=str(row.get('action_bias', 'neutral')),
            thesis=thesis,
            source_count=int(float(row.get('source_count', 0) or 0)),
            trading_stance=str(row.get('trading_stance', 'neutral')),
            event_regime=str(row.get('event_regime', 'normal')),
            approval_policy=str(row.get('approval_policy', 'auto')),
        )
