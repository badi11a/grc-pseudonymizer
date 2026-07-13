# grc-pseudonymizer

Framework de seudonimización batch para bases de datos relacionales con interfaz web y trazabilidad normativa, desarrollado como prueba de concepto para un Trabajo de Fin de Máster en ingeniería de datos con preservación de privacidad.

Procesa 15.000 registros de clientes y 150.000 pedidos preservando la integridad referencial, la utilidad estadística y la trazabilidad normativa completa — con cero pérdida de datos.

---

## Live Demo

A live demo showing a real pipeline execution on the TPC-H SF 0.1 dataset is available at:

https://grc-pseudonymizer-demo.vercel.app/

The demo page (`demo/index.html`) is automatically synced to the demo repository by the `sync-demo` GitHub Actions workflow on every push to `main`.

---

## The problem it solves

Organisations that share or analyse personal data face a hard constraint: **raw data cannot leave the privacy perimeter**, but anonymising it naively destroys the statistical properties that make it useful.

The canonical failure modes are:

| Naive approach | What breaks |
|---|---|
| Hash PK/FK blindly | Foreign-key joins fail; downstream analytics are broken |
| Mask names with random values | Non-deterministic — same person gets a different alias each run |
| Add Gaussian noise to quasi-identifiers | Correlation structure between variables collapses |

This pipeline solves all three simultaneously through a modular architecture, each module targeting a different category of personal data.

---

## Features at a glance

- **M1 — Format-Preserving Encryption (FF1, NIST SP 800-38G)** of primary and foreign keys, with referential-integrity verification on every run.
- **M3 — Deterministic semantic substitution** of direct identifiers (names, addresses) via HMAC-SHA256-seeded Faker (`es_ES`).
- **M2 — Gaussian copula synthesis** of quasi-identifiers, with Frobenius-norm quality measurement.
- **M0 — Automatic FK topology discovery** (standalone module): infers the table dependency graph from the SQL catalog and returns a safe processing order, breaking FK cycles when needed.
- **Web UI** (FastAPI + Server-Sent Events): structured connection form, connection test, real-time per-module progress, dry-run mode, and in-browser audit report preview and download.
- **REST API**: run the pipeline, stream progress events, test database connectivity, and retrieve audit reports programmatically.
- **Structured JSON logging for SIEM**: every pipeline event is emitted as one JSON line on stdout with a `run_id` correlation key; human-readable output goes to stderr.
- **Dry-run mode**: executes the full pipeline in-memory and marks the result as `SIMULACRO` without persisting the audit report.
- **Machine-readable audit report** (`informe_trazabilidad.json`) referencing RGPD Art. 32, EDPB 01/2025 and ISO 27001:2022 A.8.33.
- **Docker support**: one-command demo with a TPC-H PostgreSQL database.

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                 grc-pseudonymizer Web UI                  │
│        FastAPI · Server-Sent Events · localhost:8000      │
│   /api/run · /api/events · /api/report · /api/test-db    │
└───────────────────────┬──────────────────────────────────┘
                        │ HTTP / SSE
┌───────────────────────▼──────────────────────────────────┐
│                 grc-pseudonymizer CLI                     │
│           --config  ·  --db-url  ·  $DB_URL               │
└───────────────────┬──────────────────────────────────────┘
                    │
        ┌───────────▼───────────┐      ┌──────────────────┐
        │    pipeline.py        │─────▶│ logger.py        │
        │ orchestrates M1→M3→M2 │      │ JSON lines (SIEM)│
        └──┬────────┬───────┬───┘      └──────────────────┘
           │        │       │
     ┌─────▼──┐ ┌───▼───┐ ┌─▼───────┐   ┌──────────────────┐
     │   M1   │ │  M3   │ │   M2    │   │  M0 (standalone) │
     │  FPE   │ │ HMAC  │ │ Copulas │   │  FK topology     │
     └────────┘ └───────┘ └─────────┘   └──────────────────┘
```

### M1 — Format-Preserving Encryption on primary and foreign keys

**Algorithm:** FF1 (NIST SP 800-38G), via `fastfpe`

Primary keys (`c_custkey`) and their corresponding foreign keys (`o_custkey`) are encrypted with AES-FF1, a NIST-standardised format-preserving cipher over a decimal alphabet (values are zero-padded to 6 digits). A 6-digit integer in produces a 6-digit integer out, so all foreign-key joins continue to work on the pseudonymised dataset without any schema changes.

**Guarantee verified at runtime:** the row count of `customer JOIN orders` is compared before and after encryption; the audit report records `join_antes`, `join_despues` and the resulting `integridad_ok` flag (150,000 / 150,000 in the reference run).

### M3 — Deterministic semantic substitution of direct identifiers

**Algorithm:** HMAC-SHA256 + Faker (locale `es_ES`)

Free-text fields that directly identify a person — names (`c_name`) and postal addresses (`c_address`) — are replaced with realistic synthetic values generated by seeding Faker with the first 4 bytes of an HMAC-SHA256 digest of the original value. The same input always produces the same output across runs (deterministic), but the mapping is one-way without the secret key.

**Effect:** `"Customer#000000001"` → `"Sofía Miranda Belda"` — consistent across every pipeline execution.

### M2 — Gaussian copula synthesis for quasi-identifiers

**Algorithm:** `copulas.GaussianMultivariate`

Quasi-identifiers — numerical fields that are not directly identifying but can enable re-identification when combined (`c_acctbal`, `c_nationkey`) — are replaced with statistically equivalent synthetic values. A Gaussian copula model is fitted on a 2,000-row sample of the real data and used to generate a full-size replacement dataset that preserves the joint distribution and inter-variable correlations. Synthetic nation keys are rounded and clipped to the valid domain; non-finite values fall back to the median.

**Quality metric:** Frobenius norm of the difference between the original and synthetic Spearman correlation matrices. A value close to zero means the multivariate dependency structure is preserved.

Reference run: **Frobenius = 0.0238** (threshold < 0.5).

### M0 — Automatic FK topology discovery (standalone module)

**Module:** `pseudonymize/modules/m0_topology.py` · `get_processing_order(engine)`

M0 infers the foreign-key dependency graph of a schema directly from the database catalog — `INFORMATION_SCHEMA` on PostgreSQL, SQLAlchemy reflection on other dialects (e.g. SQLite) — and returns the tables in topological (root-first) processing order, together with each table's PK and FK metadata. If the schema contains FK **cycles**, the edge with the lowest `COUNT(DISTINCT fk_col)` cardinality is removed until the graph is acyclic, and every cut is recorded in a `cycle_breaks` entry.

**Status:** implemented and unit-tested (`tests/test_m0_topology.py`, in-memory SQLite), but **not yet wired into the orchestrator** — it is the building block for generalising the pipeline beyond the two-table demo schema (see *Current scope* below).

---

## Web UI

`pseudonymize-ui` starts a FastAPI server on **http://localhost:8000** with a single-page interface:

- **Structured connection form** — individual **Host**, **Port**, **User**, **Password** and **Database** fields (no raw connection string), pre-filled for the Docker demo database.
- **Probar conexión** — a connection-test button that validates the database credentials (`POST /api/test-db`, `SELECT 1` with a 5 s timeout) before launching anything.
- **Key handling** — the FPE key and HMAC secret are entered in masked (password) fields; the FPE key is validated as exactly 32 hexadecimal characters both in the browser and server-side.
- **Dry-run toggle** — runs the complete pipeline without persisting the audit report; the result is marked `SIMULACRO`.
- **Real-time progress** — each module's start, per-module metrics and completion are streamed to the browser over Server-Sent Events.
- **Audit report preview and download** — when the run completes, the UI shows a preview of `informe_trazabilidad.json` and offers a **Descargar informe de auditoría** button. In UI mode the report is served via the API (`GET /api/report/{run_id}`) and downloaded from the browser — it is *not* written to disk on the server.

### REST API

| Method & path | Purpose |
|---|---|
| `POST /api/run` | Launch a pipeline run. Body: `db_url`, `fpe_key` (32-hex, validated), `hmac_key`, optional `tweak`, `dry_run`. Returns `run_id`. |
| `GET /api/events/{run_id}` | Server-Sent Events stream: `start`, `module_start`, `module_done` (with per-module stats), `complete` / `error`, terminated by `[DONE]`. |
| `GET /api/report/{run_id}` | Retrieve the audit report (JSON) for a completed run. |
| `POST /api/test-db` | Test database connectivity. Returns `{ok: true}` or `{ok: false, error}`. |

---

## Structured logging (SIEM integration)

Every pipeline event — from both the CLI and the UI — is emitted by `pseudonymize/logger.py` as **one JSON object per line on stdout**, so a Docker log driver (or any collector) can ship it verbatim to a SIEM. The human-readable banner and summary go to **stderr**, keeping the machine-readable stream clean.

Each line carries a fixed envelope plus event-specific fields:

```json
{"timestamp": "2026-05-14T20:21:03Z", "run_id": "c3adc2ce", "level": "INFO", "module": "M1", "event": "join_verificado", "filas_antes": 150000, "filas_despues": 150000, "diff": 0, "integridad_ok": true}
```

The short `run_id` is the correlation key: it is shared by every log line of a run and matches the `run_id` of the audit report, so a run can be reconstructed end-to-end from the SIEM.

---

## Project layout

```
pseudonymize/
├── cli.py              # argparse entry point (pseudonymize)
├── config.py           # YAML config loader with CLI/env override
├── crypto.py           # FF1 cipher factory (shared by M1 and M2)
├── logger.py           # structured JSON logging for SIEM (stdout)
├── pipeline.py         # module orchestrator + traceability report
├── report.py           # JSON audit log writer
├── modules/
│   ├── m0_topology.py  # FK dependency graph inference (standalone)
│   ├── m1_fpe.py       # Format-Preserving Encryption
│   ├── m2_copulas.py   # Gaussian copula synthesis
│   └── m3_faker.py     # HMAC + Faker substitution
└── ui/
    ├── app.py          # FastAPI + SSE server (pseudonymize-ui)
    └── templates/
        └── index.html  # Single-page UI (glassmorphism dark theme)

tests/
└── test_m0_topology.py # unit tests for M0 (in-memory SQLite)

demo/index.html         # static demo page (synced to the demo repo by CI)
.github/workflows/
└── sync-demo.yml       # pushes demo/index.html to grc-pseudonymizer-demo
docker-compose.yml      # PostgreSQL + pipeline services
Dockerfile              # python:3.11-slim, no torch
pyproject.toml          # pip-installable package definition
config.example.yaml     # annotated configuration template
```

---

## Quickstart (Docker — recommended)

**Requirements:** Docker and Docker Compose.

```bash
git clone https://github.com/badi11a/grc-pseudonymizer.git
cd grc-pseudonymizer
```

### Option A — Web UI

Start the UI server (FastAPI, port 8000) alongside the TPC-H demo database (PostgreSQL, port 5433):

```bash
# Start PostgreSQL in the background
docker compose up postgres -d

# Start the web interface (runs locally, not in Docker)
pip install -e .
pseudonymize-ui
```

Open **http://localhost:8000**, optionally hit **Probar conexión** to verify the database, then click **Proteger datos ahora** to run the full pipeline and watch real-time progress via Server-Sent Events. When the run finishes, preview the audit report in the browser and download it with **Descargar informe de auditoría**.

### Option B — CLI only

Run the pipeline headlessly against the demo database:

```bash
docker compose up --build
```

`docker compose up` spins up:

| Service | What it does | Exposed port |
|---|---|---|
| `postgres` | TPC-H demo database (15K customers, 150K orders) | `localhost:5433` |
| `pseudonymize` | Runs the pipeline once and exits | — |

The audit log is written to `./output/informe_trazabilidad.json`.

---

## Local Development (Manual Setup)

**Requirements:** Python 3.10+, a running PostgreSQL instance.

```bash
# 1. Clone and create a virtual environment
git clone https://github.com/badi11a/grc-pseudonymizer.git
cd grc-pseudonymizer
python -m venv venv && source venv/bin/activate

# 2. Install
pip install -e .

# 3. Configure
cp config.example.yaml config.yaml
# Edit config.yaml — set your db_url, FPE key, and HMAC secret

# 4. Run the pipeline
pseudonymize --config config.yaml

# 5. Or start the web UI
pseudonymize-ui
# → http://localhost:8000
```

### CLI reference

```
pseudonymize --config FILE [--db-url URL]
```

- `--config FILE` (required) — path to the YAML configuration file.
- `--db-url URL` — SQLAlchemy connection URL; overrides `db_url` in the config file without modifying it. If the flag is absent, the **`DB_URL` environment variable** is used as a fallback — useful for CI/CD pipelines or injecting credentials from a secret manager (this is how the Docker service passes its connection string):

```bash
pseudonymize --config config.yaml \
  --db-url postgresql://user:$DB_PASS@prod-host/mydb
```

Exit codes: `1` config file not found · `2` invalid configuration · `3` unexpected error.

### Configuration reference

```yaml
# config.example.yaml
db_url: "postgresql://user:pass@localhost/mydb"

fpe:
  key: "2b7e151628aed2a6abf7158809cf4f3c"   # 32-char hex AES key
  tweak: ""
  alphabet: "0123456789"

hmac_key: "your-secret-key"                  # kept outside the codebase

tablas:
  customer:
    pk: "c_custkey"
    direct_identifiers: ["c_name", "c_address"]
    quasi_identifiers:  ["c_acctbal", "c_nationkey"]
  orders:
    fk:
      c_custkey: "o_custkey"
```

### Current scope

This is a proof of concept: the orchestrator currently targets the TPC-H `customer`/`orders` demo schema (the table and column names above). The `tablas` section documents that mapping; generalising the pipeline to arbitrary schemas is the purpose of the M0 topology module, which already infers the required table processing order but is not yet consumed by the orchestrator.

### Output — audit and compliance artefact

Every CLI run writes a machine-readable audit report to `informe_trazabilidad.json` (in UI mode it is served via `GET /api/report/{run_id}` and downloaded from the browser). This file is the primary evidence artefact for **RGPD Art. 32** accountability obligations and **ISO 27001:2022 control A.8.33** (protection of test information). It records, in a single machine-readable JSON document, which algorithm was applied to which columns, at what time, and with what measured quality outcome — ready to attach to a DPIA or hand to an auditor.

```json
{
  "run_id": "c3adc2ce-5e98-4f0b-9179-be09c511d1f3",
  "timestamp": "2026-05-14T20:21:03.485966+00:00",
  "version": "0.1.0",
  "modulos": {
    "M1": {
      "algoritmo": "FF1 NIST SP 800-38G",
      "filas_pk": 15000, "filas_fk": 150000,
      "join_antes": 150000, "join_despues": 150000,
      "integridad_ok": true, "tiempo_s": 0.915
    },
    "M3": {
      "tecnica": "HMAC-SHA256 + Faker es_ES",
      "columnas": ["c_name", "c_address"],
      "filas": 15000, "tiempo_s": 1.2
    },
    "M2": {
      "tecnica": "GaussianMultivariate copulas",
      "columnas": ["c_acctbal", "c_nationkey"],
      "filas": 15000, "frobenius": 0.023772,
      "fallback": false, "tiempo_s": 25.76
    }
  },
  "normativa": ["RGPD Art. 32", "EDPB 01/2025", "ISO 27001:2022 A.8.33"],
  "dry_run": false,
  "resultado_global": "OK",
  "tiempo_total_s": 27.875
}
```

In dry-run mode `dry_run` is `true`, `resultado_global` is `"SIMULACRO"`, and the report is not persisted to disk.

---

## Benchmark

Tested on a TPC-H dataset (scale factor 0.1) loaded into PostgreSQL:

| Dataset | Records | Time |
|---|---|---|
| `customer` (PK) | 15,000 | — |
| `orders` (FK) | 150,000 | — |
| Full pipeline | 165,000 rows processed | **27.9 s** |

| Module | Operation | Time |
|---|---|---|
| M1 — FPE FF1 | PK + FK encryption (150,000 FKs) | **0.9 s** |
| M3 — HMAC+Faker | Semantic substitution (15,000 records) | **1.2 s** |
| M2 — Cópulas gaussianas | Fit (2,000 sample) + sample (15,000) | **25.8 s** |

| Metric | Value | Threshold | Result |
|---|---|---|---|
| Referential integrity (M1) | 150,000 / 150,000 rows | 100% match | PASS |
| Frobenius norm (M2) | 0.0238 | < 0.5 | PASS |
| Determinism (M3) | verified by double-pass | exact match | PASS |

---

## Compliance

This pipeline is designed to assist with the **pseudonymisation obligations** established by the following regulations. It does not replace a full Data Protection Impact Assessment (DPIA).

### GDPR Article 32 — Security of processing

Article 32 requires controllers and processors to implement appropriate technical measures to ensure a level of security appropriate to the risk, explicitly citing **pseudonymisation** as one such measure. This pipeline operationalises that requirement by replacing all direct and quasi-identifying fields before data leaves the production perimeter.

### EDPB Guidelines 01/2025 — Pseudonymisation

The European Data Protection Board's 2025 guidelines clarify that effective pseudonymisation requires that re-identification be **not reasonably likely** without access to additional information held separately. This pipeline satisfies that standard through:

- **M1:** The FF1 key is the only means of reversing PK/FK encryption. Without it, the mapping from original to pseudonymised identifier cannot be reconstructed.
- **M3:** The HMAC secret is the only means of reproducing the name/address mapping. The substitution function is one-way for any party that does not hold the key.
- **M2:** Synthetic quasi-identifiers are generated stochastically and have no deterministic link to the original values; re-identification via these fields is not feasible.

### ISO/IEC 27001:2022 — Control A.8.33

The machine-readable audit log (`informe_trazabilidad.json`) produced on every run provides the evidence trail required by control A.8.33 (protection of test information), recording which algorithm was applied, to which columns, at what time, and with what measured quality outcome. The structured JSON log stream complements it with per-event traceability in the SIEM, correlated by `run_id`.

---

## Dependencies

| Package | Purpose |
|---|---|
| `fastfpe` | FF1 format-preserving encryption (NIST SP 800-38G) |
| `copulas` | Gaussian copula synthesis (`GaussianMultivariate`) |
| `faker` | Locale-aware synthetic name and address generation |
| `networkx` | FK dependency graph and topological sort (M0) |
| `pandas` / `numpy` | In-memory dataframes and numerical operations |
| `sqlalchemy` + `psycopg2-binary` | Database-agnostic SQL layer / PostgreSQL driver |
| `scipy` | Spearman correlation and Frobenius norm computation |
| `fastapi` + `uvicorn` | Web UI server, REST API and SSE streaming |
| `pyyaml` | Configuration file parsing |
| `xgboost` | Utility-evaluation experiments (root-level `test_xgboost*.py` scripts) |

---

## License

MIT
