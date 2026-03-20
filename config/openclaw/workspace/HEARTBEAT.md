Check only these items:

1. Pending approvals exported under `runtime/openclaw/operator_queue/approvals`
2. Active alerts exported under `runtime/openclaw/operator_queue/alerts`
3. Manual-review workflows visible in `operator_board.txt`
4. Missing protective stop warnings
5. Unresolved critical alerts
6. Any checklist item in `OPENCLAW_TODO.md` marked as blocked

If nothing needs attention, reply exactly:
HEARTBEAT_OK

If something needs attention:
- summarize only the actionable issue
- include ticker if applicable
- suggest the next operator action
- do not place orders
- do not modify broker state
