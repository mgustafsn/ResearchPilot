# Phase 13 implementation

Categorized paper cards now expose an inline, on-demand classification explanation.
The card uses the existing cached explanation when available, supports loading and
retry states, and refreshes the project if the explanation context changes while the
request is in flight. The drawer retains the same explanation behavior.
