import pandas as pd
import numpy as np
from sqlalchemy import create_engine
from sdv.single_table import GaussianCopulaSynthesizer
from sdv.metadata import SingleTableMetadata
import time
import warnings
warnings.filterwarnings('ignore')

engine = create_engine('postgresql://tfm_user:1234@localhost/tfm_db')

# --- 1. Cargar columnas QID de customer ---
print("Cargando QIDs de customer...")
df = pd.read_sql("""
    SELECT c_custkey, c_acctbal, c_nationkey
    FROM customer
""", engine)
print(f"  {len(df):,} filas cargadas")
print(f"\nEstadísticas originales:")
print(df[['c_acctbal','c_nationkey']].describe().round(2))

# --- 2. Definir metadata para SDV ---
metadata = SingleTableMetadata()
metadata.detect_from_dataframe(df)
metadata.update_column('c_custkey', sdtype='id')
metadata.set_primary_key('c_custkey')

# --- 3. Ajustar modelo ---
print("\nAjustando GaussianCopulaSynthesizer...")
t0 = time.time()
model = GaussianCopulaSynthesizer(metadata)
model.fit(df)
t1 = time.time()
print(f"  Modelo ajustado en {t1-t0:.2f}s")

# --- 4. Generar datos sintéticos ---
print("\nGenerando datos sintéticos...")
df_sintetico = model.sample(num_rows=len(df))
print(f"  {len(df_sintetico):,} filas generadas")

# --- 5. Comparar distribuciones ---
print("\nComparación de distribuciones:")
for col in ['c_acctbal', 'c_nationkey']:
    mean_orig = df[col].mean()
    mean_sint = df_sintetico[col].mean()
    std_orig  = df[col].std()
    std_sint  = df_sintetico[col].std()
    print(f"\n  {col}:")
    print(f"    Media   — original: {mean_orig:>10.2f} | sintético: {mean_sint:>10.2f}")
    print(f"    Std dev — original: {std_orig:>10.2f}  | sintético: {std_sint:>10.2f}")

# --- 6. Correlación Spearman y norma de Frobenius ---
from scipy.stats import spearmanr

cols = ['c_acctbal', 'c_nationkey']
corr_orig = df[cols].corr(method='spearman')
corr_sint = df_sintetico[cols].corr(method='spearman')
frobenius = np.linalg.norm(corr_orig.values - corr_sint.values, 'fro')

print(f"\nMatriz correlación Spearman — original:")
print(corr_orig.round(4))
print(f"\nMatriz correlación Spearman — sintético:")
print(corr_sint.round(4))
print(f"\nNorma de Frobenius (diferencia): {frobenius:.6f}")

# --- 7. Veredicto ---
print("\n" + "="*45)
if frobenius < 0.5:
    print(f"✓ M2 ESTABLE — Frobenius = {frobenius:.4f}")
    print(f"  Dependencias multivariables preservadas")
else:
    print(f"⚠ REVISAR — Frobenius = {frobenius:.4f}")
    print(f"  Considerar fallback Sarathy-Muralidhar")
print("="*45)
