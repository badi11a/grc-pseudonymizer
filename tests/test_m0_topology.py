"""Tests for m0_topology using an in-memory SQLite database."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, text

from pseudonymize.modules import m0_topology
from pseudonymize.modules.m0_topology import get_processing_order


@pytest.fixture
def engine():
    """SQLite in-memory DB with a simple parent→child FK relationship."""
    eng = create_engine("sqlite:///:memory:")
    with eng.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys = ON"))
        conn.execute(
            text(
                """
                CREATE TABLE customer (
                    id   INTEGER PRIMARY KEY,
                    name TEXT NOT NULL
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE orders (
                    id          INTEGER PRIMARY KEY,
                    customer_id INTEGER REFERENCES customer(id),
                    amount      REAL
                )
                """
            )
        )
    return eng


# ---------------------------------------------------------------------------
# Basic topology
# ---------------------------------------------------------------------------


def test_parent_comes_before_child(engine):
    result = get_processing_order(engine)
    tables = [r["table"] for r in result if "table" in r]
    assert "customer" in tables
    assert "orders" in tables
    assert tables.index("customer") < tables.index("orders")


def test_root_table_has_no_fks(engine):
    result = get_processing_order(engine)
    customer = next(r for r in result if r.get("table") == "customer")
    assert customer["fks"] == []


def test_child_fk_metadata(engine):
    result = get_processing_order(engine)
    orders = next(r for r in result if r.get("table") == "orders")
    assert len(orders["fks"]) == 1
    fk = orders["fks"][0]
    assert fk["fk_col"] == "customer_id"
    assert fk["ref_table"] == "customer"
    assert fk["ref_col"] == "id"


def test_pk_populated(engine):
    result = get_processing_order(engine)
    by_table = {r["table"]: r for r in result if "table" in r}
    assert by_table["customer"]["pk"] == "id"
    assert by_table["orders"]["pk"] == "id"


def test_no_cycle_breaks_for_acyclic_schema(engine):
    result = get_processing_order(engine)
    assert not any("cycle_breaks" in r for r in result)


# ---------------------------------------------------------------------------
# Cycle detection and breaking
# ---------------------------------------------------------------------------


def test_cycle_is_detected_and_broken(engine):
    """Inject a cyclic FK structure and verify get_processing_order resolves it."""
    cyclic_relations = [
        {"fk_table": "a", "fk_col": "b_id", "ref_table": "b", "ref_col": "id"},
        {"fk_table": "b", "fk_col": "a_id", "ref_table": "a", "ref_col": "id"},
    ]
    fake_pk_map = {"a": "id", "b": "id"}

    with (
        patch.object(m0_topology, "_get_fk_relations", return_value=cyclic_relations),
        patch.object(m0_topology, "_get_pk_map", return_value=fake_pk_map),
        patch.object(m0_topology, "_cardinality", return_value=0),
    ):
        result = get_processing_order(engine)

    tables = [r["table"] for r in result if "table" in r]
    assert set(tables) == {"a", "b"}, "Both tables must still appear in output"

    cycle_entry = next((r for r in result if "cycle_breaks" in r), None)
    assert cycle_entry is not None, "cycle_breaks entry must be present"
    breaks = cycle_entry["cycle_breaks"]
    assert len(breaks) >= 1
    cut = breaks[0]
    assert "from" in cut and "to" in cut and "fk_col" in cut


def test_cycle_break_selects_lower_cardinality_edge(engine):
    """When two edges form a cycle, the one with lower cardinality should be cut."""
    cyclic_relations = [
        {"fk_table": "x", "fk_col": "y_id", "ref_table": "y", "ref_col": "id"},
        {"fk_table": "y", "fk_col": "x_id", "ref_table": "x", "ref_col": "id"},
    ]
    fake_pk_map = {"x": "id", "y": "id"}

    # y→x edge (fk_table=x, fk_col=y_id) has cardinality 5
    # x→y edge (fk_table=y, fk_col=x_id) has cardinality 1  ← should be cut
    def fake_cardinality(_engine, table, col):
        return 1 if (table == "y" and col == "x_id") else 5

    with (
        patch.object(m0_topology, "_get_fk_relations", return_value=cyclic_relations),
        patch.object(m0_topology, "_get_pk_map", return_value=fake_pk_map),
        patch.object(m0_topology, "_cardinality", side_effect=fake_cardinality),
    ):
        result = get_processing_order(engine)

    cycle_entry = next((r for r in result if "cycle_breaks" in r), None)
    assert cycle_entry is not None
    cut = cycle_entry["cycle_breaks"][0]
    # The cut edge goes from x → y (ref_table=x means graph edge x→y)
    assert cut["fk_col"] == "x_id"
