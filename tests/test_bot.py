import os
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from telegram.ext import ConversationHandler

with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "123:test-token"}):
    from bot.formateo import Formateador, GeneradorGraficos
    from bot.handlers import MENU_DIAS, MENU_TIEMPO, MENU_TNA, MENU_VAR, BotHandlers
    from config import Config
    from main import construir_bot
    from models.models import ConfiguracionUsuario, DatosCaucion, PuntoHistorial
    from services.caucion_service import AnalizadorMercado


class ComandosBotTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.servicio = Mock()
        self.handlers = BotHandlers(self.servicio, Formateador())
        usuario = SimpleNamespace(id=12, first_name="Ana", username="ana")
        mensaje = SimpleNamespace(text="", reply_text=AsyncMock())
        self.update = SimpleNamespace(
            effective_user=usuario, effective_chat=SimpleNamespace(id=12), message=mensaje
        )
        self.jobs = Mock()
        self.jobs.get_jobs_by_name.return_value = [Mock()]
        self.contexto = SimpleNamespace(
            user_data={}, bot_data={}, job_queue=self.jobs,
            bot=SimpleNamespace(send_message=AsyncMock()),
        )

    async def test_start_publico_activa_y_programa_el_escaneo(self):
        self.contexto.bot_data["bot_abierto"] = True
        with patch.object(Config, "ID_ADMIN", 99):
            await self.handlers.cmd_start(self.update, self.contexto)
        cfg = self.contexto.user_data["config"]
        self.assertTrue(cfg.autorizado)
        self.jobs.run_repeating.assert_called_once_with(
            self.handlers.tarea_escaneo, interval=cfg.intervalo_minutos * 60,
            first=5, chat_id=12, name="12", data=cfg,
        )

    async def test_start_privado_notifica_al_admin_y_deja_pendiente(self):
        with patch.object(Config, "ID_ADMIN", 99):
            await self.handlers.cmd_start(self.update, self.contexto)
        self.assertFalse(self.contexto.user_data["config"].autorizado)
        self.jobs.run_repeating.assert_not_called()
        self.contexto.bot.send_message.assert_awaited_once()
        self.assertEqual(self.contexto.bot.send_message.await_args.args[0], 99)

    async def test_solo_el_admin_puede_aprobar(self):
        cfg = ConfiguracionUsuario()
        self.contexto.application = SimpleNamespace(user_data={12: {"config": cfg}})
        query = SimpleNamespace(data="admin_aprobar_12", answer=AsyncMock(), edit_message_text=AsyncMock())
        self.update.callback_query = query
        with patch.object(Config, "ID_ADMIN", 99):
            await self.handlers.callback_admin_acciones(self.update, self.contexto)
            self.assertFalse(cfg.autorizado)
            query.answer.assert_awaited_once_with("No tienes permiso.", show_alert=True)

            self.update.effective_user.id = 99
            await self.handlers.callback_admin_acciones(self.update, self.contexto)
        self.assertTrue(cfg.autorizado)
        self.contexto.bot.send_message.assert_awaited_once()

    async def test_menu_valida_y_guarda_preferencias(self):
        casos = (
            (self.handlers.input_tna, "tna_objetivo", "-1", "35,5", 35.5, MENU_TNA),
            (self.handlers.input_tiempo, "intervalo_minutos", "0", "2,5", 2.5, MENU_TIEMPO),
            (self.handlers.input_var, "variacion_minima", "-1", "0,2", 0.2, MENU_VAR),
            (self.handlers.input_dias, "dias_grafico_custom", "1,5", "7", 7, MENU_DIAS),
        )
        for handler, campo, invalido, valido, esperado, estado in casos:
            with self.subTest(campo=campo):
                cfg = ConfiguracionUsuario(autorizado=True)
                self.contexto.user_data["config"] = cfg
                anterior = getattr(cfg, campo)
                self.update.message.text = invalido
                self.assertEqual(await handler(self.update, self.contexto), estado)
                self.assertEqual(getattr(cfg, campo), anterior)
                self.update.message.text = valido
                self.assertEqual(await handler(self.update, self.contexto), ConversationHandler.END)
                self.assertEqual(getattr(cfg, campo), esperado)
        self.assertEqual(self.jobs.run_repeating.call_count, 2)

    async def test_stop_quita_los_jobs_del_usuario(self):
        self.contexto.user_data["config"] = ConfiguracionUsuario(autorizado=True)
        await self.handlers.cmd_stop(self.update, self.contexto)
        self.jobs.get_jobs_by_name.assert_called_once_with("12")
        self.jobs.get_jobs_by_name.return_value[0].schedule_removal.assert_called_once()

    async def test_ahora_muestra_el_ultimo_dato_con_mercado_cerrado(self):
        self.contexto.user_data["config"] = ConfiguracionUsuario(autorizado=True)
        self.servicio.analizar.return_value = AnalizadorMercado.analizar([DatosCaucion(1, 30)], 25)
        with patch.object(self.handlers, "_es_horario_mercado", return_value=False):
            await self.handlers.cmd_ahora(self.update, self.contexto)
        mensaje = self.update.message.reply_text.await_args.args[0]
        self.assertIn("MERCADO CERRADO", mensaje)
        self.assertIn("30%", mensaje)


class PresentacionTests(unittest.TestCase):
    def test_reporte_critico_respeta_la_preferencia_de_top_tres(self):
        resultado = AnalizadorMercado.analizar([DatosCaucion(1, 105)], 25)
        reporte = Formateador.reporte(resultado, 25, {1: 90}, mostrar_top3=False)
        self.assertIn("OPORTUNIDAD EXTRAORDINARIA", reporte)
        self.assertIn("105%", reporte)
        self.assertIn("⬆️", reporte)
        self.assertNotIn("Top 3", reporte)

    def test_graficos_generan_png_y_omiten_plazos_sin_datos(self):
        hora = datetime(2026, 11, 5, 15, tzinfo=timezone.utc)
        puntos = [
            PuntoHistorial(hora, {1: 20, 10: 30, 45: 35}),
            PuntoHistorial(hora + timedelta(minutes=5), {1: 25, 10: 31, 45: 36}),
        ]
        self.assertIsNone(GeneradorGraficos.generar_general(puntos[:1]))
        self.assertIsNone(GeneradorGraficos.generar_custom(puntos, 7))
        for grafico in (GeneradorGraficos.generar_general(puntos), GeneradorGraficos.generar_custom(puntos, 1)):
            with grafico:
                self.assertEqual(grafico.read(8), b"\x89PNG\r\n\x1a\n")


class InicioTests(unittest.TestCase):
    def test_construir_bot_registra_comandos_y_recoleccion_global(self):
        with (
            patch.object(Config, "TELEGRAM_TOKEN", "123:test-token"),
            patch.dict(os.environ, {"no_proxy": "*"}),
        ):
            app = construir_bot(Mock())
        comandos = {
            comando for handlers in app.handlers.values() for handler in handlers
            for comando in getattr(handler, "commands", ())
        }
        self.assertTrue({"start", "ahora", "stop", "modo"} <= comandos)
        self.assertEqual(len(app.job_queue.get_jobs_by_name("recoleccion_global")), 1)
