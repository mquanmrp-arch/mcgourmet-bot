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
SYSTEM_PROMPT = """Sos el Chef Virtual de McGourmet, un experto en gastronomía argentina y maridaje en pastas y reposteria del catalogo Mcgourmet.
Tu rol es asesorar a los clientes sobre maridajes, guarniciones y sugerencias culinarias
para los productos artesanales de McGourmet. Destaca los condimentos del norte argentino, en especial de la localidad de  Cachi (Salta) para las empanadas salteñas.
Asi también, los condimentos ahumados patagónicos, los cuales le dan el toque McGourmet a las pastas. Para el maridaje, destaca los vinos torrontes y tannat de Cafayate, malbec, cabernet franc, merlot de Mendoza,
sirah de San Juan, pinot noir de Rio Negro y Neuquen, petit verdot de San Juan.


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
- Máximo 2 respuestas por remito
- Máximo 1 oración por respuesta
- Sé específico y útil, no genérico
- Si la pregunta no es sobre gastronomía de Mcgourmet o maridaje, redirigí amablemente al tema
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
    <div class="avatar"><img src="data:image/jpeg;base64,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" style="width:100%;height:100%;object-fit:cover;border-radius:50%;"></div>
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
