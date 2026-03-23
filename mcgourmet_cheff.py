"""
McGourmet Chef Bot v1.0
Asistente de maridaje para clientes con pedido confirmado.
Flask + OpenAI GPT-4o + PostgreSQL
"""

import os, uuid, json
from datetime import datetime
from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS

# ── Configuracion ──────────────────────────────────────────────
DATABASE_URL   = os.environ.get("DATABASE_URL", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

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

# ── Registrar consulta ─────────────────────────────────────────
def registrar_consulta(id_pedido, nombre_cliente, telefono, pregunta, respuesta, productos_pedido):
    try:
        conn = get_conn()
        cur  = get_cur(conn)
        ph   = "%s" if USE_PG else "?"
        cur.execute(
            f"INSERT INTO tbl_CheffMaridaje (id_pedido, nombre_cliente, telefono, fecha_consulta, pregunta, respuesta, productos_pedido) "
            f"VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph})",
            (
                id_pedido,
                nombre_cliente,
                telefono,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                pregunta,
                respuesta,
                productos_pedido
            )
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error registrar_consulta: {e}")

# ── Verificar pedido ───────────────────────────────────────────
def verificar_pedido(id_pedido, telefono):
    """
    Verifica que el pedido exista, pertenezca al telefono dado
    y haya sido confirmado el dia de hoy.
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
                  AND p.fecha_pedido LIKE {ph}
                  AND p.estado = 'CONFIRMADO'
                GROUP BY p.id_pedido, p.nombre_cliente, p.telefono,
                         p.fecha_pedido, p.total, p.notas""",
            (id_pedido, telefono, f"{hoy}%")
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
SYSTEM_PROMPT = """Sos el Chef Virtual de McGourmet, un experto en gastronomía argentina y maridaje.
Tu rol es asesorar a los clientes sobre maridajes, guarniciones y sugerencias culinarias
para los productos artesanales de McGourmet.

Productos del catálogo:
- La Eulogia: Sorrentinos de espinaca con queso parmesano
- La Simona: Sorrentinos de Calabaza con muzzarella y jengibre
- La Rufina: Sorrentinos 4 Quesos (muzzarella, port salud, parmesano, ricota)
- La Chacha: Sorrentinos de Osobuco con condimentos patagónicos
- El Farito: Empanadas salteñas de carne, papas, huevos, cebollitas de verdeo
- Medialunas: Medialunas de manteca
- Imara: Torta Húngara
- Chimpay: Tarta de manzana
- Chimpaycito: Masas secas (alfajor de chocolate, alfajor de maicena)
- La Jacinta: Pasta frola

Reglas estrictas:
- Respondé SIEMPRE en español, con tono cercano argentino pero profesional
- Máximo 2 oraciones por respuesta
- Sé específico y útil, no genérico
- Si la pregunta no es sobre gastronomía o maridaje, redirigí amablemente al tema
- Usá el nombre del cliente cuando lo conozcas"""

def consultar_chef(historial, nombre_cliente, productos_pedido):
    """Llama a OpenAI GPT-4o con el historial de la conversacion."""
    import urllib.request

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
            "Authorization": f"Bearer {OPENAI_API_KEY}",
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
            "historial": []
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
            return "No encontré un pedido confirmado hoy con ese remito y teléfono. ¿Revisás los datos e intentás de nuevo?"

        s["nombre_cliente"]  = pedido["nombre_cliente"]
        s["productos_pedido"] = pedido["productos"]
        s["etapa"]           = "chat"
        return (f"¡Bienvenido/a {pedido['nombre_cliente']}! 🎉\n\n"
                f"Veo que hoy pediste: {pedido['productos']}.\n\n"
                f"¿En qué te puedo asesorar? Preguntame sobre maridajes, salsas, guarniciones o cómo servir tus platos.")

    # Etapa 4: chat libre con el Chef
    if etapa == "chat":
        s["historial"].append({"role": "user", "content": txt})
        respuesta = consultar_chef(
            s["historial"],
            s["nombre_cliente"],
            s["productos_pedido"]
        )
        s["historial"].append({"role": "assistant", "content": respuesta})
        # Registrar consulta en BD para seguimiento
        registrar_consulta(
            s["id_pedido"],
            s["nombre_cliente"],
            s["telefono"],
            txt,
            respuesta,
            s["productos_pedido"]
        )
        # Limitar historial a 10 turnos para no explotar tokens
        if len(s["historial"]) > 20:
            s["historial"] = s["historial"][-20:]
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
    <button class="qb" onclick="send('Que vino va bien con La Rufina?')">Maridaje La Rufina</button>
    <button class="qb" onclick="send('Como sirvo los sorrentinos?')">Como servirlos</button>
    <button class="qb" onclick="send('Que salsa sugeries?')">Salsas</button>
  </div>
  <div class="inp">
    <input id="inp" type="text" placeholder="Preguntale al Chef..." autocomplete="off" onkeydown="if(event.key==='Enter')send()">
    <button onclick="send()">></button>
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
        "openai": "configured" if OPENAI_API_KEY else "missing"
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    chef_app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
