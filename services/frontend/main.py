import os, time, httpx
from fastapi import FastAPI, Response
from prometheus_fastapi_instrumentator import Instrumentator

app = FastAPI(title="frontend-service")
Instrumentator().instrument(app).expose(app)

BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8001")


@app.get("/")
async def root():
    return {"service": "frontend", "version": "v1"}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/data")
async def get_data():
    start = time.time()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{BACKEND_URL}/data")
            resp.raise_for_status()
            backend_data = resp.json()
    except httpx.TimeoutException:
        return Response(
            content='{"error":"backend timeout"}',
            status_code=504,
            media_type="application/json",
        )
    except httpx.HTTPError as e:
        return Response(
            content=f'{{"error":"backend error","detail":"{str(e)}"}}',
            status_code=502,
            media_type="application/json",
        )
    elapsed = round((time.time() - start) * 1000, 2)
    return {
        "service": "frontend",
        "version": "v1",
        "latency_ms": elapsed,
        "backend": backend_data,
    }


@app.get("/retry-demo")
async def retry_demo():
    """Hit backend 5x — shows canary split in action."""
    results = []
    async with httpx.AsyncClient(timeout=10.0) as client:
        for _ in range(5):
            try:
                r = await client.get(f"{BACKEND_URL}/data")
                results.append(r.json())
            except Exception as e:
                results.append({"error": str(e)})
    return {
        "calls": 5,
        "versions_seen": [r.get("version", "?") for r in results],
        "responses": results,
    }
