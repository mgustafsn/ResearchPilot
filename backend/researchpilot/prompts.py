"""LLM prompt templates, kept separate from business logic."""

from .llm import PaperBrief

ABSTRACT_CHARS = 1200

CLUSTER_NAMING_SYSTEM = (
    "You label clusters of academic papers. You are given a research question and a "
    "sample of papers from one cluster. Respond with a JSON object containing: "
    "name (a short noun-phrase subtopic label, at most 8 words), "
    "description (one or two sentences on what this cluster covers, grounded only in "
    "the papers shown), and keywords (3 to 6 short lowercase terms). "
    "Do not invent papers, authors, venues, or findings."
)


def cluster_naming_messages(question: str, papers: list[PaperBrief]) -> list[dict]:
    lines = [f"Research question: {question}", "", "Papers in this cluster:"]
    for index, paper in enumerate(papers, 1):
        lines.append(f"{index}. {paper.title or 'Untitled'}")
        abstract = (paper.abstract or "").strip()
        if abstract:
            lines.append(f"   {abstract[:ABSTRACT_CHARS]}")
    return [
        {"role": "system", "content": CLUSTER_NAMING_SYSTEM},
        {"role": "user", "content": "\n".join(lines)},
    ]
