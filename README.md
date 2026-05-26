# Causiones IOL Bot

Bot de Telegram para monitorear tasas de cauciones en IOL, con API HTTP en FastAPI para exponer estadisticas del dia.

## Caracteristicas

- Bot de Telegram con alertas configurables por usuario.
- Recoleccion periodica de datos de cauciones.
- Comandos para tendencia general y personalizada.
- Endpoint HTTP con estadisticas diarias.
- API Key opcional para proteger el endpoint.

## Estructura del proyecto

- `main.py`: entrypoint principal (bot + API en el mismo event loop).
- `config.py`: carga y validacion de variables de entorno.
- `api/app.py`: app FastAPI y endpoints.
- `bot/`: handlers y formateo de mensajes.
- `services/`: scraping, cache, historial y logica de negocio.
- `models/`: modelos de datos.

## Requisitos

- Python 3.10+
- `pip`

Dependencias (ver `requirements.txt`):

- python-telegram-bot==20.7
- fastapi
- uvicorn[standard]
- requests
- pandas
- lxml
- matplotlib
- python-dotenv
- pytz

## Instalacion

1. Crear entorno virtual:

```bash
python -m venv .venv
```

2. Activar entorno virtual:

Windows (cmd):

```bat
.venv\Scripts\activate
```

Linux/macOS:

```bash
source .venv/bin/activate
```

3. Instalar dependencias:

```bash
pip install -r requirements.txt
```

## Configuracion

1. Copiar archivo de ejemplo:

```bash
copy env.example .env
```

En Linux/macOS:

```bash
cp env.example .env
```

2. Completar variables en `.env`:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_ADMIN_ID`
- `DONAR_ALIAS_PPAY`
- `DONAR_LEMONTAG`
- `DONAR_USDT_TRC20`
- `DONAR_MP_LINK`
- `API_HOST` (default: `0.0.0.0`)
- `API_PORT` (default: `8000`)
- `API_KEY` (opcional)

## Ejecucion

Correr bot + API:

```bash
python main.py
```

## Endpoint API

- `GET /health`
- `GET /api/estadisticas/hoy`

Si `API_KEY` esta configurada, enviar header:

- `X-API-Key: <tu_clave>`

Ejemplo:

```bash
curl -H "X-API-Key: tu_clave" http://localhost:8000/api/estadisticas/hoy
```

## Comandos utiles del bot

- `/start`
- `/ahora`
- `/tendencia`
- `/mitendencia`
- `/set`
- `/tiempo`
- `/variacion`
- `/set_tendencia`
- `/top3`

Comandos admin:

- `/usuarios`
- `/stats`
- `/gen`
- `/tokens`

## Notas

- Este repositorio ignora `.env` por seguridad.
- `bot_datos.pickle` (persistencia local) tambien se ignora en git.
- El archivo `Causiones-IOL-Bot.py` existe como version monolitica legacy; el entrypoint recomendado es `main.py`.
