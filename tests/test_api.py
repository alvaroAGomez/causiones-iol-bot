import os
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "test-token"}):
    from api.app import crear_api
    from config import Config
    from services.caucion_service import ServicioCauciones


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.servicio = Mock(spec=ServicioCauciones)
        self.cliente = TestClient(crear_api(self.servicio))
        self.addCleanup(self.cliente.close)
        self.ruta = "/api/estadisticas/hoy"

    def test_health_expone_disponibilidad_del_historial(self):
        for tiene_historial in (False, True):
            with self.subTest(tiene_historial=tiene_historial):
                self.servicio.tiene_grafico.return_value = tiene_historial
                respuesta = self.cliente.get("/health")
                self.assertEqual(respuesta.status_code, 200)
                self.assertEqual(respuesta.json(), {"status": "ok", "tiene_historial": tiene_historial})

    def test_estadisticas_publicas_y_respuesta_sin_datos(self):
        self.servicio.get_estadisticas_hoy.side_effect = [{"promedio": 25}, None]
        with patch.object(Config, "API_KEY", ""):
            respuesta = self.cliente.get(self.ruta)
            self.assertEqual(respuesta.status_code, 200)
            self.assertEqual(respuesta.json(), {"promedio": 25})
            self.assertEqual(self.cliente.get(self.ruta).status_code, 503)

    def test_api_key_requerida_si_se_configura(self):
        self.servicio.get_estadisticas_hoy.return_value = {"promedio": 25}
        with patch.object(Config, "API_KEY", "clave-de-prueba"):
            for headers in ({}, {"X-API-Key": "incorrecta"}):
                with self.subTest(headers=headers):
                    self.assertEqual(self.cliente.get(self.ruta, headers=headers).status_code, 403)
            self.servicio.get_estadisticas_hoy.assert_not_called()
            respuesta = self.cliente.get(self.ruta, headers={"X-API-Key": "clave-de-prueba"})
            self.assertEqual(respuesta.status_code, 200)
