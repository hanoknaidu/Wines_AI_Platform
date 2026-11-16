# Wines_AI_Platform

[![CI](https://github.com/hanoknaidu/Wines_AI_Platform/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/hanoknaidu/Wines_AI_Platform/actions/workflows/ci.yml)

## Continuous integration

Every pull request into `main` runs [`.github/workflows/ci.yml`](.github/workflows/ci.yml):

| Check | What it runs |
| --- | --- |
| Backend / lint & format | `uv lock --check`, `ruff check`, `ruff format --check` |
| Backend / unit tests | pytest; HTML test + coverage reports in the `backend-test-reports` artifact |
| Backend / docker build | builds `backend/Dockerfile` (no push) |
| Frontend / typecheck, lint, unit tests | `tsc`, eslint, vitest |
| Frontend / docker build | builds `frontend/Dockerfile` (no push) |
