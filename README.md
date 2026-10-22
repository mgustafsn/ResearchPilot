# ResearchPilot

ResearchPilot is a web application for managing references by research project. Add
citations manually or look them up by DOI, track reading and citation status, and keep
notes. Optional literature discovery searches OpenAlex or Scopus and helps organize
papers by relevance and topic.

## Run locally

Install Python 3.12+, [uv](https://docs.astral.sh/uv/getting-started/installation/), and
Docker Compose. From the repository root, run:

```sh
./scripts/start-local.sh
```

Open <http://127.0.0.1:8000>. To use literature discovery, add `OPENAI_API_KEY` to the
`.env` file created by the launcher. See `.env.example` for available settings.

## Project report

The full project report and submission are available as [the editable Typst source](docs/report.typ)
and [the compiled PDF](docs/report.pdf). The report includes the project process,
verification, and team contribution breakdown. See the [roadmap](docs/roadmap.md) and
[requirements](docs/requirements.md) for project scope and implementation details.

## Git collaboration

Use GitHub Issues to record work and problems, and pull requests to discuss and review
changes. Contributors should use their own GitHub accounts and commit identities so
their work is visible in repository history. Keep the report's contribution breakdown
accurate; this submission's report records a one-person team.

Repository: <https://github.com/mgustafsn/ResearchPilot>
