"""Tests for the FF1 memoization cache in m1_fpe.run()."""
from __future__ import annotations

import pandas as pd

from pseudonymize.modules import m1_fpe


def _make_data(n_customers: int, orders_per_customer: int):
    customer = pd.DataFrame({"c_custkey": range(1, n_customers + 1)})
    orders = pd.DataFrame({
        "o_orderkey": range(1, n_customers * orders_per_customer + 1),
        "o_custkey": [c for c in range(1, n_customers + 1) for _ in range(orders_per_customer)],
    })
    return customer, orders


def test_cache_avoids_redundant_calls():
    customer, orders = _make_data(n_customers=15, orders_per_customer=10)
    calls = {"n": 0}

    def fake_cifrar(v):
        calls["n"] += 1
        return str(1_000_000 + int(v)).zfill(6)

    _, _, stats = m1_fpe.run(customer, orders, cfg={}, cifrar=fake_cifrar)

    # Every FK value already has a cached ciphertext from the PK pass, so no
    # extra FF1 calls should occur for the FK column.
    assert calls["n"] == 15
    assert stats["cache_llamadas_ff1"] == 15
    assert stats["cache_valores_totales"] == 15 + 150
    assert stats["cache_reduccion_pct"] == round((1 - 15 / 165) * 100, 1)


def test_cache_preserves_join_integrity():
    customer, orders = _make_data(n_customers=30, orders_per_customer=5)

    def fake_cifrar(v):
        return str(1_000_000 + int(v))

    customer_out, orders_out, stats = m1_fpe.run(customer, orders, cfg={}, cifrar=fake_cifrar)

    assert stats["integridad_ok"] is True
    assert stats["join_antes"] == stats["join_despues"] == 150
    # Every original custkey must map to the same ciphertext everywhere it appears.
    assert set(customer_out["c_custkey"]) == set(orders_out["o_custkey"])
