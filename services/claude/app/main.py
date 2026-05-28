import asyncio
import json
import logging
import re
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, List, Union

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, field_validator

# ─── Config ──────────────────────────────────────────────────────────────────

CLAUDE_AGENT   = "crypto-parser"
CLAUDE_TIMEOUT = 90    # seconds — 3× the ~30s worst-case Claude response time
MAX_CONCURRENT = 10    # semaphore cap: controls max parallel CLI processes

# ─── Logging ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("crypto-parser")

# ─── Concurrency limiter ──────────────────────────────────────────────────────
# Created at module level (safe in Python 3.10+; asyncio.Semaphore no longer
# requires a running event loop at construction time).

_sem = asyncio.Semaphore(MAX_CONCURRENT)

# ─── Lifespan ─────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(_: FastAPI):
    log.info("startup — max_concurrent=%d timeout=%ds", MAX_CONCURRENT, CLAUDE_TIMEOUT)
    yield
    log.info("shutdown")


app = FastAPI(title="Crypto Parser API", version="2.0.0", lifespan=lifespan)

# ─── Allowed values ───────────────────────────────────────────────────────────

_DIRECTIONS    = {"up", "down"}
_EXPIRE_TIMES  = {"1d", "3d", "1w", "2w", "1m", "3m", "1y"}
_ENTRY_TYPES   = {"fix", "break_up", "break_down", "consolidation_up", "consolidation_down"}

# ─── Schema ───────────────────────────────────────────────────────────────────


class Scenario(BaseModel):
    model_config = ConfigDict(extra="ignore")
    direction:        str
    entry_point:      str = "now"
    entry_point_type: str = "fix"
    tp:               List[str] = []
    sl:               str       = ""
    reason:           str       = ""

    @field_validator("direction", mode="before")
    @classmethod
    def _v_direction(cls, v):
        return v if v in _DIRECTIONS else "up"

    @field_validator("entry_point_type", mode="before")
    @classmethod
    def _v_entry_type(cls, v):
        return v if v in _ENTRY_TYPES else "fix"

    @field_validator("tp", mode="before")
    @classmethod
    def _v_tp(cls, v):
        if not isinstance(v, list):
            return []
        return [str(i) for i in v if i is not None and str(i).strip()]

    @field_validator("sl", mode="before")
    @classmethod
    def _v_sl(cls, v):
        return "" if v is None else str(v).strip()

    @field_validator("entry_point", mode="before")
    @classmethod
    def _v_entry(cls, v):
        return "now" if v is None else str(v).strip()


class SignalItem(BaseModel):
    model_config = ConfigDict(extra="ignore")
    symbol:      str
    senarios:    List[Scenario] = []
    expire_time: str            = ""

    @field_validator("expire_time", mode="before")
    @classmethod
    def _v_expire(cls, v):
        return v if v in _EXPIRE_TIMES else ""

    @field_validator("senarios", mode="before")
    @classmethod
    def _v_senarios(cls, v):
        if not isinstance(v, list):
            return []
        return v


# ─── JSON extraction ──────────────────────────────────────────────────────────


_ANSI_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def extract_output(raw: str) -> Union[List[Any], str]:
    """Return parsed list or 'nok'. Raises ValueError if neither."""
    raw = _ANSI_RE.sub("", raw).strip()  # strip ANSI codes from interactive mode

    if raw.lower() == "nok":
        return "nok"

    # Try raw, then strip markdown fences
    for candidate in (raw, re.sub(r"```(?:json)?", "", raw).replace("```", "").strip()):
        if candidate.lower() == "nok":
            return "nok"
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass

    # Last resort: extract outermost [ ... ]
    s, e = raw.find("["), raw.rfind("]")
    if s != -1 and e > s:
        try:
            return json.loads(raw[s : e + 1])
        except json.JSONDecodeError:
            pass

    raise ValueError(f"No valid JSON array in agent output: {raw[:300]!r}")


# ─── Async Claude runner ──────────────────────────────────────────────────────


async def call_claude(prompt: str, req_id: str) -> str:
    """
    Launch Claude CLI as a true async subprocess. The semaphore caps concurrent
    processes at MAX_CONCURRENT. On timeout the process is killed immediately.
    """
    async with _sem:
        slots_used = MAX_CONCURRENT - _sem._value
        t0 = time.monotonic()
        log.info("[%s] claude start — concurrent=%d/%d", req_id, slots_used, MAX_CONCURRENT)

        # Interactive mode (no -p): behaves exactly like typing in terminal.
        # Prompt is written to stdin; CLI exits when stdin closes (EOF).
        proc = await asyncio.create_subprocess_exec(
            "claude",
            "--agent", CLAUDE_AGENT,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=prompt.encode("utf-8")), timeout=CLAUDE_TIMEOUT
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            log.warning("[%s] claude timed out after %ds — process killed", req_id, CLAUDE_TIMEOUT)
            raise TimeoutError(f"Claude CLI exceeded {CLAUDE_TIMEOUT}s")

        if proc.returncode != 0:
            err = stderr.decode(errors="replace").strip()
            log.error("[%s] claude exit=%d stderr=%s", req_id, proc.returncode, err[:200])
            raise RuntimeError(err or f"Claude CLI exited with code {proc.returncode}")

        output = stdout.decode(errors="replace").strip()
        log.info("[%s] claude ok — output_len=%d elapsed=%.1fs", req_id, len(output), time.monotonic() - t0)
        return output


# ─── Request model ────────────────────────────────────────────────────────────


class ParseRequest(BaseModel):
    prompt: str


# ─── Routes ───────────────────────────────────────────────────────────────────


@app.post("/parse")
async def parse(req: ParseRequest, request: Request):
    req_id = str(uuid.uuid4())[:8]
    log.info("[%s] POST /parse from=%s prompt_len=%d",
             req_id, request.client.host, len(req.prompt))

    try:
        raw_output = await call_claude(req.prompt, req_id)
    except TimeoutError:
        raise HTTPException(status_code=504, detail="Claude CLI timed out")
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="claude CLI not found — is it installed?")
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    try:
        data = extract_output(raw_output)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    if data == "nok":
        log.info("[%s] result=nok", req_id)
        return JSONResponse(content={"result": "nok"})

    try:
        signals = [SignalItem(**item).model_dump() for item in data]
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Schema validation failed: {exc} — raw: {json.dumps(data)[:300]}",
        )

    log.info("[%s] result=ok signals=%d", req_id, len(signals))
    return JSONResponse(content=signals)


@app.get("/health")
async def health():
    slots_free = _sem._value
    return {
        "status":     "ok",
        "capacity":   MAX_CONCURRENT,
        "slots_free": slots_free,
        "slots_busy": MAX_CONCURRENT - slots_free,
    }
