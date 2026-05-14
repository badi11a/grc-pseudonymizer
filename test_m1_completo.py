import pandas as pd
from sqlalchemy import create_engine
from fastfpe import ff1
import time

engine = create_engine('postgresql://tfm_user:1234@localhost/tfm_db')

KEY      = "2b7e151628aed2a6abf7158809cf4f3c"
TWEAK    = ""
ALPHABET = "0123456789"

def cifrar(valor):
    return ff1.encrypt(KEY, TWEAK, ALPHABET, str(valor).zfill(6))

# --- 1. Cargar tablas ---
print("Cargando tablas...")
customer = pd.read_sql("SELECT c_custkey FROM customer", engine)
orders   = pd.read_sql("SELECT o_orderkey, o_custkey FROM orders", engine)

print(f"  customer: {len(customer):,} filas | orders: {len(orders):,} filas")

# --- 2. JOIN original ---
join_original = customer.merge(orders, left_on='c_custkey', right_on='o_custkey')
filas_original = len(join_original)
print(f"\nJOIN original: {filas_original:,} filas")

# --- 3. Cifrar PK y FK ---
print("\nCifrando c_custkey (PK)...")
t0 = time.time()
customer['c_custkey_enc'] = customer['c_custkey'].apply(cifrar)
t1 = time.time()
print(f"  {len(customer):,} valores cifrados en {t1-t0:.2f}s")

print("Cifrando o_custkey (FK)...")
t0 = time.time()
orders['o_custkey_enc'] = orders['o_custkey'].apply(cifrar)
t1 = time.time()
print(f"  {len(orders):,} valores cifrados en {t1-t0:.2f}s")

# --- 4. JOIN sobre datos cifrados ---
join_cifrado = customer.merge(orders, left_on='c_custkey_enc', right_on='o_custkey_enc')
filas_cifrado = len(join_cifrado)
print(f"\nJOIN cifrado:   {filas_cifrado:,} filas")

# --- 5. Veredicto ---
print("\n" + "="*45)
if filas_original == filas_cifrado:
    print(f"✓ INTEGRIDAD REFERENCIAL PRESERVADA")
    print(f"  Filas originales:  {filas_original:,}")
    print(f"  Filas tras cifrado: {filas_cifrado:,}")
    print(f"  Diferencia: 0")
else:
    diff = filas_original - filas_cifrado
    print(f"✗ FALLO: se perdieron {diff:,} filas")
print("="*45)

# --- 6. Muestra 5 pares cifrados ---
print("\nMuestra (5 pares PK/FK cifrados):")
muestra = customer.head(5).merge(
    orders[['o_custkey','o_custkey_enc']].drop_duplicates('o_custkey'),
    left_on='c_custkey', right_on='o_custkey', how='inner'
)[['c_custkey','c_custkey_enc','o_custkey','o_custkey_enc']].head(5)
print(muestra.to_string(index=False))
