# Contributing

Meeting Note is a Windows desktop app for recording and transcribing meetings.

## Development setup

```powershell
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python run.py
```

API keys can be entered in the app settings or placed in `.env` for local development.
Never commit `.env`, databases, audio recordings, logs, or local agent/tool settings.

## Tests

```powershell
.\venv\Scripts\python.exe -m compileall src
.\venv\Scripts\python.exe -m unittest discover -s tests
```

## Pull requests

- Keep changes scoped and explain user-visible behavior changes.
- Add tests for database migrations, transcript parsing, and queue behavior.
- Do not include personal meeting content, generated recordings, local paths, or API keys.
- Follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## Good first contributions

- Documentation fixes in `README.md` or `docs/`.
- Small UI copy improvements.
- Unit tests for pure-Python helpers.
- Export formatting improvements.
- Troubleshooting entries backed by a confirmed fix.

See [docs/ROADMAP.md](docs/ROADMAP.md) for current priorities.
