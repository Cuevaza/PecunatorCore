# monitorPesos (exampleJV)

Herramienta **modular** para inspeccionar el consumo de **peso REST** (`X-MBX-USED-WEIGHT-1M`) en la misma IP que tus llamadas a Binance.

## “Grafiquita”

No genera imagen PNG: la visualización es una **barra ASCII en consola** (`▓` / `-`), igual que la lógica de ocupación que ahora refleja el **motor PecunatorCore** en la barra de progreso del desktop (snapshot del gateway).

## Configuración

1. Credenciales: copia `config.example.py` → **`config.py`** en `exampleJV/` (compartido con Dorothy), **o** define `PECUNATOR_BINANCE_API_KEY` / `PECUNATOR_BINANCE_API_SECRET`.
2. Escala del 100% de la barra (denominador): por defecto **6000** (Spot `exchangeInfo` típico). Ajusta con:
   - `MONITOR_PESOS_WEIGHT_TOTAL=6000`
   - o `PECUNATOR_API_WEIGHT_LIMIT_1M=6000` (alineado con el motor).

## Salida

- Consola: barra + porcentaje.
- `api_weight_MULTISYMBOL_log.csv`: series horarias para análisis (Excel, pandas, etc.).

## Integración PecunatorCore

El **gateway** del motor lee el mismo encabezado tras REST y expone `used_weight_1m` / `weight_limit_1m` en `GET /api/v1/gateway/snapshot`; la **UI Flutter** muestra la barra bajo el estado de API. Este script sigue siendo útil para depuración **fuera** del motor o para comparar con logs CSV históricos.
