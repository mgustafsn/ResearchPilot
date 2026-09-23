# Phase 15 implementation

Relevance is now scored semantically, as requirements §8 prefers. The research question and
its keywords are embedded in the same batch as the papers that need new vectors, so every
search makes one embedding call even when all paper vectors are cached. A paper's relevance
is the cosine similarity between the question vector and its title/abstract vector, mapped
linearly so cosine 0.25 is 0% and 0.60 is 100%, clamped to that range. Papers below 40%
(about cosine 0.39) are filtered before clustering. Every deduplicated paper is embedded
before filtering, but only retained papers are saved.

Lexical ranking still runs first. It now drops stopwords, so conversational questions no
longer dilute it, and its order breaks ties between equal semantic scores. It no longer
determines the displayed score. Embedding failure still fails the search and preserves the
previous results; relevance does not silently fall back to lexical scoring.

The constants come from two live `text-embedding-3-small` (512-dimension) measurements.
For "Infrastructure as Code — from manual console work to declarative provisioning, and
where generative AI fits in", the IaC and Terraform papers scored cosine 0.51–0.63, generic
"generative AI in X" papers 0.40–0.47, and stormwater and medical papers 0.25–0.32. The best
lexical score for that question had been 30%, because every question word, including
filler, had to appear in the title. For "Large language models in software engineering",
on-topic surveys scored 0.72–0.88 and NumPy/Geant4-style papers 0.23–0.30. The absolute
level depends on question phrasing, so the ceiling is set where long questions still reach
100%.

The search run does not store the scoring method. The version (0.15.0) and this note
identify it. The ANALYZING stage now reports only deduplication, and the EMBEDDING stage
reports embedding and relevance scoring.
