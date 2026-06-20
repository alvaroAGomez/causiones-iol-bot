"""
Punto de entrada: levanta el bot de Telegram y la API HTTP
en el MISMO event loop de asyncio, compartiendo una única
instancia de ServicioCauciones.
"""

import asyncio
import logging

import uvicorn
from telegram import BotCommand, BotCommandScopeAllPrivateChats, BotCommandScopeDefault, BotCommandScopeChat
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
    MENU_TNA,
    MENU_TIEMPO,
    MENU_VAR,
    MENU_DIAS,
    SELECCIONANDO,
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
        # Por defecto el bot arranca abierto (sin requerir aprobación)
        #app.bot_data.setdefault('bot_abierto', True) #solo para pruebas

        # Comandos públicos (para todos)
        cmds_publicos = [
            BotCommand("start", "Inicio"),
            BotCommand("menu", "⚙️ Configuración"),
            BotCommand("ahora", "🔎 Ver Tasas Actuales"),
            BotCommand("tendencia", "📈 Gráfico General"),
            BotCommand("mitendencia", "📊 Gráfico Personalizado"),
            BotCommand("ayuda", "📖 Guía de uso"),
            BotCommand("donar", "☕ Apoyar al Bot"),
            BotCommand("stop", "🛑 Detener alertas"),
        ]

        try:
            # Limpiar comandos residuales de todos los scopes
            await app.bot.delete_my_commands(scope=BotCommandScopeDefault())
            await app.bot.delete_my_commands(scope=BotCommandScopeAllPrivateChats())

            # Si hay admin configurado, limpiar también su scope de chat específico
            if Config.ID_ADMIN:
                try:
                    await app.bot.delete_my_commands(scope=BotCommandScopeChat(chat_id=Config.ID_ADMIN))
                except Exception:
                    pass

            # Setear comandos públicos para todos los usuarios
            await app.bot.set_my_commands(cmds_publicos, scope=BotCommandScopeDefault())
            await app.bot.set_my_commands(cmds_publicos, scope=BotCommandScopeAllPrivateChats())
            logger.info(f"[COMANDOS] Comandos públicos seteados ({len(cmds_publicos)} cmds)")

            # Comandos para el Administrador (solo si está configurado)
            if Config.ID_ADMIN:
                cmds_admin = cmds_publicos + [
                    BotCommand("modo", "ADMIN: Público/Privado"),
                    BotCommand("pendientes", "ADMIN: Aprobar Usuarios"),
                    BotCommand("usuarios", "ADMIN: Lista de Usuarios"),
                    BotCommand("stats", "ADMIN: Estadísticas"),
                ]
                await app.bot.set_my_commands(cmds_admin, scope=BotCommandScopeChat(chat_id=Config.ID_ADMIN))
                logger.info(f"[COMANDOS] Comandos admin seteados para chat {Config.ID_ADMIN}")
            else:
                logger.info("[COMANDOS] Sin ID_ADMIN - solo comandos públicos")
        except Exception as e:
            logger.error(f"[COMANDOS] Error seteando comandos: {e}")

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

    # ConversationHandler para el MENU
    conv_menu = ConversationHandler(
        entry_points=[
            CommandHandler('menu', h.cmd_menu),
            CallbackQueryHandler(h.callback_menu, pattern='^menu_')
        ],
        states={
            SELECCIONANDO: [CallbackQueryHandler(h.callback_menu, pattern='^menu_')],
            MENU_TNA: [MessageHandler(filters.TEXT & ~filters.COMMAND, h.input_tna)],
            MENU_TIEMPO: [MessageHandler(filters.TEXT & ~filters.COMMAND, h.input_tiempo)],
            MENU_VAR: [MessageHandler(filters.TEXT & ~filters.COMMAND, h.input_var)],
            MENU_DIAS: [MessageHandler(filters.TEXT & ~filters.COMMAND, h.input_dias)],
        },
        fallbacks=[CommandHandler('cancel', h.menu_cancel), CommandHandler('menu', h.cmd_menu)],
    )

    # Orden de prioridad de handlers
    app.add_handler(CommandHandler("start", h.cmd_start))
    app.add_handler(conv_menu)
    app.add_handler(CallbackQueryHandler(h.callback_admin_acciones, pattern='^admin_'))
    app.add_handler(CallbackQueryHandler(h.callback_donaciones, pattern='^donar_'))
    
    app.add_handler(CommandHandler("donar", h.cmd_donar))
    app.add_handler(CommandHandler("usuarios", h.cmd_usuarios))
    app.add_handler(CommandHandler("stats", h.cmd_stats))
    app.add_handler(CommandHandler("modo", h.cmd_modo))
    app.add_handler(CommandHandler("pendientes", h.cmd_pendientes))
    
    app.add_handler(CommandHandler("ayuda", h.cmd_ayuda))
    app.add_handler(CommandHandler("ahora", h.cmd_ahora))
    app.add_handler(CommandHandler("tendencia", h.cmd_tendencia_gral))
    app.add_handler(CommandHandler("mitendencia", h.cmd_tendencia_cust))
    app.add_handler(CommandHandler("stop", h.cmd_stop))

    app.job_queue.run_repeating(h.recoleccion_global, interval=Config.GLOBAL_SCRAPE_INTERVAL, first=10)

    return app


async def _run_api(svc: ServicioCauciones):
    fast_app = crear_api(svc)
    config = uvicorn.Config(
        fast_app,
        host=Config.API_HOST,
        port=Config.API_PORT,
        log_level="info",
        loop="none",
    )
    server = uvicorn.Server(config)
    await server.serve()


async def _run_bot(telegram_app):
    await telegram_app.initialize()
    await telegram_app.post_init(telegram_app)
    await telegram_app.start()
    await telegram_app.updater.start_polling()
    await asyncio.Event().wait()


async def main():
    svc = construir_servicio()
    telegram_app = construir_bot(svc)

    logger.info(f"🌐 API arrancando en http://{Config.API_HOST}:{Config.API_PORT}")
    logger.info("🤖 Bot Telegram arrancando...")

    await asyncio.gather(
        _run_api(svc),
        _run_bot(telegram_app),
    )


if __name__ == '__main__':
    asyncio.run(main())
