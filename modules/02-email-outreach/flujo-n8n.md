# Módulo 02 — Email Outreach automatizado

## Flujo principal (n8n workflow)

```
[Cron 09:00 L-V]
       ↓
[Supabase: SELECT leads WHERE estado='encolado' LIMIT 50]
       ↓
[Para cada lead:]
  → Claude API: personalizar apertura según rubro + nombre
  → Gmail API: enviar email 1
  → Supabase: UPDATE estado='email_1_enviado', email_1_at=now(), thread_id={gmail_thread_id}
       ↓
[Log en Supabase: tabla email_logs]
```

## Flujo follow-up 1 (email 2)

```
[Cron 09:00 L-V]
       ↓
[Supabase: SELECT WHERE estado='email_1_enviado' AND email_1_at < now()-interval '4 days']
       ↓
[Verificar respuesta en Gmail thread_id]
  → Si respondió: UPDATE estado='respondio'
  → Si no respondió:
    → Gmail API: reply al mismo thread (email 2)
    → UPDATE estado='email_2_enviado', email_2_at=now()
```

## Flujo follow-up 2 (email 3)

```
[Cron 09:00 L-V]
       ↓
[Supabase: SELECT WHERE estado='email_2_enviado' AND email_2_at < now()-interval '5 days']
       ↓
[Verificar respuesta en Gmail thread_id]
  → Si respondió: UPDATE estado='respondio'
  → Si no respondió:
    → Gmail API: reply al mismo thread (email 3)
    → UPDATE estado='email_3_enviado'
```

## Detección de respuestas

```
[Cron cada 1 hora]
       ↓
[Gmail API: buscar mensajes en inbox desde la última hora]
       ↓
[Para cada mensaje encontrado:]
  → Buscar thread_id en tabla leads
  → Si match: UPDATE estado='respondio', respondio_at=now()
  → Notificar a Belén por WhatsApp (opcional en fase 1)
```

## Personalización con Claude

El email 1 tiene una apertura genérica por defecto. Claude puede personalizarla:

**Prompt:**
```
Sos Belén de Clout Café, un tostadero artesanal de Buenos Aires.
Escribí UNA oración de apertura personalizada para un email frío a:
- Nombre del lugar: {{nombre_lugar}}
- Rubro: {{rubro}}
- Barrio: {{barrio}}

La oración debe sonar humana, específica al negocio, y llevar naturalmente a presentar Clout Café.
Máximo 25 palabras. Sin emojis. Sin "espero que" ni frases cliché.
Devolvé solo la oración, sin explicación.
```

**Ejemplo output:** "Un bar de Palermo que cuida la experiencia hasta el último detalle merece un café que esté a la altura."

## Gmail API — configuración

**Autenticación:** OAuth2 con refresh token (más seguro que App Password para n8n)

**Nodo n8n:** Gmail → Send → Reply to thread

**Headers necesarios:**
- `References: <thread_id>`
- `In-Reply-To: <thread_id>`
(n8n Gmail node lo hace automáticamente al usar "Reply to message")

## Rate limits y protección

- Máx. 50 emails/día (autoimpuesto, Gmail permite 500)
- Solo L-V 09:00-17:00 ART
- Delay de 30-60 segundos entre envíos (evita detección de spam)
- Si Gmail devuelve error 429: pausar workflow, notificar
