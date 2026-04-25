"""Narrated end-to-end demo of the Digital Co-Pilot.

Run: `uv run python scripts/demo_e2e.py`

Five acts, printed with banners, each hitting real code:

    1. SEED CHECK            historian SQLite seed -> get_existing_runs tool
    2. PARQUET GROUND TRUTH  /twin/state  vs  twin_data.get_snapshot
    3. LIVE AGENT REASONING  /agent/query -> real Groq LLM + real query_database
    4. PROACTIVE WATCHDOG    POST /telemetry CRITICAL -> websocket PROACTIVE_ALERT
    5. VERDICT               grounding checklist + exit code

Exit codes: 0 = everything grounded, 1 = at least one check failed,
            2 = GROQ_API_KEY missing (can't run acts 3 or 4).
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Any


# Make sure `import app` resolves when the script is run from anywhere.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# The audio deps are optional on some dev machines; stub them exactly the
# same way tests/conftest.py does so `import app` never explodes just to
# run the narrated demo.
import types

for modname, cls, extra in (
    ("stt.transcriber", "SpeechToText", {}),
    ("tts.speaker", "TextToSpeech", {"voice": None}),
):
    if modname in sys.modules:
        continue
    try:
        __import__(modname)
    except Exception:
        parent = modname.split(".")[0]
        sys.modules.setdefault(parent, types.ModuleType(parent))
        stub = types.ModuleType(modname)
        Cls = type(cls, (), {
            "__init__": lambda self, *a, **kw: [setattr(self, k, v) for k, v in extra.items()],
            "transcribe": lambda self, *a, **kw: "",
            "generate_speech": lambda self, *a, **kw: "",
        })
        setattr(stub, cls, Cls)
        sys.modules[modname] = stub


# --------------------------------------------------------------- ANSI helpers

_USE_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _USE_COLOR else text


def bold(t: str) -> str:   return _c("1", t)
def green(t: str) -> str:  return _c("32", t)
def red(t: str) -> str:    return _c("31", t)
def yellow(t: str) -> str: return _c("33", t)
def cyan(t: str) -> str:   return _c("36", t)
def dim(t: str) -> str:    return _c("2", t)


def banner(step: int, title: str) -> None:
    bar = "=" * 72
    print()
    print(cyan(bar))
    print(cyan(f"  ACT {step}  ·  {title}"))
    print(cyan(bar))


def sub(title: str) -> None:
    print(dim(f"  -- {title}"))


def ok(msg: str) -> None:
    print(green(f"  [OK] {msg}"))


def fail(msg: str) -> None:
    print(red(f"  [FAIL] {msg}"))


def info(msg: str) -> None:
    print(f"       {msg}")


# ------------------------------------------------------------- grounding check

_TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
_RUN_ID_RE = re.compile(r"run_id:\s*\w+|run\s+\w+", re.IGNORECASE)


def is_grounded(citation: str) -> tuple[bool, bool]:
    return bool(_TIMESTAMP_RE.search(citation)), bool(_RUN_ID_RE.search(citation))


# --------------------------------------------------------------- demo acts


def act_seed_check() -> bool:
    banner(1, "SEED CHECK  ·  historian SQLite is real")
    from Ai_Agent.tools import get_existing_runs

    raw = get_existing_runs.invoke({})
    data = json.loads(raw)
    runs = data.get("available_runs", [])
    info(f"get_existing_runs -> {runs}")
    if "R1" in runs and "R2" in runs:
        ok(f"historian has {len(runs)} run(s), R1 and R2 present")
        return True
    fail("historian seed missing R1 or R2")
    return False


def act_parquet_ground_truth(client) -> bool:
    banner(2, "PARQUET GROUND TRUTH  ·  UI numbers == simulator parquet")
    from Ai_Agent import twin_data

    city = "Barcelona"
    day = 200
    printers = client.get("/twin/printers", params={"city": city}).json()["printers"]
    printer_id = printers[0]
    info(f"city={city}  printer_id={printer_id}  day={day}")

    http = client.get(
        "/twin/state",
        params={"city": city, "printer_id": printer_id, "day": day, "horizon_min": 0},
    ).json()
    truth = twin_data.get_snapshot(city, printer_id, day, forecast_horizon_min=0)

    print()
    print(bold(f"       {'component':<22} {'HTTP':>10}   {'parquet':>10}   {'status':<12}"))
    all_match = True
    http_by = {c["id"]: c for c in http["components"]}
    for t in truth["components"]:
        h_http = http_by[t["id"]]["healthIndex"]
        h_true = t["healthIndex"]
        match = h_http == h_true
        all_match &= match
        marker = green("==") if match else red("!=")
        print(
            f"       {t['id']:<22} {h_http:>10.4f} {marker} {h_true:>10.4f}   {t['status']:<12}"
        )

    if all_match:
        ok("every healthIndex rendered by the API matches the parquet row")
        return True
    fail("API healthIndex drifted from parquet — not grounded")
    return False


def act_live_agent(client) -> tuple[bool, dict[str, Any] | None]:
    banner(3, "LIVE AGENT REASONING  ·  real Groq LLM, real DB tool, real guardrail")
    thread_id = f"demo-{uuid.uuid4().hex[:8]}"
    query = "Why did the nozzle plate fail in run R2? Cite the exact telemetry row."
    info(f"POST /agent/query  thread_id={thread_id}")
    info(f"query: {query!r}")

    t0 = time.monotonic()
    res = client.post("/agent/query", json={
        "query": query,
        "thread_id": thread_id,
        "run_identifier": "R2",
    })
    elapsed = time.monotonic() - t0

    if res.status_code != 200:
        fail(f"HTTP {res.status_code}: {res.text[:200]}")
        return False, None

    body = res.json()
    info(f"LLM round-trip: {elapsed:.1f}s")

    print()
    print(bold("       REASONING TRACE (each step is a real LangGraph transition):"))
    trace = body.get("reasoning_trace", [])
    called_query_db = False
    for i, step in enumerate(trace, 1):
        kind = step.get("kind", "?")
        label = step.get("label", "")
        content = (step.get("content") or "").strip().replace("\n", " ")
        if len(content) > 140:
            content = content[:137] + "..."
        tag = {
            "system": dim("sys "),
            "user": yellow("usr "),
            "assistant": cyan("ai  "),
            "tool_call": green("CALL"),
            "tool_result": green("RES "),
            "retrieval": yellow("tele"),
            "structured": bold("rep "),
            "meta": dim("meta"),
        }.get(kind, dim(kind[:4]))
        print(f"       {i:>2}. {tag}  {label:<32}  {dim(content)}")
        if kind == "tool_call" and "query_database" in label:
            called_query_db = True

    print()
    print(bold("       FINAL DIAGNOSTIC REPORT:"))
    info(f"severity : {body['severity_indicator']}")
    info(f"priority : {body['priority_level']}")
    info(f"grounded : {body['grounded_text']}")
    info(f"citation : {body['evidence_citation']}")
    info(f"actions  : {body['recommended_actions']}")

    has_ts, has_run = is_grounded(body["evidence_citation"])
    all_good = has_ts and has_run and called_query_db
    print()
    (ok if has_ts else fail)("citation contains ISO timestamp")
    (ok if has_run else fail)("citation contains run identifier")
    (ok if called_query_db else fail)("agent actually invoked query_database tool")
    return all_good, body


def act_watchdog(client) -> bool:
    banner(4, "PROACTIVE WATCHDOG  ·  CRITICAL telemetry -> websocket broadcast")
    run_id = f"DEMO-{uuid.uuid4().hex[:6]}"
    component = "nozzle_plate"
    ts = "2026-04-25T17:30:00"
    info(f"websocket connect /ws/notifications")
    info(f"will POST /telemetry  run_id={run_id}  status=CRITICAL")

    with client.websocket_connect("/ws/notifications") as ws:
        res = client.post("/telemetry", json={
            "timestamp": ts,
            "run_id": run_id,
            "component": component,
            "health_index": 0.07,
            "status": "CRITICAL",
            "temperature": 360.0,
            "pressure": 1.9,
            "fan_speed": 850,
            "metrics": {"clog_percentage": 93.0, "droplet_volume_pl": 1.0},
        })
        if res.status_code != 200:
            fail(f"POST /telemetry failed: {res.status_code} {res.text[:200]}")
            return False
        info(f"telemetry inserted, id={res.json().get('id')}")
        info("waiting up to 120s for watchdog broadcast...")

        deadline = time.monotonic() + 120.0
        msg: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            try:
                msg = ws.receive_json()
                break
            except Exception:
                continue

    if msg is None:
        fail("watchdog never broadcast")
        return False

    print()
    print(bold("       PROACTIVE_ALERT payload:"))
    report = msg.get("report", {})
    info(f"type      : {msg.get('type')}")
    info(f"component : {msg.get('component')}")
    info(f"severity  : {report.get('severity_indicator')}")
    info(f"grounded  : {report.get('grounded_text', '')}")
    info(f"citation  : {report.get('evidence_citation', '')}")

    has_ts, has_run = is_grounded(report.get("evidence_citation", ""))
    (ok if has_ts else fail)("alert citation contains ISO timestamp")
    (ok if has_run else fail)("alert citation contains run identifier")
    return has_ts and has_run


def verdict(results: dict[str, bool]) -> int:
    banner(5, "VERDICT  ·  proof that it is not just visual")
    all_good = True
    for name, passed in results.items():
        (ok if passed else fail)(name)
        all_good &= passed
    print()
    if all_good:
        print(green(bold("  PASS  -  the Digital Co-Pilot is grounded end-to-end.")))
        return 0
    print(red(bold("  FAIL  -  at least one check did not hold.")))
    return 1


def main() -> int:
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except Exception:
        pass

    if not os.getenv("GROQ_API_KEY"):
        print(red("GROQ_API_KEY is not set."))
        print("  Copy .env.example to .env and fill GROQ_API_KEY, then retry.")
        return 2

    from fastapi.testclient import TestClient
    from app import app

    client = TestClient(app)

    results: dict[str, bool] = {}
    results["historian seed present"] = act_seed_check()
    results["parquet == /twin/state numbers"] = act_parquet_ground_truth(client)
    agent_ok, _ = act_live_agent(client)
    results["live agent cites timestamp + run + used DB tool"] = agent_ok
    results["watchdog broadcasts grounded alert"] = act_watchdog(client)

    return verdict(results)


if __name__ == "__main__":
    sys.exit(main())
