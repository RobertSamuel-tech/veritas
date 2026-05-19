"""
serve.py — Veritas frontend + backend launcher.

Starts the Jac backend on port 8001 and runs a lightweight FastAPI
reverse proxy on port 8000 that:
  - Serves index.html at  GET /  and  GET /index.html
  - Proxies everything else to http://localhost:8001

Run with:
    python serve.py
"""

import asyncio
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, Response

JAC_PORT = 8001
PROXY_PORT = 8000
JAC_BACKEND = f"http://localhost:{JAC_PORT}"
INDEX_HTML = Path(__file__).parent / "index.html"
def _find_jac() -> str:
    import shutil
    found = shutil.which("jac")
    if found:
        return found
    # User-scripts fallback for Windows pip --user installs
    roaming = Path.home() / "AppData" / "Roaming" / "Python"
    for candidate in sorted(roaming.glob("Python3*/Scripts/jac.exe"), reverse=True):
        return str(candidate)
    raise FileNotFoundError("jac executable not found — ensure jaclang is installed")

JAC_EXE = _find_jac()

_jac_process: subprocess.Popen | None = None
_http_client: httpx.AsyncClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _jac_process, _http_client

    # Start the Jac backend
    _jac_process = subprocess.Popen(
        [str(JAC_EXE), "start", "main.jac", "--port", str(JAC_PORT)],
        cwd=Path(__file__).parent,
    )
    # Wait for Jac backend to bind its port (TCP check)
    for _ in range(30):
        await asyncio.sleep(0.5)
        try:
            _, writer = await asyncio.open_connection("127.0.0.1", JAC_PORT)
            writer.close()
            await writer.wait_closed()
            break
        except OSError:
            continue

    _http_client = httpx.AsyncClient(base_url=JAC_BACKEND, timeout=60)
    yield

    # Shutdown
    await _http_client.aclose()
    if _jac_process and _jac_process.poll() is None:
        _jac_process.terminate()


app = FastAPI(lifespan=lifespan)


@app.get("/")
@app.get("/index.html")
async def serve_frontend():
    return HTMLResponse(content=INDEX_HTML.read_text(encoding="utf-8"))


@app.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
)
async def proxy(path: str, request: Request):
    url = f"/{path}"
    if request.url.query:
        url = f"{url}?{request.url.query}"

    headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in ("host", "content-length")
    }

    body = await request.body()

    try:
        resp = await _http_client.request(
            method=request.method,
            url=url,
            headers=headers,
            content=body,
        )
        # Strip hop-by-hop headers that should not be forwarded
        excluded = {
            "transfer-encoding",
            "connection",
            "keep-alive",
            "upgrade",
            "proxy-authenticate",
            "proxy-authorization",
            "te",
            "trailers",
        }
        resp_headers = {
            k: v for k, v in resp.headers.items() if k.lower() not in excluded
        }
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            headers=resp_headers,
            media_type=resp.headers.get("content-type"),
        )
    except httpx.ConnectError:
        return Response(
            content="Backend unavailable",
            status_code=503,
            media_type="text/plain",
        )


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PROXY_PORT, log_level="info")
