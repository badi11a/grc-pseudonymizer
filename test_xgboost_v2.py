import pandas as pd
import numpy as np
from sqlalchemy import create_engine
from xgboost import XGBClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import LabelEncoder
from sdv.single_table import GaussianCopulaSynthesizer
from sdv.metadata import SingleTableMetadata
from fastfpe import ff1
import warnings
warnings.filterwarnings('ignore')

engine = create_engine('postgresql://tfm_user:1234@localhost/tfm_db')
KEY    = "2b7e151628aed2a6abf7158809cf4f3c"
TWEAK  = ""
ALPHA  = "0123456789"

def cifrar(v):
    return ff1.encrypt(KEY, TWEAK, ALPHA, str(v).zfill(6))

# --- Cargar datos originales ---
print("Cargando datos...")
df = pd.read_sql("""
    SELECT c_custkey, c_acctbal, c_nationkey,
           c_mktsegment, c_phone
    FROM customer
""", engine)

# Variable objetivo: c_mktsegment (5 clases)
le = LabelEncoder()
df['target'] = le.fit_transform(df['c_mktsegment'])
print(f"  Clases: {dict(enumerate(le.classes_))}")
print(f"  Distribución:\n{df['target'].value_counts().sort_index()}")

# Extraer prefijo numérico de c_phone como feature adicional
df['phone_prefix'] = df['c_phone'].str[:2].astype(float)

feature_cols = ['c_acctbal', 'c_nationkey', 'phone_prefix']
X = df[feature_cols]
y = df['target']

# Split — hold-out fijo para evaluar ambos modelos
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42, stratify=y)

# --- Modelo A: datos originales ---
print("\nEntrenando Modelo A (datos originales)...")
model_a = XGBClassifier(n_estimators=200, max_depth=4,
                         random_state=42, verbosity=0,
                         eval_metric='mlogloss',
                         objective='multi:softprob',
                         num_class=len(le.classes_))
model_a.fit(X_train, y_train)
auc_a = roc_auc_score(y_test,
                       model_a.predict_proba(X_test),
                       multi_class='ovr', average='macro')
print(f"  AUC Modelo A (original): {auc_a:.4f}")

# --- Generar dataset enmascarado ---
print("\nGenerando dataset enmascarado con pipeline...")

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

# Reemplazar QIDs en dataset enmascarado
df_mask = df.copy()
df_mask = df_mask.drop(columns=['c_acctbal','c_nationkey'])
df_mask['c_custkey_enc'] = df_mask['c_custkey'].apply(cifrar)
df_mask = df_mask.merge(
    df_sint[['c_custkey','c_acctbal','c_nationkey']],
    left_on='c_custkey_enc', right_on='c_custkey',
    how='left', suffixes=('_old','')
)
df_mask['phone_prefix'] = df_mask['c_phone'].str[:2].astype(float)

X_mask = df_mask[feature_cols]
y_mask = df_mask['target']

X_m_train, _, y_m_train, _ = train_test_split(
    X_mask, y_mask, test_size=0.2, random_state=42, stratify=y_mask)

# --- Modelo B: datos enmascarados ---
print("Entrenando Modelo B (datos enmascarados)...")
model_b = XGBClassifier(n_estimators=200, max_depth=4,
                          random_state=42, verbosity=0,
                          eval_metric='mlogloss',
                          objective='multi:softprob',
                          num_class=len(le.classes_))
model_b.fit(X_m_train, y_m_train)

# Ambos evaluados sobre el MISMO hold-out real
auc_b = roc_auc_score(y_test,
                       model_b.predict_proba(X_test),
                       multi_class='ovr', average='macro')
print(f"  AUC Modelo B (enmascarado): {auc_b:.4f}")

# --- Resultado ---
delta_auc = auc_a - auc_b
print("\n" + "="*50)
print(f"  AUC Modelo A (original):    {auc_a:.4f}")
print(f"  AUC Modelo B (enmascarado): {auc_b:.4f}")
print(f"  ΔAUC = {delta_auc:.4f}")
if abs(delta_auc) <= 0.05:
    print(f"  ✓ Degradación aceptable (≤ 0.05)")
else:
    print(f"  ⚠ Degradación superior al umbral (> 0.05)")
print("="*50)
