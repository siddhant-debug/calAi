# CalAI Backend — System Design @ 1,000 Users

**Date:** 2026-06-06  
**Scope:** Python FastAPI + ReAct Agent backend  
**Companion docs:** ADR-001, ADR-002, README

---

## 1. Clarifying the Scale Assumption

There are two very different architectures depending on the deployment model:

| Mode | Description | LLM |
|------|-------------|-----|
| **A — Personal** | Each user runs their own instance on their machine | Local Ollama per user |
| **B — Shared server** | A single server serves 1,000 users | Shared LLM (Ollama or cloud) |

**This document designs for Mode B (shared server)** — the more interesting engineering problem and the natural growth path from the local prototype. Mode A is just "package the README and ship."

---

## 2. Requirements

### Functional
- Accept free-text meal input + user profile, return structured nutrition + calorie goal
- Log meals, retrieve daily summary
- Store and update user profiles
- Agent loop runs reliably under concurrent load

### Non-Functional @ 1,000 users

| Requirement | Target |
|-------------|--------|
| Concurrent active users (peak) | ~100 (10% of 1k) |
| API p95 latency | < 10s (LLM-bound) |
| API p99 latency | < 20s |
| Availability | 99.5% (< 44h downtime/year) |
| Data durability | No meal log loss on restart |
| Privacy | User data isolated per account |
| Cost | Minimal — self-hosted LLM |

### Constraints
- Local LLM preferred (privacy, cost) — but now shared across users
- Python + FastAPI stack (keep what works)
- SQLite → must upgrade (concurrent writes don't scale)
- Solo/small team — avoid operational complexity

---

## 3. Load Estimation

### Users & Requests

```
1,000 registered users
Peak concurrent: 100 users (10%)
Each session: 1 agent call (3–8 LLM steps) + 1 summary GET

Agent calls/day:     1,000 users × 3 meals × 0.5 active rate = ~1,500/day
Peak burst (lunch):  ~150 requests in a 15-minute window
RPS at peak:         150 / 900s ≈ 0.17 RPS  (very manageable)
```

### LLM Bottleneck — The Critical Constraint

```
qwen2.5:3b on M-series Mac:
  ~15–25 tokens/sec
  Avg tokens per agent step: ~200 input + 50 output
  Avg step time: ~3–5s
  Steps per request: avg 5
  Total LLM time per request: ~15–25s

Concurrent LLM capacity (single GPU/CPU instance):
  1 request at a time (Ollama default — sequential queue)
  At 0.17 RPS peak, queue depth = 0.17 × 20s = ~3 requests ahead
  P95 wait time: ~60s at peak  ← PROBLEM
```

**Conclusion:** With one Ollama instance, peak latency is unacceptable at 100 concurrent users. The primary design challenge is LLM throughput.

### Storage

```
Meals per user/day: 3 × 365 = 1,095/year
Per meal record: ~2KB (JSON items + metadata)
Total storage/year: 1,000 × 1,095 × 2KB ≈ 2.2GB/year
Growth is trivial — not a bottleneck.
```

---

## 4. High-Level Architecture

```
                        ┌──────────────────┐
                        │   Flutter Apps   │
                        │  (iOS / Android) │
                        └────────┬─────────┘
                                 │ HTTPS
                        ┌────────▼─────────┐
                        │   Nginx / Caddy  │  TLS termination
                        │   Reverse Proxy  │  Rate limiting
                        └────────┬─────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              │                  │                  │
     ┌────────▼──────┐  ┌────────▼──────┐  ┌───────▼───────┐
     │  FastAPI      │  │  FastAPI      │  │  FastAPI      │
     │  Worker 1     │  │  Worker 2     │  │  Worker 3     │
     │  (Uvicorn)    │  │  (Uvicorn)    │  │  (Uvicorn)    │
     └────────┬──────┘  └────────┬──────┘  └───────┬───────┘
              │                  │                  │
              └──────────────────┼──────────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │   Task Queue (Redis)     │
                    │   Agent jobs + results   │
                    └────────────┬────────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              │                  │                  │
     ┌────────▼──────┐  ┌────────▼──────┐  ┌───────▼───────┐
     │ Agent Worker  │  │ Agent Worker  │  │ Agent Worker  │
     │   (Python)    │  │   (Python)    │  │   (Python)    │
     └────────┬──────┘  └────────┬──────┘  └───────┬───────┘
              │                  │                  │
              └──────────────────┼──────────────────┘
                                 │  HTTP (round-robin or least-busy)
              ┌──────────────────┼──────────────────┐
              │                  │                  │
     ┌────────▼──────┐  ┌────────▼──────┐           │
     │ Ollama inst 1 │  │ Ollama inst 2 │   (scale) │
     │ qwen2.5:3b    │  │ qwen2.5:3b    │           │
     └───────────────┘  └───────────────┘           │
                                 │                  │
                    ┌────────────▼────────────────── ┘
                    │   PostgreSQL                   │
                    │   + Redis (cache)              │
                    └────────────────────────────────┘
```

### Key Changes from Prototype

| Prototype (1 user) | Production (1,000 users) |
|-------------------|--------------------------|
| SQLite | PostgreSQL |
| Synchronous agent call | Async job queue (Redis + workers) |
| Single Ollama instance | Pool of Ollama instances |
| No auth | JWT authentication |
| No rate limiting | Nginx rate limits per user |
| No caching | Redis nutrition cache |

---

## 5. Component Deep Dive

### 5.1 API Layer (FastAPI Workers)

The FastAPI workers are **thin orchestrators** — they accept requests, enqueue agent jobs, and return results. Agent execution happens in separate workers so HTTP workers stay responsive.

**Pattern: async job submission**

```
POST /api/agent
  → validate request
  → push job to Redis queue
  → return job_id immediately (202 Accepted)

GET /api/agent/{job_id}
  → poll job status (pending / running / done / failed)
  → return result when done

(Flutter polls every 2s, or use WebSocket for push)
```

This decouples HTTP latency from LLM latency. Users get a `202` immediately and the Flutter app shows a loading state.

**Workers:** 3 Uvicorn processes behind Nginx, each running `uvicorn main:app --workers 1` (Uvicorn is async so 1 worker handles many connections).

---

### 5.2 Task Queue (Redis + ARQ or Celery)

**Recommended: ARQ** (async-first, lighter than Celery, works natively with FastAPI's async)

```python
# worker/agent_worker.py
from arq import cron
from agent.react_loop import ReActAgent

async def run_agent_job(ctx, job_id: str, user_input: str, user_profile: dict):
    agent = ctx["agent"]
    result = await agent.run_async(user_input, user_profile)
    await ctx["redis"].set(f"result:{job_id}", json.dumps(result), ex=3600)
    return result

class WorkerSettings:
    functions = [run_agent_job]
    max_jobs  = 3           # 3 concurrent agent jobs per worker process
    queue_name = "calai"
```

**Queue depth target:** < 10 jobs at peak. At 0.17 RPS peak and 20s/job, queue = 0.17 × 20 = ~3.4 jobs. Comfortable.

---

### 5.3 LLM Pool (Multiple Ollama Instances)

The single Ollama instance can't serve concurrent requests efficiently. Run **2–3 Ollama processes** on different ports and load-balance across them.

```
# Start 3 Ollama instances on ports 11434, 11435, 11436
OLLAMA_HOST=0.0.0.0:11434 ollama serve &
OLLAMA_HOST=0.0.0.0:11435 ollama serve &
OLLAMA_HOST=0.0.0.0:11436 ollama serve &
```

```python
# agent/llm_pool.py
import itertools
import httpx

class OllamaPool:
    def __init__(self, urls: list[str], model: str):
        self.urls = urls
        self.model = model
        self._cycle = itertools.cycle(urls)   # simple round-robin

    def next_client(self) -> OllamaClient:
        return OllamaClient(base_url=next(self._cycle), model=self.model)
```

With 3 instances on an M-series Mac (or a Linux box with a decent GPU), throughput triples: ~9 concurrent LLM steps vs. 3.

**Memory requirement:** 3 × ~2GB (qwen2.5:3b Q4_K_M) = ~6GB RAM/VRAM. Fits on a 16GB machine.

---

### 5.4 Nutrition Cache (Redis)

`parse_meal_text` calls the LLM for every meal. But "2 eggs" always returns roughly the same data. Cache aggressively.

```python
# tools/meal_parser.py
import hashlib, json, redis

r = redis.Redis()
TTL = 7 * 24 * 3600  # 1 week

def parse_meal_text(meal_text: str, meal_type: str = None) -> dict:
    cache_key = "meal:" + hashlib.sha256(meal_text.lower().strip().encode()).hexdigest()[:16]
    cached = r.get(cache_key)
    if cached:
        return json.loads(cached)

    result = _call_llm_for_meal(meal_text, meal_type)
    r.setex(cache_key, TTL, json.dumps(result))
    return result
```

**Expected hit rate:** ~60–70% (users repeat common meals). This cuts LLM calls roughly in half, doubling effective throughput.

---

### 5.5 Database: PostgreSQL

SQLite can't handle concurrent writes from multiple workers. Switch to PostgreSQL.

**Schema:**

```sql
-- Users
CREATE TABLE users (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email       TEXT UNIQUE NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- User profiles (weight, height, goal)
CREATE TABLE user_profiles (
    user_id         UUID PRIMARY KEY REFERENCES users(id),
    weight_kg       REAL NOT NULL,
    height_cm       REAL NOT NULL,
    age             INT NOT NULL,
    gender          TEXT NOT NULL CHECK (gender IN ('male','female')),
    activity_level  TEXT NOT NULL,
    goal            TEXT NOT NULL CHECK (goal IN ('lose','maintain','gain')),
    goal_rate_kg_pw REAL DEFAULT 0.5,
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Meal logs
CREATE TABLE meals (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id),
    logged_at   TIMESTAMPTZ DEFAULT NOW(),
    meal_type   TEXT,
    raw_input   TEXT NOT NULL,
    items_json  JSONB NOT NULL,
    total_kcal  REAL NOT NULL,
    protein_g   REAL,
    carbs_g     REAL,
    fat_g       REAL
);

CREATE INDEX idx_meals_user_date ON meals (user_id, logged_at::date);

-- Agent job results (short-lived cache)
CREATE TABLE agent_jobs (
    id          UUID PRIMARY KEY,
    user_id     UUID REFERENCES users(id),
    status      TEXT DEFAULT 'pending',  -- pending / running / done / failed
    result_json JSONB,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX idx_jobs_user_status ON agent_jobs (user_id, status);
```

**Connection pool:** SQLAlchemy async with `pool_size=10`, `max_overflow=20`. Each FastAPI worker shares a pool.

---

### 5.6 Authentication

At 1,000 users, data isolation is mandatory. Use **JWT tokens** (stateless, no session store needed).

```
POST /api/auth/register  → {email, password} → {access_token, refresh_token}
POST /api/auth/login     → {email, password} → {access_token}
```

All `/api/*` routes require `Authorization: Bearer <token>`. Middleware extracts `user_id` from the token and injects it into every request context — meals and profiles are always scoped to the authenticated user.

**Library:** `python-jose` + `passlib[bcrypt]`

---

## 6. API Contracts (Updated for Production)

```
POST   /api/auth/register
POST   /api/auth/login

POST   /api/agent              → 202 { job_id }
GET    /api/agent/{job_id}     → { status, result? }

POST   /api/profile            → save user profile
GET    /api/profile            → get current profile

GET    /api/summary?date=      → daily summary
GET    /api/history?from=&to=  → meal history range

GET    /api/health             → { api, ollama_pool, db, queue }
```

All endpoints except `/health` and `/auth/*` require JWT.

---

## 7. Data Flow: End-to-End Request

```
1. Flutter  → POST /api/agent (Bearer token + input text)
2. Nginx    → rate check (10 req/min/user) → forward to FastAPI worker
3. FastAPI  → validate JWT → extract user_id
             → load user_profile from PostgreSQL (or Redis cache, TTL 5min)
             → create agent_jobs row (status=pending)
             → push job to Redis queue
             → return 202 { job_id }

4. Flutter  → polls GET /api/agent/{job_id} every 2s

5. ARQ Worker → picks up job
              → instantiate ReActAgent with OllamaPool
              → run loop (up to 8 steps):
                  a. LLM call → parse ACTION/ARGS
                  b. Execute tool (check nutrition cache first)
                  c. Inject OBSERVATION
              → emit FINAL_ANSWER
              → save_meal() to PostgreSQL
              → update agent_jobs row (status=done, result_json=...)

6. Flutter  → GET /api/agent/{job_id} returns { status: done, result: {...} }
7. UI       → renders calorie summary, meal breakdown
```

---

## 8. Rate Limiting & Abuse Protection

```nginx
# nginx.conf
limit_req_zone $http_authorization zone=per_user:10m rate=10r/m;

location /api/agent {
    limit_req zone=per_user burst=3 nodelay;
    proxy_pass http://fastapi_upstream;
}
```

10 agent requests/minute/user is generous for a calorie tracker (users log ~3 meals/day). This prevents a single user from monopolizing the LLM queue.

---

## 9. Monitoring & Alerting

### Metrics to track (Prometheus + Grafana, or just logs)

| Metric | Alert threshold |
|--------|----------------|
| LLM queue depth | > 10 jobs |
| Agent p95 latency | > 30s |
| Agent failure rate | > 5% |
| Ollama instance health | Any down |
| PostgreSQL connections | > 80% pool |
| Redis memory | > 80% |

### Logging

Each agent run emits a structured log line:
```json
{
  "request_id": "uuid",
  "user_id": "uuid",
  "steps_taken": 6,
  "duration_ms": 18400,
  "cache_hits": 2,
  "final_status": "ok",
  "tools_called": ["calculate_bmr", "calculate_tdee", "calculate_calorie_goal", "parse_meal_text", "save_meal"]
}
```

This is sufficient to debug latency spikes without storing full conversation history.

---

## 10. Scaling Analysis

### Current design capacity

| Resource | Capacity | At 1k users |
|----------|----------|-------------|
| FastAPI workers (3×) | ~3,000 HTTP req/s | ✅ trivial |
| ARQ workers (2 processes × 3 jobs) | 6 concurrent agent jobs | ✅ at 0.17 RPS |
| Ollama pool (3 instances) | 3 concurrent LLM calls | ✅ with queue |
| PostgreSQL | 200 connections | ✅ trivial |
| Redis nutrition cache | 60–70% hit rate | ✅ cuts LLM load in half |

### When this breaks (10k users)

- **LLM pool saturates** — 3 Ollama instances can't serve 10× load. Options: add GPUs, switch to vLLM (batching), or offer a cloud LLM fallback.
- **ARQ workers** — add more worker processes or machines; they're stateless.
- **PostgreSQL** — add read replicas for history/summary queries; writes stay on primary.
- **Redis** — single instance is fine up to ~50k users.

### Horizontal scaling path

```
1k  users: 1 server, 3 Ollama instances (current design)
10k users: 3 servers, vLLM with tensor parallelism, PostgreSQL + 2 read replicas
100k users: managed GPU inference (RunPod/Modal), distributed workers, PgBouncer
```

---

## 11. Trade-off Summary

| Decision | Chosen | Alternative | Why |
|----------|--------|-------------|-----|
| Job queue | Redis + ARQ | Celery | Lighter, async-native, fewer deps |
| LLM scaling | Ollama pool | vLLM | vLLM is better but operationally heavier; Ollama fine at 1k |
| DB | PostgreSQL | MongoDB | Relational integrity for user/meal links; JSONB for items |
| Auth | JWT stateless | Session cookies | No session store needed; works with mobile clients |
| Polling vs. push | HTTP polling (2s) | WebSocket | Simpler at this scale; WebSocket adds connection management overhead |
| Nutrition cache | Redis (hashed text key) | Vector similarity | Exact-match cache is sufficient; semantic similarity is overkill at 1k |

---

## 12. Action Items

### Phase 1 — Get to 100 users (localhost → server)
1. [ ] Add JWT auth (`python-jose`, `passlib`)
2. [ ] Migrate SQLite → PostgreSQL (Alembic migration from prototype schema)
3. [ ] Add Redis for nutrition cache
4. [ ] Replace sync agent call with ARQ job queue
5. [ ] Add `GET /api/agent/{job_id}` polling endpoint
6. [ ] Update Flutter to poll job_id instead of awaiting response

### Phase 2 — Harden for 1,000 users
7. [ ] Spin up 3 Ollama instances on separate ports; implement `OllamaPool`
8. [ ] Add Nginx with JWT-scoped rate limiting
9. [ ] Add structured agent trace logging (JSONL)
10. [ ] Add `GET /api/health` with Ollama pool + DB + queue health checks
11. [ ] Write load test: 100 concurrent `/api/agent` requests, verify queue depth < 10

### Phase 3 — Observability
12. [ ] Prometheus metrics: queue depth, p95 latency, cache hit rate
13. [ ] Alert on agent failure rate > 5%
14. [ ] Dashboard: daily active users, meals logged, avg calories
