import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Optional, Dict, List, Tuple

import pytz

from config import Config
from models.models import PuntoHistorial, DatosCaucion

logger = logging.getLogger(__name__)


@dataclass
class _AcumuladorDia:
    """
    Estadísticas del día calculadas de forma incremental.
    No guarda todos los puntos, solo los valores necesarios.
    Ocupa memoria constante (O(1) por día).
    """
    fecha: date
    tasa_min: float = float('inf')
    tasa_max: float = float('-inf')
    hora_max: Optional[datetime] = None
    suma: float = 0.0
    cantidad: int = 0
    ultima_tasa: float = 0.0
    ultima_hora: Optional[datetime] = None

    def registrar(self, tasa: float, hora: datetime):
        if tasa < self.tasa_min:
            self.tasa_min = tasa
        if tasa > self.tasa_max:
            self.tasa_max = tasa
            self.hora_max = hora
        self.suma += tasa
        self.cantidad += 1
        self.ultima_tasa = tasa
        self.ultima_hora = hora

    @property
    def promedio(self) -> float:
        return round(self.suma / self.cantidad, 2) if self.cantidad else 0.0


class HistorialService:
    def __init__(self):
        # Para gráficos: lista cappada, solo últimas horas
        self._historial: List[PuntoHistorial] = []

        # Para estadísticas: acumulador por día, memoria constante
        # Guarda solo el día actual y el anterior (por si se pide datos
        # del día anterior antes de que abra el mercado)
        self._acumuladores: Dict[date, _AcumuladorDia] = {}

    def agregar_punto(self, datos: List[DatosCaucion]):
        tz = pytz.timezone('America/Argentina/Buenos_Aires')
        ahora = datetime.now(tz)

        if not self._es_horario_mercado(ahora):
            return

        if self._historial and (ahora - self._historial[-1].hora).total_seconds() < Config.HISTORY_MIN_INTERVAL_SECONDS:
            return

        # Tasa representativa del snapshot = la mejor oferta del mercado
        mapa: Dict[int, float] = {}
        for d in datos:
            if d.tasa > 0:
                if d.dias not in mapa or d.tasa > mapa[d.dias]:
                    mapa[d.dias] = d.tasa

        if not mapa:
            return

        hoy = ahora.date()
        # Tasa representativa del snapshot (1 día, o 3 días si es viernes)
        dias_objetivo = 3 if hoy.weekday() == 4 else 1
        tasa_representativa = mapa.get(dias_objetivo, 0.0)

        # 1. Actualizar historial de gráficos (cappado)
        self._historial.append(PuntoHistorial(ahora, mapa))
        if len(self._historial) > Config.MAX_HISTORY_POINTS:
            self._historial.pop(0)

        # 2. Actualizar acumulador del día (no cappado, memoria constante)
        if tasa_representativa > 0:
            if hoy not in self._acumuladores:
                self._acumuladores[hoy] = _AcumuladorDia(fecha=hoy)
            self._acumuladores[hoy].registrar(tasa_representativa, ahora)

        # Limpiar acumuladores viejos: guardar solo los últimos 2 días
        # (hoy + ayer). Evita que crezca indefinidamente si el servidor
        # corre meses sin reiniciarse.
        fechas_a_borrar = sorted(self._acumuladores.keys())[:-2]
        for f in fechas_a_borrar:
            del self._acumuladores[f]

    def _es_horario_mercado(self, ahora: datetime) -> bool:
        if ahora.weekday() > 4:
            return False
        return Config.HORA_APERTURA <= ahora.time() <= Config.HORA_CIERRE

    def obtener_historial(self) -> List[PuntoHistorial]:
        return self._historial.copy()

    def tiene_datos(self) -> bool:
        return len(self._historial) >= 2

    # ------------------------------------------------------------------ #
    #  Estadísticas del día para el endpoint HTTP                         #
    # ------------------------------------------------------------------ #
    def get_estadisticas_hoy(self) -> Optional[dict]:
        """
        Retorna las estadísticas del día usando el acumulador incremental,
        que cubre el día COMPLETO (no solo las últimas 2.4 horas como
        haría si usara _historial directamente).

        - Si hay acumulador de HOY → lo usa.
        - Si no (antes de que abra el mercado, fin de semana) → usa el
          último día disponible y marca datos_de_hoy=False.
        - Si no hay ningún dato todavía → retorna None.
        """
        if not self._acumuladores:
            return None

        tz = pytz.timezone('America/Argentina/Buenos_Aires')
        ahora = datetime.now(tz)
        hoy = ahora.date()

        if hoy in self._acumuladores:
            acum = self._acumuladores[hoy]
            es_hoy = True
        else:
            # Último día disponible
            ultima_fecha = max(self._acumuladores.keys())
            acum = self._acumuladores[ultima_fecha]
            es_hoy = False

        if acum.cantidad == 0:
            return None

        return {
            "fecha": acum.fecha.isoformat(),
            "mercado_abierto": es_hoy and self._es_horario_mercado(ahora),
            "datos_de_hoy": es_hoy,
            "total_registros": acum.cantidad,
            "tasa_minima": round(acum.tasa_min, 2),
            "tasa_maxima": {
                "valor": round(acum.tasa_max, 2),
                "hora": acum.hora_max.astimezone(tz).strftime('%H:%M:%S'),
            },
            "promedio": acum.promedio,
            "ultima_tasa": {
                "valor": round(acum.ultima_tasa, 2),
                "hora": acum.ultima_hora.astimezone(tz).strftime('%H:%M:%S'),
            },
        }
