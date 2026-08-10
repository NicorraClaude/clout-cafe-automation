"""
Agrega columnas nuevas a la tabla leads si no existen.
Ejecutar una sola vez (idempotente).
"""
import os, psycopg2
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "../../.env"))

DB_HOST = os.environ["SUPABASE_DB_HOST"]
DB_PASS = os.environ["SUPABASE_DB_PASS"]

conn = psycopg2.connect(
    host=DB_HOST, port=5432, dbname="postgres",
    user="postgres", password=DB_PASS, sslmode="require"
)
cur = conn.cursor()

migrations = [
    "ALTER TABLE leads ADD COLUMN IF NOT EXISTS barrio TEXT",
    "ALTER TABLE leads ADD COLUMN IF NOT EXISTS fuente TEXT DEFAULT 'apollo'",
]

for sql in migrations:
    cur.execute(sql)
    print(f"✓ {sql}")

conn.commit()
cur.close()
conn.close()
print("✅ Migración completada")
