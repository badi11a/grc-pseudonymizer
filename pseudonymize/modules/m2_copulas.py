import logging
import time
import warnings
from typing import Callable

import numpy as np
import pandas as pd
from copulas.multivariate import GaussianMultivariate
from sqlalchemy import Engine

warnings.filterwarnings("ignore")


def run(
    customer: pd.DataFrame,
    engine: Engine,
    cifrar: Callable,
    cfg: dict,
    log: logging.Logger | None = None,
) -> tuple[pd.DataFrame, dict]:
    if log is None:
        log = logging.getLogger("M2")

    t0 = time.time()

    df_qid = pd.read_sql(
        "SELECT c_custkey, c_acctbal, c_nationkey FROM customer", engine
    )
    df_qid["c_custkey"] = df_qid["c_custkey"].apply(cifrar)

    numeric_cols = ["c_acctbal", "c_nationkey"]
    sample_size = min(2000, len(df_qid))

    log.info("copula_fit_start", extra={"sample_size": sample_size, "total_filas": len(df_qid)})
    t_fit0 = time.time()

    df_fit = df_qid[numeric_cols].sample(n=sample_size, random_state=42)
    model = GaussianMultivariate()
    model.fit(df_fit)

    t_fit = round(time.time() - t_fit0, 3)
    log.info("copula_fit_end", extra={"sample_size": sample_size, "tiempo_s": t_fit})

    df_sint_numeric = model.sample(len(df_qid))

    df_sint_numeric = df_sint_numeric.replace([np.inf, -np.inf], np.nan)
    df_sint = df_qid[["c_custkey"]].copy().reset_index(drop=True)
    df_sint["c_acctbal"] = df_sint_numeric["c_acctbal"].fillna(df_qid["c_acctbal"].median()).values
    df_sint["c_nationkey"] = (
        df_sint_numeric["c_nationkey"]
        .round()
        .clip(0, 24)
        .fillna(0)
        .astype(int)
        .values
    )

    customer = customer.merge(
        df_sint[["c_custkey", "c_acctbal", "c_nationkey"]],
        on="c_custkey",
        how="left",
        suffixes=("_old", ""),
    )
    customer.drop(columns=["c_acctbal_old", "c_nationkey_old"], errors="ignore", inplace=True)

    cols = ["c_acctbal", "c_nationkey"]
    corr_o = df_qid[cols].corr(method="spearman").values
    corr_s = df_sint[cols].corr(method="spearman").values
    frobenius = round(float(np.linalg.norm(corr_o - corr_s, "fro")), 6)
    t1 = time.time()

    log.info("copula_sample_end", extra={
        "filas": len(df_sint),
        "frobenius": frobenius,
        "tiempo_s": round(t1 - t0, 3),
    })

    stats = {
        "tecnica": "GaussianMultivariate copulas",
        "columnas": cols,
        "filas": len(df_sint),
        "frobenius": frobenius,
        "fallback": False,
        "tiempo_s": round(t1 - t0, 3),
    }
    return customer, stats
