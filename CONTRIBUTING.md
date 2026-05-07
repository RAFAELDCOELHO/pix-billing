# Contributing

## Local setup

```bash
uv sync --extra dev
uv run uvicorn main:app --reload
```

## Quality gates

```bash
uv run ruff check src/        # linting
uv run mypy src/              # types
uv run bandit -r src/         # security
uv run pytest --cov=src       # tests + coverage
```

All four must pass before opening a PR.

## Code conventions

- All money is `Cents` (int). No floats anywhere.
- All I/O is `async def`. No `time.sleep`.
- Pydantic v2 strict models on every API surface.
- Layered: API → Service → Repository → Core. No cross-layer imports.
- `src/core/` is frozen. Patch your service, never core.
- Mask PII in logs. Encrypt CPF/CNPJ at rest.
- English only — code, comments, commits, docs.

## Commit style

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(pix): support dynamic merchant fields
fix(webhooks): retry on 5xx only, not on 4xx
docs(readme): rewrite quickstart
```

## Adding an endpoint

1. Add a Pydantic schema to `src/api/schemas.py`.
2. Add the route to `src/api/billing_routes.py` — depends on `rate_limit(scope, write=…)`.
3. Add a service function (no DB access in the route).
4. Add a repository helper if a new query is needed.
5. Add a test in `tests/`.
