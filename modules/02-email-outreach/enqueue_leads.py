"""Mueve leads de 'nuevo' a 'encolado' (listos para enviar email 1)."""
import os, psycopg2
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "../../.env"))

def db_conn():
    return psycopg2.connect(
        host=os.environ["SUPABASE_DB_HOST"], port=int(os.environ.get("SUPABASE_DB_PORT", 5432)), dbname="postgres",
        user=os.environ.get("SUPABASE_DB_USER", "postgres"), password=os.environ["SUPABASE_DB_PASS"], sslmode="require"
    )

def run(limit: int = 50):
    conn = db_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM leads WHERE estado = 'nuevo'")
    total = cur.fetchone()[0]
    cur.execute("""
        UPDATE leads SET estado = 'encolado', updated_at = now()
        WHERE id IN (
            SELECT id FROM leads WHERE estado = 'nuevo'
            ORDER BY created_at LIMIT %s
        )
    """, (limit,))
    conn.commit()
    print(f"✅ {cur.rowcount} leads encolados (de {total} disponibles)")
    cur.close(); conn.close()

if __name__ == "__main__":
    run()
