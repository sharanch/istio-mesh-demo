import os, random, datetime, json, uuid
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from prometheus_fastapi_instrumentator import Instrumentator
from prometheus_client import Counter
import redis

app = FastAPI(title="backend-service")
Instrumentator().instrument(app).expose(app)

VERSION = os.getenv("APP_VERSION", "v1")
REDIS_HOST = os.getenv("REDIS_HOST", "redis")

r = redis.Redis(host=REDIS_HOST, port=6379, decode_responses=True)

# ── Prometheus metrics ────────────────────────────────────────────────────────

logs_total = Counter(
    "logs_total",
    "Total log entries written, by level and version",
    ["level", "version"],
)

# ── Sample data ───────────────────────────────────────────────────────────────

SAMPLE_LOGS = [
    {"level": "INFO",  "msg": "Request processed successfully", "latency_ms": 12},
    {"level": "WARN",  "msg": "Cache miss — fallback to DB",    "latency_ms": 87},
    {"level": "ERROR", "msg": "Upstream timeout on /api/orders","latency_ms": 5020},
    {"level": "INFO",  "msg": "Health check passed",            "latency_ms": 3},
]


class LogEntry(BaseModel):
    level: str
    msg: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def extract_trace_headers(request: Request) -> dict:
    """Pull Istio/B3 trace headers from the incoming request."""
    headers = request.headers
    return {k: headers[k] for k in (
        "x-request-id",
        "x-b3-traceid",
        "x-b3-spanid",
        "x-b3-parentspanid",
        "x-b3-sampled",
    ) if k in headers}


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {"service": "backend", "version": VERSION}


@app.get("/health")
async def health():
    return {"status": "ok", "version": VERSION}


@app.get("/data")
async def get_data():
    log = random.choice(SAMPLE_LOGS)
    return {
        "service": "backend",
        "version": VERSION,
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "log_sample": log,
        "pod": os.getenv("HOSTNAME", "unknown"),
    }


@app.post("/log")
async def create_log(entry: LogEntry, request: Request):
    entry_id = str(uuid.uuid4())
    payload = {
        "id": entry_id,
        "level": entry.level,
        "msg": entry.msg,
        "version": VERSION,
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "pod": os.getenv("HOSTNAME", "unknown"),
        "trace": extract_trace_headers(request),
    }
    r.set(f"log:{entry_id}", json.dumps(payload))
    r.rpush("log:index", entry_id)
    logs_total.labels(level=entry.level, version=VERSION).inc()
    total = r.llen("log:index")
    return {"stored": total, "entry": payload}


@app.get("/log")
async def get_logs():
    ids = r.lrange("log:index", 0, -1)
    logs = []
    for entry_id in ids:
        raw = r.get(f"log:{entry_id}")
        if raw:
            logs.append(json.loads(raw))
    return {"logs": logs, "total": len(logs)}


@app.delete("/log/{entry_id}")
async def delete_log(entry_id: str):
    key = f"log:{entry_id}"
    if not r.exists(key):
        raise HTTPException(status_code=404, detail=f"Log entry {entry_id} not found")
    r.delete(key)
    r.lrem("log:index", 0, entry_id)
    return {"deleted": entry_id}


@app.delete("/log")
async def clear_logs():
    ids = r.lrange("log:index", 0, -1)
    if ids:
        r.delete(*[f"log:{i}" for i in ids])
    r.delete("log:index")
    return {"status": "cleared"}