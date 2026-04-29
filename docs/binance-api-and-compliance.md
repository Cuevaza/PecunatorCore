# Binance API & WebSocket: límites y cumplimiento (referencia)

Documento de **consulta** para PecunatorCore. Los límites y políticas **cambian**; Binance es la fuente de verdad.

| Meta | Valor |
|------|--------|
| **Última revisión** | 2026-04-29 |
| **Próxima revisión sugerida** | Tras cada actualización mayor del motor o del FAQ de Binance |

### Snapshots históricos (`exchangeInfo.rateLimits`)

Capturas fechadas del endpoint público Spot (solo `rateLimits` + metadatos) para **análisis histórico**:

- Carpeta: [`binance-limits-snapshots/`](binance-limits-snapshots/)
- Script: [`scripts/fetch_binance_exchange_info_limits.py`](../scripts/fetch_binance_exchange_info_limits.py)

---

## 1. Fuentes oficiales (mantener enlaces actualizados)

Audita periódicamente:

| Tema | URL |
|------|-----|
| Límites REST (Spot) | https://developers.binance.com/docs/binance-spot-api-docs/rest-api/limits |
| Límites WebSocket API | https://developers.binance.com/docs/binance-spot-api-docs/websocket-api/rate-limits |
| Streams WebSocket (Spot) | https://github.com/binance/binance-spot-api-docs/blob/master/web-socket-streams.md |
| FAQ API (límites duros, WAF, bans) | https://www.binance.com/en/support/faq/detail/360004492232 |
| Changelog API | https://developers.binance.com/docs/binance-spot-api-docs |

> Nota regional: si usas otro dominio (p. ej. `.info`), verifica que la política coincida con tu jurisdicción y producto (Spot vs Futures).

---

## 2. Conceptos que debes internalizar

### 2.1 Peso de peticiones (`REQUEST_WEIGHT`), no “un request = una unidad”

- Cada endpoint REST tiene un **peso** distinto; el consumo se acumula por **IP** (Spot REST típico).
- Las respuestas pueden incluir cabeceras del tipo `X-MBX-USED-WEIGHT-*` y, según endpoint, el cuerpo puede incluir información de `rateLimits`.
- Superar el límite → HTTP **429**. Insistir sin backoff puede llevar a **418** (ban por IP con duración escalable).

### 2.2 Órdenes (`ORDERS`)

- Existen límites **por cuenta** para creación de órdenes en ventanas de tiempo (p. ej. por 10 segundos y por 24 horas). Los valores exactos aparecen en documentación y FAQ; **no los fijes en código como constantes eternas**.
- Órdenes rechazadas pueden no incrementar ciertos contadores; revisa la documentación vigente.

### 2.3 Web Application Firewall (WAF)

- Patrones de tráfico sospechosos o excesivos pueden producir **403** u otros bloqueos **por IP**, con duración típica mencionada en FAQ (p. ej. del orden de minutos si es abuso leve).
- No intentes “evadir” límites; reduce frecuencia y usa streams donde corresponda.

### 2.4 WebSocket — streams de mercado (Spot)

Según el documento de streams en el repositorio público de Binance (comprueba siempre la última versión):

- Conexión única válida ~**24 h**; prevé reconexión.
- Servidor envía **ping** periódico; el cliente debe responder **pong** correctamente o la conexión cae.
- Límite típico de mensajes entrantes de control (**subscribe/unsubscribe**, ping/pong): del orden de **5 mensajes por segundo** por conexión; exceder puede desconectar y repetir puede banear la IP.
- Hasta **1024 streams** por conexión (según doc actual).
- Límite de **nuevas conexiones por ventana de tiempo por IP** (p. ej. **300 intentos / 5 minutos** — ver texto oficial).

### 2.5 WebSocket API (API sobre WS)

- Límites de **peso** y de **conexiones** están documentados aparte del REST; una conexión nueva puede tener coste de peso > 0 (p. ej. históricamente **2** unidades de peso — ver doc actual).
- Parámetros como `returnRateLimits` afectan el tamaño de las respuestas, **no** el hecho de estar limitado.

---

## 3. Cómo se relaciona esto con PecunatorCore

| Área | Comportamiento recomendado |
|------|----------------------------|
| **Polling REST** | Ajusta `PECUNATOR_ACCOUNT_POLL_SEC` en `runtime/core/settings.py` si ves 429 o latencia excesiva. |
| **Credenciales** | Usa el **vault** cifrado (`runtime/data/`) o variables de entorno; no incrustes claves en Flutter ni en repos. |
| **exampleJV** | Script opcional `scripts/run_engine_with_examplejv.py` solo **inyecta** claves desde `exampleJV/config.py` al proceso sin imprimirlas. |
| **Órdenes / bots** | Respeta filtros de símbolo (`PRICE_FILTER`, `LOT_SIZE`, notional mínimo); errores de precisión son responsabilidad de la estrategia, no de Binance “flexibilizar” reglas. |

---

## 4. Lista de verificación ante incidentes

1. ¿HTTP **429**? → Reduce frecuencia, espera `Retry-After` si viene en cabecera, revisa peso acumulado.
2. ¿HTTP **418**? → No reintentes en bucle; espera el tiempo indicado y corrige la estrategia de polling.
3. ¿**403** WAF? → Revisa volumen y patrones; espera ventana de bloqueo.
4. ¿WS desconectado? → Implementa backoff exponencial y reconexión; respuesta correcta a ping/pong.

---

## 5. Cumplimiento y términos de uso

- Las [Condiciones de uso](https://www.binance.com/en/terms) y políticas aplicables al **uso de API** prevalecen sobre cualquier automatización local.
- Este proyecto es software de **automatización local**; el operador es responsable del cumplimiento normativo (KYC, jurisdicciones, productos permitidos).

---

## 6. Historial de cambios en este documento

| Fecha | Cambio |
|-------|--------|
| 2026-04-29 | Creación: enlaces oficiales, conceptos REST/WS/WAF, relación con PecunatorCore. |
| 2026-04-29 | Snapshots `exchangeInfo.rateLimits` en `docs/binance-limits-snapshots/`; motor/UI peso REST. |

*Para actualizar: edita la tabla del §6 y la fecha de “Última revisión” arriba.*
