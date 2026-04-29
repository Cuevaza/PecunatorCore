# Binance Spot API — snapshots de `rateLimits` (análisis histórico)

Cada archivo JSON es una **captura puntual** del endpoint público:

`GET https://api.binance.com/api/v3/exchangeInfo`

Se guardan solo campos útiles para límites: `serverTime`, `timezone`, `rateLimits`.

## Cómo generar una nueva captura

Desde la raíz del repo (con red):

```powershell
.\.venv\Scripts\python.exe scripts\fetch_binance_exchange_info_limits.py
```

O manualmente con `curl`/navegador y pegar `rateLimits` en un nuevo archivo nombrado:

`exchangeInfo-rateLimits-YYYY-MM-DD.json`

## Interpretación

- `rateLimits` describe **ventanas** (`interval`, `intervalNum`) y **tipos** (`REQUEST_WEIGHT`, `RAW_REQUESTS`, `ORDERS`, etc.) según la respuesta en esa fecha.
- Los valores **cambian**; este directorio sirve para **comparar en el tiempo**, no como constantes fijas en código.
