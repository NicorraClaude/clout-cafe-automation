"""
Reporte diario de outreach — Clout Café.
Muestra: emails enviados hoy, total por empresa, estado del pipeline,
follow-ups pendientes. Corre solo o al final de run.py.
"""

import os, sys, psycopg2, datetime
from dotenv import load_dotenv
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(__file__)
load_dotenv(os.path.join(ROOT, ".env"))

ART = ZoneInfo("America/Argentina/Buenos_Aires")


def db_conn():
    return psycopg2.connect(
        host=os.environ["SUPABASE_DB_HOST"], port=5432, dbname="postgres",
        user="postgres", password=os.environ["SUPABASE_DB_PASS"], sslmode="require",
        connect_timeout=10
    )


def report():
    conn = db_conn()
    cur = conn.cursor()
    today = datetime.date.today()
    now = datetime.datetime.now(ART)

    print()
    print("=" * 62)
    print(f"  REPORTE OUTREACH — CLOUT CAFÉ")
    print(f"  {now.strftime('%A %d/%m/%Y %H:%M')} (ART)")
    print("=" * 62)

    # ── ENVIADOS HOY ──────────────────────────────────────────────
    cur.execute("""
        SELECT el.email_num, l.nombre_lugar, l.email, l.rubro,
               el.enviado_at AT TIME ZONE 'America/Argentina/Buenos_Aires'
        FROM email_logs el
        JOIN leads l ON l.id = el.lead_id
        WHERE el.enviado_at::date = %s
        ORDER BY el.enviado_at DESC
    """, (today,))
    rows_today = cur.fetchall()

    print(f"\n📬  ENVIADOS HOY ({today.strftime('%d/%m/%Y')}): {len(rows_today)}")
    if rows_today:
        iniciales  = [r for r in rows_today if r[0] == 1]
        followup1  = [r for r in rows_today if r[0] == 2]
        followup2  = [r for r in rows_today if r[0] == 3]
        if iniciales:
            print(f"\n  📧 Email inicial ({len(iniciales)}):")
            for r in iniciales:
                print(f"    → {r[1][:35]:<35} {r[2]}")
        if followup1:
            print(f"\n  🔁 Follow-up 1 ({len(followup1)}):")
            for r in followup1:
                print(f"    → {r[1][:35]:<35} {r[2]}")
        if followup2:
            print(f"\n  🔂 Follow-up 2 ({len(followup2)}):")
            for r in followup2:
                print(f"    → {r[1][:35]:<35} {r[2]}")
    else:
        print("  (ninguno)")

    # ── ENVIADOS ÚLTIMOS 7 DÍAS ───────────────────────────────────
    cur.execute("""
        SELECT el.enviado_at::date AS dia,
               COUNT(*) FILTER (WHERE el.email_num = 1) AS iniciales,
               COUNT(*) FILTER (WHERE el.email_num = 2) AS fu1,
               COUNT(*) FILTER (WHERE el.email_num = 3) AS fu2,
               COUNT(*) AS total
        FROM email_logs el
        WHERE el.enviado_at >= now() - interval '7 days'
        GROUP BY dia ORDER BY dia DESC
    """)
    week = cur.fetchall()

    print("\n📅  ÚLTIMOS 7 DÍAS:")
    if week:
        print(f"  {'Fecha':<12} {'Inicial':>8} {'FU-1':>6} {'FU-2':>6} {'Total':>6}")
        print(f"  {'-'*12} {'-'*8} {'-'*6} {'-'*6} {'-'*6}")
        for r in week:
            print(f"  {str(r[0]):<12} {r[1]:>8} {r[2]:>6} {r[3]:>6} {r[4]:>6}")
    else:
        print("  Sin envíos aún.")

    # ── PIPELINE GENERAL ──────────────────────────────────────────
    cur.execute("""
        SELECT estado, COUNT(*) FROM leads GROUP BY estado ORDER BY COUNT(*) DESC
    """)
    pipeline = cur.fetchall()

    estado_labels = {
        "nuevo": "nuevos (sin encolar)",
        "encolado": "listos para email inicial",
        "email_1_enviado": "esperando follow-up 1",
        "email_2_enviado": "esperando follow-up 2",
        "email_3_enviado": "secuencia completa",
        "respondio": "respondieron ✓",
        "descartado": "descartados",
    }

    total_leads = sum(r[1] for r in pipeline)
    print(f"\n📊  PIPELINE TOTAL ({total_leads} leads):")
    for estado, count in pipeline:
        label = estado_labels.get(estado, estado)
        print(f"  {count:>4}  {label}")

    # ── PRÓXIMOS FOLLOW-UPS ────────────────────────────────────────
    cur.execute("""
        SELECT nombre_lugar, email, rubro,
               email_1_at AT TIME ZONE 'America/Argentina/Buenos_Aires',
               (email_1_at + interval '4 days')::date AS fu1_fecha
        FROM leads
        WHERE estado = 'email_1_enviado'
          AND email_1_at >= now() - interval '4 days'
        ORDER BY email_1_at
        LIMIT 10
    """)
    upcoming_fu1 = cur.fetchall()

    if upcoming_fu1:
        print(f"\n⏰  PRÓXIMOS FOLLOW-UP 1 ({len(upcoming_fu1)} pendientes):")
        for r in upcoming_fu1:
            print(f"  {str(r[4]):<12}  {r[0][:35]:<35} {r[1]}")

    # ── BASE DE DATOS CONTACTADOS ─────────────────────────────────
    cur.execute("""
        SELECT l.nombre_lugar, l.email, l.rubro, l.ciudad,
               MAX(el.email_num) AS ultimo_email,
               MAX(el.enviado_at AT TIME ZONE 'America/Argentina/Buenos_Aires')::date AS ultimo_envio
        FROM leads l
        JOIN email_logs el ON el.lead_id = l.id
        GROUP BY l.nombre_lugar, l.email, l.rubro, l.ciudad
        ORDER BY ultimo_envio DESC
        LIMIT 50
    """)
    contacted = cur.fetchall()

    if contacted:
        print(f"\n📋  BASE DE CONTACTADOS ({len(contacted)} mostrados):")
        print(f"  {'Empresa':<30} {'Email':<32} {'Rubro':<15} {'Email#':>6} {'Último':>10}")
        print(f"  {'-'*30} {'-'*32} {'-'*15} {'-'*6} {'-'*10}")
        for r in contacted:
            print(f"  {(r[0] or '')[:30]:<30} {(r[1] or '')[:32]:<32} {(r[2] or '')[:15]:<15} {r[4]:>6} {str(r[5]):>10}")
    else:
        print("\n📋  BASE DE CONTACTADOS: vacía (aún no se envió ningún email)")

    print()
    cur.close()
    conn.close()


if __name__ == "__main__":
    report()
