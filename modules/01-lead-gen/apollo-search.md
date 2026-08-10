# Módulo 01 — Lead Gen automático

## Fuentes

### A) Apollo.io (principal)

**Endpoint:** `POST https://api.apollo.io/v1/mixed_people/search`

**Filtros para Clout Café:**
```json
{
  "person_titles": ["owner", "manager", "food and beverage manager", "chef", "dueño", "encargado", "gerente"],
  "organization_industry_tag_ids": ["restaurant", "food and beverage", "hospitality", "hotels"],
  "person_locations": ["Buenos Aires, Argentina"],
  "contact_email_status": ["verified"],
  "per_page": 25
}
```

**Flujo en n8n:**
1. Cron: lunes 08:00 ART
2. Llamada a Apollo API → lista de contactos con email
3. Deduplicar contra tabla `leads` en Supabase (por email)
4. Insertar nuevos con estado `nuevo`
5. Encolar hasta 50 por día (estado → `encolado`)

### B) Hunter.io (complementario)

**Para cuando tenemos el dominio de un negocio:**
`GET https://api.hunter.io/v2/domain-search?domain={dominio}&api_key={key}`

**Flujo:** recibe dominio → devuelve emails → filtra por pattern (info@, contacto@, reservas@) → inserta en Supabase

### C) Google Maps Places (para negocios locales)

**Búsquedas programadas:**
- `restaurant in Palermo, Buenos Aires`
- `bar in San Telmo, Buenos Aires`
- `boutique hotel Buenos Aires`
- `coworking space Buenos Aires`
- `cafeteria especialidad Buenos Aires`

**Limitación:** Google Maps no siempre devuelve email directo. Se obtiene el sitio web → Hunter.io busca el email del dominio.

**Flujo:**
1. Places API → lista de negocios con website
2. Para cada website → Hunter.io domain search
3. Si encuentra email → insertar en `leads`

## Volumen esperado

| Fuente | Leads/semana | Calidad |
|---|---|---|
| Apollo.io | 100-200 | Alta (email verificado, cargo validado) |
| Hunter.io | 20-50 | Media-Alta |
| Google Maps + Hunter | 30-60 | Media |
| **Total** | **150-310/semana** | |

Con límite de 50 emails/día → la cola se procesa en 3-6 días por semana de ingresos.
