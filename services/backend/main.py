import os, random, datetime, json
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from prometheus_fastapi_instrumentator import Instrumentator
import redis

app = FastAPI(title="backend-service")
Instrumentator().instrument(app).expose(app)

VERSION = os.getenv("APP_VERSION", "v1")
REDIS_HOST = os.getenv("REDIS_HOST", "redis")

r = redis.Redis(host=REDIS_HOST, port=6379, decode_responses=True)

SAMPLE_LOGS = [
    {"level": "INFO",  "msg": "Request processed successfully", "latency_ms": 12},
    {"level": "WARN",  "msg": "Cache miss — fallback to DB",    "latency_ms": 87},
    {"level": "ERROR", "msg": "Upstream timeout on /api/orders","latency_ms": 5020},
    {"level": "INFO",  "msg": "Health check passed",            "latency_ms": 3},
]


class LogEntry(BaseModel):
    level: str
    msg: str


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
async def create_log(entry: LogEntry):
    payload = {
        "level": entry.level,
        "msg": entry.msg,
        "version": VERSION,
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "pod": os.getenv("HOSTNAME", "unknown"),
    }
    r.rpush("logs", json.dumps(payload))
    return {"stored": r.llen("logs"), "entry": payload}


@app.get("/log")
async def get_logs():
    logs = [json.loads(l) for l in r.lrange("logs", 0, -1)]
    return {"logs": logs, "total": len(logs)}


@app.delete("/log")
async def clear_logs():
    r.delete("logs")
    return {"status": "cleared"}