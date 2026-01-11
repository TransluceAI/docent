# Docent Development Guidelines

## Python

### Type Checking with `ty`

Configuration is in `pyproject.toml`. Use `ty` for Python type checking:

```bash
ty check
```

### Linting and Formatting with `ruff`

Configuration is in `pyproject.toml` under `[tool.ruff]`. Use `ruff` for linting and formatting:

```bash
ruff format
```

## TypeScript (docent_core/_web/)

### Linting with ESLint

Configuration is in `docent_core/_web/.eslintrc.json`. From the `docent_core/_web/` directory:

```bash
# Check for issues
npm run lint

# Auto-fix issues
npm run lint-fix
```
