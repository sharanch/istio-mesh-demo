import os, random, datetime
from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

app = FastAPI(title="backend-service")
Instrumentator().instrument(app).expose(app)

VERSION = os.getenv("APP_VERSION", "v1")

SAMPLE_LOGS = [
    {"level": "INFO",  "msg": "Request processed successfully", "latency_ms": 12},
    {"level": "WARN",  "msg": "Cache miss — fallback to DB",    "latency_ms": 87},
    {"level": "ERROR", "msg": "Upstream timeout on /api/orders","latency_ms": 5020},
    {"level": "INFO",  "msg": "Health check passed",            "latency_ms": 3},
]


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
