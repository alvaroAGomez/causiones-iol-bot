import logging
from datetime import datetime
from typing import List, Optional

import pytz

from config import Config
from models.models import DatosCaucion, ResultadoAnalisis
from services.cache_service import CacheService
from services.historial_service import HistorialService
from services.scraper_iol import ScraperIOLWeb

logger = logging.getLogger(__name__)


class AnalizadorMercado:
    @staticmethod
    def analizar(datos: List[DatosCaucion], objetivo: float) -> ResultadoAnalisis:
        if not datos:
            return ResultadoAnalisis([], [], False)

        top3 = sorted(
            [d for d in datos if d.dias <= Config.MAX_DIAS_TOP3],
            key=lambda x: x.tasa, reverse=True
        )[:3]

        ops = sorted(
            [d for d in datos if d.tasa >= objetivo and Config.MIN_DIAS_OPS <= d.dias <= Config.MAX_DIAS_OPS],
            key=lambda x: x.dias
        )

        alerta = any(d.tasa >= 100 for d in datos)
        max_tasa = max(d.tasa for d in datos) if datos else 0.0

        return ResultadoAnalisis(ops, top3, alerta, max_tasa)


class ServicioCauciones:
    """
    Núcleo del dominio: orquesta scraping, caché e historial.
    Esta instancia es compartida entre el bot de Telegram y la API HTTP.
    """

    def __init__(
        self,
        scraper: ScraperIOLWeb,
        cache: CacheService,
        historial: HistorialService,
        analizador: AnalizadorMercado,
    ):
        self.scraper = scraper
        self.cache = cache
        self.historial = historial
        self.analizador = analizador
        self._ultimo_dato: List[DatosCaucion] = []

    def _es_horario_mercado(self) -> bool:
        tz = pytz.timezone('America/Argentina/Buenos_Aires')
        ahora = datetime.now(tz)
        if ahora.weekday() > 4:
            return False
        return Config.HORA_APERTURA <= ahora.time() <= Config.HORA_CIERRE

    def obtener_datos(self) -> List[DatosCaucion]:
        if not self._es_horario_mercado():
            return self._ultimo_dato

        cached = self.cache.get()
        if cached:
            return cached

        datos = self.scraper.obtener_datos()
        if datos:
            self.cache.set(datos)
            self.historial.agregar_punto(datos)
            self._ultimo_dato = datos

        return datos

    def analizar(self, objetivo: float) -> ResultadoAnalisis:
        return self.analizador.analizar(self.obtener_datos(), objetivo)

    def get_historial(self):
        return self.historial.obtener_historial()

    def tiene_grafico(self) -> bool:
        return self.historial.tiene_datos()

    # Delegado directo al HistorialService (usado por la API)
    def get_estadisticas_hoy(self) -> Optional[dict]:
        return self.historial.get_estadisticas_hoy()
