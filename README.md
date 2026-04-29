# PecunatorCore

PecunatorCore is a modular trading runtime with a local Python engine and a dedicated Flutter desktop UI.
This repository is **desktop-first**: there is **no browser dashboard**.

## Directiva de trabajo

| Ámbito | Idioma |
|--------|--------|
| Este IDE, conversación y coordinación entre nosotros | **Español latino**, por defecto |
| Código fuente, nombres de símbolos, comentarios en código, mensajes de commit orientados al repositorio, y demás artefactos de implementación | **Inglés** |

## Flutter desktop (UI)

1. Instalar [Flutter SDK (Windows)](https://docs.flutter.dev/get-started/install/windows).
2. En la raíz del repo: `powershell -ExecutionPolicy Bypass -File scripts/init_flutter_desktop.ps1`
3. Abrir `desktop_shell/` en el IDE Flutter y ejecutar (p. ej. `flutter run -d windows`).
4. Producción Windows: `flutter build windows` y ejecutar `desktop_shell/build/windows/x64/runner/Release/pecunator_desktop.exe`.

**Limpiar caché y recompilar la UI:** cierra la app (`pecunator_desktop.exe`) para liberar DLLs; en `desktop_shell/` ejecuta `flutter clean`, luego `flutter pub get` y `flutter build windows` (o `flutter run -d windows`). Datos del hub en SQLite: `runtime/data/dorothy_hub.sqlite` (elimínalo solo si quieres resetear logs/config del hub; haz copia antes).

Más detalle: [`docs/architecture-next.md`](docs/architecture-next.md).

## Motor Python (HTTP API)

Por defecto **`python main.py`** levanta la API en **http://127.0.0.1:8765** (ajusta con `PECUNATOR_API_HOST` / `PECUNATOR_API_PORT`). Opcional: **`PECUNATOR_API_WEIGHT_LIMIT_1M`** (por defecto `6000`) alinea la barra de “peso REST” en la UI con el límite de referencia de `exchangeInfo`.

- OpenAPI: http://127.0.0.1:8765/docs  
- Solo stub de log (sin servidor): `PECUNATOR_ENGINE_STUB=1 python main.py`

Conectores Binance (`python-binance`), cofre y estado: `runtime/` (ver `runtime/api/`).

- **Límites de API / WebSocket y cumplimiento (referencia actualizable):** [`docs/binance-api-and-compliance.md`](docs/binance-api-and-compliance.md)

### Credenciales desde `exampleJV/`

El ejemplo histórico usa `exampleJV/config.py` (ver `config.example.py`). Para arrancar el motor inyectando esas claves al proceso (sin imprimirlas):

`python scripts/run_engine_with_examplejv.py`

Las mismas variables pueden definirse a mano: `PECUNATOR_BINANCE_API_KEY`, `PECUNATOR_BINANCE_API_SECRET`.

## API surface (current)

- Vault + credenciales:
  - `GET /api/v1/vault/status`
  - `GET /api/v1/vault/credentials`
  - `POST /api/v1/vault/credentials`
  - `PATCH /api/v1/vault/credentials/{credential_id}`
  - `POST /api/v1/vault/credentials/{credential_id}/activate`
  - `POST /api/v1/vault/credentials/{credential_id}/delete`
  - `GET /api/v1/credentials/active`
- Gateway Binance:
  - `POST /api/v1/gateway/start`
  - `POST /api/v1/gateway/stop`
  - `GET /api/v1/gateway/snapshot`
  - `POST /api/v1/gateway/fetch_account`
  - `GET /api/v1/account/wallets?base_asset=USDT`
  - `POST /api/v1/time/sync`
- Hub Dorothy (multi-instancia):
  - `GET /api/v1/hub/bots`
  - `POST /api/v1/hub/bots`
  - `PATCH /api/v1/hub/bots/{bot_id}`
  - `DELETE /api/v1/hub/bots/{bot_id}`
  - `POST /api/v1/hub/bots/{bot_id}/start`
  - `POST /api/v1/hub/bots/{bot_id}/stop`
  - `POST /api/v1/hub/bots/{bot_id}/run_once`
  - `GET /api/v1/hub/bots/{bot_id}/logs`

Legacy single-bot endpoints remain available under `/api/v1/bot/*` for compatibility.

## Documentación

- [`docs/architecture-next.md`](docs/architecture-next.md) — arquitectura Flutter + motor  
- [`docs/binance-api-and-compliance.md`](docs/binance-api-and-compliance.md) — límites Binance REST/WebSocket y checklist  
- [`docs/binance-limits-snapshots/`](docs/binance-limits-snapshots/) — snapshots fechados de `exchangeInfo.rateLimits`  
- [`docs/git-cursor-github.md`](docs/git-cursor-github.md) — Git / Cursor / GitHub  
