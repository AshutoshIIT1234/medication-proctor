
# Vision Agents Skill

## Product Summary

Vision Agents is an open-source Python framework for building real-time voice and video AI applications. It provides a unified `Agent` class that orchestrates LLMs, speech services (STT/TTS), video processors, and external tools via MCP. The framework ships with Stream's global edge network for low-latency transport but is edge-agnostic. Install with `uv add vision-agents` and add provider plugins as needed (e.g., `uv add "vision-agents[gemini,deepgram,elevenlabs]"`). Key files: `main.py` (agent definition), `.env` (API keys), `pyproject.toml` (dependencies). CLI commands: `uv run agent.py run` (console mode), `uv run agent.py serve` (HTTP server). See https://visionagents.ai for full documentation.

## When to Use

Reach for Vision Agents when:
- Building voice assistants, customer support bots, or phone agents (Twilio integration)
- Creating video AI applications with real-time frame processing or VLM analysis
- Needing to swap LLM/STT/TTS providers without rewriting agent logic
- Deploying agents to production with HTTP session management and metrics
- Adding computer vision (YOLO, Roboflow) or RAG (Gemini FileSearch, TurboPuffer) to agents
- Handling real-time events (participant joins, transcriptions, tool calls)
- Building agents that need function calling or MCP server integration

Do not use for: static chatbots, batch processing, or applications that don't require real-time audio/video.

## Quick Reference

### Agent Constructor

```python
from vision_agents.core import Agent, User
from vision_agents.plugins import gemini, deepgram, elevenlabs, getstream

# Realtime mode (speech-to-speech, no separate STT/TTS)
agent = Agent(
    edge=getstream.Edge(),
    agent_user=User(name="Assistant", id="agent"),
    instructions="You're a helpful voice assistant.",
    llm=gemini.Realtime(),  # or openai.Realtime()
)

# Custom pipeline (STT → LLM → TTS)
agent = Agent(
    edge=getstream.Edge(),
    agent_user=User(name="Assistant", id="agent"),
    instructions="You're a helpful voice assistant.",
    llm=gemini.LLM("gemini-2.5-flash"),
    stt=deepgram.STT(),
    tts=elevenlabs.TTS(),
    processors=[yolo_processor],  # Optional video processors
    mcp_servers=[github_server],  # Optional MCP servers
)
```

### Core Methods

| Method | Purpose |
|--------|---------|
| `await agent.join(call)` | Join a call (async context manager) |
| `await agent.simple_response(text)` | Send text to LLM for processing |
| `await agent.finish()` | Wait for call to end |
| `await agent.close()` | Clean up resources |
| `@agent.events.subscribe` | Subscribe to events (async handler) |
| `@llm.register_function()` | Register Python function for LLM calling |

### Running Agents

| Mode | Command | Use Case |
|------|---------|----------|
| Console | `uv run agent.py run` | Development, single agent |
| Server | `uv run agent.py serve --host 0.0.0.0 --port 8000` | Production, multi-session |

### API Endpoints (Server Mode)

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/sessions` | Create agent session |
| DELETE | `/sessions/{id}` | Stop session |
| GET | `/sessions/{id}/metrics` | Performance metrics |
| GET | `/health` | Liveness check |
| GET | `/ready` | Readiness check |

### Environment Variables

Store API keys in `.env`:
```bash
STREAM_API_KEY=your_key
STREAM_API_SECRET=your_secret
GOOGLE_API_KEY=your_key
OPENAI_API_KEY=your_key
DEEPGRAM_API_KEY=your_key
ELEVENLABS_API_KEY=your_key
```

Load with: `from dotenv import load_dotenv; load_dotenv()`

### Plugin Installation

```bash
# LLMs & Realtime
uv add "vision-agents[gemini,openai,openrouter,anthropic,xai,huggingface]"

# Speech
uv add "vision-agents[deepgram,elevenlabs,cartesia,fish,fast_whisper,kokoro]"

# Vision
uv add "vision-agents[nvidia,ultralytics,roboflow,moondream,heygen]"

# Infrastructure
uv add "vision-agents[getstream,twilio,turbopuffer]"
```

## Decision Guidance

### When to Use Realtime vs Custom Pipeline

| Aspect | Realtime Mode | Custom Pipeline |
|--------|---------------|-----------------|
| **Latency** | Lowest (native speech-to-speech) | Higher (STT → LLM → TTS) |
| **Setup** | Simplest (one LLM) | More config (3+ components) |
| **Control** | Less (model handles STT/TTS) | Full (choose each service) |
| **Providers** | OpenAI, Gemini, Qwen, AWS Nova | Any LLM + STT + TTS combo |
| **Video** | Supported (fps parameter) | Supported (frame buffering) |
| **Best for** | Fast prototypes, demos | Production, cost optimization |

### When to Use Video Approach

| Approach | Best For | Example |
|----------|----------|---------|
| **Realtime LLM** | Direct video streaming | `gemini.Realtime(fps=3)` |
| **VLM** | Frame analysis + understanding | `nvidia.VLM(fps=1, frame_buffer_seconds=10)` |
| **Processor** | Detection before LLM | `ultralytics.YOLOPoseProcessor()` |

### When to Use RAG

| Option | Setup | Search | Best For |
|--------|-------|--------|----------|
| **Gemini FileSearch** | Simple | Managed | Quick prototypes |
| **TurboPuffer** | More setup | Hybrid (vector + BM25) | Production, custom needs |

## Workflow

### 1. Set Up Project

```bash
mkdir my-agent && cd my-agent
uv init --python 3.12
uv add vision-agents python-dotenv
uv add "vision-agents[getstream,gemini,deepgram,elevenlabs]"
echo "STREAM_API_KEY=..." > .env
echo "GOOGLE_API_KEY=..." >> .env
```

### 2. Define Agent Factory

Create `main.py`:
```python
from dotenv import load_dotenv
from vision_agents.core import Agent, AgentLauncher, Runner, User
from vision_agents.plugins import gemini, deepgram, elevenlabs, getstream

load_dotenv()

async def create_agent(**kwargs) -> Agent:
    return Agent(
        edge=getstream.Edge(),
        agent_user=User(name="Assistant", id="agent"),
        instructions="You're a helpful voice assistant.",
        llm=gemini.LLM("gemini-2.5-flash"),
        stt=deepgram.STT(),
        tts=elevenlabs.TTS(),
    )

async def join_call(agent: Agent, call_type: str, call_id: str, **kwargs) -> None:
    call = await agent.create_call(call_type, call_id)
    async with agent.join(call):
        await agent.simple_response("Hello! How can I help?")
        await agent.finish()

if __name__ == "__main__":
    Runner(AgentLauncher(create_agent=create_agent, join_call=join_call)).cli()
```

### 3. Test Locally

```bash
uv run main.py run
```

### 4. Add Features

- **Function calling**: Use `@llm.register_function(description="...")` decorator
- **Events**: Use `@agent.events.subscribe` to listen to transcripts, responses, etc.
- **Video**: Add `processors=[yolo_processor]` to Agent constructor
- **RAG**: Create `gemini.GeminiFilesearchRAG()` and pass to LLM tools

### 5. Deploy

```bash
# Build Docker image
docker buildx build --platform linux/amd64 -t my-agent .

# Deploy to Kubernetes with health checks
kubectl apply -f deployment.yaml

# Start server
uv run main.py serve --host 0.0.0.0 --port 8080
```

## Common Gotchas

- **Missing API keys**: Vision Agents scans `.env` automatically. If a key is missing, the plugin will fail silently at runtime. Always test with `uv run main.py run` first.
- **Event handler must be async**: Non-async handlers raise `RuntimeError`. Use `async def` for all `@agent.events.subscribe` handlers.
- **Agent event loops**: Avoid infinite loops by filtering agent's own events: `if event.participant.user.id == "agent": return`
- **Realtime mode doesn't need STT/TTS**: Don't pass `stt=` or `tts=` when using `gemini.Realtime()` or `openai.Realtime()`.
- **Video processors need cleanup**: Always implement `stop_processing()` and `close()` to remove frame handlers and prevent memory leaks.
- **Session affinity for stateful agents**: If using multiple server replicas, ensure sticky sessions or session affinity is enabled (agents are stateful per session).
- **GPU not needed for most agents**: Only use GPU instances if running local models (Roboflow, local VLMs). Most voice agents use cloud APIs.
- **Frame buffer size matters**: For VLMs, `frame_buffer_seconds=10` means 10 seconds of frames are held. Adjust based on memory and latency needs.
- **MCP servers timeout**: Remote MCP servers have default 10s timeout. Increase with `timeout=30.0` if needed.
- **Turn detection with realtime models**: Realtime models handle turn detection natively. Don't pass `turn_detection=` parameter.

## Verification Checklist

Before submitting agent code:

- [ ] All required API keys are in `.env` and loaded with `load_dotenv()`
- [ ] Agent runs locally with `uv run main.py run` without errors
- [ ] `create_agent()` and `join_call()` are async functions
- [ ] Event handlers use `async def` (not sync functions)
- [ ] Agent filters its own events: `if event.participant.user.id == "agent": return`
- [ ] Video processors implement `stop_processing()` and `close()`
- [ ] Realtime mode agents don't include `stt=` or `tts=` parameters
- [ ] Custom pipeline agents include both `stt=` and `tts=`
- [ ] Function calls have `description=` parameter for LLM context
- [ ] Docker image builds for Linux: `docker buildx build --platform linux/amd64`
- [ ] Health checks configured: `/health` and `/ready` endpoints
- [ ] Session limits set if needed: `max_concurrent_sessions`, `max_session_duration_seconds`
- [ ] Metrics endpoint tested: `GET /sessions/{id}/metrics`

## Resources

- **Full documentation**: https://visionagents.ai/llms.txt (comprehensive page-by-page navigation)
- **Core concepts**: [Agent Class](https://visionagents.ai/core/agent-core) — orchestration, lifecycle, event system
- **Running agents**: [Running Agents as a Server](https://visionagents.ai/guides/running) — HTTP endpoints, session management, CORS, authentication
- **Deployment**: [Production Deployment](https://visionagents.ai/guides/deployment) — Docker, Kubernetes, health checks, scaling

---

> For additional