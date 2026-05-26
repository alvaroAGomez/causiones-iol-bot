"""
API HTTP expuesta para consumo externo.
Comparte la misma instancia de ServicioCauciones con el bot de Telegram.

Endpoint:
  GET /api/estadisticas/hoy
  Header opcional:  X-API-Key: <valor de API_KEY en .env>

Respuesta de ejemplo:
{
  "fecha": "2026-05-24",
  "mercado_abierto": true,
  "total_registros": 48,
  "tasa_minima": 42.50,
  "tasa_maxima": { "valor": 68.75, "hora": "14:35:12" },
  "promedio": 55.30,
  "ultima_tasa": { "valor": 63.10, "hora": "17:30:02" }
}
"""

import logging
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security.api_key import APIKeyHeader

from config import Config
from services.caucion_service import ServicioCauciones

logger = logging.getLogger(__name__)

# Header opcional para autenticación simple
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def _crear_app(svc: ServicioCauciones) -> FastAPI:
    """
    Factory: recibe la instancia compartida del servicio y devuelve
    la aplicación FastAPI con todas las rutas registradas.
    """
    app = FastAPI(
        title="Cauciones IOL API",
        description="Estadísticas de cauciones scrapeadas de IOL",
        version="1.0.0",
    )

    # CORS: ajustá origins según tu dominio de frontend
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],   # <-- cambiá a ["https://tu-web.com"] en producción
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    # ------------------------------------------------------------------ #
    #  Dependency: validación de API Key (si está configurada en .env)    #
    # ------------------------------------------------------------------ #
    async def verificar_api_key(key: Optional[str] = Security(_api_key_header)):
        if not Config.API_KEY:
            # Sin API_KEY configurada → endpoint público
            return
        if key != Config.API_KEY:
            raise HTTPException(status_code=403, detail="API Key inválida o ausente")

    # ------------------------------------------------------------------ #
    #  ENDPOINT PRINCIPAL                                                  #
    # ------------------------------------------------------------------ #
    @app.get(
        "/api/estadisticas/hoy",
        summary="Estadísticas del día en curso",
        tags=["Cauciones"],
        dependencies=[Depends(verificar_api_key)],
    )
    async def estadisticas_hoy():
        """
        Retorna las estadísticas acumuladas del día:
        - **tasa_minima**: mínima observada
        - **tasa_maxima**: máxima observada + hora exacta
        - **promedio**: promedio de todos los snapshots del día
        - **ultima_tasa**: último valor registrado + hora
        - **total_registros**: cantidad de snapshots tomados hoy
        - **mercado_abierto**: si el mercado está operando en este momento
        """
        stats = svc.get_estadisticas_hoy()
        if stats is None:
            raise HTTPException(status_code=503, detail="Sin datos disponibles todavía")
        return stats

    @app.get("/health", tags=["Sistema"])
    async def health():
        return {"status": "ok", "tiene_historial": svc.tiene_grafico()}

    return app


def crear_api(svc: ServicioCauciones) -> FastAPI:
    return _crear_app(svc)
