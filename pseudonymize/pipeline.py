import sys
import time

import pandas as pd
from sqlalchemy import create_engine

from . import config as cfg_mod
from . import report
from .crypto import make_cifrar
from .logger import get_logger
from .modules import m0_topology, m1_fpe, m2_copulas, m3_faker


def run(config_path: str, db_url: str | None = None, dry_run: bool = False) -> dict:
    cfg = cfg_mod.load(config_path, db_url)
    engine = create_engine(cfg["db_url"])
    cifrar = make_cifrar(cfg)

    trace = report.new_trace()
    run_id = trace["run_id"][:8]
    log = get_logger(run_id, "pipeline")

    # ── Banner → stderr (human-readable, not captured by SIEM) ──────────────
    print("=" * 55, file=sys.stderr)
    print("  grc-pseudonymizer — Framework de seudonimización batch", file=sys.stderr)
    print(f"  Run ID: {run_id}...", file=sys.stderr)
    print("=" * 55, file=sys.stderr)

    log.info("pipeline_start", extra={"dry_run": dry_run})

    # ── M0 ───────────────────────────────────────────────────────────────────
    print("\n[M0] Inferencia de topología FK", file=sys.stderr)
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

    print(f"  Orden de procesamiento: {' → '.join(orden_tablas)}", file=sys.stderr)
    if ciclos_rotos:
        print(f"  Ciclos FK detectados y rotos: {ciclos_rotos}", file=sys.stderr)
    log.info("m0_end", extra={
        "orden": orden_tablas,
        "ciclos_rotos": ciclos_rotos,
        "tiempo_s": m0_stats["tiempo_s"],
    })

    if "customer" in orden_tablas and "orders" in orden_tablas:
        if orden_tablas.index("customer") > orden_tablas.index("orders"):
            log.warning("m0_orden_inesperado", extra={
                "detalle": "el catálogo indica 'orders' antes que 'customer'; "
                           "el orquestador aún procesa en el orden fijo customer→orders",
            })

    customer = pd.read_sql("SELECT * FROM customer", engine)
    orders = pd.read_sql("SELECT o_orderkey, o_custkey FROM orders", engine)

    # ── M1 ───────────────────────────────────────────────────────────────────
    print("\n[M1] Cifrado FPE (FF1) — PK y FK", file=sys.stderr)
    log.info("m1_start", extra={"filas_pk": len(customer), "filas_fk": len(orders)})

    customer, orders, m1_stats = m1_fpe.run(customer, orders, cfg, cifrar,
                                             log=get_logger(run_id, "M1"))
    trace["modulos"]["M1"] = m1_stats
    integridad_ok = m1_stats["integridad_ok"]

    print(f"  JOIN antes:   {m1_stats['join_antes']:,} filas", file=sys.stderr)
    print(f"  JOIN después: {m1_stats['join_despues']:,} filas", file=sys.stderr)
    print(f"  Integridad referencial: {'✓ OK' if integridad_ok else '✗ FALLO'}",
          file=sys.stderr)
    print(
        f"  Caché FF1: {m1_stats['cache_llamadas_ff1']:,} llamadas de "
        f"{m1_stats['cache_valores_totales']:,} valores "
        f"({m1_stats['cache_reduccion_pct']}% reducción)",
        file=sys.stderr,
    )

    log.info("m1_end", extra={
        "filas_pk": m1_stats["filas_pk"],
        "filas_fk": m1_stats["filas_fk"],
        "integridad_ok": integridad_ok,
        "tiempo_s": m1_stats["tiempo_s"],
    })

    # ── M3 ───────────────────────────────────────────────────────────────────
    print("\n[M3] Sustitución semántica (HMAC + Faker)", file=sys.stderr)
    log.info("m3_start", extra={"filas": len(customer)})

    customer, m3_stats = m3_faker.run(customer, cfg,
                                      log=get_logger(run_id, "M3"))
    trace["modulos"]["M3"] = m3_stats

    print(
        f"  {m3_stats['filas']:,} nombres y direcciones seudonimizados "
        f"en {m3_stats['tiempo_s']:.2f}s",
        file=sys.stderr,
    )
    print(
        f"  Ejemplo: c_custkey={customer['c_custkey'].iloc[0]} → {customer['c_name'].iloc[0]}",
        file=sys.stderr,
    )

    log.info("m3_end", extra={
        "filas": m3_stats["filas"],
        "tiempo_s": m3_stats["tiempo_s"],
    })

    # ── M2 ───────────────────────────────────────────────────────────────────
    print("\n[M2] Cópulas gaussianas (SDV) — QIDs", file=sys.stderr)
    log.info("m2_start", extra={"filas": len(customer)})

    customer, m2_stats = m2_copulas.run(customer, engine, cifrar, cfg,
                                        log=get_logger(run_id, "M2"))
    trace["modulos"]["M2"] = m2_stats
    frobenius = m2_stats["frobenius"]

    print(
        f"  {m2_stats['filas']:,} filas sintéticas generadas en {m2_stats['tiempo_s']:.2f}s",
        file=sys.stderr,
    )
    print(f"  Norma de Frobenius: {frobenius}", file=sys.stderr)

    log.info("m2_end", extra={
        "filas": m2_stats["filas"],
        "frobenius": frobenius,
        "tiempo_s": m2_stats["tiempo_s"],
    })

    # ── Trace & summary ──────────────────────────────────────────────────────
    trace["dry_run"] = dry_run
    trace["resultado_global"] = "SIMULACRO" if dry_run else ("OK" if integridad_ok else "FALLO")
    trace["tiempo_total_s"] = round(
        sum(m["tiempo_s"] for m in trace["modulos"].values()), 3
    )

    print("\n" + "=" * 55, file=sys.stderr)
    print("  RESUMEN FINAL", file=sys.stderr)
    print("=" * 55, file=sys.stderr)
    print(f"  M0 orden de procesamiento:  {' → '.join(orden_tablas)}", file=sys.stderr)
    print(f"  M1 integridad referencial: {'✓' if integridad_ok else '✗'}", file=sys.stderr)
    print("  M3 determinismo:            ✓", file=sys.stderr)
    print(f"  M2 Frobenius:               {frobenius}", file=sys.stderr)
    print(f"  Tiempo total:               {trace['tiempo_total_s']}s", file=sys.stderr)

    if dry_run:
        print("  MODO SIMULACRO: informe no guardado en disco", file=sys.stderr)
    else:
        report_path = "informe_trazabilidad.json"
        report.save(trace, report_path)
        print(f"  Informe guardado:           {report_path}", file=sys.stderr)

    print("=" * 55, file=sys.stderr)

    log.info("pipeline_end", extra={
        "resultado_global": trace["resultado_global"],
        "tiempo_total_s": trace["tiempo_total_s"],
        "dry_run": dry_run,
    })

    return trace
