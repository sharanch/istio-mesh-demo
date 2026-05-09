import os, time, httpx
from fastapi import FastAPI, Response, Request
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


@app.get("/canary-split")
async def canary_split():
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


# ── /log passthrough ──────────────────────────────────────────────────────────

async def _proxy_error(e: Exception, status: int, label: str) -> Response:
    """Shared error shaping for backend proxy failures."""
    return Response(
        content=f'{{"error":"{label}","detail":"{str(e)}"}}',
        status_code=status,
        media_type="application/json",
    )


@app.get("/log")
async def get_logs():
    """Return all logs stored in the backend's Redis hashes."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{BACKEND_URL}/log")
            resp.raise_for_status()
            return resp.json()
    except httpx.TimeoutException as e:
        return await _proxy_error(e, 504, "backend timeout")
    except httpx.HTTPError as e:
        return await _proxy_error(e, 502, "backend error")


@app.post("/log")
async def create_log(request: Request):
    """Forward a log entry to the backend. Accepts the same {level, msg} body."""
    try:
        body = await request.json()
    except Exception:
        return Response(
            content='{"error":"invalid JSON body"}',
            status_code=400,
            media_type="application/json",
        )
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{BACKEND_URL}/log",
                json=body,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            return resp.json()
    except httpx.TimeoutException as e:
        return await _proxy_error(e, 504, "backend timeout")
    except httpx.HTTPError as e:
        return await _proxy_error(e, 502, "backend error")


@app.delete("/log/{entry_id}")
async def delete_log(entry_id: str):
    """Delete a single log entry by ID."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.delete(f"{BACKEND_URL}/log/{entry_id}")
            resp.raise_for_status()
            return resp.json()
    except httpx.TimeoutException as e:
        return await _proxy_error(e, 504, "backend timeout")
    except httpx.HTTPError as e:
        return await _proxy_error(e, 502, "backend error")


@app.delete("/log")
async def clear_logs():
    """Tell the backend to wipe all log entries from Redis."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.delete(f"{BACKEND_URL}/log")
            resp.raise_for_status()
            return resp.json()
    except httpx.TimeoutException as e:
        return await _proxy_error(e, 504, "backend timeout")
    except httpx.HTTPError as e:
        return await _proxy_error(e, 502, "backend error")