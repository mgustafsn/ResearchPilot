import os


def database_url():
    url = os.environ.get("DATABASE_URL", "")
    if not url.startswith("postgresql+psycopg://"):
        raise RuntimeError("Set DATABASE_URL to a postgresql+psycopg:// connection URL")
    return url


def openalex_headers():
    headers = {"User-Agent": "ResearchPilot/0.20", "Accept": "application/json"}
    key = os.environ.get("OPENALEX_API_KEY", "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    email = os.environ.get("OPENALEX_EMAIL", "").strip()
    if email:
        headers["User-Agent"] += f" (mailto:{email})"
    return headers


def openai_headers():
    headers = {"User-Agent": "ResearchPilot/0.20", "Accept": "application/json"}
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def scopus_headers():
    headers = {"User-Agent": "ResearchPilot/0.20", "Accept": "application/json"}
    key = os.environ.get("ELSEVIER_API_KEY", "").strip()
    if key:
        headers["X-ELS-APIKey"] = key
    return headers


def scholarly_provider():
    name = os.environ.get("SCHOLARLY_PROVIDER", "openalex").strip().lower()
    if name not in {"openalex", "scopus"}:
        raise RuntimeError("SCHOLARLY_PROVIDER must be openalex or scopus")
    if name == "scopus" and not os.environ.get("ELSEVIER_API_KEY", "").strip():
        raise RuntimeError("Set ELSEVIER_API_KEY to use the Scopus provider")
    return name


def openai_base_url():
    return os.environ.get("OPENAI_BASE_URL", "").strip() or "https://api.openai.com/v1"
