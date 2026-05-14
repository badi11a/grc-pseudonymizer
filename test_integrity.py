import pandas as pd
from sqlalchemy import create_engine
from fastfpe import ff1

engine = create_engine('postgresql://tfm_user:1234@localhost/tfm_db')

query = """
SELECT c.c_custkey as pk, o.o_custkey as fk
FROM customer c
JOIN orders o ON c.c_custkey = o.o_custkey
LIMIT 1;
"""
df = pd.read_sql(query, engine)

key = "2b7e151628aed2a6abf7158809cf4f3c"
tweak = ""
alphabet = "0123456789"

def cifrar(valor):
    val_str = str(valor).zfill(6)
    return ff1.encrypt(key, tweak, alphabet, val_str)

df['pk_cifrado'] = df['pk'].apply(cifrar)
df['fk_cifrado'] = df['fk'].apply(cifrar)
df['coincide'] = df['pk_cifrado'] == df['fk_cifrado']

print("Resultado de la prueba de integridad:")
print(df[['pk', 'fk', 'pk_cifrado', 'fk_cifrado', 'coincide']])
