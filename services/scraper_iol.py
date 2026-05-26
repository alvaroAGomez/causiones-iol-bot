import logging
from io import StringIO
from typing import List

import requests
import pandas as pd

from models.models import DatosCaucion

logger = logging.getLogger(__name__)


class ScraperIOLWeb:
    def __init__(self, url: str):
        self.url = url

    def obtener_datos(self) -> List[DatosCaucion]:
        try:
            r = requests.get(
                self.url,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=10
            )
            r.raise_for_status()
            df = pd.read_html(StringIO(r.text))[0]
            df.columns = df.columns.str.lower()
            res = []
            for _, row in df.iterrows():
                try:
                    t = float(
                        str(row['tasa tomadora'])
                        .replace('%', '').replace('.', '').replace(',', '.').strip()
                    )
                    d = int(float(
                        str(row['plazo'])
                        .lower().replace('días', '').replace('d', '').strip()
                    ))
                    if t > 0:
                        res.append(DatosCaucion(d, t))
                except:
                    continue
            return res
        except Exception as e:
            logger.error(f"Error Scraper: {e}")
            return []
