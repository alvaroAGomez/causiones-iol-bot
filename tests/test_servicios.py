import os
import unittest
from datetime import datetime
from unittest.mock import Mock, patch

import pytz
import requests

with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "test-token"}):
    from config import Config
    from models.models import ConfiguracionUsuario, DatosCaucion
    from services.cache_service import CacheService
    from services.caucion_service import AnalizadorMercado, ServicioCauciones
    from services.historial_service import HistorialService
    from services.scraper_iol import ScraperIOLWeb


class ModelosTests(unittest.TestCase):
    def test_datos_caucion_rechaza_valores_negativos(self):
        for dias, tasa in ((-1, 20), (1, -20)):
            with self.subTest(dias=dias, tasa=tasa), self.assertRaises(ValueError):
                DatosCaucion(dias, tasa)

    def test_configuracion_valida_sus_limites(self):
        self.assertTrue(ConfiguracionUsuario(tna_objetivo=0, variacion_minima=0).validar())
        for campo, valor in (("tna_objetivo", -1), ("intervalo_minutos", 0), ("variacion_minima", -1)):
            with self.subTest(campo=campo):
                self.assertFalse(ConfiguracionUsuario(**{campo: valor}).validar())


class ScraperTests(unittest.TestCase):
    @patch("services.scraper_iol.requests.get")
    def test_parsea_decimales_y_descarta_filas_invalidas(self, get):
        get.return_value.text = """
        <table><tr><th>Plazo</th><th>Tasa Tomadora</th></tr>
        <tr><td>1</td><td>105,25 %</td></tr>
        <tr><td>7</td><td>25,50 %</td></tr>
        <tr><td>7</td><td>0,00 %</td></tr>
        <tr><td>sin plazo</td><td>20,00 %</td></tr>
        <tr><td>5</td><td>sin tasa</td></tr></table>
        """
        scraper = ScraperIOLWeb("https://iol.example/cauciones")
        self.assertEqual(scraper.obtener_datos(), [DatosCaucion(1, 105.25), DatosCaucion(7, 25.5)])
        self.assertEqual(get.call_args.args, (scraper.url,))
        get.return_value.raise_for_status.assert_called_once()

    @patch("services.scraper_iol.requests.get", side_effect=requests.Timeout)
    def test_timeout_devuelve_lista_vacia(self, get):
        with self.assertLogs("services.scraper_iol", level="ERROR"):
            self.assertEqual(ScraperIOLWeb("https://iol.example").obtener_datos(), [])
        get.assert_called_once()


class CacheYServicioTests(unittest.TestCase):
    @patch("services.cache_service.time.time")
    def test_cache_expira_al_alcanzar_ttl(self, reloj):
        cache = CacheService()
        reloj.return_value = 100
        self.assertIsNone(cache.get())
        cache.set(["cotización"])
        reloj.return_value += Config.CACHE_TTL_SECONDS - 1
        self.assertEqual(cache.get(), ["cotización"])
        reloj.return_value += 1
        self.assertIsNone(cache.get())

    def setUp(self):
        self.scraper = Mock(spec=ScraperIOLWeb)
        self.cache = Mock(spec=CacheService)
        self.cache.get.return_value = None
        self.historial = Mock(spec=HistorialService)
        self.servicio = ServicioCauciones(self.scraper, self.cache, self.historial, AnalizadorMercado())

    def test_cache_vigente_evita_consulta_y_registro(self):
        datos = [DatosCaucion(1, 30)]
        self.cache.get.return_value = datos
        with patch.object(self.servicio, "_es_horario_mercado", return_value=True):
            self.assertEqual(self.servicio.obtener_datos(), datos)
        self.scraper.obtener_datos.assert_not_called()
        self.historial.agregar_punto.assert_not_called()

    def test_consulta_nueva_se_registra_y_se_reutiliza_al_cierre(self):
        datos = [DatosCaucion(1, 30)]
        self.scraper.obtener_datos.return_value = datos
        with patch.object(self.servicio, "_es_horario_mercado", side_effect=[True, False]):
            self.assertEqual(self.servicio.obtener_datos(), datos)
            self.assertEqual(self.servicio.obtener_datos(), datos)
        self.scraper.obtener_datos.assert_called_once()
        self.cache.set.assert_called_once_with(datos)
        self.historial.agregar_punto.assert_called_once_with(datos)

    def test_consulta_vacia_no_se_registra(self):
        self.scraper.obtener_datos.return_value = []
        with patch.object(self.servicio, "_es_horario_mercado", return_value=True):
            self.assertEqual(self.servicio.obtener_datos(), [])
        self.cache.set.assert_not_called()
        self.historial.agregar_punto.assert_not_called()

    def test_analisis_ordena_oportunidades_y_filtra_plazos(self):
        datos = [DatosCaucion(30, 30), DatosCaucion(1, 25), DatosCaucion(31, 35),
                 DatosCaucion(7, 24), DatosCaucion(61, 105)]
        resultado = AnalizadorMercado.analizar(datos, 25)
        self.assertEqual([d.dias for d in resultado.oportunidades], [1, 30])
        self.assertEqual([d.dias for d in resultado.top_3], [31, 30, 1])
        self.assertEqual(resultado.tasa_maxima, 105)


class HistorialTests(unittest.TestCase):
    @patch("services.historial_service.datetime")
    def test_estadisticas_intervalo_y_fallback_al_ultimo_dia(self, reloj):
        tz = pytz.timezone("America/Argentina/Buenos_Aires")
        historial = HistorialService()
        self.assertIsNone(historial.get_estadisticas_hoy())
        reloj.now.return_value = tz.localize(datetime(2026, 11, 5, 12))
        historial.agregar_punto([DatosCaucion(1, 30), DatosCaucion(1, 20)])
        reloj.now.return_value = tz.localize(datetime(2026, 11, 5, 12, 0, 1))
        historial.agregar_punto([DatosCaucion(1, 90)])
        reloj.now.return_value = tz.localize(datetime(2026, 11, 5, 12, 5))
        historial.agregar_punto([DatosCaucion(1, 20)])
        self.assertTrue(historial.tiene_datos())
        self.assertEqual(historial.get_estadisticas_hoy(), {
            "fecha": "2026-11-05", "mercado_abierto": True, "datos_de_hoy": True,
            "total_registros": 2, "tasa_minima": 20, "promedio": 25,
            "tasa_maxima": {"valor": 30, "hora": "12:00:00"},
            "ultima_tasa": {"valor": 20, "hora": "12:05:00"},
        })
        reloj.now.return_value = tz.localize(datetime(2026, 11, 6, 12))
        stats = historial.get_estadisticas_hoy()
        self.assertEqual(stats["fecha"], "2026-11-05")
        self.assertFalse(stats["datos_de_hoy"])
        self.assertFalse(stats["mercado_abierto"])

    @patch("services.historial_service.datetime")
    def test_el_viernes_la_estadistica_usa_el_plazo_de_tres_dias(self, reloj):
        tz = pytz.timezone("America/Argentina/Buenos_Aires")
        reloj.now.return_value = tz.localize(datetime(2026, 11, 13, 12))
        historial = HistorialService()
        historial.agregar_punto([DatosCaucion(1, 80), DatosCaucion(3, 25)])
        self.assertEqual(historial.get_estadisticas_hoy()["promedio"], 25)
