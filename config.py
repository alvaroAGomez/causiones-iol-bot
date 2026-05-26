import os
import logging
import sys
from datetime import time as dtime

sys.stdout.reconfigure(encoding='utf-8')

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


class Config:
    # --- CREDENCIALES ---
    TELEGRAM_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN")
    if not TELEGRAM_TOKEN:
        logger.error("❌ FALTA TOKEN EN .ENV")
        raise ValueError("Falta TELEGRAM_BOT_TOKEN")

    try:
        ID_ADMIN: int = int(os.getenv("TELEGRAM_ADMIN_ID", "0").strip())
    except:
        ID_ADMIN = 0

    # --- DONACIONES ---
    DONAR_ALIAS_PPAY: str = os.getenv("DONAR_ALIAS_PPAY", "").strip()
    DONAR_LEMONTAG: str = os.getenv("DONAR_LEMONTAG", "").strip()
    DONAR_USDT_TRC20: str = os.getenv("DONAR_USDT_TRC20", "").strip()
    DONAR_MP_LINK: str = os.getenv("DONAR_MP_LINK", "").strip()

    # --- IOL ---
    IOL_URL: str = "https://iol.invertironline.com/mercado/cotizaciones/argentina/cauciones"
    CACHE_TTL_SECONDS: int = 25
    GLOBAL_SCRAPE_INTERVAL: int = 30
    HISTORY_MIN_INTERVAL_SECONDS: int = 30
    PERSISTENCE_FILE: str = 'bot_datos.pickle'

    # --- HORARIOS ---
    HORA_APERTURA = dtime(10, 25)
    HORA_CIERRE = dtime(17, 35)

    # --- DEFAULTS ---
    DEFAULT_TNA: float = 25.0
    DEFAULT_MINUTOS: float = 5.0
    DEFAULT_VARIACION: float = 0.5
    DEFAULT_DIAS_GRAF: int = 1

    MAX_HISTORY_POINTS: int = 288
    MAX_DIAS_TOP3: int = 60
    MAX_DIAS_OPS: int = 30
    MIN_DIAS_OPS: int = 1

    # --- API ---
    API_HOST: str = os.getenv("API_HOST", "0.0.0.0")
    API_PORT: int = int(os.getenv("API_PORT", "8000"))
    API_KEY: str = os.getenv("API_KEY", "")  # Opcional: header X-API-Key para proteger el endpoint
