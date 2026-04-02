# Contributing to WattWise

WattWise is a PhD research platform developed at Cardiff University. Contributions are welcome for bug fixes, documentation improvements, and feature additions that align with the research goals.

## Development Setup

### Backend
```bash
cd "Server Side/backend"
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# Run tests
pytest tests/ -v --cov=app
# Lint
ruff check app/
```

### Android App
```bash
cd "User Apps/Android/WattWiseUserApp"
./gradlew assembleDebug
./gradlew test
```

### Full Stack
```bash
cd "Server Side"
cp .env.production.template .env  # then fill in values
docker compose up --build
```

## Branch Naming

```
feature/short-description
fix/short-description
chore/short-description
docs/short-description
```

## Commit Message Format

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add carbon footprint tracking to user dashboard
fix: prevent duplicate energy readings on concurrent MQTT messages
docs: update MQTT topic convention in README
chore: bump influxdb client to 5.3.2
```

## Pull Request Process

1. Fork the repository and create your branch from `main`
2. Ensure all tests pass: `pytest tests/ -v` and `./gradlew test`
3. Run linting: `ruff check app/` (backend) — zero errors required
4. Update documentation if your change affects the API or architecture
5. Submit PR against the `main` branch with a clear description of what and why

## Code Style

- **Python**: [ruff](https://github.com/astral-sh/ruff) enforced, Black-compatible formatting
- **Kotlin**: ktlint enforced (run `./gradlew ktlintCheck`)
- **SQL**: lowercase keywords, snake_case columns
- **YAML/JSON**: 2-space indentation

## Testing Requirements

- Backend: maintain or improve coverage (currently targeting 80%+)
- Android: unit tests for all ViewModels, repository classes
- No PR merged without at least one test covering the changed code path

## Contact

For research-related questions or significant architectural changes, contact:

**Mr. Suhas Devmane**
PhD Researcher, School of Computer Science & Informatics (COMSC)
Cardiff University, Wales, UK
