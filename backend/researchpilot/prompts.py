"""LLM prompt templates, kept separate from business logic."""

from .llm import PaperBrief

QUERY_EXPANSION_SYSTEM = (
    "You write search queries for a scholarly keyword search engine. Given a research "
    "description and optional keywords, return a JSON object with a `queries` array "
    "containing 3 to 6 short keyword queries. Each query has 2 to 6 words, uses academic "
    "terminology, and is not a sentence or a question. Together the queries cover the main "
    "concepts of the description. Stay grounded in the description; do not add unrelated "
    "topics, claims, citations, or invented entities."
)


def query_expansion_messages(question: str, keywords: list[str]) -> list[dict]:
    keyword_text = ", ".join(keywords) if keywords else "(none)"
    return [
        {"role": "system", "content": QUERY_EXPANSION_SYSTEM},
        {
            "role": "user",
            "content": f"Research description: {question}\nKeywords: {keyword_text}",
        },
    ]


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


PAPER_EXPLANATION_SYSTEM = (
    "You explain why a single paper belongs in a research subtopic. You are given the "
    "research question, the subtopic, and one paper's title and abstract. Respond with a "
    "JSON object containing `explanation`: one or two sentences, grounded only in the "
    "paper's title and abstract, on why it fits the subtopic. Do not invent findings and "
    "do not simply restate the abstract."
)


def paper_explanation_messages(question: str, subtopic: str, paper: PaperBrief) -> list[dict]:
    abstract = (paper.abstract or "").strip()
    lines = [
        f"Research question: {question}",
        f"Subtopic: {subtopic}",
        "",
        f"Paper title: {paper.title or 'Untitled'}",
        f"Abstract: {abstract[:ABSTRACT_CHARS]}" if abstract else "Abstract: (none provided)",
    ]
    return [
        {"role": "system", "content": PAPER_EXPLANATION_SYSTEM},
        {"role": "user", "content": "\n".join(lines)},
    ]
