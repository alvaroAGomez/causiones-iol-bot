import logging
from io import BytesIO
from typing import Dict, List, Optional

import matplotlib
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pytz

from models.models import DatosCaucion, ResultadoAnalisis

matplotlib.use('Agg')
logger = logging.getLogger(__name__)


class Formateador:
    @staticmethod
    def _calcular_flecha(tasa_actual: float, dias: int, memoria: Dict[int, float]) -> str:
        if dias not in memoria:
            return " 🆕"
        diferencia = tasa_actual - memoria[dias]
        if diferencia > 0.01:
            return " ⬆️"
        if diferencia < -0.01:
            return " ⬇️"
        return " ➖ "

    @staticmethod
    def reporte(
        analisis: ResultadoAnalisis,
        objetivo: float,
        memoria_detallada: Dict[int, float],
        mostrar_top3: bool,
    ) -> str:
        msgs = []

        if analisis.hay_alerta_critica:
            msgs.append(
                f"🚨🚨 *¡OPORTUNIDAD EXTRAORDINARIA!* 🚨🚨\n"
                f"*TASA > 100% DETECTADA: {analisis.tasa_maxima}%* 🚀\n\n"
            )

        if mostrar_top3:
            msg = "🏆 *Top 3 Mejores Tasas del Mercado:*\n"
            for i in analisis.top_3:
                flecha = Formateador._calcular_flecha(i.tasa, i.dias, memoria_detallada)
                msg += f"  🟢 `{i.dias:02d} DÍAS` ➡️ *{i.tasa}%*{flecha}\n"
            msgs.append(msg)

        if analisis.oportunidades:
            msg = f"\n🔔 *Oportunidades (superan tu objetivo del {objetivo}%):*\n"
            for i in analisis.oportunidades[:5]:
                flecha = Formateador._calcular_flecha(i.tasa, i.dias, memoria_detallada)
                msg += f"  🔥 `{i.dias:02d} DÍAS` ➡️ *{i.tasa}%*{flecha}\n"
            msgs.append(msg)

        if not msgs:
            return ""

        return "\n".join(msgs)


class GeneradorGraficos:
    @staticmethod
    def _ejes(ax, titulo: str):
        tz = pytz.timezone('America/Argentina/Buenos_Aires')
        ax.set_title(titulo)
        ax.set_xlabel("Hora")
        ax.set_ylabel("Tasa %")
        ax.grid(True, linestyle='--', alpha=0.5)
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M', tz=tz))

    @staticmethod
    def generar_general(hist) -> Optional[BytesIO]:
        if not hist or len(hist) < 2:
            return None
        try:
            x = [p.hora for p in hist]
            yc = [max([v for k, v in p.tasas_por_plazo.items() if 1 <= k <= 7 and v > 0], default=None) for p in hist]
            ym = [max([v for k, v in p.tasas_por_plazo.items() if 8 <= k <= 30 and v > 0], default=None) for p in hist]
            yl = [max([v for k, v in p.tasas_por_plazo.items() if k > 30 and v > 0], default=None) for p in hist]

            fig, ax = plt.subplots(figsize=(10, 6))
            ax.plot(x, yc, 'o-', color='#2ca02c', label='Corto (1-7d)', ms=4)
            ax.plot(x, ym, 's--', color='#1f77b4', label='Medio (8-30d)', ms=4)
            ax.plot(x, yl, '^:', color='#ff7f0e', label='Largo (>30d)', ms=4)
            GeneradorGraficos._ejes(ax, "Tendencia Mercado")
            fig.autofmt_xdate()
            ax.legend()

            buf = BytesIO()
            plt.savefig(buf, format='png', bbox_inches='tight')
            buf.seek(0)
            plt.close(fig)
            return buf
        except Exception as e:
            logger.error(f"Error gráfico general: {e}")
            return None

    @staticmethod
    def generar_custom(hist, dias: int) -> Optional[BytesIO]:
        if not hist or len(hist) < 2:
            return None
        try:
            x = [p.hora for p in hist]
            y = []
            for p in hist:
                val = p.tasas_por_plazo.get(dias)
                y.append(val if val and val > 0 else None)

            if all(v is None for v in y):
                return None

            fig, ax = plt.subplots(figsize=(10, 5))
            ax.plot(x, y, '*-', color='#9467bd', label=f'{dias}d')
            GeneradorGraficos._ejes(ax, f"Tendencia {dias} Días")
            fig.autofmt_xdate()
            ax.legend()

            buf = BytesIO()
            plt.savefig(buf, format='png', bbox_inches='tight')
            buf.seek(0)
            plt.close(fig)
            return buf
        except Exception as e:
            logger.error(f"Error gráfico custom: {e}")
            return None
