# fetchall

Paste a link, get the video. A public web service built on [yt-dlp](https://github.com/yt-dlp/yt-dlp) that downloads video from almost any public, non-DRM page.

The full v1 spec is [issue #1](https://github.com/PurpleDNA/fetchall/issues/1).

## Layout

| Path | What |
|---|---|
| `api/` | Python backend: FastAPI app and RQ workers (one image, two commands) |
| `web/` | React + Vite + TypeScript frontend |
| `deploy/` | Production infrastructure: Terraform and production Compose (arrives with #14) |
| `compose.yaml` | Local development stack |

## Run locally

With Docker:

```sh
cp .env.example .env   # optional; defaults work out of the box
docker compose up --build
```

This starts Redis, the API on http://localhost:8000, a worker, and the frontend dev server on http://localhost:5173. The page shows whether the API (and its Redis) is healthy.

Without Docker, you need a Redis on `localhost:6379`, then:

```sh
cd api && uv sync && uv run uvicorn fetchall.app:create_app --factory --reload   # API
cd api && uv run python -m fetchall.worker                                      # worker
cd web && npm install && npm run dev                                            # frontend
```

## Configuration

The backend reads `FETCHALL_*` environment variables, or a `.env` file. See `.env.example`. The frontend reads `VITE_API_URL` (see `web/.env.example`). Secrets never go in the repo.

## Tests

```sh
cd api && uv run pytest        # backend
cd web && npm test             # frontend
```

CI runs both suites, plus lint, type checks and a production build, on every push.
