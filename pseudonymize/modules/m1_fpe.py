import logging
import time
from typing import Callable

import pandas as pd

from ..crypto import make_cifrar


def run(
    customer: pd.DataFrame,
    orders: pd.DataFrame,
    cfg: dict,
    cifrar: Callable | None = None,
    log: logging.Logger | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    if cifrar is None:
        cifrar = make_cifrar(cfg)
    if log is None:
        log = logging.getLogger("M1")

    log.info("fpe_pk_start", extra={"filas": len(customer)})
    t0 = time.time()

    join_antes = len(customer.merge(orders, left_on="c_custkey", right_on="o_custkey"))

    customer = customer.copy()
    orders = orders.copy()

    # FF1 es una seudopermutación determinista: el mismo valor bajo la misma
    # clave/tweak siempre cifra igual. Como cada FK referencia una PK ya
    # cifrada, cachear por valor original evita recalcular FF1 en la columna
    # FK (normalmente mucho mayor que la PK).
    cache: dict[str, str] = {}

    def cifrar_cached(valor) -> str:
        key = str(valor)
        cached = cache.get(key)
        if cached is None:
            cached = cifrar(valor)
            cache[key] = cached
        return cached

    ejemplo_antes = int(customer["c_custkey"].iloc[0])
    customer["c_custkey"] = customer["c_custkey"].apply(cifrar_cached)
    ejemplo_despues = int(customer["c_custkey"].iloc[0])

    t_pk = round(time.time() - t0, 3)
    log.info("fpe_pk_end", extra={
        "filas": len(customer),
        "ejemplo_antes": ejemplo_antes,
        "ejemplo_despues": ejemplo_despues,
        "tiempo_s": t_pk,
    })

    log.info("fpe_fk_start", extra={"filas": len(orders)})
    t_fk0 = time.time()

    orders["o_custkey"] = orders["o_custkey"].apply(cifrar_cached)

    t_fk = round(time.time() - t_fk0, 3)
    log.info("fpe_fk_end", extra={"filas": len(orders), "tiempo_s": t_fk})

    join_despues = len(customer.merge(orders, left_on="c_custkey", right_on="o_custkey"))
    t1 = time.time()

    diff = join_despues - join_antes
    log.info("join_verificado", extra={
        "filas_antes": join_antes,
        "filas_despues": join_despues,
        "diff": diff,
        "integridad_ok": diff == 0,
    })

    valores_totales = len(customer) + len(orders)
    llamadas_ff1 = len(cache)
    reduccion_pct = (
        round((1 - llamadas_ff1 / valores_totales) * 100, 1) if valores_totales else 0.0
    )
    log.info("cache_ff1", extra={
        "valores_totales": valores_totales,
        "llamadas_ff1": llamadas_ff1,
        "reduccion_pct": reduccion_pct,
    })

    stats = {
        "algoritmo": "FF1 NIST SP 800-38G",
        "filas_pk": len(customer),
        "filas_fk": len(orders),
        "join_antes": join_antes,
        "join_despues": join_despues,
        "integridad_ok": join_antes == join_despues,
        "cache_valores_totales": valores_totales,
        "cache_llamadas_ff1": llamadas_ff1,
        "cache_reduccion_pct": reduccion_pct,
        "tiempo_s": round(t1 - t0, 3),
    }
    return customer, orders, stats
