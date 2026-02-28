# Medication Proctor

Real‑time AI proctor that supervises medication administration over live video. The agent guides clinicians through a safety protocol (PPE, hand hygiene, medication identification, administration, documentation), speaks naturally, and annotates the video. It combines Google Gemini Realtime for conversational vision, Stream for ultra‑low‑latency video, and Roboflow for PPE/object detection. A Next.js UI starts/ends sessions and connects the clinician.

## Features
- Realtime voice + vision proctor (Gemini Realtime)
- Video transport via Stream Video (join/create calls)
- PPE and environment detection via Roboflow API with on‑video boxes
- Step tracking: logs completed protocol steps and violations
- HTTP server mode with `/health` and session endpoints
- Docker and docker‑compose for deployment
- Next.js frontend with one‑click “Initialize Session”

## Repo Structure
- `main.py` — Agent factory, CLI (run/server), protocol logic, Stream integration
- `roboflow_processor.py` — Roboflow inference + frame annotation publisher
- `frontend/` — Next.js 16 app using `@stream-io/video-react-sdk`
- `Dockerfile`, `docker-compose.yml` — Containerized server
- `.env.example` — Required credentials
- `pyproject.toml`, `uv.lock` — Python deps (managed by `uv`)

## Prerequisites
- Python 3.13
- Node.js 18+ and npm (for `frontend/`)
- Accounts/keys: Stream, Google (Gemini), Roboflow

## Environment Variables
Copy the example and fill values:

```bash
cp .env.example .env
```

Required keys (backend):
- `STREAM_API_KEY` — Stream API key
- `STREAM_API_SECRET` — Stream secret
- `GOOGLE_API_KEY` — Google Generative AI key (Gemini Realtime)
- `ROBOFLOW_API_KEY` — Roboflow Inference API key

Frontend (`frontend/.env.local`):
- `NEXT_PUBLIC_STREAM_API_KEY` — same as `STREAM_API_KEY`
- `STREAM_API_SECRET` — same secret (used by the Next.js API route to mint tokens)

## Quick Start (Local Dev)

### 1) Backend — console mode (joins a call directly)
Using `uv` (recommended):

```bash
# Install uv if needed: https://docs.astral.sh/uv/getting-started/installation/
uv sync
uv run python main.py run --call-type default --call-id my-test-call
```

Flags help:
- `--call-type TEXT` (e.g., `default`)
- `--call-id TEXT` (auto-generated if omitted)
- `--video-track-override FILE` to debug with a local clip

### 2) Backend — server mode (spawns agents via HTTP)
The frontend expects the backend at `http://127.0.0.1:8000` (see `frontend/next.config.ts`). Run:

```bash
uv run python main.py serve --host 127.0.0.1 --port 8000
```

Health check: `GET /health`

### 3) Frontend — Next.js UI

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:3000 and click “Initialize Session”. This:
- Creates a Stream call and joins as the clinician
- Requests a short‑lived token from `frontend/app/api/token/route.ts`
- POSTs to backend `/sessions` (via Next.js rewrite) to spawn the AI proctor

Stop session: the UI calls `DELETE /sessions/{id}` and leaves the call.

## Docker
Make sure `.env` is filled at the repo root, then:

```bash
docker compose up --build
```

Notes:
- The image exposes `8080` by default (see `Dockerfile`), and `docker-compose.yml` maps host `8080:8080`.
- The frontend rewrite targets `127.0.0.1:8000`. Either:
  - Run server on 8000 (`uv run python main.py serve --port 8000` when not using the Docker CMD), or
  - Update `frontend/next.config.ts` to rewrite to `http://127.0.0.1:8080` if you keep the container at 8080.

## How It Works
- Agent stack: `vision-agents` framework orchestrates the LLM, video transport, and processors.
- LLM: `gemini.Realtime(model="gemini-2.5-flash-native-audio-latest", fps=1)` for conversational vision/audio.
- Video: `getstream.Edge()` creates/joins Stream calls.
- Detection: `RoboflowProcessor` sends frames to Roboflow, draws boxes, and exposes summaries to the agent.
- Protocol: the agent logs step completions via tool calls (`log_step`, `log_violation`) and speaks brief guidance.

## CLI Reference
Run `python main.py --help` for commands.

- `run` — single console agent
  - `--call-type`, `--call-id`, `--debug`, `--log-level`, `--no-demo`, `--video-track-override`
- `serve` — HTTP server for multi‑session
  - `--host`, `--port`, `--agents-log-level`, `--http-log-level`, `--debug`

## Troubleshooting
- Missing tokens: ensure `.env` and `frontend/.env.local` are set. The frontend API route requires both `NEXT_PUBLIC_STREAM_API_KEY` and `STREAM_API_SECRET`.
- 404 from `/api/backend`: confirm the backend is on `127.0.0.1:8000` or update `frontend/next.config.ts`.
- Roboflow quota/errors: verify `ROBOFLOW_API_KEY`; the processor will backoff after repeated failures.
- Gemini reconnects: a patch is applied to handle certain `APIError` reconnects from the live API.

## Security & Disclaimer
This project is for demonstration only and does not replace clinical judgment. Validate all outputs and comply with local privacy regulations when handling video/audio of real people.

## License
Add your preferred license here.