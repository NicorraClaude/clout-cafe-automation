"""
Orquestador principal — Clout Café Automation.
Cron: cada día L-V a las 09:00 ART.

Flujo:
  1. Importar leads: Apollo + directorios web (Guía Oleo, Páginas Amarillas, OSM)
  2. Encolar los nuevos (estado nuevo → encolado)
  3. Detectar respuestas en inbox
  4. Enviar follow-up 2 (email #3)
  5. Enviar follow-up 1 (email #2)
  6. Enviar emails iniciales (email #1)
"""

import sys, os, importlib.util

ROOT = os.path.dirname(__file__)
sys.path.insert(0, ROOT)


def load_module(path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_emails(dry_run: bool = False, force_hours: bool = False):
    send = load_module("modules/02-email-outreach/send_emails.py", "send_emails")

    # Un solo envío a la vez, aunque se disparen dos runs en paralelo.
    if not dry_run and not send.adquirir_lock():
        print("🔒 Ya hay otro envío en curso. Este proceso no envía nada.")
        return

    try:
        _run_emails_inner(send, dry_run, force_hours)
    finally:
        send.liberar_lock()


def _run_emails_inner(send, dry_run: bool, force_hours: bool):
    print("\n[1] Encolando leads nuevos...")
    try:
        enqueue = load_module("modules/02-email-outreach/enqueue_leads.py", "enqueue_leads")
        enqueue.run(limit=100)
    except Exception as e:
        print(f"  Enqueue error (no crítico): {e}")

    print("\n[2] Detectando respuestas en inbox...")
    try:
        replies = load_module("modules/03-followups/check_replies.py", "check_replies")
        replies.run()
    except Exception as e:
        print(f"  Gmail IMAP error: {e}")

    print("\n[3] Enviando follow-ups (email #2 y #3)...")
    try:
        send.run(email_num=3, dry_run=dry_run, force_hours=force_hours)
        send.run(email_num=2, dry_run=dry_run, force_hours=force_hours)
    except Exception as e:
        print(f"  Follow-up error: {e}")

    print("\n[4] Enviando emails iniciales (email #1)...")
    try:
        send.run(email_num=1, dry_run=dry_run, force_hours=force_hours)
    except Exception as e:
        print(f"  Email inicial error: {e}")

    print("\n✅ Emails completos.")

    print("\n[REPORTE]")
    try:
        report_mod = load_module("daily_report.py", "daily_report")
        report_mod.report()
    except Exception as e:
        print(f"  Reporte error: {e}")


def run_scrape():
    print("\n[1] Importando leads desde Apollo...")
    try:
        apollo = load_module("modules/01-lead-gen/apollo_import.py", "apollo_import")
        apollo.run(pages=5, max_enrich=50)
    except Exception as e:
        print(f"  Apollo error (no crítico): {e}")

    import datetime
    day_of_year = datetime.date.today().timetuple().tm_yday

    print("\n[2] Importando leads desde Google Maps (rotación diaria)...")
    try:
        maps = load_module("modules/01-lead-gen/maps_scraper.py", "maps_scraper")
        zonas = maps.ZONAS
        # 2 zonas × 4 rubros por día ≈ 45 leads/día, ~USD 81/mes de consumo
        # de la API de Google (el crédito mensual gratuito es de USD 200).
        # Subir estos números aumenta leads Y costo: ver cálculo en el README.
        n = 2
        ini = (day_of_year * n) % len(zonas)
        batch = (zonas + zonas)[ini:ini + n]
        print(f"  Zonas de hoy: {[z[0] for z in batch]}")
        maps.run(zonas=batch, rubros=maps.RUBROS[:4])
    except Exception as e:
        print(f"  Google Maps error (no crítico): {e}")

    print("\n[3] Importando leads desde OpenStreetMap...")
    try:
        dirs = load_module("modules/01-lead-gen/directory_scraper.py", "directory_scraper")
        all_locs = dirs.ALL_LOCATIONS
        batch_size = 4
        start = (day_of_year * batch_size) % len(all_locs)
        batch = (all_locs + all_locs)[start:start + batch_size]
        print(f"  Zonas de hoy: {[b[0] for b in batch]}")
        dirs.run(locations=batch)
    except Exception as e:
        print(f"  OpenStreetMap error (no crítico): {e}")

    print("\n✅ Scraping completo.")


def main(dry_run: bool = False):
    print("=" * 50)
    print("CLOUT CAFÉ AUTOMATION — inicio")
    print("=" * 50)
    run_scrape()
    run_emails(dry_run=dry_run)


if __name__ == "__main__":
    dry = "--dry" in sys.argv
    force = "--force-hours" in sys.argv
    if "--emails-only" in sys.argv:
        run_emails(dry_run=dry, force_hours=force)
    elif "--scrape-only" in sys.argv:
        run_scrape()
    else:
        main(dry_run=dry)
