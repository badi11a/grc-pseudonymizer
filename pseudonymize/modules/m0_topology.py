"""
m0_topology – automatic FK dependency graph inference.

Queries the SQL catalog (INFORMATION_SCHEMA for PostgreSQL, SQLAlchemy
reflection for other dialects) to build a directed acyclic graph of table
dependencies and returns tables in topological (root-first) order.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

import networkx as nx
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


def _get_fk_relations(engine: Engine) -> list[dict[str, str]]:
    if engine.dialect.name == "postgresql":
        return _get_fk_relations_pg(engine)
    return _get_fk_relations_reflect(engine)


def _get_fk_relations_pg(engine: Engine) -> list[dict[str, str]]:
    """Query INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS + KEY_COLUMN_USAGE (PostgreSQL)."""
    sql = text("""
        SELECT
            kcu_fk.table_name  AS fk_table,
            kcu_fk.column_name AS fk_col,
            kcu_pk.table_name  AS ref_table,
            kcu_pk.column_name AS ref_col
        FROM information_schema.referential_constraints rc
        JOIN information_schema.key_column_usage kcu_fk
            ON  kcu_fk.constraint_name   = rc.constraint_name
            AND kcu_fk.constraint_schema = rc.constraint_schema
        JOIN information_schema.key_column_usage kcu_pk
            ON  kcu_pk.constraint_name   = rc.unique_constraint_name
            AND kcu_pk.constraint_schema = rc.unique_constraint_schema
            AND kcu_pk.ordinal_position  = kcu_fk.position_in_unique_constraint
        WHERE rc.constraint_schema = current_schema()
        ORDER BY kcu_fk.table_name, kcu_fk.ordinal_position
    """)
    with engine.connect() as conn:
        rows = conn.execute(sql).mappings().all()
    return [dict(r) for r in rows]


def _get_fk_relations_reflect(engine: Engine) -> list[dict[str, str]]:
    """SQLAlchemy reflection fallback – works with SQLite and other dialects."""
    insp = inspect(engine)
    relations: list[dict[str, str]] = []
    for table in insp.get_table_names():
        for fk in insp.get_foreign_keys(table):
            ref_table = fk["referred_table"]
            for fk_col, ref_col in zip(
                fk["constrained_columns"], fk["referred_columns"]
            ):
                relations.append(
                    {
                        "fk_table": table,
                        "fk_col": fk_col,
                        "ref_table": ref_table,
                        "ref_col": ref_col,
                    }
                )
    return relations


def _get_pk_map(engine: Engine) -> dict[str, str | None]:
    """Return {table_name: first_pk_column} via reflection."""
    insp = inspect(engine)
    return {
        t: (insp.get_pk_constraint(t).get("constrained_columns") or [None])[0]
        for t in insp.get_table_names()
    }


def _cardinality(engine: Engine, table: str, col: str) -> int:
    """COUNT(DISTINCT col) in table – used to rank FK edges when breaking cycles."""
    with engine.connect() as conn:
        return (
            conn.execute(
                text(f'SELECT COUNT(DISTINCT "{col}") FROM "{table}"')
            ).scalar()
            or 0
        )


def _break_one_cycle(
    graph: nx.DiGraph,
    engine: Engine,
    edge_meta: list[tuple[str, str, str, str]],
) -> dict[str, str | None]:
    """Remove the lowest-cardinality FK edge in a detected cycle and return a record of the cut."""
    cycle_edges = nx.find_cycle(graph)

    min_card: int | None = None
    chosen_src, chosen_dst, chosen_col = cycle_edges[0][0], cycle_edges[0][1], None

    for src, dst in cycle_edges:
        fk_col = next(
            (m[2] for m in edge_meta if m[0] == src and m[1] == dst), None
        )
        card = _cardinality(engine, dst, fk_col) if fk_col else 0
        if min_card is None or card < min_card:
            min_card, chosen_src, chosen_dst, chosen_col = card, src, dst, fk_col

    graph.remove_edge(chosen_src, chosen_dst)
    logger.warning(
        "Cycle break: removed edge %s → %s (fk_col=%s, cardinality=%s)",
        chosen_src,
        chosen_dst,
        chosen_col,
        min_card,
    )
    return {"from": chosen_src, "to": chosen_dst, "fk_col": chosen_col}


def get_processing_order(engine: Engine) -> list[dict[str, Any]]:
    """Infer FK dependency graph and return tables in topological order.

    Returns a list of dicts::

        [
            {
                "table": str,
                "pk": str | None,
                "fks": [{"fk_col": str, "ref_table": str, "ref_col": str}, ...],
            },
            ...
            # Appended only when cycles were detected and broken:
            {"cycle_breaks": [{"from": str, "to": str, "fk_col": str | None}, ...]},
        ]

    Root tables (no FK dependencies) appear first. If the schema contains
    FK cycles (NetworkXUnfeasible), the edge with the lowest
    COUNT(DISTINCT fk_col) cardinality is removed until the graph is acyclic.
    All removals are recorded in the ``cycle_breaks`` entry.
    """
    relations = _get_fk_relations(engine)
    pk_map = _get_pk_map(engine)

    graph: nx.DiGraph = nx.DiGraph()
    graph.add_nodes_from(pk_map.keys())

    fks_by_table: dict[str, list[dict[str, str]]] = defaultdict(list)
    # (ref_table, fk_table, fk_col, ref_col) – parallel to graph edges
    edge_meta: list[tuple[str, str, str, str]] = []

    for r in relations:
        fks_by_table[r["fk_table"]].append(
            {
                "fk_col": r["fk_col"],
                "ref_table": r["ref_table"],
                "ref_col": r["ref_col"],
            }
        )
        graph.add_edge(r["ref_table"], r["fk_table"])
        edge_meta.append((r["ref_table"], r["fk_table"], r["fk_col"], r["ref_col"]))

    cycle_breaks: list[dict[str, str | None]] = []

    while not nx.is_directed_acyclic_graph(graph):
        try:
            cycle_breaks.append(_break_one_cycle(graph, engine, edge_meta))
        except nx.exception.NetworkXNoCycle:
            break

    order = list(nx.topological_sort(graph))

    result: list[dict[str, Any]] = [
        {
            "table": table,
            "pk": pk_map.get(table),
            "fks": list(fks_by_table.get(table, [])),
        }
        for table in order
    ]

    if cycle_breaks:
        result.append({"cycle_breaks": cycle_breaks})

    return result
