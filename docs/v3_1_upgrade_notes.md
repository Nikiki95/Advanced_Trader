# V3.1 upgrade notes

V3.1 tightens the OpenClaw integration in three functional ways:

1. richer research contracts
   - event risk score
   - contradiction score
   - action bias
   - trading stance
   - thesis summaries
2. stronger decision-layer usage
   - new entries can be blocked when OpenClaw indicates a high-risk event cluster
   - new entries can be blocked when research is contradictory
   - sentiment is attenuated by relevance, event risk and contradiction
3. operator workflow exports
   - approval markdown review templates
   - alert markdown review templates
   - review packet JSON bundles with the latest symbol-level OpenClaw context

The broker boundary remains unchanged:
OpenClaw does not execute broker actions directly.
