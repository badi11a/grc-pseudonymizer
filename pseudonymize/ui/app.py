import asyncio
import json
import logging
import re
import threading
import traceback
import uuid
from pathlib import Path
from typing import AsyncGenerator

logging.basicConfig(level=logging.INFO)

import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from pydantic import BaseModel

app = FastAPI(title="grc-pseudonymizer")

_queues: dict[str, asyncio.Queue] = {}
_loops: dict[str, asyncio.AbstractEventLoop] = {}
_reports: dict[str, dict] = {}


class RunRequest(BaseModel):
    db_url: str
    fpe_key: str
    hmac_key: str
    tweak: str = ""
    dry_run: bool = False


class TestDbRequest(BaseModel):
    db_url: str


@app.post("/api/test-db")
async def test_db(req: TestDbRequest):
    from sqlalchemy import create_engine, text
    logging.info("test-db request: %s", req.db_url)
    try:
        engine = create_engine(req.db_url, connect_args={"connect_timeout": 5})
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logging.info("test-db OK")
        return {"ok": True}
    except Exception as exc:
        logging.error("test-db FAILED:\n%s", traceback.format_exc())
        return {"ok": False, "error": str(exc)}


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(
        (Path(__file__).parent / "templates" / "index.html").read_text(encoding="utf-8")
    )


@app.post("/api/run")
async def start_run(req: RunRequest):
    if not re.fullmatch(r"[0-9a-fA-F]{32}", req.fpe_key):
        return Response(
            json.dumps({"detail": "fpe_key must be exactly 32 hexadecimal characters"}),
            status_code=400, media_type="application/json",
        )
    if not req.hmac_key.strip():
        return Response(
            json.dumps({"detail": "hmac_key must not be empty"}),
            status_code=400, media_type="application/json",
        )

    run_id = str(uuid.uuid4())
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    _queues[run_id] = queue
    _loops[run_id] = loop

    cfg = {
        "db_url": req.db_url,
        "fpe": {"key": req.fpe_key, "tweak": req.tweak, "alphabet": "0123456789"},
        "hmac_key": req.hmac_key.encode(),
        "tablas": {
            "customer": {
                "pk": "c_custkey",
                "direct_identifiers": ["c_name", "c_address"],
                "quasi_identifiers": ["c_acctbal", "c_nationkey"],
            },
            "orders": {"fk": {"c_custkey": "o_custkey"}},
        },
    }

    def run_pipeline():
        try:
            _execute(cfg, run_id, dry_run=req.dry_run)
        except Exception as exc:
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {"type": "error", "message": str(exc)},
            )
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    threading.Thread(target=run_pipeline, daemon=True).start()
    return {"run_id": run_id}


@app.get("/api/events/{run_id}")
async def sse_events(run_id: str):
    if run_id not in _queues:
        return Response("run not found", status_code=404)

    queue = _queues[run_id]

    async def generator() -> AsyncGenerator[str, None]:
        try:
            while True:
                event = await queue.get()
                if event is None:
                    yield "data: [DONE]\n\n"
                    break
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/report/{run_id}")
async def get_report(run_id: str):
    if run_id not in _reports:
        return Response("report not found", status_code=404)
    return _reports[run_id]


def _execute(cfg: dict, run_id: str, dry_run: bool = False) -> None:
    import time

    import pandas as pd
    from sqlalchemy import create_engine

    from pseudonymize import report as report_mod
    from pseudonymize.crypto import make_cifrar
    from pseudonymize.logger import get_logger
    from pseudonymize.modules import m0_topology, m1_fpe, m2_copulas, m3_faker

    loop = _loops[run_id]
    queue = _queues[run_id]

    # Structured JSON logger — same run_id used as correlation key for SIEM
    short_id = run_id[:8]
    log = get_logger(short_id, "pipeline")

    def emit(event: dict) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, event)

    engine = create_engine(cfg["db_url"])
    cifrar = make_cifrar(cfg)
    trace = report_mod.new_trace()

    log.info("pipeline_start", extra={"dry_run": dry_run, "source": "ui"})
    emit({"type": "start", "run_id": run_id, "dry_run": dry_run})

    # M0 runs ahead of the UI's three-card progress view (no card is rendered
    # for it in index.html) but its result is logged and recorded in the
    # audit trace like the CLI path.
    log.info("m0_start")
    t_m0_0 = time.time()
    topology = m0_topology.get_processing_order(engine)
    orden_tablas = [t["table"] for t in topology if "table" in t]
    ciclos_rotos = next((t["cycle_breaks"] for t in topology if "cycle_breaks" in t), [])
    m0_stats = {
        "algoritmo": "FK topological sort (networkx)",
        "orden": orden_tablas,
        "ciclos_rotos": ciclos_rotos,
        "tiempo_s": round(time.time() - t_m0_0, 3),
    }
    trace["modulos"]["M0"] = m0_stats
    log.info("m0_end", extra={
        "orden": orden_tablas,
        "ciclos_rotos": ciclos_rotos,
        "tiempo_s": m0_stats["tiempo_s"],
    })

    customer = pd.read_sql("SELECT * FROM customer", engine)
    orders = pd.read_sql("SELECT o_orderkey, o_custkey FROM orders", engine)

    emit({
        "type": "module_start",
        "module": "M1",
        "label": "Format-Preserving Encryption (FF1)",
        "detail": f"{len(customer):,} PKs · {len(orders):,} FKs",
    })
    log.info("m1_start", extra={"filas_pk": len(customer), "filas_fk": len(orders)})
    customer, orders, m1_stats = m1_fpe.run(customer, orders, cfg, cifrar,
                                             log=get_logger(short_id, "M1"))
    trace["modulos"]["M1"] = m1_stats
    log.info("m1_end", extra={
        "filas_pk": m1_stats["filas_pk"],
        "filas_fk": m1_stats["filas_fk"],
        "integridad_ok": m1_stats["integridad_ok"],
        "tiempo_s": m1_stats["tiempo_s"],
    })
    emit({"type": "module_done", "module": "M1", "stats": m1_stats, "ok": m1_stats["integridad_ok"]})

    emit({
        "type": "module_start",
        "module": "M3",
        "label": "HMAC-SHA256 + Faker substitution",
        "detail": f"{len(customer):,} direct identifiers",
    })
    log.info("m3_start", extra={"filas": len(customer)})
    customer, m3_stats = m3_faker.run(customer, cfg, log=get_logger(short_id, "M3"))
    trace["modulos"]["M3"] = m3_stats
    log.info("m3_end", extra={"filas": m3_stats["filas"], "tiempo_s": m3_stats["tiempo_s"]})
    emit({"type": "module_done", "module": "M3", "stats": m3_stats, "ok": True})

    emit({
        "type": "module_start",
        "module": "M2",
        "label": "Gaussian Copula synthesis",
        "detail": f"{len(customer):,} quasi-identifiers",
    })
    log.info("m2_start", extra={"filas": len(customer)})
    customer, m2_stats = m2_copulas.run(customer, engine, cifrar, cfg,
                                        log=get_logger(short_id, "M2"))
    trace["modulos"]["M2"] = m2_stats
    log.info("m2_end", extra={
        "filas": m2_stats["filas"],
        "frobenius": m2_stats["frobenius"],
        "tiempo_s": m2_stats["tiempo_s"],
    })
    emit({"type": "module_done", "module": "M2", "stats": m2_stats, "ok": m2_stats["frobenius"] < 0.5})

    trace["dry_run"] = dry_run
    trace["resultado_global"] = "SIMULACRO" if dry_run else ("OK" if m1_stats["integridad_ok"] else "FALLO")
    trace["tiempo_total_s"] = round(
        sum(m["tiempo_s"] for m in trace["modulos"].values()), 3
    )

    log.info("pipeline_end", extra={
        "resultado_global": trace["resultado_global"],
        "tiempo_total_s": trace["tiempo_total_s"],
        "dry_run": dry_run,
        "source": "ui",
    })
    _reports[run_id] = trace
    emit({"type": "complete", "trace": trace})


def main():
    uvicorn.run("pseudonymize.ui.app:app", host="0.0.0.0", port=8000, reload=False)
