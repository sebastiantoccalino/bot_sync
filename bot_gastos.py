import logging
import re
import calendar
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters, JobQueue
import gspread
from google.oauth2.service_account import Credentials
import datetime
import pytz
from apscheduler.schedulers.background import BackgroundScheduler
import os
import json

# Agrego la función para limpiar montos

def limpiar_monto(monto_str):
    # Elimina puntos de miles y deja solo el decimal
    monto_str = monto_str.replace("$", "").replace(",", ".").strip()
    if monto_str.count(".") > 1:
        partes = monto_str.split('.')
        monto_str = ''.join(partes[:-1]) + '.' + partes[-1]
    return monto_str

def sumar_meses(fecha, meses):
    mes = fecha.month - 1 + meses
    anio = fecha.year + mes // 12
    mes = mes % 12 + 1
    dia = min(fecha.day, calendar.monthrange(anio, mes)[1])
    return fecha.replace(year=anio, month=mes, day=dia)

def parsear_cuotas(monto_raw, descripcion_partes):
    """
    Detecta cuotas en dos formatos:
      - monto con xN al final: "80000x3"
      - última palabra de descripción con Nc: "regalo 3c"
    Devuelve (monto_str_limpio, descripcion_limpia, num_cuotas)
    """
    cuotas = 1
    # Formato 1: monto contiene xN (ej: 80000x3)
    match = re.match(r'^([\d.,\$]+)[xX](\d+)$', monto_raw)
    if match:
        return match.group(1), " ".join(descripcion_partes), int(match.group(2))
    # Formato 2: última palabra de descripción es Nc (ej: 3c, 12c)
    if descripcion_partes:
        match = re.match(r'^(\d+)[cC]$', descripcion_partes[-1])
        if match:
            return monto_raw, " ".join(descripcion_partes[:-1]), int(match.group(1))
    return monto_raw, " ".join(descripcion_partes), cuotas

# Configuración básica de logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)


TOKEN = os.environ["TOKEN"]

# --- Configuración de Google Sheets ---
# Nombre exacto de tu hoja de cálculo (cambiá esto si tu sheet tiene otro nombre)
SHEET_NAME = 'Gastos'

# Ámbitos requeridos para Google Sheets y Drive
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

# Inicializa el cliente de Google Sheets
with open("credentials.json") as f:
    creds_dict = json.load(f)
creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
gc = gspread.authorize(creds)
sh = gc.open(SHEET_NAME)
worksheet = sh.worksheet('SYNC TG')

# Hoja para cuotas pendientes (se crea si no existe)
try:
    ws_cuotas = sh.worksheet('CUOTAS_PENDIENTES')
except Exception:
    ws_cuotas = sh.add_worksheet(title='CUOTAS_PENDIENTES', rows=200, cols=7)
    ws_cuotas.update('A1:G1', [['persona', 'monto_cuota', 'division_cuota', 'descripcion_base', 'proxima_cuota', 'total_cuotas', 'dia_mes']])

# --- HANDLERS DE COMANDOS Y MENSAJES ---

def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == 'private':
        programar_recordatorio_mensual(context.application, update.effective_chat.id)
    return update.message.reply_text(
        "¡Hola! Soy tu bot de gastos compartidos. Mandame los gastos en el formato:\npersona [fecha|hoy|ayer|DD-MM] monto descripcion\nEjemplo: seba hoy 54000 ferreteria"
    )

def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Nuevo formato flexible: persona [fecha|hoy|ayer] monto descripcion
    text = update.message.text.strip().lower()
    if "gracias" in text:
        return update.message.reply_text("¡De nada Vicky! Para servirte siempre 😄\n Que tengas un excelente día ")
    if "puto" in text:
        return update.message.reply_text("Puto tu viejo, conchuda")
    if "pelotudo" in text:
        return update.message.reply_text("Chupame bien los huevos")
    if "estupido" in text:
        return update.message.reply_text("Me dice estupido y no puede ni cargar un gasto en un excel")
    if "forro" in text:
        return update.message.reply_text("Taradita")
    try:
        partes = text.split()
        if len(partes) < 4:
            raise ValueError("Faltan datos. Formato: persona [fecha|hoy|ayer] monto descripcion")
        persona = partes[0].capitalize()
        posible_fecha = partes[1].lower()

        # Procesar fecha
        if posible_fecha == "hoy":
            fecha = datetime.date.today().isoformat()
        elif posible_fecha == "ayer":
            fecha = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        else:
            try:
                # Si es YYYY-MM-DD
                fecha = datetime.datetime.strptime(posible_fecha, "%Y-%m-%d").date().isoformat()
            except ValueError:
                try:
                    # Si es DD-MM o D-M, asume año actual
                    fecha_dt = datetime.datetime.strptime(posible_fecha, "%d-%m")
                    fecha = fecha_dt.replace(year=datetime.date.today().year).date().isoformat()
                except ValueError:
                    raise ValueError("La fecha debe ser 'hoy', 'ayer', YYYY-MM-DD o DD-MM (usa año actual)")

        monto_raw = partes[2]
        descripcion_partes = partes[3:]
        monto_str, descripcion, num_cuotas = parsear_cuotas(monto_raw, descripcion_partes)

        monto_str = limpiar_monto(monto_str)
        monto_total = float(monto_str)
        monto_cuota = monto_total / num_cuotas
        division_cuota = monto_cuota / 2

        fecha_base = datetime.date.fromisoformat(fecha)
        desc_cuota1 = f"{descripcion} (1/{num_cuotas})" if num_cuotas > 1 else descripcion

        # Buscar la primera fila vacía en las columnas A-E
        values = worksheet.get_values('A3:E1000')
        row_idx = 3
        for fila in values:
            if all(cell == '' for cell in fila):
                break
            row_idx += 1

        # Insertar solo la cuota del mes actual
        try:
            worksheet.update(f'A{row_idx}:E{row_idx}', [[persona, fecha, monto_cuota, division_cuota, desc_cuota1]])
        except Exception as error_gs:
            logging.error(f"Error escribiendo en Google Sheets: {error_gs}")
            return update.message.reply_text(f"Error escribiendo en Google Sheets: {error_gs}")

        # Guardar cuotas restantes en la hoja CUOTAS_PENDIENTES
        if num_cuotas > 1:
            ws_cuotas.append_row([persona, monto_cuota, division_cuota, descripcion, 2, num_cuotas, fecha_base.day])
            return update.message.reply_text(
                f"Gasto en {num_cuotas} cuotas guardado:\nPersona: {persona}\nMonto total: {monto_total}\n"
                f"Monto por cuota: {round(monto_cuota, 2)}\nDescripción: {descripcion}\nCada uno paga por cuota: {round(division_cuota, 2)}\n"
                f"Cuotas 2 a {num_cuotas} se cargarán automáticamente al cerrar cada mes."
            )
        return update.message.reply_text(
            f"Gasto guardado:\nPersona: {persona}\nFecha: {fecha}\nMonto: {monto_total}\nDescripción: {descripcion}\nCada uno paga: {round(division_cuota, 2)}"
        )
    except Exception as e:
        logging.error(f"Error procesando el mensaje: {e}")
        return update.message.reply_text(
            f"Error al procesar el gasto. Formato: persona [fecha|hoy|ayer] monto descripcion\nEjemplo: seba hoy 54000 ferreteria\n\nDetalle: {e}"
        )

def resumen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import calendar
    # Leer solo datos del mes actual (A3:E1000)
    values = worksheet.get_values('A3:E1000')
    rows = [fila for fila in values if any(cell != '' for cell in fila)]
    if not rows:
        return update.message.reply_text("No hay gastos registrados.")

    # Filtrar solo los del mes actual (por fecha)
    hoy = datetime.date.today()
    mes_actual = hoy.month
    anio_actual = hoy.year
    gastos = {'seba': 0, 'vicky': 0}
    for fila in rows:
        persona = fila[0].strip().lower()
        fecha_str = fila[1].strip()
        monto_str = limpiar_monto(fila[2])
        try:
            fecha = datetime.datetime.strptime(fecha_str, "%Y-%m-%d").date()
            mes = fecha.month
            anio = fecha.year
        except Exception:
            continue
        if mes == mes_actual and anio == anio_actual:
            if 'seba' in persona:
                gastos['seba'] += float(monto_str)
            elif 'vicky' in persona:
                gastos['vicky'] += float(monto_str)

    s = gastos['seba']
    v = gastos['vicky']
    if s > v:
        msg = f"VICKY DEBE ${round((s-v)/2,2)}"
    elif v > s:
        msg = f"SEBA DEBE ${round((v-s)/2,2)}"
    else:
        msg = "IGUALES"
    msg += f"\n\nTotal Seba: ${round(s,2)}\nTotal Vicky: ${round(v,2)}"
    return update.message.reply_text(msg)

def gastos_seba(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Leer solo datos del mes actual (A3:E1000)
    values = worksheet.get_values('A3:E1000')
    hoy = datetime.date.today()
    mes_actual = hoy.month
    anio_actual = hoy.year
    total = 0
    detalles = []
    for fila in values:
        if not any(cell != '' for cell in fila):
            continue
        persona = fila[0].strip().lower()
        fecha_str = fila[1].strip()
        monto_str = limpiar_monto(fila[2])
        try:
            fecha = datetime.datetime.strptime(fecha_str, "%Y-%m-%d").date()
            mes = fecha.month
            anio = fecha.year
        except Exception:
            continue
        if mes == mes_actual and anio == anio_actual and 'seba' in persona:
            total += float(monto_str)
            detalles.append(f"{fecha_str}: ${monto_str} - {fila[4]}")
    if detalles:
        msg = f"Gastos de Seba este mes:\n" + "\n".join(detalles) + f"\n\nTotal: ${round(total,2)}"
    else:
        msg = "No hay gastos de Seba este mes."
    return update.message.reply_text(msg)


def gastos_vicky(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Leer solo datos del mes actual (A3:E1000)
    values = worksheet.get_values('A3:E1000')
    hoy = datetime.date.today()
    mes_actual = hoy.month
    anio_actual = hoy.year
    total = 0
    detalles = []
    for fila in values:
        if not any(cell != '' for cell in fila):
            continue
        persona = fila[0].strip().lower()
        fecha_str = fila[1].strip()
        monto_str = limpiar_monto(fila[2])
        try:
            fecha = datetime.datetime.strptime(fecha_str, "%Y-%m-%d").date()
            mes = fecha.month
            anio = fecha.year
        except Exception:
            continue
        if mes == mes_actual and anio == anio_actual and 'vicky' in persona:
            total += float(monto_str)
            detalles.append(f"{fecha_str}: ${monto_str} - {fila[4]}")
    if detalles:
        msg = f"Gastos de Vicky este mes:\n" + "\n".join(detalles) + f"\n\nTotal: ${round(total,2)}"
    else:
        msg = "No hay gastos de Vicky este mes."
    return update.message.reply_text(msg)

async def cerrar_mes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import calendar
    from datetime import datetime
    now = datetime.now()
    nombre_mes = calendar.month_name[now.month]
    anio = now.year
    mes_actual = f"{nombre_mes} {anio}"

    # Leer y calcular conclusión ANTES de modificar la hoja
    rows = worksheet.get_values('A3:E1000')
    gastos = {'seba': 0, 'vicky': 0}
    for fila in rows:
        if not any(cell != '' for cell in fila):
            continue
        persona = fila[0].strip().lower()
        fecha_str = fila[1].strip()
        monto_str = limpiar_monto(fila[2])
        try:
            fecha = datetime.strptime(fecha_str, "%Y-%m-%d").date()
        except Exception:
            continue
        if fecha.month == now.month and fecha.year == now.year:
            if 'seba' in persona:
                gastos['seba'] += float(monto_str)
            elif 'vicky' in persona:
                gastos['vicky'] += float(monto_str)
    s = gastos['seba']
    v = gastos['vicky']
    if s > v:
        conclusion = f"Vicky le debe a Seba: ${round((s - v) / 2, 2)}"
    elif v > s:
        conclusion = f"Seba le debe a Vicky: ${round((v - s) / 2, 2)}"
    else:
        conclusion = "No había deuda pendiente."

    worksheet.insert_cols([[], [], [], [], []], 1)
    worksheet.merge_cells(1, 1, 1, 5)
    worksheet.update_cell(1, 1, mes_actual)
    headers = ["persona", "fecha", "monto", "division", "descripcion"]
    worksheet.update('A2:E2', [headers])
    empty_rows = [["" for _ in range(5)] for _ in range(997)]
    worksheet.update('A3:E1000', empty_rows)

    # Insertar cuotas pendientes en el nuevo mes
    cuotas_data = ws_cuotas.get_all_values()
    filas_pendientes = cuotas_data[1:] if len(cuotas_data) > 1 else []
    filas_a_conservar = []
    cuotas_insertadas = []
    row_idx = 3
    for row in filas_pendientes:
        if not any(cell != '' for cell in row):
            continue
        persona_c, monto_c_str, division_c_str, desc_base, proxima_c_str, total_c_str, dia_mes_str = row
        monto_c = float(monto_c_str)
        division_c = float(division_c_str)
        proxima_c = int(proxima_c_str)
        total_c = int(total_c_str)
        dia_mes_c = int(dia_mes_str)

        dia = min(dia_mes_c, calendar.monthrange(now.year, now.month)[1])
        fecha_c = datetime(now.year, now.month, dia).date().isoformat()
        desc_c = f"{desc_base} ({proxima_c}/{total_c})"
        worksheet.update(f'A{row_idx}:E{row_idx}', [[persona_c, fecha_c, monto_c, division_c, desc_c]])
        cuotas_insertadas.append(desc_c)
        row_idx += 1

        if proxima_c < total_c:
            filas_a_conservar.append([persona_c, monto_c, division_c, desc_base, proxima_c + 1, total_c, dia_mes_c])

    # Actualizar hoja CUOTAS_PENDIENTES
    ws_cuotas.clear()
    headers_cuotas = [['persona', 'monto_cuota', 'division_cuota', 'descripcion_base', 'proxima_cuota', 'total_cuotas', 'dia_mes']]
    if filas_a_conservar:
        ws_cuotas.update(f'A1:G{1 + len(filas_a_conservar)}', headers_cuotas + filas_a_conservar)
    else:
        ws_cuotas.update('A1:G1', headers_cuotas)

    msg = f"Mes cerrado CRACK! Se inició el listado para {mes_actual}.\n\n{conclusion}"
    if cuotas_insertadas:
        msg += "\n\nCuotas cargadas automáticamente:\n" + "\n".join(f"• {c}" for c in cuotas_insertadas)
    await update.message.reply_text(msg)

def resumen_mes_anterior(context):
    # Calcula el resumen del mes anterior y lo envía por chat privado
    app = context.bot
    chat_id = context.job.context  # El chat_id se pasa como context
    hoy = datetime.date.today()
    if hoy.month == 1:
        mes = 12
        anio = hoy.year - 1
    else:
        mes = hoy.month - 1
        anio = hoy.year
    rows = worksheet.get_values('A3:E1000')
    gastos = {'seba': 0, 'vicky': 0}
    for fila in rows:
        if not fila:
            continue
        persona = fila[0].strip().lower()
        fecha_str = fila[1].strip()
        monto_str = limpiar_monto(fila[2])
        try:
            if "/" in fecha_str:
                partes = fecha_str.split("/")
                dia = int(partes[0])
                mes_gasto = int(partes[1])
                if len(partes) > 2:
                    anio_gasto = int(partes[2])
                else:
                    anio_gasto = anio
            else:
                fecha = datetime.datetime.strptime(fecha_str, "%Y-%m-%d").date()
                mes_gasto = fecha.month
                anio_gasto = fecha.year
        except Exception:
            continue
        if mes_gasto == mes and anio_gasto == anio:
            if 'seba' in persona:
                gastos['seba'] += float(monto_str)
            elif 'vicky' in persona:
                gastos['vicky'] += float(monto_str)
    s = gastos['seba']
    v = gastos['vicky']
    if s > v:
        msg = f"VICKY DEBE ${round((s-v)/2,2)}"
    elif v > s:
        msg = f"SEBA DEBE ${round((v-s)/2,2)}"
    else:
        msg = "IGUALES"
    msg += f"\n\nTotal Seba: ${round(s,2)}\nTotal Vicky: ${round(v,2)}"
    app.send_message(chat_id=chat_id, text=f"Resumen del mes anterior:\n{msg}")

def programar_recordatorio_mensual(app, chat_id):
    scheduler = BackgroundScheduler(timezone=pytz.timezone('America/Argentina/Buenos_Aires'))
    # Ejecuta todos los días a las 08:00 AM, pero solo manda el resumen si es el primer día del mes
    def tarea():
        if datetime.date.today().day == 1:
            resumen_mes_anterior(type('obj', (object,), {'bot': app, 'job': type('obj', (object,), {'context': chat_id})})())
    scheduler.add_job(tarea, 'cron', hour=8, minute=0)
    scheduler.start()

# --- MAIN ---
def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("resumen", resumen))
    app.add_handler(CommandHandler("gastos_seba", gastos_seba))
    app.add_handler(CommandHandler("gastos_vicky", gastos_vicky))
    app.add_handler(CommandHandler("cerrar_mes", cerrar_mes))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.run_polling()
    print("Bot corriendo. Presioná Ctrl+C para frenar.")

if __name__ == "__main__":
    main()
