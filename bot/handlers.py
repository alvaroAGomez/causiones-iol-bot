import logging
import secrets
import string
from datetime import datetime

import pytz
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
)

from config import Config
from models.models import ConfiguracionUsuario
from bot.formateo import GeneradorGraficos
from services.caucion_service import ServicioCauciones

logger = logging.getLogger(__name__)

# Estados del wizard
ESPERANDO_CODIGO, ESPERANDO_TASA, ESPERANDO_TIEMPO, ESPERANDO_VARIACION, ESPERANDO_DIAS_GRAFICO = range(5)


class BotHandlers:
    def __init__(self, svc: ServicioCauciones, fmt):
        self.svc = svc
        self.fmt = fmt

    # ------------------------------------------------------------------ #
    #  HELPERS                                                             #
    # ------------------------------------------------------------------ #
    def _es_horario_mercado(self) -> bool:
        tz = pytz.timezone('America/Argentina/Buenos_Aires')
        ahora = datetime.now(tz)
        if ahora.weekday() > 4:
            return False
        return Config.HORA_APERTURA <= ahora.time() <= Config.HORA_CIERRE

    def _es_admin(self, user_id: int) -> bool:
        return user_id == Config.ID_ADMIN

    def _esta_autorizado(self, user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
        if self._es_admin(user_id):
            return True
        config = context.user_data.get('config')
        return config and isinstance(config, ConfiguracionUsuario) and config.autorizado

    def _actualizar_identidad(self, user, context):
        if not user:
            return
        config = context.user_data.get('config')
        if config:
            nombre = user.first_name if user.first_name else "Anónimo"
            username = f"@{user.username}" if user.username else "SinUser"
            if config.nombre != nombre or config.username != username:
                config.nombre = nombre
                config.username = username
                context.user_data['config'] = config

    def _actualizar_job(self, chat_id, context):
        for j in context.job_queue.get_jobs_by_name(str(chat_id)):
            j.schedule_removal()
        c = context.user_data.get('config', ConfiguracionUsuario())
        context.job_queue.run_repeating(
            self.tarea_escaneo,
            interval=c.intervalo_minutos * 60,
            first=5,
            chat_id=chat_id,
            name=str(chat_id),
            data=c
        )

    # ------------------------------------------------------------------ #
    #  ADMIN COMMANDS                                                      #
    # ------------------------------------------------------------------ #
    async def cmd_generar_token(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._es_admin(update.effective_user.id):
            return
        alfabeto = string.ascii_uppercase + string.digits
        codigo = ''.join(secrets.choice(alfabeto) for _ in range(6))
        if 'codigos_validos' not in context.bot_data:
            context.bot_data['codigos_validos'] = []
        context.bot_data['codigos_validos'].append(codigo)
        await update.message.reply_text(f"🎟️ *NUEVO TOKEN:*\n`{codigo}`", parse_mode='Markdown')

    async def cmd_listar_tokens(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._es_admin(update.effective_user.id):
            return
        codigos = context.bot_data.get('codigos_validos', [])
        msg = "\n".join([f"`{c}`" for c in codigos]) if codigos else "Ninguno."
        await update.message.reply_text(f"🎟️ *Pendientes:*\n{msg}", parse_mode='Markdown')

    async def cmd_usuarios(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._es_admin(update.effective_user.id):
            return
        from collections import Counter
        msg_lines = ["📋 *LISTA DE USUARIOS*\n"]
        total = 0
        for uid, data in context.application.user_data.items():
            cfg = data.get('config')
            if cfg and isinstance(cfg, ConfiguracionUsuario):
                total += 1
                estado = "🟢 VIP" if cfg.autorizado else "🔴 Pend"
                top3 = "Top3:SI" if cfg.mostrar_top3 else "Top3:NO"
                nombre = getattr(cfg, 'nombre', 'Desconocido')
                user = getattr(cfg, 'username', '---')
                msg_lines.append(
                    f"👤 *{nombre}* ({user})\n   └ {estado} | Obj: {cfg.tna_objetivo}% | {cfg.intervalo_minutos}min | {top3}\n"
                )
        if total == 0:
            await update.message.reply_text("📭 No hay usuarios.")
        else:
            final_msg = "\n".join(msg_lines)
            if len(final_msg) > 4000:
                final_msg = final_msg[:4000] + "\n... (cortado)"
            await update.message.reply_text(final_msg, parse_mode='Markdown')

    async def cmd_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._es_admin(update.effective_user.id):
            return
        from collections import Counter
        total_usuarios = len(context.application.user_data)
        usuarios_autorizados = 0
        tasas_objetivo = []
        for uid, data in context.application.user_data.items():
            cfg = data.get('config')
            if cfg and isinstance(cfg, ConfiguracionUsuario) and cfg.autorizado:
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
            f"💡 Usá /usuarios para ver el detalle."
        )
        await update.message.reply_text(msg, parse_mode='Markdown')

    # ------------------------------------------------------------------ #
    #  DONACIONES                                                          #
    # ------------------------------------------------------------------ #
    async def cmd_donar(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        keyboard = []
        if Config.DONAR_ALIAS_PPAY:
            keyboard.append([InlineKeyboardButton("🇦🇷 Alias Personal Pay", callback_data='donar_ppay')])
        if Config.DONAR_LEMONTAG:
            keyboard.append([InlineKeyboardButton("🍋 LemonTag ($/Cripto)", callback_data='donar_lemon')])
        if Config.DONAR_USDT_TRC20:
            keyboard.append([InlineKeyboardButton("💎 USDT (TRC20)", callback_data='donar_usdt')])
        if Config.DONAR_MP_LINK:
            keyboard.append([InlineKeyboardButton("💳 Mercado Pago (Link)", url=Config.DONAR_MP_LINK)])
        if not keyboard:
            await update.message.reply_text(
                "🚧 *En mantenimiento*.\nContactá al administrador para colaborar.",
                parse_mode='Markdown'
            )
            return
        await update.message.reply_text(
            "☕ *¡Gracias por apoyar el proyecto!*\n\n"
            "El servidor tiene costos mensuales de mantenimiento.\n"
            "Elegí tu método preferido para colaborar:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

    async def callback_donaciones(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        try:
            await query.answer()
            if 'donar_' not in query.data:
                return
            mensajes = {
                'donar_ppay': f"🇦🇷 *Personal Pay (Transferencia)*\n\nAlias:\n`{Config.DONAR_ALIAS_PPAY}`\n\n_Tocá el texto para copiar_",
                'donar_lemon': f"🍋 *Lemon Cash (LemonTag)*\n\nTag:\n`{Config.DONAR_LEMONTAG}`\n\n_Tocá el texto para copiar_",
                'donar_usdt': f"💎 *Donación Cripto (USDT)*\n\n⚠️ *RED: TRC20 (Tron)*\n\nAddress:\n`{Config.DONAR_USDT_TRC20}`\n\n_Tocá el texto para copiar_",
            }
            msj = mensajes.get(query.data)
            if msj:
                await query.message.reply_text(msj, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Error callback donaciones: {e}")

    # ------------------------------------------------------------------ #
    #  WIZARD START                                                        #
    # ------------------------------------------------------------------ #
    async def start_wizard_init(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        self._actualizar_identidad(user, context)
        msg_extra = ""
        if not self._es_horario_mercado():
            msg_extra = "\n🌑 *MERCADO CERRADO*: Se guardará la config, pero no habrá alertas.\n"

        if self._es_admin(user.id):
            if 'config' not in context.user_data:
                context.user_data['config'] = ConfiguracionUsuario(
                    autorizado=True, nombre=user.first_name, username=f"@{user.username}"
                )
            else:
                context.user_data['config'].autorizado = True
            await update.message.reply_text(
                f"👑 *Modo Admin*{msg_extra}\n\n1️⃣ *DEFINIR TASA MÍNIMA (TNA)*\n(Ej: `30`)",
                parse_mode='Markdown'
            )
            return ESPERANDO_TASA

        if self._esta_autorizado(user.id, context):
            await update.message.reply_text(
                f"👋 *Hola {user.first_name}*{msg_extra}\n\n1️⃣ *DEFINIR TASA MÍNIMA (TNA)*\n(Ej: `30`)",
                parse_mode='Markdown'
            )
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
            config = context.user_data.get('config', ConfiguracionUsuario())
            config.autorizado = True
            config.nombre = user.first_name
            config.username = f"@{user.username}" if user.username else "SinUser"
            context.user_data['config'] = config
            await update.message.reply_text(
                "🔓 *Acceso Concedido.*\n\n1️⃣ *DEFINIR TASA MÍNIMA (TNA)*\n(Ej: `30`)",
                parse_mode='Markdown'
            )
            return ESPERANDO_TASA
        else:
            await update.message.reply_text("⛔ *Token Inválido*.", parse_mode='Markdown')
            return ESPERANDO_CODIGO

    async def start_wizard_tasa(self, update, context):
        try:
            val = float(update.message.text.replace(',', '.'))
            if val < 0:
                raise ValueError
            context.user_data['temp_tna'] = val
            await update.message.reply_text(
                f"✅ Tasa: {val}%.\n\n2️⃣ *FRECUENCIA (MINUTOS)*\n(Ej: `5`)", parse_mode='Markdown'
            )
            return ESPERANDO_TIEMPO
        except:
            return ESPERANDO_TASA

    async def start_wizard_tiempo(self, update, context):
        try:
            val = float(update.message.text.replace(',', '.'))
            if val <= 0:
                raise ValueError
            context.user_data['temp_time'] = val
            await update.message.reply_text(
                f"✅ Frecuencia: {val} min.\n\n3️⃣ *ANTI-SPAM (VARIACIÓN)*\n(Ej: `0.5`)", parse_mode='Markdown'
            )
            return ESPERANDO_VARIACION
        except:
            return ESPERANDO_TIEMPO

    async def start_wizard_variacion(self, update, context):
        try:
            val = float(update.message.text.replace(',', '.'))
            if val < 0:
                raise ValueError
            context.user_data['temp_var'] = val
            await update.message.reply_text(
                f"✅ Anti-Spam: {val}%.\n\n4️⃣ *DÍAS GRÁFICO*\n(Ej: `1`)", parse_mode='Markdown'
            )
            return ESPERANDO_DIAS_GRAFICO
        except:
            return ESPERANDO_VARIACION

    async def start_wizard_final(self, update, context):
        try:
            dias = int(update.message.text)
            if dias < 1:
                raise ValueError
            config = context.user_data.get('config', ConfiguracionUsuario())
            config.tna_objetivo = context.user_data.get('temp_tna', Config.DEFAULT_TNA)
            config.intervalo_minutos = context.user_data.get('temp_time', Config.DEFAULT_MINUTOS)
            config.variacion_minima = context.user_data.get('temp_var', Config.DEFAULT_VARIACION)
            config.dias_grafico_custom = dias
            if self._es_admin(update.effective_user.id):
                config.autorizado = True
            context.user_data['config'] = config
            self._actualizar_job(update.effective_chat.id, context)
            await update.message.reply_text("🚀 *¡Configuración Lista!*", parse_mode='Markdown')
            return ConversationHandler.END
        except:
            return ESPERANDO_DIAS_GRAFICO

    async def wizard_cancel(self, update, context):
        await update.message.reply_text("❌ Cancelado.")
        return ConversationHandler.END

    # ------------------------------------------------------------------ #
    #  TAREAS PERIÓDICAS                                                   #
    # ------------------------------------------------------------------ #
    async def tarea_escaneo(self, context: ContextTypes.DEFAULT_TYPE):
        job = context.job
        config: ConfiguracionUsuario = job.data
        if not config.autorizado:
            job.schedule_removal()
            return
        if not self._es_horario_mercado():
            return

        res = self.svc.analizar(config.tna_objetivo)
        if not res.top_3:
            return

        mejor_tasa = res.tasa_maxima or 0.0
        enviar = False

        if res.hay_alerta_critica:
            enviar = True
        else:
            if config.mostrar_top3:
                if (res.oportunidades or res.top_3) and abs(mejor_tasa - config.ultima_tasa_notificada_max) >= config.variacion_minima:
                    enviar = True
            else:
                if res.oportunidades and abs(mejor_tasa - config.ultima_tasa_notificada_max) >= config.variacion_minima:
                    enviar = True

        if enviar:
            try:
                msg = self.fmt.reporte(res, config.tna_objetivo, config.memoria_tasas_detallada, config.mostrar_top3)
                if not msg.strip():
                    return
                sent_msg = await context.bot.send_message(job.chat_id, msg, parse_mode='Markdown')
                if res.hay_alerta_critica:
                    try:
                        await context.bot.pin_chat_message(job.chat_id, sent_msg.message_id)
                    except:
                        pass
                config.ultima_tasa_notificada_max = mejor_tasa
                nueva_memoria = config.memoria_tasas_detallada.copy()
                for item in res.top_3 + res.oportunidades:
                    nueva_memoria[item.dias] = item.tasa
                config.memoria_tasas_detallada = nueva_memoria
                context.application.user_data[job.chat_id]['config'] = config
            except Exception as e:
                if "Forbidden" in str(e):
                    job.schedule_removal()

    async def recoleccion_global(self, context: ContextTypes.DEFAULT_TYPE):
        try:
            if not self._es_horario_mercado():
                return
            datos = self.svc.obtener_datos()
            if datos:
                logger.info(f"🔄 Global: {len(datos)} regs")
                tz = pytz.timezone('America/Argentina/Buenos_Aires')
                context.bot_data['ultima_actualizacion'] = datetime.now(tz).strftime('%Y-%m-%d %H:%M:%S')
                max_tasa = max(d.tasa for d in datos) if datos else 0.0
                if max_tasa >= 100:
                    logger.info(f"☢️ ALERTA NUCLEAR: {max_tasa}%")
                    res_nuclear = self.svc.analizar(0)
                    for uid, data in context.application.user_data.items():
                        cfg = data.get('config')
                        if cfg and isinstance(cfg, ConfiguracionUsuario) and cfg.autorizado:
                            if abs(max_tasa - cfg.ultima_tasa_notificada_max) >= cfg.variacion_minima:
                                try:
                                    msg = self.fmt.reporte(res_nuclear, cfg.tna_objetivo, cfg.memoria_tasas_detallada, cfg.mostrar_top3)
                                    if msg.strip():
                                        sent_msg = await context.bot.send_message(uid, msg, parse_mode='Markdown')
                                        try:
                                            await context.bot.pin_chat_message(uid, sent_msg.message_id)
                                        except:
                                            pass
                                        cfg.ultima_tasa_notificada_max = max_tasa
                                        nueva_memoria = cfg.memoria_tasas_detallada.copy()
                                        for item in res_nuclear.top_3 + res_nuclear.oportunidades:
                                            nueva_memoria[item.dias] = item.tasa
                                        cfg.memoria_tasas_detallada = nueva_memoria
                                        context.application.user_data[uid]['config'] = cfg
                                except Exception as e:
                                    logger.error(f"Error broadcast {uid}: {e}")
        except Exception as e:
            logger.error(f"Err Global: {e}")

    # ------------------------------------------------------------------ #
    #  COMANDOS USUARIO                                                    #
    # ------------------------------------------------------------------ #
    async def cmd_toggle_top3(self, update, context):
        if not self._esta_autorizado(update.effective_user.id, context):
            return
        self._actualizar_identidad(update.effective_user, context)
        config = context.user_data.get('config')
        config.mostrar_top3 = not config.mostrar_top3
        context.user_data['config'] = config
        estado = "✅ VISIBLE" if config.mostrar_top3 else "❌ OCULTO"
        await update.message.reply_text(f"Top 3: *{estado}*", parse_mode='Markdown')

    async def cmd_ahora(self, update, context):
        if not self._esta_autorizado(update.effective_user.id, context):
            return
        self._actualizar_identidad(update.effective_user, context)
        cfg = context.user_data.get('config')
        msg_extra = ""
        if not self._es_horario_mercado():
            msg_extra = "\n🌑 *MERCADO CERRADO* (Datos del cierre anterior)\n"
        res = self.svc.analizar(cfg.tna_objetivo)
        if not res.top_3:
            return await update.message.reply_text("📉 Sin datos.")
        await update.message.reply_text(
            f"🔎 *MANUAL* (Obj: {cfg.tna_objetivo}%){msg_extra}\n\n"
            + self.fmt.reporte(res, cfg.tna_objetivo, cfg.memoria_tasas_detallada, cfg.mostrar_top3),
            parse_mode='Markdown'
        )

    async def cmd_tendencia_gral(self, update, context):
        if not self._esta_autorizado(update.effective_user.id, context):
            return
        self._actualizar_identidad(update.effective_user, context)
        if not self.svc.tiene_grafico():
            return await update.message.reply_text("⏳ Recolectando datos...")
        await update.message.reply_text("🎨 Generando gráfico general...")
        img = GeneradorGraficos.generar_general(self.svc.get_historial())
        if img:
            await update.message.reply_photo(img, caption="📊 Mercado")
        else:
            await update.message.reply_text("⚠️ Gráfico vacío")

    async def cmd_tendencia_cust(self, update, context):
        if not self._esta_autorizado(update.effective_user.id, context):
            return
        self._actualizar_identidad(update.effective_user, context)
        if not self.svc.tiene_grafico():
            return await update.message.reply_text("⏳ Recolectando datos...")
        dias = context.user_data.get('config').dias_grafico_custom
        await update.message.reply_text(f"🎨 Generando gráfico de *{dias} días*...", parse_mode='Markdown')
        img = GeneradorGraficos.generar_custom(self.svc.get_historial(), dias)
        if img:
            await update.message.reply_photo(img, caption=f"📊 {dias}d")
        else:
            await update.message.reply_text("⚠️ Sin datos.")

    async def cmd_stop(self, update, context):
        if not self._esta_autorizado(update.effective_user.id, context):
            return
        for j in context.job_queue.get_jobs_by_name(str(update.effective_chat.id)):
            j.schedule_removal()
        await update.message.reply_text("🛑 Detenido.")

    async def cmd_set_tna(self, update, context):
        if not self._esta_autorizado(update.effective_user.id, context):
            return
        self._actualizar_identidad(update.effective_user, context)
        try:
            v = float(context.args[0])
            c = context.user_data.get('config')
            c.tna_objetivo = v
            context.user_data['config'] = c
            self._actualizar_job(update.effective_chat.id, context)
            await update.message.reply_text(f"✅ TNA: {v}%")
        except:
            await update.message.reply_text("❌ /set 30")

    async def cmd_set_tiempo(self, update, context):
        if not self._esta_autorizado(update.effective_user.id, context):
            return
        self._actualizar_identidad(update.effective_user, context)
        try:
            v = float(context.args[0])
            c = context.user_data.get('config')
            c.intervalo_minutos = v
            context.user_data['config'] = c
            self._actualizar_job(update.effective_chat.id, context)
            await update.message.reply_text(f"✅ Tiempo: {v} min")
        except:
            await update.message.reply_text("❌ /tiempo 5")

    async def cmd_set_variacion(self, update, context):
        if not self._esta_autorizado(update.effective_user.id, context):
            return
        self._actualizar_identidad(update.effective_user, context)
        try:
            v = float(context.args[0])
            c = context.user_data.get('config')
            c.variacion_minima = v
            context.user_data['config'] = c
            await update.message.reply_text(f"✅ Anti-Spam: {v}%")
        except:
            await update.message.reply_text("❌ /variacion 0.5")

    async def cmd_set_dias(self, update, context):
        if not self._esta_autorizado(update.effective_user.id, context):
            return
        self._actualizar_identidad(update.effective_user, context)
        try:
            v = int(context.args[0])
            c = context.user_data.get('config')
            c.dias_grafico_custom = v
            context.user_data['config'] = c
            await update.message.reply_text(f"✅ Gráfico: {v} días")
        except:
            await update.message.reply_text("❌ /set_tendencia 7")
