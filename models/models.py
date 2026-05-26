from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class DatosCaucion:
    dias: int
    tasa: float

    def __post_init__(self):
        if self.dias < 0 or self.tasa < 0:
            raise ValueError("Datos negativos")


@dataclass
class PuntoHistorial:
    hora: object  # datetime con tz
    tasas_por_plazo: Dict[int, float] = field(default_factory=dict)


@dataclass
class ResultadoAnalisis:
    oportunidades: List[DatosCaucion]
    top_3: List[DatosCaucion]
    hay_alerta_critica: bool
    tasa_maxima: Optional[float] = None


@dataclass
class ConfiguracionUsuario:
    autorizado: bool = False
    nombre: str = "Desconocido"
    username: str = "SinUser"
    tna_objetivo: float = 25.0
    intervalo_minutos: float = 5.0
    dias_grafico_custom: int = 1
    variacion_minima: float = 0.5
    mostrar_top3: bool = True
    ultima_tasa_notificada_max: float = 0.0
    memoria_tasas_detallada: Dict[int, float] = field(default_factory=dict)

    def validar(self) -> bool:
        return self.tna_objetivo >= 0 and self.intervalo_minutos > 0 and self.variacion_minima >= 0
