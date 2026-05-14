import pandas as pd
from sqlalchemy import create_engine
from fastfpe import ff1

# 1. Conexión a la BD
engine = create_engine('postgresql://tfm_user:1234@localhost/tfm_db')
df = pd.read_sql("SELECT c_custkey FROM customer LIMIT 5;", engine)

# 2. Configurar parámetros FF1
key = "2b7e151628aed2a6abf7158809cf4f3c"
tweak = ""
alphabet = "0123456789"

# 3. Función para cifrar conservando formato
def seudonimizar_pk(valor):
    valor_str = str(valor)
    # Por seguridad matemática, FF1 exige un mínimo de 6 caracteres en base 10
    if len(valor_str) < 6:
        valor_str = valor_str.zfill(6)
    return ff1.encrypt(key, tweak, alphabet, valor_str)

# 4. Aplicar la transformación
df['custkey_seudonimo'] = df['c_custkey'].apply(seudonimizar_pk)

print("¡Cifrado FF1 Exitoso! Compara las claves primarias:")
print(df)
