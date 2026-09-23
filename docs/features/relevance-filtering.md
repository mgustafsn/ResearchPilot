# Relevance filtering

*Formerly Phase 11.*

Ranked papers now pass through a deterministic lexical relevance filter before embedding
and clustering. The default threshold is 0.10. Filtered records are not saved as project
papers, while the search run records and displays the filtered count. Manual relevance
patches continue to apply to retained project papers and are never overwritten by the
filtering step.
