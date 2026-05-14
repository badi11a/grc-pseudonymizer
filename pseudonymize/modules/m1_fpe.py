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

    ejemplo_antes = int(customer["c_custkey"].iloc[0])
    customer["c_custkey"] = customer["c_custkey"].apply(cifrar)
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

    orders["o_custkey"] = orders["o_custkey"].apply(cifrar)

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

    stats = {
        "algoritmo": "FF1 NIST SP 800-38G",
        "filas_pk": len(customer),
        "filas_fk": len(orders),
        "join_antes": join_antes,
        "join_despues": join_despues,
        "integridad_ok": join_antes == join_despues,
        "tiempo_s": round(t1 - t0, 3),
    }
    return customer, orders, stats
