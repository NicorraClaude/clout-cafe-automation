# Pipeline de leads — Estados y flujo

## Estados de un lead

```
nuevo → encolado → email_1_enviado → email_2_enviado → email_3_enviado → cerrado
                        ↓                  ↓                  ↓
                   respondió          respondió          respondió
                       ↓                  ↓                  ↓
                    cliente            cliente            cliente
```

| Estado | Significado |
|---|---|
| `nuevo` | Lead importado, aún no contactado |
| `encolado` | Validado, listo para enviar email 1 |
| `email_1_enviado` | Email inicial enviado |
| `email_2_enviado` | Follow-up 1 enviado (día 4) |
| `email_3_enviado` | Follow-up 2 enviado (día 9) |
| `respondio` | El contacto respondió (cualquier email) |
| `muestra_pedida` | Pidió muestra de café |
| `cliente` | Primer pedido confirmado |
| `descartado` | No interesado / email inválido / unsubscribe |

## Reglas de automatización

1. **Email 1** → se envía el mismo día que el lead entra con estado `encolado`
2. **Email 2** → se envía si `email_1_enviado` Y no respondió en 4 días calendario
3. **Email 3** → se envía si `email_2_enviado` Y no respondió en 5 días más
4. **Detección de respuesta** → n8n monitorea la bandeja de cafeclout@gmail.com cada hora; si detecta respuesta al thread, marca como `respondio`
5. **Límite diario** → máximo 50 emails/día para proteger la reputación de Gmail
6. **Ventana de envío** → lunes a viernes, 9:00-17:00 ART (horario comercial)

## Tabla Supabase: `leads`

```sql
create table leads (
  id uuid primary key default gen_random_uuid(),
  nombre_contacto text,
  nombre_lugar text not null,
  email text not null unique,
  rubro text,           -- 'restaurante' | 'bar' | 'hotel' | 'oficina' | 'coworking'
  barrio text,
  ciudad text default 'Buenos Aires',
  fuente text,          -- 'apollo' | 'hunter' | 'maps' | 'instagram' | 'manual'
  estado text default 'nuevo',
  email_1_at timestamptz,
  email_2_at timestamptz,
  email_3_at timestamptz,
  respondio_at timestamptz,
  thread_id text,       -- Gmail thread ID para detectar respuestas
  notas text,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);
```
