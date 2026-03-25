"""
Bot de Telegram para Cauciones IOL - Versión V17 (Lista Detallada de Usuarios)

LIBRERÍAS REQUERIDAS:
pip3 install python-telegram-bot==20.7 requests pandas lxml nest-asyncio matplotlib python-dotenv pytz

CONFIGURACIÓN (.env):
TELEGRAM_BOT_TOKEN=tu_token
TELEGRAM_ADMIN_ID=tu_id
"""

import logging
import os
import time
import asyncio
import random
import secrets
import string
from dataclasses import dataclass, field
from datetime import datetime, time as dtime
from collections import Counter
from io import BytesIO, StringIO
from typing import List, Optional, Dict, Tuple, Set

from dotenv import load_dotenv
load_dotenv()

import pytz
import matplotlib
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
import requests

from telegram import Update, BotCommand, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    PicklePersistence,
    Application
)

matplotlib.use('Agg')

# ============================================================================
# CONSTANTES Y ESTADOS
# ============================================================================

ESPERANDO_CODIGO, ESPERANDO_TASA, ESPERANDO_TIEMPO, ESPERANDO_VARIACION, ESPERANDO_DIAS_GRAFICO = range(5)

class Config:
    TELEGRAM_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN")
    if not TELEGRAM_TOKEN: raise ValueError("❌ Error: Falta TELEGRAM_BOT_TOKEN en .env")

    try:
        ID_ADMIN: int = int(os.getenv("TELEGRAM_ADMIN_ID", "0").strip())
    except ValueError:
        raise ValueError("❌ Error: TELEGRAM_ADMIN_ID debe ser numérico.")

    IOL_URL: str = "https://iol.invertironline.com/mercado/cotizaciones/argentina/cauciones"
    CACHE_TTL_SECONDS: int = 40
    GLOBAL_SCRAPE_INTERVAL: int = 45
    HISTORY_MIN_INTERVAL_SECONDS: int = 30 
    PERSISTENCE_FILE: str = 'bot_datos.pickle' # V17
    
    # ⏰ HORARIOS
    HORA_APERTURA = dtime(10, 25)
    HORA_CIERRE = dtime(17, 5)
    
    # Defaults
    DEFAULT_TNA: float = 25.0
    DEFAULT_MINUTOS: float = 5.0
    DEFAULT_VARIACION: float = 0.5
    DEFAULT_DIAS_GRAF: int = 1
    
    MAX_HISTORY_POINTS: int = 288
    MAX_DIAS_TOP3: int = 60
    MAX_DIAS_OPS: int = 30
    MIN_DIAS_OPS: int = 1


# ============================================================================
# MODELOS DE DATOS
# ============================================================================

@dataclass
class DatosCaucion:
    dias: int
    tasa: float
    def __post_init__(self):
        if self.dias < 0 or self.tasa < 0: raise ValueError("Datos negativos")

@dataclass
class PuntoHistorial:
    hora: datetime
    tasas_por_plazo: Dict[int, float] = field(default_factory=dict) 

@dataclass
class ConfiguracionUsuario:
    autorizado: bool = False
    
    # 👤 DATOS DE IDENTIDAD (NUEVO)
    nombre: str = "Desconocido"
    username: str = "SinUser"
    
    tna_objetivo: float = Config.DEFAULT_TNA
    intervalo_minutos: float = Config.DEFAULT_MINUTOS
    dias_grafico_custom: int = Config.DEFAULT_DIAS_GRAF
    variacion_minima: float = Config.DEFAULT_VARIACION 
    mostrar_top3: bool = True
    ultima_tasa_notificada_max: float = 0.0
    memoria_tasas_detallada: Dict[int, float] = field(default_factory=dict)
    
    def validar(self) -> bool:
        return self.tna_objetivo >= 0 and self.intervalo_minutos > 0 and self.variacion_minima >= 0


@dataclass
class ResultadoAnalisis:
    oportunidades: List[DatosCaucion]
    top_3: List[DatosCaucion]
    hay_alerta_critica: bool
    tasa_maxima: Optional[float] = None


# ============================================================================
# SERVICIOS BASE
# ============================================================================

class TelegramLogger:
    def __init__(self, name: str = __name__):
        self.logger = logging.getLogger(name)
        logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
    def info(self, msj): self.logger.info(msj)
    def error(self, msj): self.logger.error(msj)

class CacheService:
    def __init__(self):
        self._cache = {"timestamp": 0, "data": []}
    def get(self):
        if time.time() - self._cache["timestamp"] < Config.CACHE_TTL_SECONDS: return self._cache["data"]
        return None
    def set(self, data):
        self._cache = {"timestamp": time.time(), "data": data}

class HistorialService:
    def __init__(self):
        self._historial = []
    def agregar_punto(self, datos):
        tz = pytz.timezone('America/Argentina/Buenos_Aires')
        ahora = datetime.now(tz)
        if not self._es_horario_mercado(ahora): return
        if self._historial and (ahora - self._historial[-1].hora).total_seconds() < Config.HISTORY_MIN_INTERVAL_SECONDS: return
        mapa = {}
        for d in datos:
            if d.tasa > 0: 
                if d.dias not in mapa or d.tasa > mapa[d.dias]: mapa[d.dias] = d.tasa
        if mapa:
            self._historial.append(PuntoHistorial(ahora, mapa))
            if len(self._historial) > Config.MAX_HISTORY_POINTS: self._historial.pop(0)

    def _es_horario_mercado(self, ahora):
        if ahora.weekday() > 4: return False 
        return Config.HORA_APERTURA <= ahora.time() <= Config.HORA_CIERRE

    def obtener_historial(self): return self._historial.copy()
    def tiene_datos(self): return len(self._historial) >= 2

class ScraperIOLWeb:
    def __init__(self, url, logger):
        self.url = url
        self.logger = logger
    def obtener_datos(self):
        try:
            r = requests.get(self.url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            r.raise_for_status()
            df = pd.read_html(StringIO(r.text))[0]
            df.columns = df.columns.str.lower()
            res = []
            for _, row in df.iterrows():
                try:
                    t = float(str(row['tasa tomadora']).replace('%','').replace('.','').replace(',','.').strip())
                    d = int(float(str(row['plazo']).lower().replace('días','').replace('d','').strip()))
                    if t > 0: res.append(DatosCaucion(d, t))
                except: continue
            return res
        except Exception as e:
            self.logger.error(f"Error Scraper: {e}")
            return []


# ============================================================================
# LÓGICA & GRÁFICOS
# ============================================================================

class AnalizadorMercado:
    @staticmethod
    def analizar(datos, objetivo):
        if not datos: return ResultadoAnalisis([], [], False)
        
        top3 = sorted([d for d in datos if d.dias <= Config.MAX_DIAS_TOP3], key=lambda x: x.tasa, reverse=True)[:3]
        ops = sorted([d for d in datos if d.tasa >= objetivo and Config.MIN_DIAS_OPS <= d.dias <= Config.MAX_DIAS_OPS], key=lambda x: x.dias)
        alerta = any(d.tasa >= 100 for d in datos)
        max_tasa = max(d.tasa for d in datos) if datos else 0.0
        return ResultadoAnalisis(ops, top3, alerta, max_tasa)

class GeneradorGraficos:
    @staticmethod
    def _ejes(ax, titulo):
        tz = pytz.timezone('America/Argentina/Buenos_Aires')
        ax.set_title(titulo); ax.set_xlabel("Hora"); ax.set_ylabel("Tasa %")
        ax.grid(True, linestyle='--', alpha=0.5)
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M', tz=tz))

    @staticmethod
    def generar_general(hist):
        if not hist or len(hist)<2: return None
        try:
            x = [p.hora for p in hist]
            yc = [max([v for k,v in p.tasas_por_plazo.items() if 1<=k<=7 and v > 0], default=None) for p in hist]
            ym = [max([v for k,v in p.tasas_por_plazo.items() if 8<=k<=30 and v > 0], default=None) for p in hist]
            yl = [max([v for k,v in p.tasas_por_plazo.items() if k>30 and v > 0], default=None) for p in hist]

            fig, ax = plt.subplots(figsize=(10,6))
            ax.plot(x, yc, 'o-', color='#2ca02c', label='Corto (1-7d)', ms=4)
            ax.plot(x, ym, 's--', color='#1f77b4', label='Medio (8-30d)', ms=4)
            ax.plot(x, yl, '^:', color='#ff7f0e', label='Largo (>30d)', ms=4)
            
            GeneradorGraficos._ejes(ax, "Tendencia Mercado")
            fig.autofmt_xdate(); ax.legend()
            buf = BytesIO(); plt.savefig(buf, format='png', bbox_inches='tight'); buf.seek(0); plt.close(fig)
            return buf
        except: return None

    @staticmethod
    def generar_custom(hist, dias):
        if not hist or len(hist)<2: return None
        try:
            x = [p.hora for p in hist]
            y = []
            for p in hist:
                val = p.tasas_por_plazo.get(dias)
                if val is not None and val > 0: y.append(val)
                else: y.append(None)

            if all(v is None for v in y): return None
            fig, ax = plt.subplots(figsize=(10,5))
            ax.plot(x, y, '*-', color='#9467bd', label=f'{dias}d')
            GeneradorGraficos._ejes(ax, f"Tendencia {dias} Días")
            fig.autofmt_xdate(); ax.legend()
            buf = BytesIO(); plt.savefig(buf, format='png', bbox_inches='tight'); buf.seek(0); plt.close(fig)
            return buf
        except: return None

class Formateador:
    @staticmethod
    def _calcular_flecha(tasa_actual: float, dias: int, memoria: Dict[int, float]) -> str:
        if dias not in memoria: return " 🆕"
        tasa_anterior = memoria[dias]
        diferencia = tasa_actual - tasa_anterior
        if diferencia > 0.01: return " ⬆️"
        if diferencia < -0.01: return " ⬇️"
        return "" 

    @staticmethod
    def reporte(analisis, objetivo, memoria_detallada: Dict[int, float], mostrar_top3: bool):
        msgs = []
        if analisis.hay_alerta_critica: 
            msgs.append(f"🚨🚨 *¡OPORTUNIDAD EXTRAORDINARIA!* 🚨🚨\n*TASA > 100% DETECTADA: {analisis.tasa_maxima}%* \n\n")
        
        if mostrar_top3:
            msg = "*🏆 Top 3 Mercado:*\n\n"
            for i in analisis.top_3: 
                flecha = Formateador._calcular_flecha(i.tasa, i.dias, memoria_detallada)
                msg += f"✅ {i.dias} DÍAS | {i.tasa}%{flecha}\n"
            msgs.append(msg)
        
        if analisis.oportunidades:
            msg = f"\n🔔 *Oportunidades > ({objetivo}%):*\n\n"
            for i in analisis.oportunidades[:5]: 
                flecha = Formateador._calcular_flecha(i.tasa, i.dias, memoria_detallada)
                msg += f"✅ {i.dias} DÍAS | {i.tasa}%{flecha}\n"
            msgs.append(msg)
        return "\n".join(msgs)


# ============================================================================
# HANDLERS Y ASISTENTE
# ============================================================================

class BotHandlers:
    def __init__(self, servicio, formateador):
        self.svc = servicio
        self.fmt = formateador

    # --- HELPERS ---
    def _es_horario_mercado(self) -> bool:
        tz = pytz.timezone('America/Argentina/Buenos_Aires')
        ahora = datetime.now(tz)
        if ahora.weekday() > 4: return False
        return Config.HORA_APERTURA <= ahora.time() <= Config.HORA_CIERRE

    def _esta_autorizado(self, user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
        if self._es_admin(user_id): return True
        config = context.user_data.get('config')
        if config and isinstance(config, ConfiguracionUsuario) and config.autorizado: return True
        return False
    
    def _es_admin(self, user_id: int) -> bool:
        return user_id == Config.ID_ADMIN

    def _actualizar_identidad(self, user, context):
        """Guarda nombre y usuario para el admin"""
        if not user: return
        config = context.user_data.get('config')
        if config:
            nombre = user.first_name if user.first_name else "Anónimo"
            username = f"@{user.username}" if user.username else "SinUser"
            # Solo actualizamos si cambió algo
            if config.nombre != nombre or config.username != username:
                config.nombre = nombre
                config.username = username
                context.user_data['config'] = config

    # --- ADMIN COMMANDS ---
    async def cmd_generar_token(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._es_admin(update.effective_user.id): return
        alfabeto = string.ascii_uppercase + string.digits
        codigo = ''.join(secrets.choice(alfabeto) for _ in range(6))
        if 'codigos_validos' not in context.bot_data: context.bot_data['codigos_validos'] = []
        context.bot_data['codigos_validos'].append(codigo)
        await update.message.reply_text(f"🎟️ *NUEVO TOKEN:*\n`{codigo}`", parse_mode='Markdown')

    async def cmd_listar_tokens(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._es_admin(update.effective_user.id): return
        codigos = context.bot_data.get('codigos_validos', [])
        msg = "\n".join([f"`{c}`" for c in codigos]) if codigos else "Ninguno."
        await update.message.reply_text(f"🎟️ *Pendientes:*\n{msg}", parse_mode='Markdown')

    # 🟢 COMANDO NUEVO: LISTAR USUARIOS DETALLADOS
    async def cmd_usuarios(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._es_admin(update.effective_user.id): return

        msg_lines = ["📋 *LISTA DE USUARIOS*\n"]
        total = 0
        
        for uid, data in context.application.user_data.items():
            cfg = data.get('config')
            if cfg and isinstance(cfg, ConfiguracionUsuario):
                total += 1
                estado = "🟢 VIP" if cfg.autorizado else "🔴 Pend"
                top3 = "Top3:SI" if cfg.mostrar_top3 else "Top3:NO"
                
                # Manejo de usuarios viejos sin nombre guardado
                nombre = getattr(cfg, 'nombre', 'Desconocido')
                user = getattr(cfg, 'username', '---')
                
                linea = (
                    f"👤 *{nombre}* ({user})\n"
                    f"   └ {estado} | Obj: {cfg.tna_objetivo}% | {cfg.intervalo_minutos}min | {top3}\n"
                )
                msg_lines.append(linea)

        if total == 0:
            await update.message.reply_text("📭 No hay usuarios registrados.")
        else:
            final_msg = "\n".join(msg_lines)
            # Cortar si es muy largo (Telegram limita a 4096 chars)
            if len(final_msg) > 4000: final_msg = final_msg[:4000] + "\n... (cortado)"
            await update.message.reply_text(final_msg, parse_mode='Markdown')

    async def cmd_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._es_admin(update.effective_user.id): return
        total_usuarios = len(context.application.user_data)
        usuarios_autorizados = 0
        tasas_objetivo = []
        for uid, data in context.application.user_data.items():
            cfg = data.get('config')
            if cfg and isinstance(cfg, ConfiguracionUsuario):
                if cfg.autorizado:
                    usuarios_autorizados += 1
                    tasas_objetivo.append(cfg.tna_objetivo)

        tokens_pendientes = len(context.bot_data.get('codigos_validos', []))
        ultimo_scrape = context.bot_data.get('ultima_actualizacion', 'Nunca')
        top_tasas = "N/A"
        if tasas_objetivo:
            counts = Counter(tasas_objetivo).most_common(3)
            top_tasas = ", ".join([f"{t}% ({c})" for t, c in counts])

        msg = (
            f"📊 *ESTADÍSTICAS*\n\n"
            f"👥 *Total:* {total_usuarios} (VIP: {usuarios_autorizados})\n"
            f"🎟️ *Tokens:* {tokens_pendientes}\n"
            f"📉 *Tasas:* {top_tasas}\n"
            f"🩺 *Scrape:* {ultimo_scrape}\n\n"
            "💡 Usá /usuarios para ver el detalle."
        )
        await update.message.reply_text(msg, parse_mode='Markdown')

    # --- WIZARD START ---
    async def start_wizard_init(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        self._actualizar_identidad(user, context) # <--- CAPTURAR NOMBRE

        msg_extra = ""
        if not self._es_horario_mercado():
            msg_extra = "\n🌑 *MERCADO CERRADO*: Se guardará la config, pero no habrá alertas.\n"

        if self._es_admin(user.id):
            if 'config' not in context.user_data: context.user_data['config'] = ConfiguracionUsuario(autorizado=True, nombre=user.first_name, username=f"@{user.username}")
            else: context.user_data['config'].autorizado = True
            await update.message.reply_text(f"👑 *Modo Admin*{msg_extra}\n\n1️⃣ *DEFINIR TASA MÍNIMA (TNA)*\n(Ej: `30`)", parse_mode='Markdown')
            return ESPERANDO_TASA

        if self._esta_autorizado(user.id, context):
            await update.message.reply_text(f"👋 *Hola {user.first_name}*{msg_extra}\n\n1️⃣ *DEFINIR TASA MÍNIMA (TNA)*\n(Ej: `30`)", parse_mode='Markdown')
            return ESPERANDO_TASA
        
        await update.message.reply_text("🔒 *SISTEMA CERRADO*\nIngrese su *TOKEN DE ACCESO*:", parse_mode='Markdown')
        return ESPERANDO_CODIGO

    async def wizard_check_code(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        code = update.message.text.strip().upper()
        validos = context.bot_data.get('codigos_validos', [])
        user = update.effective_user
        
        if code in validos:
            validos.remove(code)
            context.bot_data['codigos_validos'] = validos
            
            # Guardamos config con identidad
            config = context.user_data.get('config', ConfiguracionUsuario())
            config.autorizado = True
            config.nombre = user.first_name
            config.username = f"@{user.username}" if user.username else "SinUser"
            context.user_data['config'] = config
            
            await update.message.reply_text("🔓 *Acceso Concedido.*\n\n1️⃣ *DEFINIR TASA MÍNIMA (TNA)*\n(Ej: `30`)", parse_mode='Markdown')
            return ESPERANDO_TASA
        else:
            await update.message.reply_text("⛔ *Token Inválido*.", parse_mode='Markdown')
            return ESPERANDO_CODIGO

    # --- PASOS CONFIG ---
    async def start_wizard_tasa(self, update, context):
        try:
            val = float(update.message.text.replace(',', '.'))
            if val < 0: raise ValueError
            context.user_data['temp_tna'] = val
            await update.message.reply_text(f"✅ Tasa: {val}%.\n\n2️⃣ *FRECUENCIA (MINUTOS)*\n(Ej: `5`)", parse_mode='Markdown')
            return ESPERANDO_TIEMPO
        except: return ESPERANDO_TASA 

    async def start_wizard_tiempo(self, update, context):
        try:
            val = float(update.message.text.replace(',', '.'))
            if val <= 0: raise ValueError
            context.user_data['temp_time'] = val
            await update.message.reply_text(f"✅ Frecuencia: {val} min.\n\n3️⃣ *ANTI-SPAM (VARIACIÓN)*\n(Ej: `0.5`)", parse_mode='Markdown')
            return ESPERANDO_VARIACION
        except: return ESPERANDO_TIEMPO

    async def start_wizard_variacion(self, update, context):
        try:
            val = float(update.message.text.replace(',', '.'))
            if val < 0: raise ValueError
            context.user_data['temp_var'] = val
            await update.message.reply_text(f"✅ Anti-Spam: {val}%.\n\n4️⃣ *DÍAS GRÁFICO*\n(Ej: `1`)", parse_mode='Markdown')
            return ESPERANDO_DIAS_GRAFICO
        except: return ESPERANDO_VARIACION

    async def start_wizard_final(self, update, context):
        try:
            dias = int(update.message.text)
            if dias < 1: raise ValueError
            
            config = context.user_data.get('config', ConfiguracionUsuario())
            
            # Update campos finales
            config.tna_objetivo = context.user_data.get('temp_tna', Config.DEFAULT_TNA)
            config.intervalo_minutos = context.user_data.get('temp_time', Config.DEFAULT_MINUTOS)
            config.variacion_minima = context.user_data.get('temp_var', Config.DEFAULT_VARIACION)
            config.dias_grafico_custom = dias
            
            # Asegurar admin
            if self._es_admin(update.effective_user.id): config.autorizado = True
            
            context.user_data['config'] = config
            self._actualizar_job(update.effective_chat.id, context)
            
            await update.message.reply_text("🚀 *¡Configuración Lista!*", parse_mode='Markdown')
            return ConversationHandler.END
        except: return ESPERANDO_DIAS_GRAFICO

    async def wizard_cancel(self, update, context):
        await update.message.reply_text("❌ Cancelado.")
        return ConversationHandler.END

    # --- TAREA DE ESCANEO ---
    async def tarea_escaneo(self, context: ContextTypes.DEFAULT_TYPE):
        job = context.job
        config: ConfiguracionUsuario = job.data
        if not config.autorizado: job.schedule_removal(); return
        if not self._es_horario_mercado(): return 

        res = self.svc.analizar(config.tna_objetivo)
        if not res.top_3: return

        mejor_tasa = res.tasa_maxima if res.tasa_maxima else 0.0
        enviar = False
        
        if res.hay_alerta_critica: enviar = True
        else:
            if config.mostrar_top3:
                if (res.oportunidades or res.top_3) and abs(mejor_tasa - config.ultima_tasa_notificada_max) >= config.variacion_minima: enviar = True
            else:
                if res.oportunidades and abs(mejor_tasa - config.ultima_tasa_notificada_max) >= config.variacion_minima: enviar = True

        if enviar:
            try:
                msg = self.fmt.reporte(res, config.tna_objetivo, config.memoria_tasas_detallada, config.mostrar_top3)
                if not msg.strip(): return
                sent_msg = await context.bot.send_message(job.chat_id, msg, parse_mode='Markdown')
                if res.hay_alerta_critica: 
                    try: await context.bot.pin_chat_message(job.chat_id, sent_msg.message_id)
                    except: pass
                config.ultima_tasa_notificada_max = mejor_tasa
                nueva_memoria = config.memoria_tasas_detallada.copy()
                for item in res.top_3 + res.oportunidades: nueva_memoria[item.dias] = item.tasa
                config.memoria_tasas_detallada = nueva_memoria
                context.application.user_data[job.chat_id]['config'] = config
            except Exception as e:
                if "Forbidden" in str(e): job.schedule_removal()

    # --- COMANDOS GLOBALES ---
    async def recoleccion_global(self, context):
        try:
            if not self._es_horario_mercado(): return
            await asyncio.sleep(random.uniform(0.1, 3.0))
            datos = self.svc.obtener_datos()
            if datos: 
                logging.info(f"🔄 Global: {len(datos)} regs")
                tz = pytz.timezone('America/Argentina/Buenos_Aires')
                context.bot_data['ultima_actualizacion'] = datetime.now(tz).strftime('%Y-%m-%d %H:%M:%S')
        except Exception as e: logging.error(f"Err Global: {e}")

    async def cmd_toggle_top3(self, update, context):
        if not self._esta_autorizado(update.effective_user.id, context): return
        self._actualizar_identidad(update.effective_user, context)
        config = context.user_data.get('config')
        config.mostrar_top3 = not config.mostrar_top3
        context.user_data['config'] = config
        estado = "✅ VISIBLE" if config.mostrar_top3 else "❌ OCULTO"
        await update.message.reply_text(f"Top 3: *{estado}*", parse_mode='Markdown')

    async def cmd_ahora(self, update, context):
        if not self._esta_autorizado(update.effective_user.id, context): return
        self._actualizar_identidad(update.effective_user, context)
        cfg = context.user_data.get('config')
        msg_extra = ""
        if not self._es_horario_mercado(): msg_extra = "\n🌑 *MERCADO CERRADO* (Datos del cierre anterior)\n"
        res = self.svc.analizar(cfg.tna_objetivo)
        if not res.top_3: return await update.message.reply_text("📉 Sin datos.")
        await update.message.reply_text(f"🔎 *MANUAL* (Obj: {cfg.tna_objetivo}%){msg_extra}\n\n" + self.fmt.reporte(res, cfg.tna_objetivo, cfg.memoria_tasas_detallada, cfg.mostrar_top3), parse_mode='Markdown')

    async def cmd_tendencia_gral(self, update, context):
        if not self._esta_autorizado(update.effective_user.id, context): return
        self._actualizar_identidad(update.effective_user, context)
        if not self.svc.tiene_grafico(): return await update.message.reply_text("⏳ Recolectando datos...")
        await update.message.reply_text("🎨 Generando gráfico general...") 
        img = GeneradorGraficos.generar_general(self.svc.get_historial())
        if img: await update.message.reply_photo(img, caption="📊 Mercado")
        else: await update.message.reply_text("⚠️ Gráfico vacío")

    async def cmd_tendencia_cust(self, update, context):
        if not self._esta_autorizado(update.effective_user.id, context): return
        self._actualizar_identidad(update.effective_user, context)
        if not self.svc.tiene_grafico(): return await update.message.reply_text("⏳ Recolectando datos...")
        dias = context.user_data.get('config').dias_grafico_custom
        await update.message.reply_text(f"🎨 Generando gráfico de *{dias} días*...", parse_mode='Markdown') 
        img = GeneradorGraficos.generar_custom(self.svc.get_historial(), dias)
        if img: await update.message.reply_photo(img, caption=f"📊 {dias}d")
        else: await update.message.reply_text("⚠️ Sin datos.")

    async def cmd_stop(self, update, context):
        if not self._esta_autorizado(update.effective_user.id, context): return
        for j in context.job_queue.get_jobs_by_name(str(update.effective_chat.id)): j.schedule_removal()
        await update.message.reply_text("🛑 Detenido.")

    # Setters (Agregamos actualización de identidad a todos)
    async def cmd_set_tna(self, update, context):
        if not self._esta_autorizado(update.effective_user.id, context): return
        self._actualizar_identidad(update.effective_user, context)
        try:
            v = float(context.args[0]); c = context.user_data.get('config')
            c.tna_objetivo = v; context.user_data['config'] = c; self._actualizar_job(update.effective_chat.id, context)
            await update.message.reply_text(f"✅ TNA: {v}%")
        except: await update.message.reply_text("❌ /set 30")

    async def cmd_set_tiempo(self, update, context):
        if not self._esta_autorizado(update.effective_user.id, context): return
        self._actualizar_identidad(update.effective_user, context)
        try:
            v = float(context.args[0]); c = context.user_data.get('config')
            c.intervalo_minutos = v; context.user_data['config'] = c; self._actualizar_job(update.effective_chat.id, context)
            await update.message.reply_text(f"✅ Tiempo: {v} min")
        except: await update.message.reply_text("❌ /tiempo 5")

    async def cmd_set_variacion(self, update, context):
        if not self._esta_autorizado(update.effective_user.id, context): return
        self._actualizar_identidad(update.effective_user, context)
        try:
            v = float(context.args[0]); c = context.user_data.get('config')
            c.variacion_minima = v; context.user_data['config'] = c
            await update.message.reply_text(f"✅ Anti-Spam: {v}%")
        except: await update.message.reply_text("❌ /variacion 0.5")

    async def cmd_set_dias(self, update, context):
        if not self._esta_autorizado(update.effective_user.id, context): return
        self._actualizar_identidad(update.effective_user, context)
        try:
            v = int(context.args[0]); c = context.user_data.get('config')
            c.dias_grafico_custom = v; context.user_data['config'] = c
            await update.message.reply_text(f"✅ Gráfico: {v} días")
        except: await update.message.reply_text("❌ /set_tendencia 7")

    def _actualizar_job(self, chat_id, context):
        for j in context.job_queue.get_jobs_by_name(str(chat_id)): j.schedule_removal()
        c = context.user_data.get('config', ConfiguracionUsuario())
        context.job_queue.run_repeating(self.tarea_escaneo, interval=c.intervalo_minutos*60, first=5, chat_id=chat_id, name=str(chat_id), data=c)


# ============================================================================
# MAIN
# ============================================================================

class ServicioCauciones:
    def __init__(self, s, c, h, a, l):
        self.s=s; self.c=c; self.h=h; self.a=a; self.l=l
    def obtener_datos(self):
        d = self.c.get()
        if d: return d
        d = self.s.obtener_datos()
        if d: self.c.set(d); self.h.agregar_punto(d)
        return d
    def analizar(self, obj): return self.a.analizar(self.obtener_datos(), obj)
    def get_historial(self): return self.h.obtener_historial()
    def tiene_grafico(self): return self.h.tiene_datos()

def main():
    logger = TelegramLogger()
    svc = ServicioCauciones(ScraperIOLWeb(Config.IOL_URL, logger), CacheService(), HistorialService(), AnalizadorMercado(), logger)
    fmt = Formateador()
    h = BotHandlers(svc, fmt)

    async def post_init(app):
        await app.bot.set_my_commands([
            BotCommand("start", "Inicio"),
            BotCommand("ahora", "Ver Manual"),
            BotCommand("tendencia", "Gráfico General"),
            BotCommand("mitendencia", "Gráfico Custom"),
            BotCommand("top3", "Activar/Desactivar Top 3"),
            # Admin only
            BotCommand("usuarios", "ADMIN: Lista Detallada"),
            BotCommand("stats", "ADMIN: Resumen"),
            BotCommand("gen", "ADMIN: Generar Token"),
            BotCommand("tokens", "ADMIN: Ver Tokens")
        ])
        if app.user_data:
            c = 0
            for cid, d in app.user_data.items():
                try:
                    cfg = d.get('config')
                    if cfg:
                        if not hasattr(cfg, 'autorizado'): cfg.autorizado = True 
                        if not hasattr(cfg, 'ultima_tasa_notificada_max'): cfg.ultima_tasa_notificada_max = 0.0
                        if not hasattr(cfg, 'memoria_tasas_detallada'): cfg.memoria_tasas_detallada = {}
                        if not hasattr(cfg, 'mostrar_top3'): cfg.mostrar_top3 = True
                        if not hasattr(cfg, 'nombre'): cfg.nombre = "Desconocido"
                        if not hasattr(cfg, 'username'): cfg.username = "SinUser"
                        
                        es_admin = (cid == Config.ID_ADMIN)
                        if cfg.autorizado or es_admin:
                            app.job_queue.run_repeating(h.tarea_escaneo, interval=cfg.intervalo_minutos*60, first=10+(c*2), chat_id=cid, name=str(cid), data=cfg)
                            c+=1
                except: pass
            logger.info(f"♻️ Restaurados {c} usuarios")

    app = ApplicationBuilder().token(Config.TELEGRAM_TOKEN).persistence(PicklePersistence(Config.PERSISTENCE_FILE)).post_init(post_init).build()

    conv_start = ConversationHandler(
        entry_points=[CommandHandler('start', h.start_wizard_init)],
        states={
            ESPERANDO_CODIGO: [MessageHandler(filters.TEXT & ~filters.COMMAND, h.wizard_check_code)],
            ESPERANDO_TASA: [MessageHandler(filters.TEXT & ~filters.COMMAND, h.start_wizard_tasa)],
            ESPERANDO_TIEMPO: [MessageHandler(filters.TEXT & ~filters.COMMAND, h.start_wizard_tiempo)],
            ESPERANDO_VARIACION: [MessageHandler(filters.TEXT & ~filters.COMMAND, h.start_wizard_variacion)],
            ESPERANDO_DIAS_GRAFICO: [MessageHandler(filters.TEXT & ~filters.COMMAND, h.start_wizard_final)],
        },
        fallbacks=[CommandHandler('cancel', h.wizard_cancel)]
    )

    app.add_handler(conv_start)
    app.add_handler(CommandHandler("usuarios", h.cmd_usuarios)) # <--- NUEVO
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

    app.job_queue.run_repeating(h.recoleccion_global, interval=Config.GLOBAL_SCRAPE_INTERVAL, first=10)
    
    logger.info("🤖 Bot V17 Iniciado (Detalle Usuarios)")
    app.run_polling()

if __name__ == '__main__':
    main()
