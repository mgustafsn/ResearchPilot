# Repository Instructions

## General
- Follow existing project structure.
- Prefer simple implementations over premature abstractions.
- Do not implement features marked as future/out-of-scope.
- Do not add dependencies unless necessary.
- Keep external integrations behind interfaces.

## Architecture
- Scholarly metadata must come from PaperProvider implementations.
- LLMs must never generate authoritative paper metadata.
- LLM calls must use structured responses.
- Business logic must not directly depend on OpenAI or OpenAlex.
- User edits override AI-generated categorization.

## Development
- Run tests before considering a task complete.
- Add tests for new business logic.
- Do not commit secrets.
- API keys come from environment variables.

## Current Scope
Refer to `docs/requirements.md` and `docs/roadmap.md`.

Implement only the currently requested phase.
