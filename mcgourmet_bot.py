"""
McGourmet Bot - Version 2.0 LIMPIA
LangGraph + Flask + SQLite
"""

import sqlite3
import uuid
import threading
import os
from datetime import datetime
from typing import TypedDict, Annotated, Optional
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langchain_core.messages import HumanMessage, AIMessage
from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS

# ─────────────────────────────────────────────
#  CONFIGURACION
# ─────────────────────────────────────────────
DB_PATH = "mcgourmet.db"

# ─────────────────────────────────────────────
#  BASE DE DATOS
# ─────────────────────────────────────────────
def setup_database():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS tbl_Catalogo (
            id_producto     INTEGER PRIMARY KEY AUTOINCREMENT,
            categoria       TEXT    NOT NULL,
            nombre_producto TEXT    NOT NULL,
            descripcion     TEXT,
            precio          REAL    NOT NULL,
            disponible      INTEGER DEFAULT 10,
            imagen_url      TEXT    DEFAULT ''
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS tbl_PedBot (
            id_pedido       INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id      TEXT    NOT NULL,
            nombre_cliente  TEXT,
            telefono        TEXT,
            fecha_pedido    TEXT    NOT NULL,
            estado          TEXT    DEFAULT 'CONFIRMADO',
            total           REAL    DEFAULT 0,
            notas           TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS tbl_PedBot_Detalle (
            id_detalle      INTEGER PRIMARY KEY AUTOINCREMENT,
            id_pedido       INTEGER NOT NULL,
            nombre_producto TEXT    NOT NULL,
            cantidad        INTEGER NOT NULL DEFAULT 1,
            precio_unit     REAL    NOT NULL,
            subtotal        REAL    NOT NULL
        )
    """)

    cur.execute("SELECT COUNT(*) FROM tbl_Catalogo")
    if cur.fetchone()[0] == 0:
        productos = [
            ("Pastas",     "La Eulogia",   "Sorrentinos de espinaca con queso parmesano - Caja 12 unidades.",                                           15000.00, 10, ""),
            ("Pastas",     "La Simona",    "Sorrentinos de Calabaza con muzzarella y jengibre - Caja 12 unidades.",                                     15000.00, 10, ""),
            ("Pastas",     "La Rufina",    "Sorrentinos 4 Quesos (muzzarella, port salud, parmesano, ricota) - Caja 12 unidades.",                      15000.00, 10, ""),
            ("Pastas",     "La Chacha",    "Sorrentinos de Osobuco con condimentos patagonicos - Caja 12 unidades.",                                    15000.00, 10, ""),
            ("Empanadas",  "El Farito",    "Empanadas saltenas de carne, papas, huevos, cebollitas de verdeo - Caja 12 unidades.",                      18000.00, 10, ""),
            ("Reposteria", "Medialunas",   "Medialunas de manteca - Caja de 6 unidades.",                                                              14000.00, 10, ""),
            ("Reposteria", "Imara",        "Torta Hungara - Caja 1 unidad (rinde 6 porciones).",                                                        9000.00, 10, ""),
            ("Reposteria", "Chimpay",      "Tarta de manzana - Caja 1 unidad (rinde 6 personas).",                                                      9000.00, 10, ""),
            ("Reposteria", "Chimpaycito",  "Masas secas (alfajor de chocolate, alfajor de maicena) - Caja 4 personas.",                                 9000.00, 10, ""),
            ("Reposteria", "La Jacinta",   "Pasta frola - Caja 1 unidad (rinde 6 personas).",                                                           9000.00, 10, ""),
        ]
        cur.executemany("""
            INSERT INTO tbl_Catalogo (categoria, nombre_producto, descripcion, precio, disponible, imagen_url)
            VALUES (?, ?, ?, ?, ?, ?)
        """, productos)

    conn.commit()
    conn.close()
    print("BD lista con productos McGourmet.")


def get_catalogo():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("""
        SELECT id_producto, categoria, nombre_producto, descripcion, precio
        FROM   tbl_Catalogo
        WHERE  disponible > 0
        ORDER  BY categoria, id_producto
    """)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def crear_pedido(session_id, nombre, telefono, notas):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO tbl_PedBot (session_id, nombre_cliente, telefono, fecha_pedido, estado, notas)
        VALUES (?, ?, ?, ?, 'CONFIRMADO', ?)
    """, (session_id, nombre, telefono, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), notas))
    id_pedido = cur.lastrowid
    conn.commit()
    conn.close()
    return id_pedido


def agregar_detalle(id_pedido, id_producto, cantidad):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT nombre_producto, precio FROM tbl_Catalogo WHERE id_producto=?", (id_producto,))
    prod = cur.fetchone()
    if prod:
        subtotal = prod["precio"] * cantidad
        cur.execute("""
            INSERT INTO tbl_PedBot_Detalle (id_pedido, nombre_producto, cantidad, precio_unit, subtotal)
            VALUES (?, ?, ?, ?, ?)
        """, (id_pedido, prod["nombre_producto"], cantidad, prod["precio"], subtotal))
        cur.execute("UPDATE tbl_PedBot SET total = total + ? WHERE id_pedido = ?", (subtotal, id_pedido))
    conn.commit()
    conn.close()


def get_pedido_completo(id_pedido):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM tbl_PedBot WHERE id_pedido=?", (id_pedido,))
    ped = dict(cur.fetchone())
    cur.execute("SELECT * FROM tbl_PedBot_Detalle WHERE id_pedido=?", (id_pedido,))
    ped["items"] = [dict(r) for r in cur.fetchall()]
    conn.close()
    return ped


# ─────────────────────────────────────────────
#  ESTADO LANGGRAPH
# ─────────────────────────────────────────────
class McGourmetState(TypedDict):
    session_id:     str
    etapa:          str
    messages:       Annotated[list, add_messages]
    carrito:        list
    id_pedido:      Optional[int]
    nombre_cliente: str
    telefono:       str
    notas:          str
    total:          float
    user_input:     str


# ─────────────────────────────────────────────
#  NODOS
# ─────────────────────────────────────────────
def nodo_bienvenida(state):
    msg = (
        "Bienvenido a McGourmet!\n\n"
        "Soy tu asistente de pedidos.\n\n"
        "Escribi MENU para ver nuestra carta\n"
        "Escribi AYUDA para ver todos los comandos"
    )
    return {**state, "etapa": "carrito", "carrito": [], "total": 0.0,
            "messages": [AIMessage(content=msg)]}


def nodo_mostrar_menu(state):
    catalogo = get_catalogo()

    if not catalogo:
        return {**state, "messages": [AIMessage(content="El menu no esta disponible en este momento.")]}

    categorias = {}
    for p in catalogo:
        cat = p["categoria"]
        categorias.setdefault(cat, []).append(p)

    lineas = ["MENU McGourmet", "-" * 35]
    for cat, prods in categorias.items():
        lineas.append("")
        lineas.append(cat)
        for p in prods:
            lineas.append(f"  [{p['id_producto']}] {p['nombre_producto']}")
            lineas.append(f"      {p['descripcion']}")
            lineas.append(f"      $ {p['precio']:,.0f}")

    lineas += [
        "",
        "-" * 35,
        "Para agregar escribi:",
        "  AGREGAR [numero] [cantidad]",
        "  Ej: AGREGAR 1 2",
        "",
        "VER CARRITO - CONFIRMAR - CANCELAR"
    ]

    return {**state, "etapa": "carrito", "messages": [AIMessage(content="\n".join(lineas))]}


def nodo_procesar(state):
    txt     = state.get("user_input", "").strip().upper()
    carrito = list(state.get("carrito", []))
    etapa   = state.get("etapa", "carrito")

    # ── Recoleccion de datos ──────────────────────────────────────
    if etapa == "datos_nombre":
        nombre = state["user_input"].strip()
        return {**state, "nombre_cliente": nombre, "etapa": "datos_telefono",
                "messages": [AIMessage(content=f"Perfecto {nombre}!\n\nIngresa tu numero de telefono:")]}

    if etapa == "datos_telefono":
        telefono = state["user_input"].strip()
        return {**state, "telefono": telefono, "etapa": "datos_notas",
                "messages": [AIMessage(content="Alguna aclaracion para tu pedido?\n(alergias, sin TACC, etc.)\n\nSi no tenes, escribi NO")]}

    if etapa == "datos_notas":
        notas    = "" if txt == "NO" else state["user_input"].strip()
        nombre   = state.get("nombre_cliente", "")
        telefono = state.get("telefono", "")

        # Guardar pedido
        id_pedido = crear_pedido(state["session_id"], nombre, telefono, notas)
        for item in carrito:
            agregar_detalle(id_pedido, item["id_producto"], item["cantidad"])

        ped   = get_pedido_completo(id_pedido)
        total = ped["total"]

        lineas = [
            f"PEDIDO #{id_pedido} CONFIRMADO!",
            "",
            f"Cliente  : {nombre}",
            f"Telefono : {telefono}",
            f"Fecha    : {ped['fecha_pedido']}",
            "",
            "Detalle:",
        ]
        for it in ped["items"]:
            lineas.append(f"  {it['cantidad']}x {it['nombre_producto']}")
            lineas.append(f"     $ {it['subtotal']:,.0f}")
        if notas:
            lineas.append(f"\nNotas: {notas}")
        lineas += ["", f"TOTAL: $ {total:,.0f}", "",
                   "Tu pedido fue registrado!",
                   "Te contactamos pronto.",
                   "",
                   "Escribi MENU para hacer otro pedido."]

        return {**state, "notas": notas, "id_pedido": id_pedido,
                "etapa": "finalizado", "carrito": [], "total": 0.0,
                "messages": [AIMessage(content="\n".join(lineas))]}

    # ── Comandos generales ────────────────────────────────────────
    if txt in ("MENU", "CARTA"):
        return nodo_mostrar_menu(state)

    if txt.startswith("AGREGAR"):
        partes = txt.split()
        try:
            id_prod  = int(partes[1])
            cantidad = int(partes[2]) if len(partes) > 2 else 1
        except (IndexError, ValueError):
            return {**state, "messages": [AIMessage(content="Formato: AGREGAR [numero] [cantidad]\nEj: AGREGAR 1 2")]}

        catalogo    = get_catalogo()
        catalogo_idx = {p["id_producto"]: p for p in catalogo}
        prod = catalogo_idx.get(id_prod)
        if not prod:
            return {**state, "messages": [AIMessage(content=f"No encontre el producto #{id_prod}. Revisa el menu.")]}

        existe = next((i for i, x in enumerate(carrito) if x["id_producto"] == id_prod), None)
        if existe is not None:
            carrito[existe]["cantidad"] += cantidad
            carrito[existe]["subtotal"]  = carrito[existe]["cantidad"] * prod["precio"]
        else:
            carrito.append({"id_producto": id_prod, "nombre": prod["nombre_producto"],
                            "precio": prod["precio"], "cantidad": cantidad,
                            "subtotal": prod["precio"] * cantidad})

        total = sum(x["subtotal"] for x in carrito)
        resp  = (f"Agregado: {cantidad}x {prod['nombre_producto']}\n"
                 f"Subtotal: $ {prod['precio'] * cantidad:,.0f}\n\n"
                 f"Carrito: {len(carrito)} item(s) - Total: $ {total:,.0f}\n\n"
                 "Seguí agregando o escribi CONFIRMAR")
        return {**state, "carrito": carrito, "total": total, "messages": [AIMessage(content=resp)]}

    if "VER CARRITO" in txt or txt == "CARRITO":
        if not carrito:
            return {**state, "messages": [AIMessage(content="Tu carrito esta vacio.\nEscribi MENU para ver las opciones.")]}
        total  = sum(x["subtotal"] for x in carrito)
        lineas = ["Tu Carrito McGourmet", "-" * 30]
        for item in carrito:
            lineas.append(f"  {item['cantidad']}x {item['nombre']}")
            lineas.append(f"     $ {item['subtotal']:,.0f}")
        lineas += ["-" * 30, f"TOTAL: $ {total:,.0f}", "",
                   "CONFIRMAR - MENU - CANCELAR"]
        return {**state, "messages": [AIMessage(content="\n".join(lineas))]}

    if "CONFIRMAR" in txt:
        if not carrito:
            return {**state, "messages": [AIMessage(content="Tu carrito esta vacio. Agrega productos primero.")]}
        return {**state, "etapa": "datos_nombre",
                "messages": [AIMessage(content="Para completar tu pedido necesito algunos datos.\n\nEscribi tu nombre completo:")]}

    if "CANCELAR" in txt:
        return {**state, "carrito": [], "total": 0.0, "etapa": "carrito",
                "messages": [AIMessage(content="Pedido cancelado. Carrito vaciado.\n\nEscribi MENU cuando quieras. ")]}

    if "AYUDA" in txt:
        resp = ("Comandos disponibles:\n\n"
                "MENU            - Ver la carta\n"
                "AGREGAR N CANT  - Agregar producto\n"
                "VER CARRITO     - Ver tu seleccion\n"
                "CONFIRMAR       - Finalizar pedido\n"
                "CANCELAR        - Vaciar carrito\n"
                "AYUDA           - Este mensaje")
        return {**state, "messages": [AIMessage(content=resp)]}

    if etapa == "finalizado" and txt == "MENU":
        return nodo_mostrar_menu({**state, "carrito": [], "total": 0.0})

    return {**state, "messages": [AIMessage(content="No entendi ese comando.\nEscribi AYUDA para ver las opciones.")]}


# ─────────────────────────────────────────────
#  SESIONES Y PROCESAMIENTO
# ─────────────────────────────────────────────
sesiones = {}

def procesar_mensaje(session_id, mensaje):
    if session_id not in sesiones:
        sesiones[session_id] = {
            "session_id": session_id, "etapa": "bienvenida",
            "messages": [], "carrito": [], "id_pedido": None,
            "nombre_cliente": "", "telefono": "", "notas": "",
            "total": 0.0, "user_input": "",
        }

    estado              = sesiones[session_id]
    estado["user_input"] = mensaje
    estado["messages"]   = list(estado.get("messages", [])) + [HumanMessage(content=mensaje)]

    etapa = estado.get("etapa", "bienvenida")

    if etapa == "bienvenida":
        nuevo = nodo_bienvenida(estado)
    elif etapa == "menu":
        nuevo = nodo_mostrar_menu(estado)
    else:
        nuevo = nodo_procesar(estado)

    sesiones[session_id] = nuevo
    msgs = [m for m in nuevo.get("messages", []) if isinstance(m, AIMessage)]
    return msgs[-1].content if msgs else "..."


# ─────────────────────────────────────────────
#  FLASK APP
# ─────────────────────────────────────────────
flask_app = Flask(__name__)
CORS(flask_app)

HTML_CHAT = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>McGourmet Bot</title>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700&family=DM+Sans:wght@400;500&display=swap" rel="stylesheet">
<style>
:root{--brand:#C8360A;--brand-dk:#8B240A;--gold:#E8A020;--bg:#FDF8F3;--surface:#fff;--bot-bg:#FFF3EC;--text:#1A1208;--muted:#7A6A5A;}
*{box-sizing:border-box;margin:0;padding:0;}
body{font-family:'DM Sans',sans-serif;background:var(--bg);display:flex;justify-content:center;align-items:center;min-height:100vh;padding:16px;}
.wrap{width:100%;max-width:480px;display:flex;flex-direction:column;height:92vh;background:var(--surface);border-radius:24px;box-shadow:0 20px 60px rgba(200,54,10,.15);overflow:hidden;}
.header{background:var(--brand);padding:20px 24px;display:flex;align-items:center;gap:14px;}
.logo{width:48px;height:48px;border-radius:50%;background:var(--gold);display:flex;align-items:center;justify-content:center;font-size:22px;flex-shrink:0;}
.header h1{font-family:'Playfair Display',serif;color:#fff;font-size:20px;}
.header p{color:rgba(255,255,255,.75);font-size:12px;margin-top:3px;}
.dot{display:inline-block;width:8px;height:8px;background:#4ADE80;border-radius:50%;margin-right:4px;}
.msgs{flex:1;overflow-y:auto;padding:20px 16px;display:flex;flex-direction:column;gap:12px;scroll-behavior:smooth;}
.msgs::-webkit-scrollbar{width:4px;}
.msgs::-webkit-scrollbar-thumb{background:#e0d4c8;border-radius:4px;}
.bw{display:flex;align-items:flex-end;gap:8px;}
.bw.user{flex-direction:row-reverse;}
.av{width:28px;height:28px;border-radius:50%;background:var(--gold);display:flex;align-items:center;justify-content:center;font-size:14px;flex-shrink:0;}
.bubble{max-width:78%;padding:12px 16px;border-radius:18px;font-size:14px;line-height:1.6;white-space:pre-wrap;word-break:break-word;}
.bubble.bot{background:var(--bot-bg);color:var(--text);border-bottom-left-radius:4px;border:1px solid #F0DDD0;}
.bubble.user{background:var(--brand);color:#fff;border-bottom-right-radius:4px;}
.qr{display:flex;flex-wrap:wrap;gap:8px;padding:0 16px 12px;}
.qb{background:transparent;border:1.5px solid var(--brand);color:var(--brand);padding:6px 14px;border-radius:20px;font-size:12px;font-family:'DM Sans',sans-serif;cursor:pointer;transition:all .2s;font-weight:500;}
.qb:hover{background:var(--brand);color:#fff;}
.inp{padding:12px 16px 20px;display:flex;gap:10px;border-top:1px solid #F0DDD0;}
.inp input{flex:1;border:1.5px solid #E8D8CC;border-radius:24px;padding:12px 18px;font-size:14px;font-family:'DM Sans',sans-serif;outline:none;color:var(--text);background:var(--bg);transition:border .2s;}
.inp input:focus{border-color:var(--brand);}
.inp button{width:46px;height:46px;border-radius:50%;background:var(--brand);border:none;color:#fff;font-size:18px;cursor:pointer;flex-shrink:0;transition:background .2s;display:flex;align-items:center;justify-content:center;}
.inp button:hover{background:var(--brand-dk);}
.typing{display:flex;align-items:center;gap:5px;padding:4px 0;}
.td{width:7px;height:7px;background:var(--muted);border-radius:50%;animation:bounce .9s infinite;}
.td:nth-child(2){animation-delay:.15s;}
.td:nth-child(3){animation-delay:.3s;}
@keyframes bounce{0%,80%,100%{transform:translateY(0)}40%{transform:translateY(-6px)}}
</style>
</head>
<body>
<div class="wrap">
  <div class="header">
    <div class="logo">🍽️</div>
    <div>
      <h1>McGourmet</h1>
      <p><span class="dot"></span>Asistente de pedidos</p>
    </div>
  </div>
  <div class="msgs" id="msgs"></div>
  <div class="qr">
    <button class="qb" onclick="send('MENU')">📋 Menu</button>
    <button class="qb" onclick="send('VER CARRITO')">🛒 Carrito</button>
    <button class="qb" onclick="send('CONFIRMAR')">✅ Confirmar</button>
    <button class="qb" onclick="send('AYUDA')">❓ Ayuda</button>
  </div>
  <div class="inp">
    <input id="inp" type="text" placeholder="Escribi tu mensaje..." autocomplete="off" onkeydown="if(event.key==='Enter')send()">
    <button onclick="send()">➤</button>
  </div>
</div>
<script>
const sid='sess_'+Math.random().toString(36).substr(2,9);
function addMsg(t,r){
  const c=document.getElementById('msgs');
  const w=document.createElement('div');w.className='bw '+r;
  const a=document.createElement('div');a.className='av';a.textContent=r==='bot'?'🍽️':'👤';
  const b=document.createElement('div');b.className='bubble '+r;b.textContent=t;
  if(r==='bot'){w.appendChild(a);w.appendChild(b);}else{w.appendChild(b);w.appendChild(a);}
  c.appendChild(w);c.scrollTop=c.scrollHeight;
}
function showTyping(){
  const c=document.getElementById('msgs');
  const d=document.createElement('div');d.id='typing';d.className='bw bot';
  d.innerHTML='<div class="av">🍽️</div><div class="bubble bot"><div class="typing"><div class="td"></div><div class="td"></div><div class="td"></div></div></div>';
  c.appendChild(d);c.scrollTop=c.scrollHeight;
}
function removeTyping(){const t=document.getElementById('typing');if(t)t.remove();}
async function send(t){
  const inp=document.getElementById('inp');
  const msg=t||inp.value.trim();
  if(!msg)return;
  inp.value='';
  addMsg(msg,'user');
  showTyping();
  try{
    const r=await fetch('/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_id:sid,message:msg})});
    const d=await r.json();
    removeTyping();
    addMsg(d.response,'bot');
  }catch(e){removeTyping();addMsg('Error de conexion. Intentá nuevamente.','bot');}
}
window.onload=async()=>{
  showTyping();
  try{
    const r=await fetch('/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_id:sid,message:'INICIO'})});
    const d=await r.json();removeTyping();addMsg(d.response,'bot');
  }catch(e){removeTyping();addMsg('Hola! Escribi MENU para empezar.','bot');}
};
</script>
</body>
</html>"""

@flask_app.route("/")
def index():
    return render_template_string(HTML_CHAT)

@flask_app.route("/chat", methods=["POST"])
def chat():
    data      = request.get_json(force=True)
    session_id = data.get("session_id", str(uuid.uuid4()))
    mensaje    = data.get("message", "").strip()
    if not mensaje:
        return jsonify({"error": "Mensaje vacio"}), 400
    respuesta = procesar_mensaje(session_id, mensaje)
    return jsonify({"session_id": session_id, "response": respuesta})

@flask_app.route("/pedidos")
def listar_pedidos():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur  = conn.cursor()
    cur.execute("SELECT * FROM tbl_PedBot ORDER BY fecha_pedido DESC")
    pedidos = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify(pedidos)

@flask_app.route("/health")
def health():
    return jsonify({"status": "ok", "app": "McGourmet Bot v2"})


# ─────────────────────────────────────────────
#  ARRANQUE
# ─────────────────────────────────────────────
if __name__ == "__main__":
    setup_database()

    IN_COLAB = "COLAB_GPU" in os.environ or "COLAB_RELEASE_TAG" in os.environ

    if IN_COLAB:
        from pyngrok import ngrok, conf
        token = os.environ.get("NGROK_TOKEN", "")
        if token:
            conf.get_default().auth_token = token
        tunnel = ngrok.connect(5000)
        print(f"\n{'='*55}")
        print(f"  URL PUBLICA: {tunnel.public_url}")
        print(f"{'='*55}\n")
        flask_app.run(port=5000, use_reloader=False, threaded=True)
    else:
        port = int(os.environ.get("PORT", 5000))
        setup_database()
        flask_app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
