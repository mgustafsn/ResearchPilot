import os


def database_url():
    url = os.environ.get("DATABASE_URL", "")
    if not url.startswith("postgresql+psycopg://"):
        raise RuntimeError("Set DATABASE_URL to a postgresql+psycopg:// connection URL")
    return url


def openalex_headers():
    headers = {"User-Agent": "ResearchPilot/0.15", "Accept": "application/json"}
    key = os.environ.get("OPENALEX_API_KEY", "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    email = os.environ.get("OPENALEX_EMAIL", "").strip()
    if email:
        headers["User-Agent"] += f" (mailto:{email})"
    return headers


def openai_headers():
    headers = {"User-Agent": "ResearchPilot/0.15", "Accept": "application/json"}
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def openai_base_url():
    return os.environ.get("OPENAI_BASE_URL", "").strip() or "https://api.openai.com/v1"
