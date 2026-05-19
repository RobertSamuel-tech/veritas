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
import os
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# Load .env into os.environ before anything reads env vars.
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, Response

JAC_PORT = 8001
PROXY_PORT = 8000
JAC_BACKEND = f"http://localhost:{JAC_PORT}"
INDEX_HTML = Path(__file__).parent / "index.html"


def _find_jac() -> Path:
    # Prefer the venv jac that matches this project's installed packages.
    venv_jac = Path(__file__).parent / ".venv" / "Scripts" / "jac.exe"
    if venv_jac.exists():
        return venv_jac

    import shutil

    found = shutil.which("jac")
    if found:
        return Path(found)

    # Fallback: pip --user install on Windows
    roaming = Path.home() / "AppData" / "Roaming" / "Python"
    for candidate in sorted(roaming.glob("Python3*/Scripts/jac.exe"), reverse=True):
        return candidate

    raise FileNotFoundError(
        "jac executable not found — activate the venv or install jaclang"
    )


JAC_EXE = _find_jac()

_jac_process: subprocess.Popen | None = None
_http_client: httpx.AsyncClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _jac_process, _http_client

    # Inherit env and force UTF-8 so jac's Rich banner doesn't crash on Windows.
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

    print(f"[serve.py] Starting jac backend:  {JAC_EXE} start main.jac -p {JAC_PORT}")
    _jac_process = subprocess.Popen(
        [str(JAC_EXE), "start", "main.jac", "-p", str(JAC_PORT)],
        cwd=Path(__file__).parent,
        env=env,
    )

    # Wait up to 15 s for the jac backend to accept TCP connections.
    print(f"[serve.py] Waiting for jac on port {JAC_PORT}…")
    for attempt in range(30):
        await asyncio.sleep(0.5)
        try:
            _, writer = await asyncio.open_connection("127.0.0.1", JAC_PORT)
            writer.close()
            await writer.wait_closed()
            print(f"[serve.py] Jac backend ready on port {JAC_PORT}.")
            break
        except OSError:
            pass
    else:
        print(
            f"[serve.py] WARNING: jac did not bind port {JAC_PORT} within 15 s — "
            "proxy will return 503 until it does."
        )

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
