# Clout Café Automation

Sistema de automatización de ventas mayoristas para **Clout Café** (clout.ar).

## Estado actual

**Fase 0 — Setup.** Estructura creada. Esperando cuentas de Apollo.io y Hunter.io para arrancar.

## Módulos

1. **Lead Gen automático** — Apollo.io + Hunter.io + Google Maps scraping → Supabase
2. **Email outreach** — Gmail API desde cafeclout@gmail.com, secuencia 3 emails con variables
3. **Follow-ups automáticos** — Días 4 y 9, solo a no-respondedores
4. *(Futuro)* **WhatsApp bot** — Respuesta automática a consultas mayoristas
5. *(Futuro)* **Instagram DMs** — Captación de leads desde IG

## Stack

- **Orquestación:** n8n self-hosted (mismo VPS Hetzner que Biograffiti si existe, o nuevo CX22)
- **DB:** Supabase (PostgreSQL) — tabla `leads` con estado del pipeline
- **Lead gen:** Apollo.io API + Hunter.io API + Google Maps Places API
- **Email outbound:** Gmail API (OAuth2 desde cafeclout@gmail.com)
- **IA texto:** Claude API (personalización de emails por rubro/contacto)

## Costo estimado mensual

| Servicio | Plan | Costo |
|---|---|---|
| n8n (Hetzner CX22) | Self-hosted | ~USD 5/mes |
| Supabase | Free tier | USD 0 |
| Apollo.io | Basic (50 exports/mes) | USD 49/mes |
| Hunter.io | Starter (500 búsquedas) | USD 34/mes |
| Gmail API | Free (10k envíos/día) | USD 0 |
| Claude API | ~1k llamadas/mes | ~USD 3/mes |
| **Total** | | **~USD 91/mes** |

> Alternativa low-cost: solo Hunter.io + Google Maps manual → USD 34/mes

## Documentación

- [docs/01-plan.md](docs/01-plan.md) — Fases y timeline
- [docs/02-cuentas.md](docs/02-cuentas.md) — Cuentas a crear
- [docs/03-decisiones.md](docs/03-decisiones.md) — Decisiones técnicas
- [docs/04-pipeline.md](docs/04-pipeline.md) — Estados del lead y flujo completo
