# Bot de Telegram para Cauciones IOL

Bot automatizado que monitorea las tasas de cauciones en IOL (Invertir Online) y notifica a través de Telegram sobre oportunidades de inversión.

## 📋 Descripción

Este bot:
- **Monitorea en tiempo real** las tasas de cauciones del mercado argentino
- **Notifica automáticamente** cuando hay oportunidades según criterios configurables
- **Genera gráficos** del histórico de tasas
- **Mantiene historial** de datos para análisis
- **Soporta múltiples usuarios** con configuraciones personalizadas (autorización admin)

---

## 🔧 Requisitos Previos

- **Python 3.9+**
- **pip** (gestor de paquetes de Python)
- **Token de Bot de Telegram** (obtener de [@BotFather](https://t.me/botfather))
- **ID de Usuario de Telegram** (tu ID numérico de Telegram)

---

## 📦 Instalación de Dependencias

### Opción 1: Instalación Manual

```bash
pip install -r requirements.txt
```

### Opción 2: Instalación Individual

Si no tienes `requirements.txt`, instala manualmente:

```bash
pip install python-telegram-bot==20.7
pip install requests
pip install pandas
pip install lxml
pip install nest-asyncio
pip install matplotlib
pip install python-dotenv
pip install pytz
```

---

## ⚙️ Configuración

### 1. Crear archivo `.env`

En la raíz de la carpeta del proyecto, crea un archivo llamado `.env` con el siguiente contenido:

```env
# ── OBLIGATORIAS ──────────────────────────────────────────────
# Token del bot obtenido de @BotFather en Telegram
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklmnoPQRstuvWXYZ1234567890

# Tu ID de usuario de Telegram (número entero)
# Obtener en: https://t.me/userinfobot
TELEGRAM_ADMIN_ID=123456789

# ── DONACIONES (opcionales) ───────────────────────────────────
# Alias de Personal Pay (ej: mi.alias.ppay)
DONAR_ALIAS_PPAY=

# LemonTag de Lemon Cash (ej: @usuario)
DONAR_LEMONTAG=

# Dirección USDT en red TRC20
DONAR_USDT_TRC20=

# Link de pago de Mercado Pago
DONAR_MP_LINK=
```

| Variable | Requerida | Descripción |
|----------|-----------|-------------|
| `TELEGRAM_BOT_TOKEN` | ✅ Sí | Token del bot ([@BotFather](https://t.me/botfather)) |
| `TELEGRAM_ADMIN_ID` | ✅ Sí | Tu ID numérico de Telegram ([@userinfobot](https://t.me/userinfobot)) |
| `DONAR_ALIAS_PPAY` | ❌ No | Alias de Personal Pay para donaciones |
| `DONAR_LEMONTAG` | ❌ No | LemonTag de Lemon Cash |
| `DONAR_USDT_TRC20` | ❌ No | Dirección USDT (red TRC20) |
| `DONAR_MP_LINK` | ❌ No | Link de Mercado Pago |

> Las variables de donación son opcionales. Si están vacías, el botón `/donar` no mostrará esa opción.

**⚠️ IMPORTANTE**:
- No compartas tu `TELEGRAM_BOT_TOKEN` ni tu `TELEGRAM_ADMIN_ID`
- El archivo `.env` debe estar en la misma carpeta que el script Python
- El `.gitignore` ya excluye `.env` automáticamente

### 2. Estructura de Carpetas

```
bot IOL Causiones/
├── Causiones-IOL-Bot.py
├── .env                          # ← Crear este archivo
├── bot_datos_v13.pickle          # ← Se crea automáticamente
├── README.md
└── requirements.txt              # (opcional pero recomendado)
```

---

## 🚀 Ejecución Local (Desarrollo en VS Code)

### Paso 1: Preparar VS Code

1. Abre VS Code
2. Abre la carpeta: **File → Open Folder** → Selecciona `bot IOL Causiones`
3. Abre una terminal integrada: **Ctrl + `** (backtick)

### Paso 2: Crear y Activar Entorno Virtual (Recomendado)

```bash
# Windows
python -m venv venv
venv\Scripts\activate

# Linux/Mac
python3 -m venv venv
source venv/bin/activate
```

Verás `(venv)` al inicio de la línea de comando si está activado.

### Paso 3: Instalar Dependencias

```bash
pip install -r requirements.txt
# o si no tienes requirements.txt:
pip install python-telegram-bot==20.7 requests pandas lxml nest-asyncio matplotlib python-dotenv pytz
```

### Paso 4: Ejecutar el Bot

```bash
python Causiones-IOL-Bot.py
```

Deberías ver algo como:
```
INFO:root - Bot iniciado correctamente
INFO:root - Bot conectado a Telegram
```

### Paso 5: Usar el Bot en Telegram

1. Abre Telegram
2. Busca tu bot por el nombre que le diste a `@BotFather`
3. Envía `/start` para comenzar
4. Configura tus parámetros:
   - `/tasa XX.XX` - Tasa objetivo de interés
   - `/intervalo N` - Intervalo en minutos entre notificaciones
   - `/variacion X.X` - Variación mínima para alertar
   - `/grafico N` - Días a mostrar en el gráfico

---

## 📊 Comandos del Bot

| Comando | Descripción |
|---------|------------|
| `/start` | Inicia el bot |
| `/ayuda` | Muestra la ayuda |
| `/status` | Estado actual del bot |
| `/tasa [valor]` | Configura tasa objetivo |
| `/intervalo [minutos]` | Intervalo de monitoreo |
| `/variacion [valor]` | Variación mínima para alertas |
| `/grafico [días]` | Generar gráfico histórico |
| `/top3` | Mostrar top 3 tasas |

---

## 🌐 Deployment en Producción (Servidor)

### Opción 1: VPS Linux (Recomendado)

#### 1.1 Conectar al Servidor

```bash
ssh usuario@tu_servidor_ip
```

#### 1.2 Instalar Python y Dependencias del Sistema

```bash
sudo apt update
sudo apt install python3 python3-pip python3-venv -y
```

#### 1.3 Clonar o Copiar el Proyecto

```bash
cd /home/usuario
git clone https://tu_repositorio.git bot-cauciones
# O copiar manualmente via SCP:
# scp -r "bot IOL Causiones" usuario@tu_servidor_ip:/home/usuario/bot-cauciones
cd bot-cauciones
```

#### 1.4 Crear Entorno Virtual

```bash
python3 -m venv venv
source venv/bin/activate
```

#### 1.5 Instalar Dependencias

```bash
pip install -r requirements.txt
```

#### 1.6 Configurar `.env` en el Servidor

```bash
nano .env
```

Pega tu configuración y guarda (`Ctrl+O`, `Enter`, `Ctrl+X`)

#### 1.7 Crear Servicio Systemd (Para que corra en background)

Crea archivo `/etc/systemd/system/bot-cauciones.service`:

```bash
sudo nano /etc/systemd/system/bot-cauciones.service
```

Pega el siguiente contenido:

```ini
[Unit]
Description=Bot Telegram Cauciones IOL
After=network.target

[Service]
Type=simple
User=usuario
WorkingDirectory=/home/usuario/bot-cauciones
ExecStart=/home/usuario/bot-cauciones/venv/bin/python3 Causiones-IOL-Bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Guarda y ejecuta:

```bash
sudo systemctl daemon-reload
sudo systemctl start bot-cauciones
sudo systemctl enable bot-cauciones
```

#### 1.8 Verificar Estado

```bash
sudo systemctl status bot-cauciones
# Ver logs:
sudo journalctl -u bot-cauciones -f
```

### Opción 2: Docker (Alternativa)

#### 2.1 Crear `Dockerfile`

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY Causiones-IOL-Bot.py .
COPY .env .

CMD ["python", "Causiones-IOL-Bot.py"]
```

#### 2.2 Crear `docker-compose.yml`

```yaml
version: '3'
services:
  bot:
    build: .
    container_name: bot-cauciones
    restart: always
    environment:
      - TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
      - TELEGRAM_ADMIN_ID=${TELEGRAM_ADMIN_ID}
    volumes:
      - ./bot_datos_v13.pickle:/app/bot_datos_v13.pickle
```

#### 2.3 Ejecutar

```bash
docker-compose up -d
docker-compose logs -f
```

### Opción 3: Heroku (Gratuito con limitaciones)

```bash
# Login
heroku login

# Crear app
heroku create nombre-tu-bot

# Configurar variables
heroku config:set TELEGRAM_BOT_TOKEN=tu_token
heroku config:set TELEGRAM_ADMIN_ID=tu_id

# Deploy
git push heroku main

# Ver logs
heroku logs -t
```

---

## 📝 Archivo `requirements.txt`

Crea este archivo en la carpeta del proyecto:

```
python-telegram-bot==20.7
requests==2.31.0
pandas==2.0.3
lxml==4.9.3
nest-asyncio==1.5.8
matplotlib==3.7.2
python-dotenv==1.0.0
pytz==2023.3
```

---

## 🐛 Solución de Problemas

### Error: "ModuleNotFoundError: No module named 'telegram'"
```bash
pip install python-telegram-bot==20.7
```

### Error: "Falta TELEGRAM_BOT_TOKEN en el archivo .env"
- Verifica que el archivo `.env` está en la carpeta correcta
- Verifica que el token esté escrito correctamente sin espacios

### Error: "TELEGRAM_ADMIN_ID debe ser un número entero"
- Tu ID de Telegram debe ser solo números (ej: `123456789`)
- Obtén tu ID en: [@userinfobot](https://t.me/userinfobot)

### El bot no responde en Telegram
- Verifica que el bot esté corriendo: `python Causiones-IOL-Bot.py`
- Verifica los logs para errores
- Asegúrate de haber enviado `/start` primero

### Error de conexión a IOL
- Verifica tu conexión a internet
- Verifica que el sitio de IOL esté disponible
- El bot reintenará automáticamente

---

## 📋 Estructura del Código

```
Causiones-IOL-Bot.py
├── Config                    # Configuración central
├── Models                    # Dataclasses (DatosCaucion, ConfiguracionUsuario, etc.)
├── Services
│   ├── TelegramLogger        # Logging
│   ├── CacheService          # Caché de datos
│   ├── HistorialService      # Historial de tasas
│   └── ScraperIOLWeb         # Scraper de datos
├── AnalizadorMercado         # Lógica de análisis
├── GraficadorTasas           # Generación de gráficos
└── Handlers                  # Manejadores de comandos Telegram
```

---

## 🔐 Seguridad

- ✅ Usa variables de entorno (`.env`) para credenciales
- ✅ No compartas tu `TELEGRAM_BOT_TOKEN`
- ✅ Agrega `.env` a `.gitignore`
- ✅ En producción, usa un servicio de secrets management
- ✅ Limita permisos del bot (solo admin puede ciertos comandos)

---

## 📧 Soporte

Si encuentras problemas:

1. Revisa los logs del bot
2. Verifica la configuración del `.env`
3. Comprueba que todas las dependencias estén instaladas
4. Reinicia el bot

---

## 📜 Licencia

Este proyecto es de uso personal/privado.

---

## 🔄 Actualizaciones

- **V13**: Full config desde `.env`, persistencia mejorada
- Soporta Python 3.9+
- Compatible con Windows, Linux y macOS

---

**Última actualización**: Enero 2026
