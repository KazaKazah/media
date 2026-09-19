# AGENTS.md

## Project overview

This repository is a Django application for managing a NAS-style photo/video library. The app stores metadata in SQLite, reads media from a configured filesystem root, and serves a web UI with Django templates + Bootstrap. Most business logic lives in the `photos/` app, while the project settings live in `dropandtag/settings.py`.

## Key project structure

- `dropandtag/` — Django project settings and URL wiring
- `photos/` — main application code: models, views, library logic, tests, auth-related behavior
- `templates/photos/` — Django templates for catalog, detail pages, profile, notes, and media UI
- `static/photos/` — JS and CSS used by the UI
- `data/` — app data directory for tags, SQLite files, generated indexes, and other runtime state
- `media_library/` — default local media root used for development and examples
- `docker-compose*.yml` and `Dockerfile` — container-based setup

## Build and validation commands

Use these commands from the repo root.

- Install dependencies:
  - `python -m venv .venv`
  - `. .venv/bin/activate`
  - `pip install -r requirements.txt`
- Apply migrations:
  - `python manage.py migrate`
- Run the app locally:
  - `MEDIA_ROOT="/path/to/photos" APP_DATA_DIR="./data" python manage.py runserver 0.0.0.0:8000`
- Run the Django test suite:
  - `python manage.py test`
- Run via Docker:
  - `docker compose up -d --build`

## Environment and configuration conventions

- Prefer environment variables over hardcoded paths.
- The app reads file-system settings from `MEDIA_ROOT`, `APP_DATA_DIR`, and `SQLITE_PATH`.
- Local development defaults are established in `dropandtag/settings.py`; Docker values are typically provided via environment variables or compose files.
- Keep the app working both with local folders and with Synology/NAS-style mounted volumes.
- Do not add new storage paths without respecting the existing `MEDIA_LIBRARY_ROOT` and `APP_DATA_DIR` conventions.

## Architecture conventions

- Keep Django ORM logic in `photos/models.py` and use the existing app structure instead of creating unrelated top-level modules.
- Prefer the current Django view/template patterns over introducing new frameworks or build tools.
- This project is not a React/Vite app; server-rendered templates are the standard UI pattern.
- Media protections matter: auth checks and adult-content gating exist around media access and catalog views. Preserve these safeguards when changing URLs or file-serving logic.
- File move/copy operations should stay inside the configured media root and should handle user-selected directories safely.

## UI and content conventions

- UI labels and help text are often in Russian; preserve the existing language style when editing layouts or forms.
- Template work should stay in `templates/photos/` and reuse existing partials where possible.
- Keep JS/CSS changes inside `static/photos/` unless a broader architectural refactor is truly required.

## Safety rules for agents

- Do not hardcode hostnames, storage roots, or secret keys into new code.
- Preserve login requirements for protected library access.
- Before changing media paths, confirm the behavior is compatible with the file-serving and access-control code.
- Keep changes small and project-consistent; this repo is a focused Django app rather than a generic template.

## Project references

- Main setup and run notes: [README.md](README.md)
- Django project config: [dropandtag/settings.py](dropandtag/settings.py)
- Main app logic: [photos/](photos/)
- Existing tests: [photos/tests.py](photos/tests.py)

When in doubt, favor the existing Django + filesystem patterns already used in this codebase.
