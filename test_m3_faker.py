import pandas as pd
import hmac
import hashlib
from faker import Faker
from sqlalchemy import create_engine

engine = create_engine('postgresql://tfm_user:1234@localhost/tfm_db')

SECRET_KEY = b'clave_maestra_tfm_2026'
fake = Faker('es_ES')

def seudonimizar_nombre(valor_original):
    digest = hmac.new(SECRET_KEY, str(valor_original).encode(), hashlib.sha256).digest()
    seed = int.from_bytes(digest[:4], 'big')
    fake.seed_instance(seed)
    return fake.name()

def seudonimizar_direccion(valor_original):
    digest = hmac.new(SECRET_KEY, str(valor_original).encode(), hashlib.sha256).digest()
    seed = int.from_bytes(digest[:4], 'big')
    fake.seed_instance(seed)
    return fake.address().replace('\n', ', ')

print("Cargando customer...")
df = pd.read_sql("SELECT c_custkey, c_name, c_address FROM customer LIMIT 10", engine)

print("\nDatos originales:")
print(df[['c_custkey','c_name','c_address']].to_string(index=False))

df['c_name_pseudo']    = df['c_name'].apply(seudonimizar_nombre)
df['c_address_pseudo'] = df['c_address'].apply(seudonimizar_direccion)

print("\nDatos seudonimizados:")
print(df[['c_custkey','c_name_pseudo','c_address_pseudo']].to_string(index=False))

print("\nVerificando determinismo (doble pasada):")
df['c_name_check'] = df['c_name'].apply(seudonimizar_nombre)
ok = (df['c_name_pseudo'] == df['c_name_check']).all()
print(f"  Mismo resultado en ambas pasadas: {'✓ TRUE' if ok else '✗ FALSE'}")
