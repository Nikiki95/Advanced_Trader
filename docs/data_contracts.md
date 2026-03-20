# V3.1 Data Contracts

## OpenClaw article bundle

```json
{
  "generated_at": "2026-03-20T07:15:00Z",
  "articles": [
    {
      "id": "news-1",
      "symbol": "AAPL",
      "company": "Apple Inc.",
      "published_at": "2026-03-20T06:58:00Z",
      "source": "Reuters",
      "title": "Apple launches updated product line",
      "summary": "Analysts see stronger demand.",
      "relevance_score": 0.92,
      "sentiment_score": 0.36,
      "confidence": 0.81,
      "impact_horizon": "near_term",
      "action_bias": "bullish",
      "event_flags": ["product_launch"],
      "event_risk": "medium",
      "thesis": "Launch supports near-term demand and margin outlook.",
      "url": "https://example.com/aapl-1"
    }
  ]
}
```

## Normalized snapshot contract

```json
{
  "as_of": "2026-03-20T07:15:00Z",
  "symbol": "AAPL",
  "company": "Apple Inc.",
  "relevance_score": 0.92,
  "sentiment_score": 0.36,
  "confidence": 0.81,
  "source_count": 1,
  "headline_risk": "medium",
  "event_flags": ["product_launch"],
  "event_risk_score": 0.35,
  "contradiction_score": 0.0,
  "action_bias": "bullish",
  "trading_stance": "favor_long",
  "thesis": "Launch supports near-term demand and margin outlook.",
  "articles": []
}
```

## Operator decision file

```json
{
  "kind": "approval",
  "approval_id": "approval:OPEN_SHORT:TSLA:...",
  "decision": "approve",
  "operator": "alice",
  "note": "approved for supervised paper session"
}
```

Supported `kind` values:
- `approval`
- `alert`
