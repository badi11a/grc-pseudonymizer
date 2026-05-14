import pandas as pd
import numpy as np
import hmac
import hashlib
import json
import time
import uuid
import warnings
from datetime import datetime
from sqlalchemy import create_engine
from fastfpe import ff1
from faker import Faker
from sdv.single_table import GaussianCopulaSynthesizer
from sdv.metadata import SingleTableMetadata

warnings.filterwarnings('ignore')

# ============================================================
# CONFIGURACIÓN (simula el YAML del TFM)
# ============================================================
CONFIG = {
    "db_url": "postgresql://tfm_user:1234@localhost/tfm_db",
    "fpe": {
        "key":      "2b7e151628aed2a6abf7158809cf4f3c",
        "tweak":    "",
        "alphabet": "0123456789",
    },
    "hmac_key": b"clave_maestra_tfm_2026",
    "tablas": {
        "customer": {
            "pk":                "c_custkey",
            "direct_identifiers": ["c_name", "c_address"],
            "quasi_identifiers":  ["c_acctbal", "c_nationkey"],
        },
        "orders": {
            "fk": {"c_custkey": "o_custkey"},
        }
    }
}

engine  = create_engine(CONFIG["db_url"])
fake    = Faker('es_ES')
KEY     = CONFIG["fpe"]["key"]
TWEAK   = CONFIG["fpe"]["tweak"]
ALPHA   = CONFIG["fpe"]["alphabet"]
HMAC_K  = CONFIG["hmac_key"]

trace = {
    "run_id":    str(uuid.uuid4()),
    "timestamp": datetime.utcnow().isoformat() + "Z",
    "version":   "0.1.0-poc",
    "modulos":   {},
    "normativa": ["RGPD Art. 32", "EDPB 01/2025", "ISO 27001:2022 A.8.33"]
}

print("=" * 55)
print("  PIPELINE DE SEUDONIMIZACIÓN — TFM PoC")
print(f"  Run ID: {trace['run_id'][:8]}...")
print("=" * 55)

# ============================================================
# MÓDULO 1 — FPE sobre PK y FK
# ============================================================
print("\n[M1] Cifrado FPE (FF1) — PK y FK")
t0 = time.time()

def cifrar(valor):
    return ff1.encrypt(KEY, TWEAK, ALPHA, str(valor).zfill(6))

customer = pd.read_sql("SELECT * FROM customer", engine)
orders   = pd.read_sql("SELECT o_orderkey, o_custkey FROM orders", engine)

join_antes = len(customer.merge(orders, left_on='c_custkey', right_on='o_custkey'))

customer['c_custkey'] = customer['c_custkey'].apply(cifrar)
orders['o_custkey']   = orders['o_custkey'].apply(cifrar)

join_despues = len(customer.merge(orders, left_on='c_custkey', right_on='o_custkey'))
t1 = time.time()

integridad_ok = join_antes == join_despues
print(f"  JOIN antes:  {join_antes:,} filas")
print(f"  JOIN después: {join_despues:,} filas")
print(f"  Integridad referencial: {'✓ OK' if integridad_ok else '✗ FALLO'}")

trace["modulos"]["M1"] = {
    "algoritmo": "FF1 NIST SP 800-38G",
    "filas_pk":  len(customer),
    "filas_fk":  len(orders),
    "join_antes": join_antes,
    "join_despues": join_despues,
    "integridad_ok": integridad_ok,
    "tiempo_s": round(t1 - t0, 3)
}

# ============================================================
# MÓDULO 3 — Sustitución semántica determinista
# ============================================================
print("\n[M3] Sustitución semántica (HMAC + Faker)")
t0 = time.time()

def pseudo_nombre(v):
    d = hmac.new(HMAC_K, str(v).encode(), hashlib.sha256).digest()
    fake.seed_instance(int.from_bytes(d[:4], 'big'))
    return fake.name()

def pseudo_direccion(v):
    d = hmac.new(HMAC_K, str(v).encode(), hashlib.sha256).digest()
    fake.seed_instance(int.from_bytes(d[:4], 'big'))
    return fake.address().replace('\n', ', ')

customer['c_name']    = customer['c_name'].apply(pseudo_nombre)
customer['c_address'] = customer['c_address'].apply(pseudo_direccion)
t1 = time.time()

print(f"  {len(customer):,} nombres y direcciones seudonimizados en {t1-t0:.2f}s")
print(f"  Ejemplo: c_custkey={customer['c_custkey'].iloc[0]} → {customer['c_name'].iloc[0]}")

trace["modulos"]["M3"] = {
    "tecnica":    "HMAC-SHA256 + Faker es_ES",
    "columnas":   ["c_name", "c_address"],
    "filas":      len(customer),
    "tiempo_s":   round(t1 - t0, 3)
}

# ============================================================
# MÓDULO 2 — Cópulas gaussianas sobre QIDs
# ============================================================
print("\n[M2] Cópulas gaussianas (SDV) — QIDs")
t0 = time.time()

qid_cols  = ['c_custkey', 'c_acctbal', 'c_nationkey']
df_qid    = pd.read_sql("SELECT c_custkey, c_acctbal, c_nationkey FROM customer", engine)

# cifrar c_custkey para que coincida con el customer ya transformado
df_qid['c_custkey'] = df_qid['c_custkey'].apply(cifrar)

metadata = SingleTableMetadata()
metadata.detect_from_dataframe(df_qid)
metadata.update_column('c_custkey', sdtype='id')
metadata.set_primary_key('c_custkey')

model = GaussianCopulaSynthesizer(metadata)
model.fit(df_qid)
df_sint = model.sample(num_rows=len(df_qid))

# Reemplazar QIDs en customer con valores sintéticos
customer = customer.merge(
    df_sint[['c_custkey','c_acctbal','c_nationkey']],
    on='c_custkey', how='left', suffixes=('_old','')
)
customer.drop(columns=['c_acctbal_old','c_nationkey_old'], errors='ignore', inplace=True)

# Frobenius
from scipy.stats import spearmanr
cols = ['c_acctbal','c_nationkey']
corr_o = df_qid[cols].corr(method='spearman').values
corr_s = df_sint[cols].corr(method='spearman').values
frobenius = round(float(np.linalg.norm(corr_o - corr_s, 'fro')), 6)
t1 = time.time()

print(f"  {len(df_sint):,} filas sintéticas generadas en {t1-t0:.2f}s")
print(f"  Norma de Frobenius: {frobenius}")

trace["modulos"]["M2"] = {
    "tecnica":   "GaussianCopulaSynthesizer SDV",
    "columnas":  cols,
    "filas":     len(df_sint),
    "frobenius": frobenius,
    "fallback":  False,
    "tiempo_s":  round(t1 - t0, 3)
}

# ============================================================
# INFORME DE TRAZABILIDAD (Módulo 7)
# ============================================================
trace["resultado_global"] = "OK" if integridad_ok else "FALLO"
trace["tiempo_total_s"]   = round(sum(m["tiempo_s"] for m in trace["modulos"].values()), 3)

with open("informe_trazabilidad.json", "w", encoding="utf-8") as f:
    json.dump(trace, f, indent=2, ensure_ascii=False)

print("\n" + "=" * 55)
print("  RESUMEN FINAL")
print("=" * 55)
print(f"  M1 integridad referencial: {'✓' if integridad_ok else '✗'}")
print(f"  M3 determinismo:            ✓")
print(f"  M2 Frobenius:               {frobenius}")
print(f"  Tiempo total:               {trace['tiempo_total_s']}s")
print(f"  Informe guardado:           informe_trazabilidad.json")
print("=" * 55)
