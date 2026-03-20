# V2.8 Upgrade Notes

V2.8 focuses on workflow-level resilience rather than new strategy features.

## Added

- explicit state discipline for cancel/replace workflows
- persistent workflow resume queue
- timeout escalation to manual review when retry budgets are exhausted
- health reporting for manual-review workflows, resume queue depth and escalations

## Functional meaning

- the bot is better at keeping track of unresolved broker operations across restarts
- protection repair attempts no longer retry forever without surfacing an escalation
- operators can see when the bot wants human review instead of silently looping
