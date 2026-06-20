import logging
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

# Estados del menú
MENU_TNA, MENU_TIEMPO, MENU_VAR, MENU_DIAS, SELECCIONANDO = range(5)


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
    async def cmd_modo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._es_admin(update.effective_user.id):
            return
        abierto = context.bot_data.get('bot_abierto', False)
        context.bot_data['bot_abierto'] = not abierto
        estado = "ABIERTO (Público)" if not abierto else "CERRADO (Requiere Aprobación)"
        await update.effective_message.reply_text(f"⚙️ El bot ahora está en modo: *{estado}*", parse_mode='Markdown')

    async def cmd_pendientes(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._es_admin(update.effective_user.id):
            return
        
        pendientes = []
        for uid, data in context.application.user_data.items():
            cfg = data.get('config')
            if cfg and isinstance(cfg, ConfiguracionUsuario) and not cfg.autorizado and uid != Config.ID_ADMIN:
                pendientes.append((uid, cfg))
        
        if not pendientes:
            await update.effective_message.reply_text("📭 No hay usuarios pendientes de aprobación.")
            return

        for uid, cfg in pendientes:
            keyboard = [
                [
                    InlineKeyboardButton("✅ Aprobar", callback_data=f"admin_aprobar_{uid}"),
                    InlineKeyboardButton("❌ Rechazar", callback_data=f"admin_rechazar_{uid}")
                ]
            ]
            await update.effective_message.reply_text(
                f"👤 *Usuario Pendiente*\nNombre: {cfg.nombre}\nUsername: {cfg.username}\nID: `{uid}`",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )

    async def callback_admin_acciones(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if not self._es_admin(update.effective_user.id):
            await query.answer("No tienes permiso.", show_alert=True)
            return

        await query.answer()
        data = query.data
        if data.startswith("admin_aprobar_"):
            uid = int(data.split("_")[2])
            user_data = context.application.user_data.get(uid)
            if user_data and 'config' in user_data:
                user_data['config'].autorizado = True
                await query.edit_message_text(f"✅ Usuario {uid} aprobado.")
                try:
                    await context.bot.send_message(
                        uid, 
                        "✅ *¡Tu cuenta ha sido aprobada!*\nYa puedes utilizar el bot. Escribe /menu para configurar tus alertas.",
                        parse_mode='Markdown'
                    )
                except:
                    pass
            else:
                await query.edit_message_text(f"⚠️ No se encontró la data del usuario {uid}.")
                
        elif data.startswith("admin_rechazar_"):
            uid = int(data.split("_")[2])
            await query.edit_message_text(f"❌ Usuario {uid} rechazado.")
            try:
                await context.bot.send_message(uid, "❌ Tu solicitud de acceso ha sido rechazada por el administrador.")
            except:
                pass


    async def cmd_usuarios(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._es_admin(update.effective_user.id):
            return
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
            await update.effective_message.reply_text("📭 No hay usuarios.")
        else:
            final_msg = "\n".join(msg_lines)
            if len(final_msg) > 4000:
                final_msg = final_msg[:4000] + "\n... (cortado)"
            await update.effective_message.reply_text(final_msg, parse_mode='Markdown')

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
        
        abierto = context.bot_data.get('bot_abierto', False)
        modo = "ABIERTO" if abierto else "CERRADO"
        ultimo_scrape = context.bot_data.get('ultima_actualizacion', 'Nunca')
        top_tasas = "N/A"
        if tasas_objetivo:
            counts = Counter(tasas_objetivo).most_common(3)
            top_tasas = ", ".join([f"{t}% ({c})" for t, c in counts])
        msg = (
            f"📊 *ESTADÍSTICAS*\n\n"
            f"⚙️ *Modo:* {modo}\n"
            f"👥 *Total:* {total_usuarios} (VIP: {usuarios_autorizados})\n"
            f"📉 *Tasas:* {top_tasas}\n"
            f"🩺 *Scrape:* {ultimo_scrape}\n\n"
            f"💡 Usá /usuarios para ver el detalle o /pendientes para aprobar."
        )
        await update.effective_message.reply_text(msg, parse_mode='Markdown')

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
            await update.effective_message.reply_text(
                "🚧 *En mantenimiento*.\nContactá al administrador para colaborar.",
                parse_mode='Markdown'
            )
            return
        await update.effective_message.reply_text(
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
    #  USER START & SETUP                                                  #
    # ------------------------------------------------------------------ #
    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        
        # Inicializar config si no existe
        if 'config' not in context.user_data:
            context.user_data['config'] = ConfiguracionUsuario(
                nombre=user.first_name, 
                username=f"@{user.username}" if user.username else "SinUser",
                autorizado=False
            )
        
        cfg = context.user_data['config']
        self._actualizar_identidad(user, context)

        # Si es admin, siempre está autorizado
        if self._es_admin(user.id):
            cfg.autorizado = True
            context.user_data['config'] = cfg
            await update.message.reply_text(
                "👑 *Bienvenido Administrador*\nYa tienes acceso total. Usa /menu para configurar tus alertas o /ayuda para ver los comandos.",
                parse_mode='Markdown'
            )
            return

        # Si ya está autorizado, darle la bienvenida y sugerir el menú
        if cfg.autorizado:
            await update.message.reply_text(
                f"👋 ¡Hola de nuevo, {user.first_name}!\nTu cuenta está activa. Usa /menu para configurar tus alertas o /ahora para ver las tasas del momento.",
                parse_mode='Markdown'
            )
            return

        # Si no está autorizado, revisar modo del bot
        abierto = context.bot_data.get('bot_abierto', False)
        if abierto:
            cfg.autorizado = True
            context.user_data['config'] = cfg
            self._actualizar_job(update.effective_chat.id, context)
            await update.message.reply_text(
                f"👋 ¡Hola {user.first_name}! Bienvenido al **Bot de Cauciones**.\n\n"
                "Te ayudaré a monitorear las mejores tasas del mercado de forma automática para que le saques el mayor rendimiento a tu dinero.\n\n"
                "✅ *Tu cuenta ha sido activada automáticamente.*\n"
                "👉 Escribe /menu para configurar tus alertas.",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                f"👋 ¡Hola {user.first_name}! Bienvenido al **Bot de Cauciones**.\n\n"
                "🔒 *Actualmente el acceso es privado y requiere aprobación.*\n"
                "He enviado tu solicitud al administrador. Te avisaré por aquí en cuanto seas aprobado.",
                parse_mode='Markdown'
            )
            try:
                await context.bot.send_message(
                    Config.ID_ADMIN,
                    f"👤 *Nueva Solicitud de Acceso*\nNombre: {user.first_name}\nUsername: @{user.username}\nID: `{user.id}`\n\nUsa /pendientes para revisar.",
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.error(f"No se pudo notificar al admin: {e}")

    # ------------------------------------------------------------------ #
    #  MENÚ INTERACTIVO                                                    #
    # ------------------------------------------------------------------ #
    async def cmd_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if 'config' not in context.user_data:
            context.user_data['config'] = ConfiguracionUsuario(
                nombre=update.effective_user.first_name, 
                username=f"@{update.effective_user.username}" if update.effective_user.username else "SinUser",
                autorizado=self._es_admin(update.effective_user.id)
            )

        if not self._esta_autorizado(update.effective_user.id, context):
            await update.effective_message.reply_text("⛔ No estás autorizado para usar el bot.")
            return ConversationHandler.END

        cfg = context.user_data.get('config')
        top3_estado = "Activado" if cfg.mostrar_top3 else "Desactivado"
        
        keyboard = [
            [InlineKeyboardButton(f"⚙️ Tasa Objetivo (Actual: {cfg.tna_objetivo}%)", callback_data='menu_tna')],
            [InlineKeyboardButton(f"⏱️ Frecuencia (Actual: {cfg.intervalo_minutos} min)", callback_data='menu_tiempo')],
            [InlineKeyboardButton(f"🛡️ Anti-Spam (Actual: {cfg.variacion_minima}%)", callback_data='menu_var')],
            [InlineKeyboardButton(f"📊 Días de Gráfico (Actual: {cfg.dias_grafico_custom}d)", callback_data='menu_dias')],
            [InlineKeyboardButton(f"🏆 Top 3: {top3_estado}", callback_data='menu_top3')],
            [
                InlineKeyboardButton("📈 Tendencia General", callback_data='menu_tendencia_gral'),
                InlineKeyboardButton("📊 Tendencia Custom", callback_data='menu_tendencia_cust')
            ],
            [
                InlineKeyboardButton("☕ Donar / Apoyar", callback_data='menu_donar'),
                InlineKeyboardButton("📖 Ayuda / Guía", callback_data='menu_ayuda')
            ]
        ]
        
        if self._es_admin(update.effective_user.id):
            keyboard.append([
                InlineKeyboardButton("👑 Cambiar Modo Bot", callback_data='menu_admin_modo'),
                InlineKeyboardButton("👥 Aprobar Pendientes", callback_data='menu_admin_pend')
            ])
            keyboard.append([
                InlineKeyboardButton("📋 Lista de Usuarios", callback_data='menu_admin_users'),
                InlineKeyboardButton("📊 Stats del Bot", callback_data='menu_admin_stats')
            ])

        await update.effective_message.reply_text(
            "🛠 *MENÚ PRINCIPAL*\nSelecciona una opción:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
        return SELECCIONANDO

    async def callback_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if not self._esta_autorizado(update.effective_user.id, context):
            await query.answer("No estás autorizado.")
            return ConversationHandler.END

        await query.answer()
        cfg = context.user_data.get('config')

        if query.data == 'menu_tna':
            await query.message.reply_text(
                "⚙️ *Tasa Objetivo (TNA)*\n\n"
                "¿A partir de qué Tasa quieres que te avise? Si la tasa en el mercado supera este número, te enviaré una alerta.\n\n"
                "👉 Escribe el nuevo valor (Ej: `35`):",
                parse_mode='Markdown'
            )
            return MENU_TNA
            
        elif query.data == 'menu_tiempo':
            await query.message.reply_text(
                "⏱️ *Frecuencia de Búsqueda*\n\n"
                "¿Cada cuántos minutos reviso el mercado por ti? Se recomienda entre 5 y 15 minutos para no saturarte.\n\n"
                "👉 Escribe los minutos (Ej: `10`):",
                parse_mode='Markdown'
            )
            return MENU_TIEMPO
            
        elif query.data == 'menu_var':
            await query.message.reply_text(
                "🛡️ *Filtro Anti-Spam*\n\n"
                "Es la variación mínima necesaria para volver a notificarte (para no repetir el mismo valor). Si estaba en 35% y pones variación de 0.5%, te avisaré si llega a 35.5%.\n\n"
                "👉 Escribe el porcentaje (Ej: `0.5`):",
                parse_mode='Markdown'
            )
            return MENU_VAR
            
        elif query.data == 'menu_dias':
            await query.message.reply_text(
                "📊 *Gráfico Personalizado*\n\n"
                "¿Cuántos días de plazo de caución quieres seguir de cerca en tu gráfico?\n\n"
                "👉 Escribe los días (Ej: `1` o `7`):",
                parse_mode='Markdown'
            )
            return MENU_DIAS
            
        elif query.data == 'menu_top3':
            cfg.mostrar_top3 = not cfg.mostrar_top3
            context.user_data['config'] = cfg
            estado = "✅ ACTIVADO" if cfg.mostrar_top3 else "❌ DESACTIVADO"
            await query.edit_message_text(f"🏆 Mostrar Top 3 en alertas: *{estado}*", parse_mode='Markdown')
            return ConversationHandler.END

        elif query.data == 'menu_tendencia_gral':
            await self.cmd_tendencia_gral(update, context)
            return ConversationHandler.END
            
        elif query.data == 'menu_tendencia_cust':
            await self.cmd_tendencia_cust(update, context)
            return ConversationHandler.END
            
        elif query.data == 'menu_donar':
            await self.cmd_donar(update, context)
            return ConversationHandler.END
            
        elif query.data == 'menu_ayuda':
            await self.cmd_ayuda(update, context)
            return ConversationHandler.END
            
        # Callbacks de ADMIN desde el menú
        elif query.data == 'menu_admin_modo':
            await self.cmd_modo(update, context)
            return ConversationHandler.END
        elif query.data == 'menu_admin_pend':
            await self.cmd_pendientes(update, context)
            return ConversationHandler.END
        elif query.data == 'menu_admin_users':
            await self.cmd_usuarios(update, context)
            return ConversationHandler.END
        elif query.data == 'menu_admin_stats':
            await self.cmd_stats(update, context)
            return ConversationHandler.END

    # Inputs del Menú
    async def input_tna(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            val = float(update.message.text.replace(',', '.'))
            if val < 0: raise ValueError
            cfg = context.user_data.get('config')
            cfg.tna_objetivo = val
            context.user_data['config'] = cfg
            self._actualizar_job(update.effective_chat.id, context)
            await update.message.reply_text(f"✅ ¡Guardado! Te avisaré cuando las tasas superen el *{val}%*.", parse_mode='Markdown')
            return ConversationHandler.END
        except:
            await update.message.reply_text("❌ Valor inválido. Por favor escribe un número como `35` o `35.5`.")
            return MENU_TNA

    async def input_tiempo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            val = float(update.message.text.replace(',', '.'))
            if val <= 0: raise ValueError
            cfg = context.user_data.get('config')
            cfg.intervalo_minutos = val
            context.user_data['config'] = cfg
            self._actualizar_job(update.effective_chat.id, context)
            await update.message.reply_text(f"✅ ¡Guardado! Buscaré oportunidades cada *{val} minutos*.", parse_mode='Markdown')
            return ConversationHandler.END
        except:
            await update.message.reply_text("❌ Valor inválido. Por favor escribe un número mayor a cero.")
            return MENU_TIEMPO

    async def input_var(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            val = float(update.message.text.replace(',', '.'))
            if val < 0: raise ValueError
            cfg = context.user_data.get('config')
            cfg.variacion_minima = val
            context.user_data['config'] = cfg
            await update.message.reply_text(f"✅ ¡Guardado! Variación anti-spam configurada en *{val}%*.", parse_mode='Markdown')
            return ConversationHandler.END
        except:
            await update.message.reply_text("❌ Valor inválido. Por favor escribe un número positivo.")
            return MENU_VAR

    async def input_dias(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            val = int(update.message.text)
            if val < 1: raise ValueError
            cfg = context.user_data.get('config')
            cfg.dias_grafico_custom = val
            context.user_data['config'] = cfg
            await update.message.reply_text(f"✅ ¡Guardado! Tu gráfico mostrará el plazo de *{val} días*.", parse_mode='Markdown')
            return ConversationHandler.END
        except:
            await update.message.reply_text("❌ Valor inválido. Por favor escribe un número entero (ej: `1`).")
            return MENU_DIAS

    async def menu_cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("❌ Operación cancelada.")
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
    async def cmd_ayuda(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = (
            "📖 *GUÍA DE USO*\n\n"
            "🔹 /start - Iniciar el bot y ver el estado de tu cuenta.\n"
            "🔹 /menu - Configurar tus alertas (Tasa, tiempo, anti-spam, etc).\n"
            "🔹 /ahora - Ver las tasas actuales en el mercado al instante.\n"
            "🔹 /tendencia - Ver gráfico general de tasas a corto, medio y largo plazo.\n"
            "🔹 /mitendencia - Ver gráfico de la cantidad de días que elegiste en tu menú.\n"
            "🔹 /stop - Detener las alertas automáticas.\n"
            "🔹 /donar - Ayudar al mantenimiento del bot.\n\n"
            "💡 *¿Qué es el Filtro Anti-Spam?*\n"
            "Sirve para no enviarte mensajes repetidos. Si la tasa máxima sube o baja más allá de ese porcentaje, te enviaré una alerta nueva."
        )
        await update.effective_message.reply_text(msg, parse_mode='Markdown')

    async def cmd_ahora(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._esta_autorizado(update.effective_user.id, context):
            return
        self._actualizar_identidad(update.effective_user, context)
        cfg = context.user_data.get('config')
        msg_extra = ""
        if not self._es_horario_mercado():
            msg_extra = "\n🌑 *MERCADO CERRADO* (Datos del cierre anterior)\n"
        res = self.svc.analizar(cfg.tna_objetivo)
        if not res.top_3:
            return await update.message.reply_text("📉 Sin datos actualmente.")
        await update.message.reply_text(
            f"🔎 *Tasas Actuales* (Tu Objetivo: {cfg.tna_objetivo}%){msg_extra}\n\n"
            + self.fmt.reporte(res, cfg.tna_objetivo, cfg.memoria_tasas_detallada, cfg.mostrar_top3),
            parse_mode='Markdown'
        )

    async def cmd_tendencia_gral(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._esta_autorizado(update.effective_user.id, context):
            return
        self._actualizar_identidad(update.effective_user, context)
        if not self.svc.tiene_grafico():
            return await update.effective_message.reply_text("⏳ Recolectando datos, intenta más tarde...")
        await update.effective_message.reply_text("🎨 Generando gráfico general...")
        img = GeneradorGraficos.generar_general(self.svc.get_historial())
        if img:
            await update.effective_message.reply_photo(img, caption="📊 Tendencia General del Mercado")
        else:
            await update.effective_message.reply_text("⚠️ Gráfico vacío por el momento.")

    async def cmd_tendencia_cust(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._esta_autorizado(update.effective_user.id, context):
            return
        self._actualizar_identidad(update.effective_user, context)
        if not self.svc.tiene_grafico():
            return await update.effective_message.reply_text("⏳ Recolectando datos...")
        dias = context.user_data.get('config').dias_grafico_custom
        await update.effective_message.reply_text(f"🎨 Generando gráfico de *{dias} días*...", parse_mode='Markdown')
        img = GeneradorGraficos.generar_custom(self.svc.get_historial(), dias)
        if img:
            await update.effective_message.reply_photo(img, caption=f"📊 Tendencia a {dias} días")
        else:
            await update.effective_message.reply_text("⚠️ Sin datos para ese plazo en este momento.")

    async def cmd_stop(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._esta_autorizado(update.effective_user.id, context):
            return
        for j in context.job_queue.get_jobs_by_name(str(update.effective_chat.id)):
            j.schedule_removal()
        await update.message.reply_text("🛑 Alertas automáticas detenidas. Vuelve a configurar la frecuencia en /menu para activarlas de nuevo.")
