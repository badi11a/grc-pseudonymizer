import pandas as pd
import numpy as np
from sqlalchemy import create_engine
from xgboost import XGBClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_auc_score
from sdv.single_table import GaussianCopulaSynthesizer
from sdv.metadata import SingleTableMetadata
import hmac, hashlib
from faker import Faker
from fastfpe import ff1
import warnings
warnings.filterwarnings('ignore')

engine  = create_engine('postgresql://tfm_user:1234@localhost/tfm_db')
KEY     = "2b7e151628aed2a6abf7158809cf4f3c"
TWEAK   = ""
ALPHA   = "0123456789"
HMAC_K  = b'clave_maestra_tfm_2026'
fake    = Faker('es_ES')

def cifrar(v):
    return ff1.encrypt(KEY, TWEAK, ALPHA, str(v).zfill(6))

# --- Cargar datos originales ---
print("Cargando datos...")
df = pd.read_sql("""
    SELECT c_custkey, c_acctbal, c_nationkey, c_mktsegment
FROM customer
""", engine)

# Variable objetivo: saldo por encima de la mediana
mediana = df['c_acctbal'].median()
df['target'] = (df['c_acctbal'] > mediana).astype(int)
print(f"  Mediana c_acctbal: {mediana:.2f}")
print(f"  Distribución target: {df['target'].value_counts().to_dict()}")

# One-hot encoding de c_mktsegment
df = pd.get_dummies(df, columns=['c_mktsegment'])
feature_cols = [c for c in df.columns
                if c not in ['c_custkey','c_acctbal','target']]

X = df[feature_cols]
y = df['target']

# --- Modelo A: entrenado sobre datos ORIGINALES ---
print("\nEntrenando Modelo A (datos originales)...")
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42, stratify=y)

model_a = XGBClassifier(n_estimators=100, random_state=42,
                         eval_metric='logloss', verbosity=0)
model_a.fit(X_train, y_train)
auc_a = roc_auc_score(y_test, model_a.predict_proba(X_test)[:,1])
print(f"  AUC Modelo A (original): {auc_a:.4f}")

# --- Generar dataset enmascarado ---
print("\nGenerando dataset enmascarado...")

# M1: cifrar c_custkey
df_mask = pd.read_sql("""
    SELECT c_custkey, c_acctbal, c_nationkey, c_mktsegment
FROM customer
""", engine)
df_mask['c_custkey'] = df_mask['c_custkey'].apply(cifrar)

# M2: cópulas gaussianas sobre QIDs
df_qid = pd.read_sql(
    "SELECT c_custkey, c_acctbal, c_nationkey FROM customer", engine)
df_qid['c_custkey'] = df_qid['c_custkey'].apply(cifrar)

meta = SingleTableMetadata()
meta.detect_from_dataframe(df_qid)
meta.update_column('c_custkey', sdtype='id')
meta.set_primary_key('c_custkey')
model_sdv = GaussianCopulaSynthesizer(meta)
model_sdv.fit(df_qid)
df_sint = model_sdv.sample(num_rows=len(df_qid))

df_mask = df_mask.drop(columns=['c_acctbal','c_nationkey'])
df_mask = df_mask.merge(
    df_sint[['c_custkey','c_acctbal','c_nationkey']],
    on='c_custkey', how='left')

# Variable objetivo sobre datos enmascarados
df_mask['target'] = (df_mask['c_acctbal'] > mediana).astype(int)
df_mask = pd.get_dummies(df_mask, columns=['c_mktsegment'])

# Alinear columnas con el dataset original
for col in feature_cols:
    if col not in df_mask.columns:
        df_mask[col] = 0
df_mask = df_mask[feature_cols + ['target']]

X_mask = df_mask[feature_cols]
y_mask = df_mask['target']

# --- Modelo B: entrenado sobre datos ENMASCARADOS ---
print("Entrenando Modelo B (datos enmascarados)...")
X_m_train, _, y_m_train, _ = train_test_split(
    X_mask, y_mask, test_size=0.2, random_state=42, stratify=y_mask)

model_b = XGBClassifier(n_estimators=100, random_state=42,
                          eval_metric='logloss', verbosity=0)
model_b.fit(X_m_train, y_m_train)

# Ambos modelos evaluados sobre el MISMO hold-out real
auc_b = roc_auc_score(y_test, model_b.predict_proba(X_test)[:,1])
print(f"  AUC Modelo B (enmascarado, eval. sobre hold-out real): {auc_b:.4f}")

# --- Resultado ---
delta_auc = auc_a - auc_b
print("\n" + "="*50)
print(f"  AUC Modelo A (original):    {auc_a:.4f}")
print(f"  AUC Modelo B (enmascarado): {auc_b:.4f}")
print(f"  ΔAUC = {delta_auc:.4f}")
if abs(delta_auc) <= 0.05:
    print(f"  ✓ Degradación de utilidad aceptable (≤ 0.05)")
else:
    print(f"  ⚠ Degradación superior al umbral (> 0.05)")
print("="*50)
