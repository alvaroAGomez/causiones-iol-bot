"""
Punto de entrada: levanta el bot de Telegram y la API HTTP
en el MISMO event loop de asyncio, compartiendo una única
instancia de ServicioCauciones.
"""

import asyncio
import logging

import uvicorn
from telegram import BotCommand
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    PicklePersistence,
    filters,
)

from api.app import crear_api
from bot.formateo import Formateador
from bot.handlers import (
    BotHandlers,
    ESPERANDO_CODIGO,
    ESPERANDO_TASA,
    ESPERANDO_TIEMPO,
    ESPERANDO_VARIACION,
    ESPERANDO_DIAS_GRAFICO,
)
from config import Config
from models.models import ConfiguracionUsuario
from services.cache_service import CacheService
from services.caucion_service import AnalizadorMercado, ServicioCauciones
from services.historial_service import HistorialService
from services.scraper_iol import ScraperIOLWeb

logger = logging.getLogger(__name__)


def construir_servicio() -> ServicioCauciones:
    scraper   = ScraperIOLWeb(Config.IOL_URL)
    cache     = CacheService()
    historial = HistorialService()
    analizador = AnalizadorMercado()
    svc = ServicioCauciones(scraper, cache, historial, analizador)

    # ------------------------------------------------------------------ #
    #  TESTING LOCAL: forzar datos sin esperar al horario de mercado.     #
    #  Descomentar este bloque para probar el endpoint /api/estadisticas/ #
    #  Eliminar (o volver a comentar) antes de subir a producción.        #
    # ------------------------------------------------------------------ #
    from datetime import datetime
    import pytz
    from models.models import PuntoHistorial
    tz = pytz.timezone('America/Argentina/Buenos_Aires')
    datos_prueba = scraper.obtener_datos()
    if datos_prueba:
        mapa = {d.dias: d.tasa for d in datos_prueba}
        for _ in range(3):
            historial._historial.append(PuntoHistorial(datetime.now(tz), mapa.copy()))

    return svc


def construir_bot(svc: ServicioCauciones):
    fmt = Formateador()
    h = BotHandlers(svc, fmt)

    async def post_init(app):
        await app.bot.set_my_commands([
            BotCommand("start", "Inicio"),
            BotCommand("donar", "☕ Apoyar al Bot"),
            BotCommand("ahora", "Ver Manual"),
            BotCommand("tendencia", "Gráfico General"),
            BotCommand("mitendencia", "Gráfico Custom"),
            BotCommand("top3", "Activar/Desactivar Top 3"),
            BotCommand("set", "Cambiar TNA objetivo"),
            BotCommand("tiempo", "Cambiar frecuencia (min)"),
            BotCommand("variacion", "Cambiar anti-spam"),
            BotCommand("set_tendencia", "Cambiar días del gráfico"),
            BotCommand("usuarios", "ADMIN: Lista Detallada"),
            BotCommand("stats", "ADMIN: Resumen"),
            BotCommand("gen", "ADMIN: Generar Token"),
            BotCommand("tokens", "ADMIN: Ver Tokens"),
        ])

        # Restaurar jobs de usuarios persistidos
        if app.user_data:
            c = 0
            for cid, d in app.user_data.items():
                try:
                    cfg = d.get('config')
                    if cfg:
                        # Migraciones de campos faltantes
                        for attr, default in [
                            ('autorizado', True),
                            ('ultima_tasa_notificada_max', 0.0),
                            ('memoria_tasas_detallada', {}),
                            ('mostrar_top3', True),
                            ('nombre', 'Desconocido'),
                            ('username', 'SinUser'),
                        ]:
                            if not hasattr(cfg, attr):
                                setattr(cfg, attr, default)

                        es_admin = (cid == Config.ID_ADMIN)
                        if cfg.autorizado or es_admin:
                            app.job_queue.run_repeating(
                                h.tarea_escaneo,
                                interval=cfg.intervalo_minutos * 60,
                                first=10 + (c * 2),
                                chat_id=cid,
                                name=str(cid),
                                data=cfg,
                            )
                            c += 1
                except Exception as ex:
                    logger.error(f"Error restaurando user {cid}: {ex}")
            logger.info(f"♻️ Restaurados {c} usuarios")

    app = (
        ApplicationBuilder()
        .token(Config.TELEGRAM_TOKEN)
        .persistence(PicklePersistence(Config.PERSISTENCE_FILE))
        .post_init(post_init)
        .build()
    )

    # ConversationHandler
    conv_start = ConversationHandler(
        entry_points=[CommandHandler('start', h.start_wizard_init)],
        states={
            ESPERANDO_CODIGO: [MessageHandler(filters.TEXT & ~filters.COMMAND, h.wizard_check_code)],
            ESPERANDO_TASA: [MessageHandler(filters.TEXT & ~filters.COMMAND, h.start_wizard_tasa)],
            ESPERANDO_TIEMPO: [MessageHandler(filters.TEXT & ~filters.COMMAND, h.start_wizard_tiempo)],
            ESPERANDO_VARIACION: [MessageHandler(filters.TEXT & ~filters.COMMAND, h.start_wizard_variacion)],
            ESPERANDO_DIAS_GRAFICO: [MessageHandler(filters.TEXT & ~filters.COMMAND, h.start_wizard_final)],
        },
        fallbacks=[CommandHandler('cancel', h.wizard_cancel)],
    )

    # Orden de prioridad de handlers
    app.add_handler(CallbackQueryHandler(h.callback_donaciones, pattern='^donar_'))
    app.add_handler(CommandHandler("donar", h.cmd_donar))
    app.add_handler(CommandHandler("usuarios", h.cmd_usuarios))
    app.add_handler(CommandHandler("stats", h.cmd_stats))
    app.add_handler(CommandHandler("gen", h.cmd_generar_token))
    app.add_handler(CommandHandler("tokens", h.cmd_listar_tokens))
    app.add_handler(CommandHandler("set", h.cmd_set_tna))
    app.add_handler(CommandHandler("tiempo", h.cmd_set_tiempo))
    app.add_handler(CommandHandler("variacion", h.cmd_set_variacion))
    app.add_handler(CommandHandler("set_tendencia", h.cmd_set_dias))
    app.add_handler(CommandHandler("top3", h.cmd_toggle_top3))
    app.add_handler(CommandHandler("ahora", h.cmd_ahora))
    app.add_handler(CommandHandler("tendencia", h.cmd_tendencia_gral))
    app.add_handler(CommandHandler("mitendencia", h.cmd_tendencia_cust))
    app.add_handler(CommandHandler("stop", h.cmd_stop))
    app.add_handler(conv_start)

    app.job_queue.run_repeating(h.recoleccion_global, interval=Config.GLOBAL_SCRAPE_INTERVAL, first=10)

    return app


async def _run_api(svc: ServicioCauciones):
    """Corre uvicorn en modo programático dentro del event loop existente."""
    fast_app = crear_api(svc)
    config = uvicorn.Config(
        fast_app,
        host=Config.API_HOST,
        port=Config.API_PORT,
        log_level="info",
        loop="none",   # ← le decimos que NO cree su propio loop
    )
    server = uvicorn.Server(config)
    await server.serve()


async def _run_bot(telegram_app):
    """Corre el bot de Telegram en modo programático."""
    await telegram_app.initialize()
    await telegram_app.start()
    await telegram_app.updater.start_polling()
    # Espera indefinida hasta que uvicorn pare (o Ctrl+C)
    await asyncio.Event().wait()


async def main():
    svc = construir_servicio()
    telegram_app = construir_bot(svc)

    logger.info(f"🌐 API arrancando en http://{Config.API_HOST}:{Config.API_PORT}")
    logger.info("🤖 Bot Telegram arrancando...")

    # Ambos corren concurrentemente en el MISMO event loop
    await asyncio.gather(
        _run_api(svc),
        _run_bot(telegram_app),
    )


if __name__ == '__main__':
    asyncio.run(main())
