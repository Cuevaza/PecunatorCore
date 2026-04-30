# exampleJV_enhanced

Versiones mejoradas de los 3 bots de `exampleJV/` (Dorothy7.0, Masha2.0, Thusnelda1.0).
**No reemplazan** a los originales: viven en paralelo para comparar y validar.

## Mejoras aplicadas a los 3 bots

Cada bot recibió **únicamente** las siguientes mejoras (respetando arquitectura
y estilo originales). Los cambios están marcados en el código con
`# [MEJORA] ...` para identificarlos rápido.

### 1. Stop-loss / protección por drawdown
Módulo `risk_manager.py`.
- **Drawdown global:** si el equity cae bajo el peak histórico más allá de
  `MAX_DRAWDOWN_PCT`, el bot **deja de abrir nuevas compras** hasta que la
  cuenta se recupere. Antes los bots seguían comprando indefinidamente en
  mercados bajistas prolongados.
- **Stop-loss por posición:** si el precio cae bajo el precio de referencia
  (compra individual / DCA / promedio multi-símbolo) × `(1 - STOP_LOSS_PCT)`,
  liquida esa posición a mercado. Antes no había salida en pérdida; el
  capital quedaba atrapado.

### 2. Persistencia de estado robusta
Módulo `state_store.py` (SQLite local).
- Tabla `bot_state` (clave/valor): peak de equity, último precio de compra,
  flags de bloqueo. Sustituye la dependencia de órdenes vivas en Binance
  para reconstruir contexto.
- Tabla `trades`: cada compra y venta (BUY/SELL, MARKET/LIMIT) con qty,
  price y cost. Permite reanalizar performance offline.
- Tabla `equity_snapshots`: serie temporal del equity. Base de la curva.
- Tabla `metrics_log`: histórico de Sharpe/win-rate/max-DD.
- Reanudación: el bot reconstruye `peak_equity` al arrancar.

### 3. Métricas de performance
Módulo `metrics.py`. Cálculo cada `METRICS_INTERVAL_CYCLES` ciclos y
persistencia en `metrics_log`.
- **Win rate:** trades cerrados (BUY emparejado FIFO con SELL) con PnL > 0
  sobre total de trades cerrados.
- **Sharpe:** `mean(returns) / stdev(returns) × sqrt(N)` sobre los retornos
  por par BUY→SELL.
- **Max drawdown:** peak-to-trough sobre la curva de equity registrada.

## Variables nuevas (configurar al inicio de cada `main.py`)

| Variable | Descripción | Default sugerido |
|----------|-------------|------------------|
| `BOT_NAME` | Identificador único en la DB | `"dorothy"`, `"masha"`, `"thusnelda"` |
| `DB_PATH` | Ruta del SQLite local | `./<bot>_state.db` |
| `MAX_DRAWDOWN_PCT` | Drawdown máximo tolerado (decimal) | `Decimal("0.20")` (20%) |
| `STOP_LOSS_PCT` | Pérdida máxima por posición (decimal o `None`) | `Decimal("0.10")` (10%) |
| `EQUITY_BASE_ASSET` | Activo de referencia para equity | `"USDT"` |
| `METRICS_INTERVAL_CYCLES` | Cada cuántos ciclos calcular métricas | `5` |

## Estructura

```
exampleJV_enhanced/
├── Dorothy7.1/
│   ├── main.py               # original + [MEJORA]
│   ├── accesoAPI.py
│   ├── state_store.py        # NUEVO
│   ├── risk_manager.py       # NUEVO
│   └── metrics.py            # NUEVO
├── Masha2.1/
│   ├── main.py               # original + [MEJORA]
│   ├── accesoAPI.py
│   ├── solicitarOHLCAPI.py
│   ├── obtenerPosicionOrdenSellLimit.py
│   ├── compraMarket.py
│   ├── solicitaBalancesAPI.py
│   ├── actualizarOrdenSellLimitDCA.py
│   ├── obtenerUltimaCompra.py
│   ├── state_store.py        # NUEVO
│   ├── risk_manager.py       # NUEVO
│   └── metrics.py            # NUEVO
└── Thusnelda1.1/
    ├── main.py               # original + [MEJORA]
    ├── accesoAPI.py
    ├── simbolos.txt
    ├── state_store.py        # NUEVO
    ├── risk_manager.py       # NUEVO
    └── metrics.py            # NUEVO
```

## Credenciales

Igual que los bots originales: `config.py` (no versionado) o variables de
entorno `PECUNATOR_BINANCE_API_KEY` / `PECUNATOR_BINANCE_API_SECRET`. El
`accesoAPI.py` es idéntico al original.

## Inspección rápida de la DB

```bash
sqlite3 dorothy_state.db
sqlite> SELECT * FROM metrics_log ORDER BY id DESC LIMIT 5;
sqlite> SELECT ts_utc, equity_usdt FROM equity_snapshots ORDER BY id DESC LIMIT 20;
sqlite> SELECT side, qty, price, cost FROM trades ORDER BY id DESC LIMIT 20;
```
