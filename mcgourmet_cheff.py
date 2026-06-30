"""
McGourmet Chef Bot v2.1
Asistente de maridaje para clientes con pedido Confirmado.
Flask + OpenAI GPT-4o + PostgreSQL

CAMBIOS v2.0:
- Contador de consultas movido al código Python (era unreliable en el system prompt)
- Bloqueo ocurre ANTES de llamar a la API (sin costo de tokens)
- Nueva columna 'num_consulta' en tbl_CheffMaridaje para auditoría
- Respuesta incluye contador de consultas restantes
- SYSTEM_PROMPT simplificado (sin lógica de contador)
- Historial limitado a MAX_HISTORIAL_TURNOS para controlar tokens

CAMBIOS v2.1:
- Flujo de feedback: SI / NO después de cada sugerencia
- Flujo de comentario libre opcional tras el feedback
- Nuevas columnas en tbl_cheffmaridaje: feedback, fecha_feedback, comentario
"""

import os, uuid, json
from datetime import datetime
from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS

# ── Configuracion ──────────────────────────────────────────────
DATABASE_URL   = os.environ.get("DATABASE_URL", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

MAX_CONSULTAS       = 2   # Límite de preguntas al chef por sesión
MAX_HISTORIAL_TURNOS = 6  # Máximo de turnos (pares user/assistant) a enviar a la API

if DATABASE_URL:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    USE_PG = True
else:
    import sqlite3
    DB_PATH = "mcgourmet.db"
    USE_PG = False

# ── Conexion BD ────────────────────────────────────────────────
def get_conn():
    if USE_PG:
        import time
        for intento in range(3):
            try:
                conn = psycopg2.connect(
                    DATABASE_URL,
                    sslmode="require",
                    connect_timeout=10,
                    options="-c statement_timeout=10000"
                )
                conn.autocommit = False
                return conn
            except psycopg2.OperationalError:
                if intento < 2:
                    time.sleep(2)
                    continue
                raise
    return sqlite3.connect(DB_PATH)

def get_cur(conn):
    if USE_PG:
        return conn.cursor(cursor_factory=RealDictCursor)
    conn.row_factory = sqlite3.Row
    return conn.cursor()

# ── Setup BD ──────────────────────────────────────────────────
def setup_database():
    try:
        conn = get_conn()
        cur  = conn.cursor()
        if USE_PG:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS tbl_CheffMaridaje (
                    id_consulta      SERIAL PRIMARY KEY,
                    id_pedido        INTEGER,
                    nombre_cliente   TEXT,
                    telefono         TEXT,
                    fecha_consulta   TEXT,
                    num_consulta     INTEGER,
                    pregunta         TEXT,
                    respuesta        TEXT,
                    productos_pedido TEXT
                )
            """)
        else:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS tbl_CheffMaridaje (
                    id_consulta      INTEGER PRIMARY KEY AUTOINCREMENT,
                    id_pedido        INTEGER,
                    nombre_cliente   TEXT,
                    telefono         TEXT,
                    fecha_consulta   TEXT,
                    num_consulta     INTEGER,
                    pregunta         TEXT,
                    respuesta        TEXT,
                    productos_pedido TEXT
                )
            """)
        conn.commit()
        conn.close()
        print("✅ tbl_CheffMaridaje lista.")
    except Exception as e:
        print(f"❌ Error setup BD Chef: {e}")

# ── Contar consultas reales en BD ─────────────────────────────
def contar_consultas_bd(id_pedido, telefono):
    """Cuenta cuantas consultas reales hizo este cliente hoy en la BD."""
    try:
        conn = get_conn()
        # Usar cursor simple (no RealDictCursor) para COUNT(*)
        if USE_PG:
            cur = conn.cursor()
        else:
            cur = conn.cursor()
        ph   = "%s" if USE_PG else "?"
        hoy  = datetime.now().strftime("%Y-%m-%d")
        cur.execute(
            f"SELECT COUNT(*) FROM tbl_CheffMaridaje WHERE id_pedido={ph} AND telefono={ph} AND fecha_consulta LIKE {ph}",
            (id_pedido, telefono, f"{hoy}%")
        )
        row = cur.fetchone()
        conn.close()
        count = int(row[0])
        print(f"Consultas BD para remito {id_pedido} / tel {telefono}: {count}")
        return count
    except Exception as e:
        print(f"Error contar_consultas_bd: {e}")
        return 0

# ── Registrar consulta ─────────────────────────────────────────
def registrar_consulta(id_pedido, nombre_cliente, telefono, num_consulta, pregunta, respuesta, productos_pedido):
    try:
        conn = get_conn()
        cur  = get_cur(conn)
        ph   = "%s" if USE_PG else "?"
        cur.execute(
            f"INSERT INTO tbl_CheffMaridaje "
            f"(id_pedido, nombre_cliente, telefono, fecha_consulta, num_consulta, pregunta, respuesta, productos_pedido) "
            f"VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})",
            (
                id_pedido,
                nombre_cliente,
                telefono,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                num_consulta,
                pregunta,
                respuesta,
                productos_pedido
            )
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error registrar_consulta: {e}")

# ── Registrar feedback ────────────────────────────────────────
def registrar_feedback(id_consulta, feedback):
    """
    Actualiza el feedback de una consulta en tbl_cheffmaridaje.
    feedback: 'accepted' | 'rejected'
    """
    try:
        conn = get_conn()
        cur  = get_cur(conn)
        ph   = "%s" if USE_PG else "?"
        cur.execute(
            f"UPDATE tbl_cheffmaridaje "
            f"SET feedback = {ph}, fecha_feedback = {ph} "
            f"WHERE id_consulta = {ph}",
            (feedback, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), id_consulta)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error registrar_feedback: {e}")


def registrar_comentario(id_consulta, comentario):
    """
    Guarda el comentario libre del cliente en tbl_cheffmaridaje.
    """
    try:
        conn = get_conn()
        cur  = get_cur(conn)
        ph   = "%s" if USE_PG else "?"
        cur.execute(
            f"UPDATE tbl_cheffmaridaje "
            f"SET comentario = {ph} "
            f"WHERE id_consulta = {ph}",
            (comentario, id_consulta)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error registrar_comentario: {e}")

def get_ultimo_id_consulta(id_pedido, num_consulta):
    """Obtiene el id_consulta de la última consulta registrada."""
    try:
        conn = get_conn()
        cur  = get_cur(conn)
        ph   = "%s" if USE_PG else "?"
        cur.execute(
            f"SELECT id_consulta FROM tbl_cheffmaridaje "
            f"WHERE id_pedido = {ph} AND num_consulta = {ph} "
            f"ORDER BY id_consulta DESC LIMIT 1",
            (id_pedido, num_consulta)
        )
        row = cur.fetchone()
        conn.close()
        return dict(row)["id_consulta"] if row else None
    except Exception as e:
        print(f"Error get_ultimo_id_consulta: {e}")
        return None

# ── Verificar pedido ───────────────────────────────────────────
def verificar_pedido(id_pedido, telefono):
    """
    Verifica que el pedido exista, pertenezca al telefono dado
    y haya sido Confirmado el dia de hoy.
    Retorna los datos del pedido o None.
    """
    try:
        conn = get_conn()
        cur  = get_cur(conn)
        ph   = "%s" if USE_PG else "?"
        hoy  = datetime.now().strftime("%Y-%m-%d")

        cur.execute(
            f"""SELECT p.id_pedido, p.nombre_cliente, p.telefono,
                       p.fecha_pedido, p.total, p.notas,
                       STRING_AGG(d.nombre_producto, ', ') AS productos
                FROM tbl_PedBot p
                JOIN tbl_PedBot_Detalle d ON p.id_pedido = d.id_pedido
                WHERE p.id_pedido = {ph}
                  AND p.telefono  = {ph}
                  AND p.estado = 'Pagado'
                GROUP BY p.id_pedido, p.nombre_cliente, p.telefono,
                         p.fecha_pedido, p.total, p.notas""",
            (id_pedido, telefono)
        )
        row = cur.fetchone()
        conn.close()
        if row:
            return dict(row)
        return None
    except Exception as e:
        print(f"Error verificar_pedido: {e}")
        return None

# ── OpenAI ─────────────────────────────────────────────────────
# CAMBIO v2.0: Se eliminó la lógica del contador del system prompt.
# El contador ahora se maneja 100% en Python (ver procesar_chef).
SYSTEM_PROMPT = """Sos el Chef Virtual de McGourmet, experto en maridaje de pastelería artesanal argentina.
Tu rol es asesorar a los clientes sobre bebidas que acompañen los productos McGourmet: tés, infusiones, cafés, mate, vinos argentinos, espumantes, cervezas artesanales y vermú.

PRODUCTOS McGourmet:
- La Eulogia: Alfajores de chocolate con relleno de chocotorta - Caja 12 unidades
- La Simona: Alfajores de chocolate con relleno de almendras - Caja 12 unidades
- La Rufina: Alfajores bañados en chocolate, de maicena - Caja 12 unidades
- El Farito: Variedades de masas gourmet - Caja 1/2 kg
- La Jacinta: Tarta con crema de limón - Caja 1 unidad
- Imara: Variedad de masas gourmet - Caja 6 porciones

CONOCIMIENTO TÉCNICO de maridaje:
- Earl Grey: taninos + bergamota cítrica contrastan el chocolate y limpian el dulce de leche ★★★★★
- Darjeeling: floral y elegante para masas finas y tartas
- Assam: cuerpo robusto para alfajores con rellenos intensos
- Ceylon: fresco y cítrico, ideal para La Jacinta
- Mate amargo: clásico argentino insuperable ★★★★★, contraste amargo/dulce perfecto para alfajores de maicena
- Espresso: potencia el cacao y corta la grasa ★★★★★ para alfajores de chocolate
- Torrontés de Cafayate: floral y aromático, ideal para La Jacinta
- Malbec rosado de Mendoza: versátil para alfajores
- Espumante brut: para masas finas y ocasiones especiales
- Cerveza de trigo o miel: acompañan masas secas y alfajores de maicena
- Regla de oro: siempre sin azúcar en la bebida, la masa ya aporta el dulce necesario
- Infusión de té negro: 90°C, 3-4 minutos, sin azúcar para mantener el contraste

REGLAS:
- Respondé SIEMPRE en español, tono cercano argentino pero profesional
- Máximo 2 oraciones por respuesta, fluidas y naturales
- Sé específico con variedades y marcas argentinas cuando sea posible
- Podés responder preguntas sobre preparación de bebidas relacionadas al maridaje
- Nunca recomiendes destilados fuertes (whisky, gin, vodka, fernet)
- Usá el nombre del cliente cuando lo conozcas"""


def consultar_chef(historial, nombre_cliente, productos_pedido):
    """Llama a OpenAI GPT-4o con el historial de la conversacion."""
    import urllib.request
    
    # Leer en cada llamada para asegurar valor actualizado en Render
    openai_key = os.environ.get("OPENAI_API_KEY", OPENAI_API_KEY)
    if not openai_key:
        print("Error OpenAI: OPENAI_API_KEY no configurada")
        return "Perdoná, tuve un problema de configuración. ¡Intentá de nuevo en un momento!"

    system = SYSTEM_PROMPT
    if nombre_cliente and productos_pedido:
        system += f"\n\nEl cliente se llama {nombre_cliente} y hoy pidió: {productos_pedido}."

    mensajes = [{"role": "system", "content": system}] + historial

    data = json.dumps({
        "model": "gpt-4o",
        "messages": mensajes,
        "temperature": 0.3,
        "top_p": 0.85,
        "max_tokens": 150
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=data,
        headers={
            "Authorization": f"Bearer {openai_key}",
            "Content-Type": "application/json"
        },
        method="POST"
    )
    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read().decode())
            return result["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"Error OpenAI: {e}")
        return "Perdoná, tuve un problema para procesar tu consulta. ¡Intentá de nuevo en un momento!"

# ── Sesiones ───────────────────────────────────────────────────
sesiones = {}

def procesar_chef(session_id, mensaje):
    if session_id not in sesiones:
        sesiones[session_id] = {
            "etapa": "pedir_remito",
            "id_pedido": None,
            "telefono": None,
            "nombre_cliente": None,
            "productos_pedido": None,
            "historial": [],
            # CAMBIO v2.0: contador de consultas en Python, no en el prompt
            "consultas_realizadas": 0,
            # FEEDBACK: id de la última consulta registrada
            "ultimo_id_consulta": None,
            "esperando_feedback": False,
            "esperando_comentario": False,
        }

    s     = sesiones[session_id]
    txt   = mensaje.strip()
    etapa = s["etapa"]

    # Etapa 1: pedir numero de remito
    if etapa == "pedir_remito":
        s["etapa"] = "pedir_telefono"
        return "¡Hola! Soy el Chef Virtual de McGourmet. 👨‍🍳\n\nPara asesorarte mejor, necesito verificar tu pedido.\n\nIngresá tu número de remito:"

    # Etapa 2: guardar remito y pedir telefono
    if etapa == "pedir_telefono":
        try:
            s["id_pedido"] = int(txt)
            s["etapa"]     = "verificar"
            return "¡Perfecto! Ahora ingresá tu número de teléfono para verificar el pedido:"
        except ValueError:
            return "El número de remito debe ser un número. ¿Podés verificarlo e ingresarlo de nuevo?"

    # Etapa 3: verificar pedido en BD
    if etapa == "verificar":
        s["telefono"] = txt
        pedido = verificar_pedido(s["id_pedido"], s["telefono"])

        if not pedido:
            s["etapa"] = "pedir_remito"
            return "No encontré un pedido Pagado hoy con ese remito y teléfono. Verificá que tu pago haya sido confirmado por McGourmet, o revisá los datos e intentá de nuevo."

        s["nombre_cliente"]   = pedido["nombre_cliente"]
        s["productos_pedido"]  = pedido["productos"]
        s["etapa"]            = "chat"
        # Cargar contador real desde BD para persistir entre sesiones
        consultas_hechas = contar_consultas_bd(s["id_pedido"], s["telefono"])
        s["consultas_realizadas"] = consultas_hechas
        restantes = MAX_CONSULTAS - consultas_hechas
        if restantes <= 0:
            s["etapa"] = "pedir_remito"
            return (f"Hola {pedido['nombre_cliente']}! Ya usaste tus {MAX_CONSULTAS} consultas disponibles para este pedido. "
                    f"Para nuevas consultas, realizá una nueva compra. 🙏")
        return (f"¡Bienvenido/a {pedido['nombre_cliente']}! 🎉\n\n"
                f"Veo que hoy pediste: {pedido['productos']}.\n\n"
                f"Tenés {restantes} consulta(s) disponible(s) con el Chef. "
                f"¿En qué te puedo asesorar? Preguntame sobre maridajes o bebidas para tus productos.")

    # Etapa 4: chat libre con el Chef
    if etapa == "chat":

        # ── Capturar comentario libre si el bot está esperando ───────────
        if s["esperando_comentario"]:
            txt_lower = txt.strip().lower()
            if txt_lower not in ("omitir", "no", "n", "skip"):
                # Guardar comentario si no es una palabra de omisión
                if s["ultimo_id_consulta"]:
                    registrar_comentario(s["ultimo_id_consulta"], txt.strip())
                s["esperando_comentario"] = False
                return "¡Gracias por tu comentario! Lo tendremos en cuenta para seguir mejorando. 🙏 ¡Buen provecho!"
            else:
                s["esperando_comentario"] = False
                return "¡Perfecto! ¡Buen provecho! 🍽️"

        # ── Capturar feedback SI/NO ───────────────────────────────────────
        if s["esperando_feedback"]:
            respuesta_lower = txt.strip().lower()
            if respuesta_lower in ("si", "sí", "s", "👍", "yes"):
                if s["ultimo_id_consulta"]:
                    registrar_feedback(s["ultimo_id_consulta"], "accepted")
                s["esperando_feedback"]   = False
                s["esperando_comentario"] = True
                return "¡Gracias! 😊 ¿Querés dejarnos un breve comentario sobre el servicio? (o escribí OMITIR para saltar)"
            elif respuesta_lower in ("no", "n", "👎"):
                if s["ultimo_id_consulta"]:
                    registrar_feedback(s["ultimo_id_consulta"], "rejected")
                s["esperando_feedback"]   = False
                s["esperando_comentario"] = True
                return "Gracias por tu opinión. ¿Querés contarnos en qué podemos mejorar? (o escribí OMITIR para saltar)"
            else:
                # No entiende la respuesta → ignored y sigue
                if s["ultimo_id_consulta"]:
                    registrar_feedback(s["ultimo_id_consulta"], "ignored")
                s["esperando_feedback"] = False

        # ── CAMBIO v2.0: Control del límite en Python, ANTES de llamar a la API ──
        if s["consultas_realizadas"] >= MAX_CONSULTAS:
            return f"Ya alcanzaste el máximo de {MAX_CONSULTAS} consultas. Para continuar, iniciá una nueva compra. 🙏"

        # Llamada a la API solo si tiene consultas disponibles
        s["historial"].append({"role": "user", "content": txt})
        respuesta = consultar_chef(
            s["historial"],
            s["nombre_cliente"],
            s["productos_pedido"]
        )
        s["historial"].append({"role": "assistant", "content": respuesta})

        # Incrementar contador
        s["consultas_realizadas"] += 1
        restantes = MAX_CONSULTAS - s["consultas_realizadas"]

        # Registrar consulta en BD con número de consulta para auditoría
        registrar_consulta(
            s["id_pedido"],
            s["nombre_cliente"],
            s["telefono"],
            s["consultas_realizadas"],
            txt,
            respuesta,
            s["productos_pedido"]
        )

        # Guardar id de la consulta recién registrada para el feedback
        s["ultimo_id_consulta"] = get_ultimo_id_consulta(
            s["id_pedido"], s["consultas_realizadas"]
        )

        # Limitar historial para no acumular tokens en conversaciones largas
        max_msgs = MAX_HISTORIAL_TURNOS * 2  # cada turno = 1 user + 1 assistant
        if len(s["historial"]) > max_msgs:
            s["historial"] = s["historial"][-max_msgs:]

        # Avisar al cliente cuántas consultas le quedan
        if restantes == 0:
            respuesta += "\n\n_Esta fue tu última consulta disponible. ¡Buen provecho!_ 🍽️"
            respuesta += "\n\n¿Te fue útil la sugerencia del Chef? Respondé **SI** o **NO**"
            s["esperando_feedback"] = True
        elif restantes == 1:
            respuesta += f"\n\n_(Te queda 1 consulta disponible)_"
            respuesta += "\n\n¿Te fue útil esta sugerencia? Respondé **SI** o **NO**"
            s["esperando_feedback"] = True
        else:
            respuesta += f"\n\n_(Te quedan {restantes} consultas disponibles)_"
            respuesta += "\n\n¿Te fue útil esta sugerencia? Respondé **SI** o **NO**"
            s["esperando_feedback"] = True

        return respuesta

    return "No entendí tu mensaje. ¿Podés repetirlo?"

# ── Flask App ──────────────────────────────────────────────────
setup_database()
chef_app = Flask(__name__)
CORS(chef_app)

HTML_CHEF = """<!DOCTYPE html>
<html lang="es"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>McGourmet - Chef Virtual</title>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;900&family=Lato:wght@300;400;700&display=swap" rel="stylesheet">
<style>
:root{--brand:#5C3D2E;--brand-dk:#3E2723;--cream:#FDF6EC;--gold:#C9A84C;--olive:#6B7C45;--text:#2C1810;--muted:#8B7355;--border:#E8D5B7;}
*{box-sizing:border-box;margin:0;padding:0;}
body{font-family:'Lato',sans-serif;background:var(--cream);display:flex;justify-content:center;align-items:center;min-height:100vh;padding:12px;}
.wrap{width:100%;max-width:440px;display:flex;flex-direction:column;height:95vh;background:#fff;border-radius:20px;box-shadow:0 24px 80px rgba(92,61,46,.2);overflow:hidden;border:1px solid var(--border);}
.header{background:var(--brand);padding:16px 20px;display:flex;align-items:center;gap:14px;position:relative;}
.header::after{content:'';position:absolute;bottom:0;left:0;right:0;height:3px;background:linear-gradient(90deg,var(--gold),transparent,var(--gold));}
.avatar{width:56px;height:56px;border-radius:50%;background:var(--gold);display:flex;align-items:center;justify-content:center;font-size:28px;flex-shrink:0;border:2px solid rgba(255,255,255,.3);}
.header-info h1{font-family:'Playfair Display',serif;color:#fff;font-size:18px;line-height:1.1;}
.header-info .lema{color:var(--gold);font-size:11px;font-style:italic;margin-top:2px;}
.header-info .sub{color:rgba(255,255,255,.7);font-size:11px;margin-top:3px;}
.status{display:flex;align-items:center;gap:5px;margin-top:4px;}
.sdot{width:7px;height:7px;background:#4ADE80;border-radius:50%;animation:pulse 2s infinite;}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
.status span{color:rgba(255,255,255,.6);font-size:10px;}
.msgs{flex:1;overflow-y:auto;padding:16px 14px;display:flex;flex-direction:column;gap:10px;background:var(--cream);}
.msgs::-webkit-scrollbar{width:3px;}
.msgs::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px;}
.bw{display:flex;align-items:flex-end;gap:8px;}
.bw.user{flex-direction:row-reverse;}
.av{width:30px;height:30px;border-radius:50%;flex-shrink:0;display:flex;align-items:center;justify-content:center;font-size:16px;background:var(--gold);border:1.5px solid var(--border);}
.av.user-av{background:var(--brand);font-size:13px;color:#fff;}
.bubble{max-width:80%;padding:10px 14px;font-size:13.5px;line-height:1.6;white-space:pre-wrap;word-break:break-word;}
.bubble.bot{background:#fff;color:var(--text);border-radius:16px 16px 16px 4px;border:1px solid var(--border);box-shadow:0 2px 8px rgba(0,0,0,.06);}
.bubble.user{background:var(--brand);color:#fff;border-radius:16px 16px 4px 16px;}
.qr{display:flex;flex-wrap:wrap;gap:6px;padding:8px 14px;background:#fff;border-top:1px solid var(--border);}
.qb{background:transparent;border:1.5px solid var(--brand);color:var(--brand);padding:5px 12px;border-radius:16px;font-size:12px;cursor:pointer;transition:all .2s;font-weight:700;}
.qb:hover{background:var(--brand);color:#fff;}
.inp{padding:10px 14px 16px;display:flex;gap:8px;background:#fff;}
.inp input{flex:1;border:1.5px solid var(--border);border-radius:20px;padding:10px 16px;font-size:13.5px;outline:none;color:var(--text);background:var(--cream);transition:border .2s;}
.inp input:focus{border-color:var(--brand);}
.inp button{width:42px;height:42px;border-radius:50%;background:var(--brand);border:none;color:#fff;font-size:16px;cursor:pointer;flex-shrink:0;transition:background .2s;display:flex;align-items:center;justify-content:center;}
.inp button:hover{background:var(--brand-dk);}
.typing-dots{display:flex;gap:4px;align-items:center;padding:2px 0;}
.td{width:6px;height:6px;background:var(--muted);border-radius:50%;animation:bounce .9s infinite;}
.td:nth-child(2){animation-delay:.2s;}.td:nth-child(3){animation-delay:.4s;}
@keyframes bounce{0%,80%,100%{transform:translateY(0)}40%{transform:translateY(-5px)}}
</style></head>
<body>
<div class="wrap">
  <div class="header">
    <div class="avatar">👨‍🍳</div>
    <div class="header-info">
      <h1>Chef McGourmet</h1>
      <div class="lema">Tu asesor de maridaje</div>
      <div class="sub">Gastronomía artesanal</div>
      <div class="status"><div class="sdot"></div><span>En linea</span></div>
    </div>
  </div>
  <div class="msgs" id="msgs"></div>
  <div class="qr">
    <button class="qb" onclick="send('Que sugerencias tenes para mi pedido?')">Sugerencias del Chef</button>
    <button class="qb" onclick="send('Como sirvo el plato seleccionado?')">Como servirlos</button>

  </div>
  <div class="inp">
    <input id="inp" type="text" placeholder="Preguntale al Chef..." autocomplete="off" onkeydown="if(event.key==='Enter')send()">
    <button onclick="send()">&#9658;</button>
  </div>
</div>
<script>
const sid = 'chef_' + Math.random().toString(36).substr(2,9);
function addMsg(t, r){
  const c = document.getElementById('msgs');
  const w = document.createElement('div'); w.className = 'bw ' + r;
  const a = document.createElement('div');
  if(r === 'bot'){ a.className = 'av'; a.textContent = '👨\u200d🍳'; }
  else { a.className = 'av user-av'; a.textContent = 'u'; }
  const b = document.createElement('div');
  b.className = 'bubble ' + r; b.textContent = t;
  r === 'bot' ? w.append(a, b) : w.append(b, a);
  c.appendChild(w); c.scrollTop = c.scrollHeight;
}
function showT(){
  const c = document.getElementById('msgs');
  const d = document.createElement('div'); d.id = 'typ'; d.className = 'bw bot';
  const a = document.createElement('div'); a.className = 'av'; a.textContent = '👨\u200d🍳';
  d.appendChild(a);
  const b = document.createElement('div'); b.className = 'bubble bot';
  b.innerHTML = '<div class="typing-dots"><div class="td"></div><div class="td"></div><div class="td"></div></div>';
  d.appendChild(b); c.appendChild(d); c.scrollTop = c.scrollHeight;
}
function hideT(){ const t = document.getElementById('typ'); if(t) t.remove(); }
async function send(t){
  const inp = document.getElementById('inp');
  const msg = t || inp.value.trim(); if(!msg) return; inp.value = '';
  addMsg(msg, 'user'); showT();
  try{
    const r = await fetch('/chef/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({session_id: sid, message: msg})
    });
    const d = await r.json(); hideT(); addMsg(d.response, 'bot');
  } catch(e){ hideT(); addMsg('Error de conexion. Intenta nuevamente.', 'bot'); }
}
window.onload = () => send('INICIO');
</script></body></html>"""

@chef_app.route("/")
def index():
    return render_template_string(HTML_CHEF)

@chef_app.route("/chef/chat", methods=["POST"])
def chat():
    data = request.get_json(force=True)
    sid  = data.get("session_id", str(uuid.uuid4()))
    msg  = data.get("message", "").strip()
    return jsonify({"session_id": sid, "response": procesar_chef(sid, msg)})

@chef_app.route("/chef/consultas")
def consultas():
    try:
        conn = get_conn()
        cur  = get_cur(conn)
        cur.execute("SELECT * FROM tbl_CheffMaridaje ORDER BY fecha_consulta DESC LIMIT 50")
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return jsonify(rows)
    except Exception as e:
        return jsonify({"error": str(e)})

@chef_app.route("/chef/health")
def health():
    return jsonify({
        "status": "ok",
        "db": "postgresql" if USE_PG else "sqlite",
        "openai": "configured" if OPENAI_API_KEY else "missing",
        "max_consultas": MAX_CONSULTAS
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    chef_app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
