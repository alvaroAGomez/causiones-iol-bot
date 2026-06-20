# 📈 Causiones IOL Bot

Bot de Telegram que monitorea en tiempo real las tasas de cauciones bursátiles desde InvertirOnline (IOL), enviando alertas personalizadas a cada usuario cuando se detectan oportunidades según sus preferencias.

También expone una API HTTP (FastAPI) con las estadísticas del día para integración con dashboards o aplicaciones externas.

---

## ✨ Características principales

### Para usuarios
- **Alertas automáticas** cuando la tasa supera tu objetivo personal.
- **Configuración flexible** desde un menú interactivo (`/menu`):
  - Tasa objetivo (TNA mínima para alertar).
  - Frecuencia de escaneo (cada cuántos minutos revisa el mercado).
  - Filtro anti-spam (variación mínima entre alertas).
  - Días de plazo a seguir en el gráfico personalizado.
  - Activar/desactivar Top 3 mejores tasas en las alertas.
- **Gráficos de tendencia** general y personalizado.
- **Top 3** mejores tasas del momento incluidas en las alertas.
- **Alertas críticas** (tasas extremas) con mensaje pinneado automáticamente.

### Para el administrador
- Modo **Abierto/Cerrado**: controla si los nuevos usuarios se aprueban automáticamente o requieren autorización manual.
- **Aprobación de usuarios** pendientes con botones inline.
- **Lista de usuarios** con estado (VIP / Pendiente).
- **Estadísticas** del bot (total usuarios, tokens, etc.).

### API HTTP
- Endpoint de estadísticas del día (tasa máxima, mínima, promedio, última).
- Endpoint de health check.
- Protección opcional con API Key (header `X-API-Key`).
- CORS configurado para integración con frontends.

---

## 📁 Estructura del proyecto

```
├── main.py                 # Entrypoint: bot + API en el mismo event loop
├── config.py               # Variables de entorno y constantes
├── api/
│   └── app.py              # App FastAPI y endpoints
├── bot/
│   ├── handlers.py         # Comandos y lógica del bot
│   └── formateo.py         # Formateo de mensajes y reportes
├── services/
│   ├── caucion_service.py  # Lógica de negocio y análisis
│   ├── scraper_iol.py      # Scraping de datos de IOL
│   ├── cache_service.py    # Caché de datos recientes
│   └── historial_service.py# Historial de puntos de datos
├── models/
│   └── models.py           # Modelos de datos (dataclasses)
├── requirements.txt
├── env.example             # Plantilla de variables de entorno
└── .gitignore
```

---

## 🛠️ Requisitos

- Python 3.10+
- pip

### Dependencias principales

| Paquete | Uso |
|---------|-----|
| python-telegram-bot | Framework del bot |
| fastapi + uvicorn | API HTTP |
| requests | Peticiones HTTP |
| pandas + lxml | Parsing de tablas HTML |
| matplotlib | Generación de gráficos |
| python-dotenv | Carga de `.env` |
| pytz | Manejo de zonas horarias |

---

## 🚀 Instalación

1. **Clonar el repositorio**

2. **Crear entorno virtual:**

```bash
python -m venv .venv
```

3. **Activar entorno virtual:**

Windows:
```bat
.venv\Scripts\activate
```

Linux/macOS:
```bash
source .venv/bin/activate
```

4. **Instalar dependencias:**

```bash
pip install -r requirements.txt
```

---

## ⚙️ Configuración

1. Copiar la plantilla de variables de entorno:

```bash
cp env.example .env
```

2. Completar las variables en `.env`:

| Variable | Requerida | Descripción |
|----------|-----------|-------------|
| `TELEGRAM_BOT_TOKEN` | ✅ | Token del bot obtenido de @BotFather |
| `TELEGRAM_ADMIN_ID` | ❌ | Chat ID del administrador (si no se setea, no hay funciones admin) |
| `DONAR_ALIAS_PPAY` | ❌ | Alias para donaciones por Personal Pay |
| `DONAR_LEMONTAG` | ❌ | LemonTag para donaciones por Lemon |
| `DONAR_USDT_TRC20` | ❌ | Dirección USDT (TRC20) para donaciones crypto |
| `DONAR_MP_LINK` | ❌ | Link de Mercado Pago para donaciones |
| `API_HOST` | ❌ | Host de la API (default configurable) |
| `API_PORT` | ❌ | Puerto de la API (default configurable) |
| `API_KEY` | ❌ | Clave para proteger el endpoint (si está vacío, es público) |

---

## ▶️ Ejecución

```bash
python main.py
```

Esto inicia simultáneamente:
- 🤖 El bot de Telegram (polling)
- 🌐 La API HTTP

---

## 🤖 Comandos del Bot

### Comandos de usuario

| Comando | Descripción |
|---------|-------------|
| `/start` | Registrarse / iniciar el bot |
| `/menu` | Menú interactivo de configuración |
| `/ahora` | Ver tasas actuales del mercado |
| `/tendencia` | Gráfico general de tendencia del día |
| `/mitendencia` | Gráfico personalizado (plazo configurado) |
| `/ayuda` | Guía de uso detallada |
| `/donar` | Opciones para apoyar el bot |
| `/stop` | Detener alertas automáticas |

### Comandos de administrador

| Comando | Descripción |
|---------|-------------|
| `/modo` | Alternar entre modo Abierto/Cerrado |
| `/pendientes` | Ver y aprobar/rechazar solicitudes |
| `/usuarios` | Lista completa de usuarios registrados |
| `/stats` | Estadísticas generales del bot |

---

## 🌐 API HTTP

### Endpoints

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/api/estadisticas/hoy` | Estadísticas de cauciones del día |

### Autenticación

Si `API_KEY` está configurada, se requiere el header:

```
X-API-Key: <tu_clave>
```

### Ejemplo de respuesta

```json
{
  "fecha": "2026-05-24",
  "mercado_abierto": true,
  "total_registros": 48,
  "tasa_minima": 42.50,
  "tasa_maxima": { "valor": 68.75, "hora": "14:35:12" },
  "promedio": 55.30,
  "ultima_tasa": { "valor": 63.10, "hora": "17:30:02" }
}
```

---

## 📋 Notas

- El archivo `.env` está excluido de git por seguridad.
- `bot_datos.pickle` (persistencia de usuarios) también se ignora en git.
- El bot opera en horario de mercado argentino (lunes a viernes, horario bursátil).
- Los datos se scrapean periódicamente y se mantienen en caché para optimizar rendimiento.
- El archivo `Causiones-IOL-Bot.py` es una versión legacy monolítica; el entrypoint recomendado es `main.py`.
