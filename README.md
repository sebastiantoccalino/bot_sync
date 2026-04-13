# bot_sync

Bot de Telegram para registrar y dividir gastos compartidos en Google Sheets.

## Funcionalidades

### Registro de gastos
Enviá un mensaje en el siguiente formato:
```
persona [fecha] monto descripcion
```

**Fechas válidas:**
- `hoy` — fecha de hoy
- `ayer` — fecha de ayer
- `DD-MM` — día y mes (asume año actual)
- `YYYY-MM-DD` — fecha completa

**Ejemplos:**
```
seba hoy 54000 ferreteria
vicky 03-04 12500 supermercado
seba 2026-04-01 173652 expensas
```

### Gastos en cuotas
Se puede registrar un gasto en cuotas de dos formas:

**Formato 1 — monto con xN:**
```
seba hoy 90000x3 electrodomestico
```

**Formato 2 — Nc al final de la descripción:**
```
seba hoy 90000 electrodomestico 3c
```

En ambos casos se registra solo la cuota del mes actual. Las cuotas restantes se cargan automáticamente al ejecutar `/cerrar_mes` cada mes.

### Comandos disponibles

| Comando | Descripción |
|---|---|
| `/start` | Inicia el bot y activa el recordatorio mensual |
| `/resumen` | Muestra quién le debe a quién en el mes actual |
| `/gastos_seba` | Lista todos los gastos de Seba del mes con detalle |
| `/gastos_vicky` | Lista todos los gastos de Vicky del mes con detalle |
| `/cerrar_mes` | Cierra el mes: calcula deuda final, archiva datos y prepara el sheet para el mes siguiente |

### Recordatorio automático
Al ejecutar `/start` desde un chat privado, el bot programa un recordatorio automático que se envía el **1ro de cada mes a las 8:00 AM** (hora Argentina) con el resumen del mes anterior.

---

## Configuración

### Requisitos
- Python 3.10+
- Cuenta de Telegram con un bot creado via [@BotFather](https://t.me/BotFather)
- Google Sheet llamado `Gastos` con las hojas:
  - `SYNC TG` — donde se registran los gastos (columnas: persona, fecha, monto, division, descripcion desde A2)
  - `Copia de SYNC` — con fórmula de CONCLUSIÓN en celda H6
  - `CUOTAS_PENDIENTES` — se crea automáticamente si no existe

### Variables de entorno
```bash
export TOKEN='tu_token_de_telegram'
```

### Credenciales de Google
1. Crear una Service Account en [Google Cloud Console](https://console.cloud.google.com)
2. Habilitar las APIs de Google Sheets y Google Drive
3. Descargar el JSON de credenciales y guardarlo como `credentials.json`
4. Compartir el Google Sheet con el email de la Service Account

---

## Correr en Oracle Cloud VM (Free Tier)

### Primera vez

1. **Crear instancia** en Oracle Cloud:
   - Image: Ubuntu 22.04
   - Shape: VM.Standard.E2.1.Micro (free tier)
   - Agregar tu SSH key pública en el campo "SSH keys"

2. **Conectarse por SSH:**
   ```bash
   ssh -i ~/.ssh/id_ed25519 ubuntu@<IP_PUBLICA>
   ```

3. **Clonar el repo e instalar dependencias:**
   ```bash
   git clone https://github.com/sebastiantoccalino/bot_sync.git
   cd bot_sync
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

4. **Copiar credenciales desde tu Mac:**
   ```bash
   scp -i ~/.ssh/id_ed25519 ~/Downloads/credentials.json ubuntu@<IP_PUBLICA>:~/bot_sync/credentials.json
   ```

5. **Correr el bot:**
   ```bash
   export TOKEN='tu_token_de_telegram'
   source .venv/bin/activate
   python3 bot_gastos.py
   ```

### Actualizar el bot con cambios nuevos

Desde la VM:
```bash
cd ~/bot_sync
git pull origin main
```

Luego reiniciá el proceso del bot (Ctrl+C y volvé a correr `python3 bot_gastos.py`).

### Correr en background (para que no se detenga al cerrar la terminal)

```bash
nohup python3 bot_gastos.py > bot.log 2>&1 &
```

Para ver los logs:
```bash
tail -f bot.log
```

Para detenerlo:
```bash
pkill -f bot_gastos.py
```
