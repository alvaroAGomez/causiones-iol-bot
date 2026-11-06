import os
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call, patch

import pytz

# Config requires a token at import time. All Telegram calls are mocked.
with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "test-token"}):
    from bot.handlers import BotHandlers
    from models.models import ConfiguracionUsuario, DatosCaucion
    from services.caucion_service import AnalizadorMercado, ServicioCauciones
    from services.historial_service import HistorialService


TZ = pytz.timezone("America/Argentina/Buenos_Aires")


class HorarioMercadoTests(unittest.TestCase):
    def test_horario_y_dias_sin_rueda(self):
        bot = BotHandlers(Mock(), Mock())
        servicio = ServicioCauciones(Mock(), Mock(), Mock(), AnalizadorMercado())
        historial = HistorialService()
        casos = (
            (datetime(2026, 11, 5, 10, 24, 59), False),
            (datetime(2026, 11, 5, 10, 25), True),
            (datetime(2026, 11, 5, 16, 59, 59), True),
            (datetime(2026, 11, 5, 17), False),
            (datetime(2026, 11, 5, 17, 30), False),
            (datetime(2026, 11, 6, 12), False),  # Día del Bancario
            (datetime(2026, 11, 7, 12), False),  # Sábado
            (datetime(2026, 11, 11, 12), True),
        )
        for fecha, abierto in casos:
            ahora = TZ.localize(fecha)
            with (
                self.subTest(fecha=fecha),
                patch("bot.handlers.datetime") as reloj_bot,
                patch("services.caucion_service.datetime") as reloj_servicio,
            ):
                reloj_bot.now.return_value = ahora
                reloj_servicio.now.return_value = ahora
                self.assertEqual(bot._es_horario_mercado(), abierto)
                self.assertEqual(servicio._es_horario_mercado(), abierto)
                self.assertEqual(historial._es_horario_mercado(ahora), abierto)


class AlertasCaucionesTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.datos = [DatosCaucion(1, 105.0)]
        self.servicio = Mock(spec=ServicioCauciones)
        self.servicio.obtener_datos.return_value = self.datos
        self.servicio.analizar.side_effect = lambda objetivo: AnalizadorMercado.analizar(
            self.datos, objetivo
        )
        self.handlers = BotHandlers(self.servicio, Mock(**{"reporte.return_value": "Alerta"}))
        usuarios = {
            1: {"config": ConfiguracionUsuario(autorizado=True, tna_objetivo=150)},
            2: {"config": ConfiguracionUsuario(autorizado=True)},
            3: {"config": ConfiguracionUsuario(autorizado=False)},
        }
        self.telegram = SimpleNamespace(send_message=AsyncMock(), pin_chat_message=AsyncMock())
        self.contexto = SimpleNamespace(
            bot=self.telegram,
            bot_data={},
            application=SimpleNamespace(user_data=usuarios),
            job=SimpleNamespace(chat_id=1, data=usuarios[1]["config"]),
        )

    async def test_alerta_global_llega_a_autorizados_sin_fijar(self):
        with patch.object(self.handlers, "_es_horario_mercado", return_value=True):
            await self.handlers.recoleccion_global(self.contexto)

        self.assertEqual(
            self.telegram.send_message.await_args_list,
            [call(1, "Alerta", parse_mode="Markdown"), call(2, "Alerta", parse_mode="Markdown")],
        )
        self.telegram.pin_chat_message.assert_not_called()

    async def test_alerta_individual_se_envia_sin_fijar(self):
        with patch.object(self.handlers, "_es_horario_mercado", return_value=True):
            await self.handlers.tarea_escaneo(self.contexto)

        self.telegram.send_message.assert_awaited_once_with(1, "Alerta", parse_mode="Markdown")
        self.telegram.pin_chat_message.assert_not_called()

    async def test_ambas_tareas_omiten_consulta_y_envio_con_rueda_cerrada(self):
        with patch("bot.handlers.datetime") as reloj:
            reloj.now.return_value = TZ.localize(datetime(2026, 11, 6, 12))
            await self.handlers.tarea_escaneo(self.contexto)
            await self.handlers.recoleccion_global(self.contexto)

        self.servicio.obtener_datos.assert_not_called()
        self.servicio.analizar.assert_not_called()
        self.telegram.send_message.assert_not_called()

    async def test_escaneo_individual_no_envia_si_cierra_durante_la_consulta(self):
        with patch.object(self.handlers, "_es_horario_mercado", side_effect=[True, False]):
            await self.handlers.tarea_escaneo(self.contexto)

        self.servicio.analizar.assert_called_once()
        self.telegram.send_message.assert_not_called()

    async def test_envio_global_se_detiene_si_cierra_durante_la_difusion(self):
        with patch.object(self.handlers, "_es_horario_mercado", side_effect=[True, True, False]):
            await self.handlers.recoleccion_global(self.contexto)

        self.telegram.send_message.assert_awaited_once_with(1, "Alerta", parse_mode="Markdown")

    async def test_tasa_menor_a_100_no_dispara_la_difusion_global(self):
        self.datos[:] = [DatosCaucion(1, 99.99)]
        with patch.object(self.handlers, "_es_horario_mercado", return_value=True):
            await self.handlers.recoleccion_global(self.contexto)

        self.telegram.send_message.assert_not_called()

    def test_umbral_critico_incluye_100_exacto(self):
        for tasa, critica in ((99.99, False), (100, True), (100.01, True)):
            with self.subTest(tasa=tasa):
                resultado = AnalizadorMercado.analizar([DatosCaucion(1, tasa)], objetivo=150)
                self.assertEqual(resultado.hay_alerta_critica, critica)
