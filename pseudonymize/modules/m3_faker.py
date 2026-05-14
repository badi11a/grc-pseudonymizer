import hashlib
import hmac
import logging
import time

import pandas as pd
from faker import Faker


def run(
    customer: pd.DataFrame,
    cfg: dict,
    log: logging.Logger | None = None,
) -> tuple[pd.DataFrame, dict]:
    if log is None:
        log = logging.getLogger("M3")

    hmac_key = cfg["hmac_key"]
    key = hmac_key if isinstance(hmac_key, bytes) else hmac_key.encode()
    fake = Faker("es_ES")

    def pseudo_nombre(v: str) -> str:
        d = hmac.new(key, str(v).encode(), hashlib.sha256).digest()
        fake.seed_instance(int.from_bytes(d[:4], "big"))
        return fake.name()

    def pseudo_direccion(v: str) -> str:
        d = hmac.new(key, str(v).encode(), hashlib.sha256).digest()
        fake.seed_instance(int.from_bytes(d[:4], "big"))
        return fake.address().replace("\n", ", ")

    log.info("sustitucion_start", extra={"filas": len(customer)})
    t0 = time.time()

    customer = customer.copy()
    customer["c_name"] = customer["c_name"].apply(pseudo_nombre)
    customer["c_address"] = customer["c_address"].apply(pseudo_direccion)

    t1 = time.time()
    tiempo_s = round(t1 - t0, 3)

    log.info("sustitucion_end", extra={"filas": len(customer), "tiempo_s": tiempo_s})

    stats = {
        "tecnica": "HMAC-SHA256 + Faker es_ES",
        "columnas": ["c_name", "c_address"],
        "filas": len(customer),
        "tiempo_s": tiempo_s,
    }
    return customer, stats
