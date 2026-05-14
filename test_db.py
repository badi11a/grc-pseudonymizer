import pandas as pd
from sqlalchemy import create_engine

# Conectar a la base de datos PostgreSQL local
engine = create_engine('postgresql://tfm_user:1234@localhost/tfm_db')

# Intentar leer 5 registros de la tabla customer
try:
    df = pd.read_sql("SELECT * FROM customer LIMIT 5;", engine)
    print("¡Conexión exitosa! Aquí tienes 5 clientes de prueba:")
    print(df.head())
except Exception as e:
    print("Error de conexión:", e)
