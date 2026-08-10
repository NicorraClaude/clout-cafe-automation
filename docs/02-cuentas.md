# Cuentas a crear — Clout Café Automation

> Lo que Nico/Belén tienen que hacer manualmente. Claude Code hace todo lo demás.

## Pendientes

### 1. Apollo.io
- **URL:** https://app.apollo.io/
- **Plan:** Basic (USD 49/mes) o Free (10 exports/mes para testear)
- **Para qué:** Búsqueda de contactos B2B por rubro + zona geográfica. Tiene emails verificados.
- **Qué traer:** API Key (Settings → Integrations → API)
- **Rubros a buscar:** "restaurant", "hotel", "bar", "cafe", "coworking" + Buenos Aires, Argentina

### 2. Hunter.io
- **URL:** https://hunter.io/
- **Plan:** Starter (USD 34/mes, 500 búsquedas) o Free (25/mes para testear)
- **Para qué:** Encontrar emails de contacto por dominio de empresa
- **Qué traer:** API Key (Dashboard → API)

### 3. Gmail API (OAuth2 para cafeclout@gmail.com)
- **URL:** https://console.cloud.google.com/
- **Pasos:**
  1. Crear proyecto "Clout Outreach"
  2. Habilitar Gmail API
  3. Crear credenciales OAuth2 (Desktop App)
  4. Descargar `credentials.json`
  5. Traer el archivo JSON a Claude Code
- **Alternativa más fácil:** App Password de Gmail (si 2FA está activado en cafeclout@gmail.com)
  - Settings → Security → App passwords → crear "Clout n8n"
  - Traer el password de 16 caracteres

### 4. Google Maps Places API (opcional, para scraping local)
- **URL:** https://console.cloud.google.com/ (mismo proyecto)
- **Para qué:** Buscar bares/restaurantes/hoteles en CABA con email
- **Costo:** USD 0 (tiene free tier de USD 200/mes de crédito)
- **Qué traer:** API Key

### 5. Supabase (base de datos de leads)
- **URL:** https://supabase.com/
- **Plan:** Free tier (suficiente para empezar)
- **Para qué:** Guardar leads, estado del pipeline, historial de emails enviados
- **Qué traer:** URL del proyecto + anon key + service role key

### 6. n8n
- **Opción A — Compartir VPS con Biograffiti** (si el Hetzner ya está corriendo): sin costo extra
- **Opción B — n8n Cloud** (más fácil): https://n8n.io/ → Starter USD 20/mes, sin VPS propio
- **Opción C — Nuevo VPS Hetzner CX22**: USD 5/mes (Claude Code instala n8n con Docker)

## Ya disponibles

- ✅ cafeclout@gmail.com — cuenta de envío
- ✅ clout.ar — dominio verificado en Resend (pero para outreach usaremos Gmail)
- ✅ Resend (pedidos@clout.ar) — para transaccional, NO para outreach frío

## Orden de prioridad

1. Gmail App Password (más rápido, 5 minutos) → desbloquea el módulo de email
2. Supabase (5 minutos) → base de datos
3. Apollo.io o Hunter.io → fuente de leads
4. n8n → orquestador (último paso, necesita todo lo anterior)
