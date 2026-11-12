"""
McGourmet Bot v6.4 - Catálogo Visual + Landing Page
Flask + PostgreSQL + Carrito UI con imágenes desde GitHub
Se Elimina el Envio message x wsap de cliente a 2615024133 
Envio message x Telegram a 2616741098
Se adiciona la opcion de imprimir el remito en pdf
version Oct-2026 mrp — v6.1 botón Inicio en header y en formulario/remito
v6.2 Nov-2026 — fix remito PDF: incluye cliente, teléfono y aclaraciones; textos largos con salto de línea
v6.3 Nov-2026 — precios, subtotales y total del pedido se toman de tbl_Catalogo (no del navegador)
v6.4 Nov-2026 — /pedidos, /debug y /seed protegidas con ADMIN_KEY; fecha y hora de Argentina (UTC-3)
"""

import os, uuid, threading, time, urllib.request, urllib.parse, json, hmac
from datetime import datetime, timezone, timedelta
from functools import wraps
from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS

# ── Configuración ──────────────────────────────────────────────
DATABASE_URL        = os.environ.get("DATABASE_URL", "")
GMAIL_USER          = os.environ.get("GMAIL_USER", "")
GMAIL_PASSWORD      = os.environ.get("GMAIL_PASSWORD", "")
EMAIL_DESTINO       = os.environ.get("EMAIL_DESTINO", "")
TELEGRAM_BOT_TOKEN  = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID    = os.environ.get("TELEGRAM_CHAT_ID", "")

# URL base de imágenes en GitHub (raw)
# Estructura: images/{id_producto}.jpg  (ej: images/1.jpg, images/2.jpg, ...)
GITHUB_IMAGES_BASE = os.environ.get(
    "GITHUB_IMAGES_BASE",
    "https://raw.githubusercontent.com/mquanmrp-arch/mcgourmet-bot/main/images"
)
LOGO_URL = f"{GITHUB_IMAGES_BASE}/logo.png"

LIMITE_PEDIDOS_DIA = int(os.environ.get("LIMITE_PEDIDOS_DIA", "50"))
LIMITE_UNIDADES    = int(os.environ.get("LIMITE_UNIDADES", "2"))

# Clave para las rutas privadas (/pedidos, /debug, /seed).
# Definir ADMIN_KEY en Render → Environment. Sin clave definida, esas rutas quedan bloqueadas.
ADMIN_KEY = os.environ.get("ADMIN_KEY", "")

# Hora oficial argentina (UTC-3, sin horario de verano)
TZ_AR = timezone(timedelta(hours=-3), "ART")

def ahora():
    """Fecha y hora actual de Argentina, sin depender de la zona horaria del servidor."""
    return datetime.now(TZ_AR)

# ── BD: PostgreSQL ──────────────────────────────────────────────
if DATABASE_URL:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    USE_PG = True
else:
    import sqlite3
    DB_PATH = "mcgourmet.db"
    USE_PG  = False

def get_conn():
    if USE_PG:
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

# ── SETUP BD ───────────────────────────────────────────────────
def setup_database():
    try:
        conn = get_conn()
        cur  = conn.cursor()
        ph   = "%s" if USE_PG else "?"
        auto = "SERIAL" if USE_PG else "INTEGER"

        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS tbl_Catalogo (
                id_producto     {auto} PRIMARY KEY,
                categoria       TEXT,
                nombre_producto TEXT,
                descripcion     TEXT,
                precio          REAL,
                disponible      INTEGER DEFAULT 1,
                imagen_url      TEXT DEFAULT ''
            )
        """)
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS tbl_PedBot (
                id_pedido      {auto} PRIMARY KEY,
                session_id     TEXT,
                nombre_cliente TEXT,
                telefono       TEXT,
                fecha_pedido   TEXT,
                estado         TEXT DEFAULT 'Confirmado',
                total          REAL DEFAULT 0,
                notas          TEXT,
                notificado     INTEGER DEFAULT 0
            )
        """)
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS tbl_PedBot_Detalle (
                id_detalle      {auto} PRIMARY KEY,
                id_pedido       INTEGER,
                nombre_producto TEXT,
                cantidad        INTEGER,
                precio_unit     REAL,
                subtotal        REAL
            )
        """)

        cur.execute("SELECT COUNT(*) FROM tbl_Catalogo")
        row   = cur.fetchone()
        count = row[0]  # cursor plano (no RealDictCursor) → siempre tupla
        if count == 0:
            productos = [
                ("Pasteleria", "La Eulogia",    "Alfajor negro de vino malbec, relleno dulce de leche y jalea de vino - Caja 6 unidades.", 15000.00),
                ("Pasteleria", "La Simona",     "Alfajor blanco, con crema Bariloche y pistacho - Caja de 6 unidades.",                    18000.00),
                ("Pasteleria", "La Florentina", "Alfajor negro, relleno dulce de leche y mermelada de membrillo - Caja 6 unidades.",       15000.00),
                ("Pasteleria", "La Rufina",     "Alfajor de chocolate con relleno de chocotorta - Caja de 6 unidades.",                    12000.00),
                ("Pasteleria", "La Aurora",     "Alfajor de chocolate con relleno de almendras - Caja 6 unidades.",                        12000.00),
                ("Pasteleria", "La Petrona",    "Alfajor de maicena - Caja de 12 unidades.",                                               12000.00),
                ("Pasteleria", "La Jacinta",    "Tarta con crema de limon - Caja 1 unidad.",                                               23000.00),
                ("Pasteleria", "La Imara",      "Variedad de masas gourmet - Caja 6 porciones.",                                           18000.00),
            ]         

            sql = (f"INSERT INTO tbl_Catalogo (categoria,nombre_producto,descripcion,precio,disponible) VALUES ({ph},{ph},{ph},{ph},1)"
                   if USE_PG else
                   "INSERT INTO tbl_Catalogo (categoria,nombre_producto,descripcion,precio,disponible) VALUES (?,?,?,?,1)")
            for p in productos:
                cur.execute(sql, p)

        conn.commit()
        conn.close()
        print("✅ BD lista.")
    except Exception as e:
        print(f"❌ BD error: {e}")

# ── HELPERS BD ─────────────────────────────────────────────────
def get_catalogo():
    try:
        conn = get_conn()
        cur  = get_cur(conn)
        cur.execute(
            "SELECT id_producto,categoria,nombre_producto,descripcion,precio,disponible,imagen_url "
            "FROM tbl_Catalogo WHERE disponible=1 ORDER BY id_producto"
        )
        rows = cur.fetchall()
        catalogo = []
        for r in rows:
            id_p = r["id_producto"] if USE_PG else r[0]
            img  = r["imagen_url"]  if USE_PG else r[6]
            # Si no tiene imagen_url en BD, construir desde GitHub por id
            if not img:
                img = f"{GITHUB_IMAGES_BASE}/{id_p}.jpg"
            catalogo.append({
                "id_producto":    id_p,
                "categoria":      r["categoria"]       if USE_PG else r[1],
                "nombre_producto":r["nombre_producto"] if USE_PG else r[2],
                "descripcion":    r["descripcion"]     if USE_PG else r[3],
                "precio":         float(r["precio"]    if USE_PG else r[4]),
                "disponible":     bool(r["disponible"] if USE_PG else r[5]),
                "imagen":         img,
            })
        cur.close(); conn.close()
        return catalogo
    except Exception as e:
        print(f"⚠️ get_catalogo: {e}")
        return []

def contar_pedidos_hoy():
    conn = get_conn(); cur = get_cur(conn)
    hoy  = ahora().strftime("%Y-%m-%d")
    ph   = "%s" if USE_PG else "?"
    cur.execute(f"SELECT COUNT(*) AS cnt FROM tbl_PedBot WHERE fecha_pedido LIKE {ph} AND estado='Confirmado'", (f"{hoy}%",))
    row  = cur.fetchone()
    count = row["cnt"] if USE_PG else row[0]
    conn.close(); return count

def crear_pedido(session_id, nombre, telefono, notas):
    conn = get_conn(); cur = get_cur(conn)
    ph   = "%s" if USE_PG else "?"
    sql  = (f"INSERT INTO tbl_PedBot (session_id,nombre_cliente,telefono,fecha_pedido,estado,notas)"
            f" VALUES ({ph},{ph},{ph},{ph},{ph},{ph})")
    if USE_PG:
        sql += " RETURNING id_pedido"
    cur.execute(sql, (session_id, nombre, telefono,
                      ahora().strftime("%Y-%m-%d %H:%M:%S"), "Confirmado", notas))
    id_p = cur.fetchone()["id_pedido"] if USE_PG else cur.lastrowid
    conn.commit(); conn.close(); return id_p

def agregar_detalle(id_pedido, id_producto, cantidad):
    conn = get_conn(); cur = get_cur(conn)
    ph   = "%s" if USE_PG else "?"
    cur.execute(f"SELECT nombre_producto,precio FROM tbl_Catalogo WHERE id_producto={ph}", (id_producto,))
    prod = cur.fetchone()
    if prod:
        nombre = prod["nombre_producto"] if USE_PG else prod[0]
        precio = float(prod["precio"]    if USE_PG else prod[1])
        sub    = precio * cantidad
        cur.execute(
            f"INSERT INTO tbl_PedBot_Detalle (id_pedido,nombre_producto,cantidad,precio_unit,subtotal)"
            f" VALUES ({ph},{ph},{ph},{ph},{ph})",
            (id_pedido, nombre, cantidad, precio, sub)
        )
        cur.execute(f"UPDATE tbl_PedBot SET total=total+{ph} WHERE id_pedido={ph}", (sub, id_pedido))
    conn.commit(); conn.close()

def get_pedido(id_pedido):
    conn = get_conn(); cur = get_cur(conn)
    ph   = "%s" if USE_PG else "?"
    cur.execute(f"SELECT * FROM tbl_PedBot WHERE id_pedido={ph}", (id_pedido,))
    ped  = dict(cur.fetchone())
    cur.execute(f"SELECT * FROM tbl_PedBot_Detalle WHERE id_pedido={ph}", (id_pedido,))
    ped["items"] = [dict(r) for r in cur.fetchall()]
    conn.close(); return ped

# ── TELEGRAM ───────────────────────────────────────────────────
def enviar_telegram(id_pedido):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Telegram: variables no configuradas")
        return
    try:
        ped     = get_pedido(id_pedido)
        items   = ped["items"]
        detalle = "\n".join([f"  • {it['cantidad']}x {it['nombre_producto']}  $ {it['subtotal']:,.0f}" for it in items])
        texto   = (f"🛒 *NUEVO PEDIDO McGourmet \\#{id_pedido}*\n"
                   f"{'─'*30}\n"
                   f"👤 *Cliente:* {ped['nombre_cliente']}\n"
                   f"📱 *Teléfono:* {ped['telefono']}\n"
                   f"📅 *Fecha:* {ped['fecha_pedido']}\n"
                   f"📝 *Notas:* {ped['notas'] or 'Sin notas'}\n\n"
                   f"*DETALLE:*\n{detalle}\n\n"
                   f"{'─'*30}\n"
                   f"💰 *TOTAL: $ {ped['total']:,.0f}*")
        data = json.dumps({
            "chat_id":    TELEGRAM_CHAT_ID,
            "text":       texto,
            "parse_mode": "Markdown"
        }).encode("utf-8")
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(f"📱 Telegram enviado #{id_pedido} - {resp.status}")
    except Exception as e:
        print(f"❌ Telegram error: {e}")

# ── EMAIL (SendGrid) ───────────────────────────────────────────
def enviar_email(id_pedido):
    api_key       = os.environ.get("SENDGRID_API_KEY", "")
    gmail_user    = os.environ.get("GMAIL_USER", "")
    email_destino = os.environ.get("EMAIL_DESTINO", "")
    if not all([api_key, gmail_user, email_destino]):
        print("⚠️ Email: variables no configuradas")
        return
    try:
        ped     = get_pedido(id_pedido)
        items   = ped["items"]
        detalle = "\n".join([f"  {it['cantidad']}x {it['nombre_producto']}  $ {it['subtotal']:,.0f}" for it in items])
        cuerpo  = (f"NUEVO PEDIDO McGourmet #{id_pedido}\n{'='*40}\n"
                   f"Cliente  : {ped['nombre_cliente']}\n"
                   f"Telefono : {ped['telefono']}\n"
                   f"Fecha    : {ped['fecha_pedido']}\n"
                   f"Notas    : {ped['notas'] or 'Sin notas'}\n\n"
                   f"DETALLE:\n{detalle}\n\n{'='*40}\n"
                   f"TOTAL: $ {ped['total']:,.0f}\n{'='*40}")
        data = json.dumps({
            "personalizations": [{"to": [{"email": email_destino}]}],
            "from": {"email": gmail_user},
            "subject": f"Nuevo Pedido #{id_pedido} - {ped['nombre_cliente']} - $ {ped['total']:,.0f}",
            "content": [{"type": "text/plain", "value": cuerpo}]
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://api.sendgrid.com/v3/mail/send", data=data,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req) as resp:
            print(f"✉️ Email enviado #{id_pedido} - {resp.status}")
        conn = get_conn(); cur = get_cur(conn)
        ph   = "%s" if USE_PG else "?"
        cur.execute(f"UPDATE tbl_PedBot SET notificado=1 WHERE id_pedido={ph}", (id_pedido,))
        conn.commit(); conn.close()
    except Exception as e:
        print(f"❌ Email error: {e}")

# ── REMITO ─────────────────────────────────────────────────────
def generar_remito(id_pedido, nombre, telefono, notas, carrito, total, fecha=None):
    fecha  = fecha or ahora().strftime("%d/%m/%Y %H:%M")
    sep    = "=" * 40
    lineas = [sep, "          McGourmet", "     Sabores que encantan",
              "       Tel: 261 5024133", sep,
              f"  REMITO N {id_pedido:04d}", f"  Fecha   : {fecha}",
              f"  Cliente : {nombre}", f"  Tel     : {telefono}", sep,
              "  DETALLE", "-" * 40]
    for item in carrito:
        lineas.append(f"  {item['cantidad']}x {item['nombre']}")
        if item.get('descripcion'):
            lineas.append(f"     {item['descripcion']}")
        lineas.append(f"     $ {item['precio']:,.0f} c/u  =  $ {item['subtotal']:,.0f}")
    lineas += ["-" * 40, f"  TOTAL:          $ {total:,.0f}", sep]
    if notas:
        lineas.append(f"  Notas: {notas}"); lineas.append(sep)
    lineas += ["  Gracias por elegirnos!", "  Te contactaremos pronto.", sep]
    return "\n".join(lineas)

# ── SESIONES ───────────────────────────────────────────────────
sesiones = {}

# ── Validar carrito contra el catálogo ─────────────────────────
def validar_carrito(carrito_json):
    """
    Reconstruye el carrito con los datos de tbl_Catalogo.
    Del frontend solo usa id_producto y cantidad; ignora nombre, precio y subtotal.
    Devuelve (carrito, None) si está bien, o (None, mensaje_de_error).
    """
    if not isinstance(carrito_json, list):
        return None, "El carrito no es válido."

    # Unificar cantidades por producto
    cantidades = {}
    for item in carrito_json:
        try:
            id_prod  = int(item["id_producto"])
            cantidad = int(item["cantidad"])
        except (KeyError, TypeError, ValueError):
            return None, "El carrito no es válido."
        if cantidad < 1:
            return None, "El carrito tiene cantidades no válidas."
        cantidades[id_prod] = cantidades.get(id_prod, 0) + cantidad
    if not cantidades:
        return None, "El carrito está vacío."

    conn = get_conn(); cur = get_cur(conn)
    ph   = "%s" if USE_PG else "?"
    carrito = []
    try:
        for id_prod, cantidad in cantidades.items():
            cur.execute(
                f"SELECT nombre_producto,descripcion,precio,disponible "
                f"FROM tbl_Catalogo WHERE id_producto={ph}", (id_prod,))
            prod = cur.fetchone()
            if not prod:
                return None, "Uno de los productos ya no está en el catálogo. Recargá la página."
            nombre      = prod["nombre_producto"] if USE_PG else prod[0]
            descripcion = prod["descripcion"]     if USE_PG else prod[1]
            precio      = float(prod["precio"]    if USE_PG else prod[2])
            disponible  = prod["disponible"]      if USE_PG else prod[3]
            if not disponible:
                return None, f"{nombre} no está disponible en este momento."
            if cantidad > LIMITE_UNIDADES:
                return None, f"El máximo por pedido es {LIMITE_UNIDADES} unidades de {nombre}."
            carrito.append({
                "id_producto": id_prod,
                "nombre":      nombre,
                "descripcion": descripcion or "",
                "precio":      precio,
                "cantidad":    cantidad,
                "subtotal":    precio * cantidad,
            })
    finally:
        conn.close()
    return carrito, None

# ── API: confirmar pedido desde el carrito visual ──────────────
def confirmar_pedido_api(session_id, nombre, telefono, notas, carrito_json):
    """
    Recibe carrito como lista de {id_producto, nombre, precio, cantidad, subtotal}
    desde el frontend. Crea el pedido en BD y devuelve el remito.
    """
    # Nombre, descripción, precio y subtotal salen SIEMPRE de tbl_Catalogo;
    # del navegador solo se toman id_producto y cantidad.
    carrito, error = validar_carrito(carrito_json)
    if error:
        return {"ok": False, "msg": error}
    total = sum(item["subtotal"] for item in carrito)

    if contar_pedidos_hoy() >= LIMITE_PEDIDOS_DIA:
        return {"ok": False, "msg": "Lo sentimos, alcanzamos el límite de pedidos por hoy.\nPara pedidos especiales escríbenos por mail."}

    id_p = crear_pedido(session_id, nombre, telefono, notas)
    for item in carrito:
        agregar_detalle(id_p, item["id_producto"], item["cantidad"])

    fecha  = ahora().strftime("%d/%m/%Y %H:%M")
    remito = generar_remito(id_p, nombre, telefono, notas, carrito, total, fecha)
    threading.Thread(target=enviar_email,    args=(id_p,), daemon=True).start()
    threading.Thread(target=enviar_telegram, args=(id_p,), daemon=True).start()
    # Número de WhatsApp de McGourmet para el botón del cliente
    wa_numero = os.environ.get("WA_NUMERO", "5492615024133")  # formato internacional sin +
    return {"ok": True, "id_pedido": id_p, "remito": remito, "total": total,
            "fecha": fecha, "items": carrito, "wa_numero": wa_numero}

# ── FLASK ──────────────────────────────────────────────────────
setup_database()
flask_app = Flask(__name__)
CORS(flask_app)

# ── HTML: Catálogo Visual v5.0 ──────────────────────────────────
HTML = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>McGourmet — Pedidos</title>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;900&family=Lato:wght@300;400;700&display=swap" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js"></script>
<style>
:root{
  --brand:#B5261E; --brand-dk:#8B1A14; --cream:#FDF6EC;
  --gold:#D4A843;  --text:#2C1810;     --muted:#8B7355;
  --border:#E8D5B7; --green:#22c55e;
}
*{box-sizing:border-box;margin:0;padding:0;}
body{font-family:'Lato',sans-serif;background:var(--cream);min-height:100vh;display:flex;justify-content:center;padding:12px;}
.app{width:100%;max-width:480px;display:flex;flex-direction:column;min-height:95vh;}

/* HEADER */
.header{background:var(--brand);padding:14px 18px;display:flex;align-items:center;gap:12px;border-radius:20px 20px 0 0;position:relative;}
.header::after{content:'';position:absolute;bottom:0;left:0;right:0;height:3px;background:linear-gradient(90deg,var(--gold),transparent,var(--gold));}
.logo-wrap{width:52px;height:52px;border-radius:50%;overflow:hidden;border:2px solid var(--gold);flex-shrink:0;background:#fff;}
.logo-wrap img{width:100%;height:100%;object-fit:cover;}
.header-info h1{font-family:'Playfair Display',serif;color:#fff;font-size:17px;}
.header-info .lema{color:var(--gold);font-size:11px;font-style:italic;margin-top:2px;}
.header-info .tel{color:rgba(255,255,255,.65);font-size:11px;margin-top:2px;}
.sdot{width:7px;height:7px;background:var(--green);border-radius:50%;animation:pulse 2s infinite;display:inline-block;margin-right:4px;}
.sonline{color:rgba(255,255,255,.55);font-size:10px;}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}

/* BARRA INICIO */
.barra-inicio{background:#fff;border-bottom:1px solid var(--border);padding:6px 14px;}
.barra-inicio a{display:inline-flex;align-items:center;gap:5px;color:var(--brand);font-size:13px;font-weight:700;text-decoration:none;}
.barra-inicio a:hover{opacity:.75;}

/* TABS */
.tabs{display:flex;background:#fff;border-bottom:2px solid var(--border);}
.tab{flex:1;padding:10px 4px;font-size:13px;font-weight:700;color:var(--muted);border:none;background:none;cursor:pointer;transition:color .2s;position:relative;}
.tab.active{color:var(--brand);}
.tab.active::after{content:'';position:absolute;bottom:-2px;left:0;right:0;height:2px;background:var(--brand);}
.tab .badge{background:var(--brand);color:#fff;border-radius:9px;font-size:10px;padding:1px 6px;margin-left:4px;vertical-align:middle;}

/* SECCIÓN */
.section{display:none;flex:1;overflow-y:auto;background:var(--cream);padding:14px;}
.section.active{display:block;}

/* CATÁLOGO */
.cat-title{font-family:'Playfair Display',serif;color:var(--brand);font-size:15px;margin:8px 0 10px;border-bottom:1px solid var(--border);padding-bottom:4px;}
.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:12px;margin-bottom:16px;}
.card{background:#fff;border-radius:14px;overflow:hidden;box-shadow:0 2px 10px rgba(0,0,0,.07);border:1px solid var(--border);transition:transform .15s;}
.card:hover{transform:translateY(-2px);}
.card-img{width:100%;aspect-ratio:1;object-fit:cover;background:#f5ede0;}
.card-img.fallback{display:flex;align-items:center;justify-content:center;font-size:32px;color:var(--muted);}
.card-body{padding:10px;}
.card-name{font-weight:700;font-size:13px;color:var(--text);line-height:1.3;}
.card-desc{font-size:11px;color:var(--muted);margin:4px 0 6px;line-height:1.4;}
.card-price{font-family:'Playfair Display',serif;color:var(--brand);font-size:14px;font-weight:700;margin-top:6px;}
.card-ctrl{display:flex;flex-direction:column;align-items:stretch;gap:8px;margin-top:8px;}
.qty-wrap{display:flex;align-items:center;justify-content:center;gap:0;}
.qty-btn{width:32px;height:32px;border-radius:50%;border:1.5px solid var(--brand);background:transparent;color:var(--brand);font-size:18px;line-height:1;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:all .15s;}
.qty-btn:hover{background:var(--brand);color:#fff;}
.qty-num{width:36px;text-align:center;font-size:14px;font-weight:700;color:var(--text);}
.add-btn{background:var(--brand);color:#fff;border:none;border-radius:10px;padding:8px 10px;font-size:12px;font-weight:700;cursor:pointer;transition:background .15s;width:100%;}
.add-btn:hover{background:var(--brand-dk);}
.add-btn:disabled{background:var(--muted);cursor:default;}

/* CARRITO */
.cart-empty{text-align:center;padding:40px 20px;color:var(--muted);}
.cart-empty .icon{font-size:48px;margin-bottom:10px;}
.cart-empty p{font-size:14px;}
.cart-item{background:#fff;border-radius:12px;padding:12px;margin-bottom:10px;border:1px solid var(--border);display:flex;gap:10px;align-items:center;}
.cart-item-img{width:54px;height:54px;border-radius:8px;object-fit:cover;flex-shrink:0;background:#f5ede0;}
.cart-item-info{flex:1;}
.cart-item-name{font-weight:700;font-size:13px;color:var(--text);}
.cart-item-price{font-size:12px;color:var(--muted);margin-top:2px;}
.cart-item-subtotal{font-family:'Playfair Display',serif;color:var(--brand);font-size:14px;font-weight:700;text-align:right;margin-left:auto;}
.cart-item-ctrl{display:flex;align-items:center;gap:0;margin-top:6px;}
.del-btn{background:none;border:none;color:var(--muted);cursor:pointer;font-size:18px;line-height:1;padding:0 4px;}
.del-btn:hover{color:var(--brand);}

.cart-total-box{background:#fff;border-radius:14px;padding:14px 16px;border:2px solid var(--border);margin-top:8px;}
.cart-total-row{display:flex;justify-content:space-between;align-items:center;}
.cart-total-label{font-size:14px;color:var(--muted);}
.cart-total-val{font-family:'Playfair Display',serif;font-size:22px;color:var(--brand);font-weight:700;}
.btn-confirm{width:100%;margin-top:12px;padding:13px;background:var(--brand);color:#fff;border:none;border-radius:12px;font-size:15px;font-weight:700;cursor:pointer;font-family:'Playfair Display',serif;letter-spacing:.5px;transition:background .2s;}
.btn-confirm:hover{background:var(--brand-dk);}
.btn-confirm:disabled{background:var(--muted);cursor:default;}
.btn-clear{width:100%;margin-top:8px;padding:9px;background:transparent;color:var(--muted);border:1.5px solid var(--border);border-radius:12px;font-size:13px;cursor:pointer;}
.btn-clear:hover{color:var(--brand);border-color:var(--brand);}

/* FORMULARIO */
.form-box{background:#fff;border-radius:14px;padding:18px;border:1px solid var(--border);}
.form-title{font-family:'Playfair Display',serif;color:var(--brand);font-size:16px;margin-bottom:14px;}
.form-group{margin-bottom:12px;}
.form-group label{display:block;font-size:12px;font-weight:700;color:var(--muted);margin-bottom:4px;text-transform:uppercase;letter-spacing:.5px;}
.form-group input,
.form-group textarea{width:100%;border:1.5px solid var(--border);border-radius:10px;padding:10px 14px;font-size:14px;color:var(--text);background:var(--cream);font-family:'Lato',sans-serif;transition:border .2s;outline:none;}
.form-group input:focus,
.form-group textarea:focus{border-color:var(--brand);}
.form-group textarea{resize:vertical;min-height:60px;}

/* REMITO */
.remito-box{background:#fff;border-radius:14px;padding:16px;border:1px dashed var(--gold);font-family:monospace;font-size:12.5px;line-height:1.7;color:var(--text);white-space:pre-wrap;word-break:break-word;}
.remito-ok{text-align:center;margin-bottom:16px;}
.remito-ok .check{font-size:48px;}
.remito-ok p{font-size:14px;color:var(--muted);margin-top:6px;}
.btn-nuevo{width:100%;margin-top:8px;padding:12px;background:var(--green);color:#fff;border:none;border-radius:12px;font-size:15px;font-weight:700;cursor:pointer;transition:opacity .2s;}
.btn-nuevo:hover{opacity:.88;}
.btn-pdf{width:100%;margin-top:8px;padding:12px;background:#fff;color:var(--brand);border:2px solid var(--brand);border-radius:12px;font-size:15px;font-weight:700;cursor:pointer;transition:all .2s;}
.btn-pdf:hover{background:var(--brand);color:#fff;}

/* ESTADO */
.toast{position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:var(--text);color:#fff;padding:10px 20px;border-radius:10px;font-size:13px;z-index:999;opacity:0;transition:opacity .3s;pointer-events:none;}
.toast.show{opacity:1;}

/* loader */
.loader{text-align:center;padding:40px 20px;color:var(--muted);font-size:13px;}
</style>
</head>
<body>
<div class="app">

  <!-- HEADER -->
  <div class="header">
    <div class="logo-wrap">
      <img id="logo-img" src="__LOGO_URL__" alt="McGourmet"
           onerror="this.style.display='none';document.getElementById('logo-fallback').style.display='flex'">
      <div id="logo-fallback" style="display:none;width:100%;height:100%;align-items:center;justify-content:center;font-size:24px;">🍫</div>
    </div>
    <div class="header-info">
      <h1>McGourmet</h1>
      <div class="lema">Sabores que encantan</div>
      <div class="tel">Tel: 261 5024133</div>
      <div><span class="sdot"></span><span class="sonline">En línea</span></div>
    </div>
  </div>

  <!-- BARRA INICIO -->
  <div class="barra-inicio">
    <a href="/">&#8592; Inicio</a>
  </div>

  <!-- TABS -->
  <div class="tabs">
    <button class="tab active" onclick="showTab('catalogo')">🛍️ Catálogo</button>
    <button class="tab" id="tab-carrito" onclick="showTab('carrito')">🛒 Carrito <span class="badge" id="cart-count" style="display:none">0</span></button>
  </div>

  <!-- CATÁLOGO -->
  <div class="section active" id="sec-catalogo">
    <div id="catalogo-content"><div class="loader">Cargando productos...</div></div>
  </div>

  <!-- CARRITO + FORM + REMITO -->
  <div class="section" id="sec-carrito">
    <div id="carrito-content"></div>
  </div>

</div>

<!-- Toast -->
<div class="toast" id="toast"></div>

<script>
const LOGO = '__LOGO_URL__';
const GITHUB_BASE = '__GITHUB_IMAGES_BASE__';
const LIMITE_UNIDADES = __LIMITE_UNIDADES__;

// ── Estado global ───────────────────────────────────────────────
let catalogo = [];
let carrito  = {};  // id_producto -> {id_producto, nombre, precio, imagen, cantidad}
let vista    = 'catalogo'; // catalogo | carrito | form | remito
let ultimoPedido = null;   // datos del último pedido confirmado (para el PDF del remito)

// ── Tab ────────────────────────────────────────────────────────
function showTab(tab) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
  const tabEl = tab === 'catalogo'
    ? document.querySelector('.tab:first-child')
    : document.getElementById('tab-carrito');
  tabEl.classList.add('active');
  document.getElementById('sec-' + tab).classList.add('active');
  if (tab === 'carrito') renderCarrito();
}

// ── Toast ───────────────────────────────────────────────────────
function toast(msg, ms = 2000) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove('show'), ms);
}

// ── Imagen producto ─────────────────────────────────────────────
function imgSrc(prod) {
  if (prod.imagen && prod.imagen.startsWith('http')) return prod.imagen;
  return `${GITHUB_BASE}/${prod.id_producto}.jpg`;
}

// ── Cargar catálogo ─────────────────────────────────────────────
async function cargarCatalogo() {
  try {
    const r = await fetch('/catalogo');
    catalogo = await r.json();
    renderCatalogo();
  } catch (e) {
    document.getElementById('catalogo-content').innerHTML =
      '<div class="loader">❌ Error al cargar el catálogo. Recargá la página.</div>';
  }
}

// ── Render catálogo ─────────────────────────────────────────────
function renderCatalogo() {
  const cats = {};
  catalogo.forEach(p => {
    const c = p.categoria || 'Productos';
    if (!cats[c]) cats[c] = [];
    cats[c].push(p);
  });

  let html = '';
  Object.entries(cats).forEach(([cat, prods]) => {
    html += `<div class="cat-title">${cat}</div><div class="grid">`;
    prods.forEach(p => {
      const en_carrito = carrito[p.id_producto] ? carrito[p.id_producto].cantidad : 0;
      html += `
        <div class="card">
          <img class="card-img" src="${imgSrc(p)}" alt="${p.nombre_producto}"
               onerror="this.outerHTML='<div class=\\'card-img fallback\\'>🍫</div>'">
          <div class="card-body">
            <div class="card-name">${p.nombre_producto}</div>
            <div class="card-desc">${p.descripcion}</div>
            <div class="card-price">$ ${p.precio.toLocaleString('es-AR')}</div>
            <div class="card-ctrl">
              <div class="qty-wrap">
                <button class="qty-btn" onclick="cambiarQty(${p.id_producto},-1)">−</button>
                <div class="qty-num" id="qty-${p.id_producto}">${en_carrito}</div>
                <button class="qty-btn" onclick="cambiarQty(${p.id_producto},+1)">+</button>
              </div>
              <button class="add-btn" id="btn-add-${p.id_producto}"
                onclick="agregarAlCarrito(${p.id_producto})"
                ${en_carrito >= LIMITE_UNIDADES ? 'disabled' : ''}>
                ${en_carrito > 0 ? '✓ En carrito' : '🛒 Agregar'}
              </button>
            </div>
          </div>
        </div>`;
    });
    html += '</div>';
  });
  document.getElementById('catalogo-content').innerHTML = html;
}

// ── Control cantidad en catálogo ────────────────────────────────
function cambiarQty(id, delta) {
  const el = document.getElementById(`qty-${id}`);
  if (!el) return;
  let val = parseInt(el.textContent) + delta;
  val = Math.max(0, Math.min(LIMITE_UNIDADES, val));
  el.textContent = val;
}

function agregarAlCarrito(id_producto) {
  const prod = catalogo.find(p => p.id_producto === id_producto);
  if (!prod) return;
  const qtyEl = document.getElementById(`qty-${id_producto}`);
  const qty   = qtyEl ? parseInt(qtyEl.textContent) || 1 : 1;
  const final = Math.max(1, Math.min(qty, LIMITE_UNIDADES));

  if (carrito[id_producto]) {
    const nueva = Math.min(carrito[id_producto].cantidad + final, LIMITE_UNIDADES);
    carrito[id_producto].cantidad = nueva;
    carrito[id_producto].subtotal = nueva * prod.precio;
  } else {
    carrito[id_producto] = {
      id_producto: prod.id_producto,
      nombre:      prod.nombre_producto,
      descripcion: prod.descripcion,
      precio:      prod.precio,
      imagen:      imgSrc(prod),
      cantidad:    final,
      subtotal:    final * prod.precio,
    };
  }

  actualizarBadge();
  renderCatalogo(); // refresca estados de botones
  toast(`✓ ${prod.nombre_producto} agregado al carrito`);
}

// ── Badge carrito ───────────────────────────────────────────────
function actualizarBadge() {
  const total = Object.values(carrito).reduce((s, i) => s + i.cantidad, 0);
  const badge = document.getElementById('cart-count');
  if (total > 0) {
    badge.textContent = total;
    badge.style.display = 'inline';
  } else {
    badge.style.display = 'none';
  }
}

// ── Cambiar qty en carrito ──────────────────────────────────────
function cambiarQtyCarrito(id, delta) {
  if (!carrito[id]) return;
  const nueva = carrito[id].cantidad + delta;
  if (nueva <= 0) {
    delete carrito[id];
  } else {
    carrito[id].cantidad = Math.min(nueva, LIMITE_UNIDADES);
    carrito[id].subtotal = carrito[id].cantidad * carrito[id].precio;
  }
  actualizarBadge();
  renderCarrito();
}

function eliminarDelCarrito(id) {
  delete carrito[id];
  actualizarBadge();
  renderCarrito();
}

// ── Render carrito ──────────────────────────────────────────────
function renderCarrito() {
  const items = Object.values(carrito);
  const cont  = document.getElementById('carrito-content');

  if (items.length === 0) {
    cont.innerHTML = `
      <div class="cart-empty">
        <div class="icon">🛒</div>
        <p>Tu carrito está vacío.<br>Explorá el catálogo y agregá productos.</p>
      </div>`;
    return;
  }

  const total = items.reduce((s, i) => s + i.subtotal, 0);
  let html = '';
  items.forEach(item => {
    html += `
      <div class="cart-item">
        <img class="cart-item-img" src="${item.imagen}" alt="${item.nombre}"
             onerror="this.style.display='none'">
        <div class="cart-item-info">
          <div class="cart-item-name">${item.nombre}</div>
          <div class="cart-item-price">$ ${item.precio.toLocaleString('es-AR')} c/u</div>
          <div class="cart-item-ctrl">
            <button class="qty-btn" onclick="cambiarQtyCarrito(${item.id_producto},-1)">−</button>
            <div class="qty-num">${item.cantidad}</div>
            <button class="qty-btn" onclick="cambiarQtyCarrito(${item.id_producto},+1)">+</button>
            <button class="del-btn" onclick="eliminarDelCarrito(${item.id_producto})" title="Quitar">🗑</button>
          </div>
        </div>
        <div class="cart-item-subtotal">$ ${item.subtotal.toLocaleString('es-AR')}</div>
      </div>`;
  });

  html += `
    <div class="cart-total-box">
      <div class="cart-total-row">
        <span class="cart-total-label">Total del pedido</span>
        <span class="cart-total-val">$ ${total.toLocaleString('es-AR')}</span>
      </div>
      <button class="btn-confirm" onclick="mostrarFormulario()">Confirmar pedido →</button>
      <button class="btn-clear" onclick="vaciarCarrito()">Vaciar carrito</button>
    </div>`;

  cont.innerHTML = html;
}

function vaciarCarrito() {
  carrito = {};
  actualizarBadge();
  renderCarrito();
  renderCatalogo();
  toast('Carrito vaciado');
}

// ── Formulario de datos ─────────────────────────────────────────
function mostrarFormulario() {
  const items = Object.values(carrito);
  if (items.length === 0) { toast('El carrito está vacío'); return; }
  const total = items.reduce((s,i) => s + i.subtotal, 0);

  document.getElementById('carrito-content').innerHTML = `
    <div class="form-box">
      <div class="form-title">📋 Datos del pedido</div>
      <div class="form-group">
        <label>Nombre completo *</label>
        <input id="f-nombre" type="text" placeholder="Tu nombre" autocomplete="name">
      </div>
      <div class="form-group">
        <label>Teléfono *</label>
        <input id="f-tel" type="tel" placeholder="261 XXXXXXX" autocomplete="tel">
      </div>
      <div class="form-group">
        <label>Aclaraciones</label>
        <textarea id="f-notas" placeholder="hora de retiro, etc. (todos nuestros productos son c/gluten)"></textarea>
      </div>
      <div class="cart-total-box" style="margin-top:4px;">
        <div class="cart-total-row">
          <span class="cart-total-label">Total a abonar</span>
          <span class="cart-total-val">$ ${total.toLocaleString('es-AR')}</span>
        </div>
      </div>
      <button class="btn-confirm" onclick="enviarPedido()">✓ Enviar pedido</button>
      <button class="btn-clear" onclick="renderCarrito()">← Volver al carrito</button>
    </div>`;
}

// ── Enviar pedido ───────────────────────────────────────────────
async function enviarPedido() {
  const nombre = document.getElementById('f-nombre').value.trim();
  const tel    = document.getElementById('f-tel').value.trim();
  const notas  = document.getElementById('f-notas').value.trim();

  if (!nombre) { toast('⚠️ Ingresá tu nombre'); return; }
  if (!tel)    { toast('⚠️ Ingresá tu teléfono'); return; }

  const btn = document.querySelector('.btn-confirm');
  btn.disabled = true;
  btn.textContent = 'Enviando...';

  try {
    const items = Object.values(carrito);
    const resp  = await fetch('/pedido', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({
        session_id: 'web_' + Math.random().toString(36).substr(2,9),
        nombre, telefono: tel, notas,
        carrito: items.map(i => ({
          id_producto: i.id_producto,
          nombre:      i.nombre,
          descripcion: i.descripcion || '',
          precio:      i.precio,
          cantidad:    i.cantidad,
          subtotal:    i.subtotal,
        }))
      })
    });
    const data = await resp.json();

    if (data.ok) {
      // Guardar los datos ANTES de mostrar el remito: mostrarRemito() reemplaza
      // el formulario y los inputs f-nombre / f-tel / f-notas dejan de existir.
      ultimoPedido = {
        id_pedido: data.id_pedido,
        nombre, telefono: tel, notas,
        fecha: data.fecha,   // fecha y hora de Argentina, la misma del remito en pantalla
        // precios y total confirmados por el servidor (tbl_Catalogo)
        total: data.total,
        items: data.items.map(i => ({
          nombre: i.nombre, descripcion: i.descripcion || '',
          precio: i.precio, cantidad: i.cantidad, subtotal: i.subtotal,
        })),
      };
      mostrarRemito(data.remito, data.id_pedido);
      carrito = {};
      actualizarBadge();
    } else {
      toast(data.msg || 'Error al procesar el pedido', 4000);
      btn.disabled = false;
      btn.textContent = '✓ Enviar pedido';
    }
  } catch (e) {
    toast('❌ Error de conexión. Intenta nuevamente.', 4000);
    btn.disabled = false;
    btn.textContent = '✓ Enviar pedido';
  }
}

// ── Mostrar remito ──────────────────────────────────────────────
function mostrarRemito(remito, id_pedido) {
  document.getElementById('carrito-content').innerHTML = `
    <div class="remito-ok">
      <div class="check">✅</div>
      <p><strong>¡Pedido #${id_pedido} recibido!</strong><br>Te contactaremos pronto para coordinar la entrega.</p>
    </div>
    <div class="remito-box">${remito}</div>
    <button class="btn-pdf" onclick="descargarRemitoPDF(${id_pedido})">📄 Guardar remito PDF</button>
    <button class="btn-nuevo" onclick="nuevoPedido()">🛍️ Hacer otro pedido</button>`;
}

function nuevoPedido() {
  renderCatalogo();
  showTab('catalogo');
}

// ── Generar PDF del remito ──────────────────────────────────────
function descargarRemitoPDF(id_pedido) {
  const ped = ultimoPedido;
  if (!ped || ped.id_pedido !== id_pedido) {
    toast('No se encontraron los datos del pedido para generar el PDF', 4000);
    return;
  }

  const { jsPDF } = window.jspdf;
  const doc = new jsPDF({ unit: 'mm', format: 'a6' });

  const W      = doc.internal.pageSize.getWidth();
  const H      = doc.internal.pageSize.getHeight();
  const margen = 10;
  const ancho  = W - margen * 2;
  let y = 12;
  const money = n => '$ ' + Number(n).toLocaleString('es-AR');

  // Escribe texto con salto de línea automático y salto de página si hace falta
  function escribir(texto, opts = {}) {
    const x     = opts.x || margen;
    const alto  = opts.alto || 4;
    const lineas = doc.splitTextToSize(String(texto), ancho - (x - margen));
    lineas.forEach(l => {
      if (y > H - 12) { doc.addPage(); y = 12; }
      doc.text(l, x, y);
      y += alto;
    });
  }
  function separador() {
    if (y > H - 12) { doc.addPage(); y = 12; }
    doc.line(margen, y, W - margen, y); y += 5;
  }

  // Encabezado
  doc.setFontSize(16);
  doc.setFont('helvetica', 'bold');
  doc.text('McGourmet', W / 2, y, { align: 'center' }); y += 6;
  doc.setFontSize(9);
  doc.setFont('helvetica', 'normal');
  doc.text('Sabores que encantan', W / 2, y, { align: 'center' }); y += 5;
  doc.text('Tel: 261 5024133', W / 2, y, { align: 'center' }); y += 5;

  doc.setDrawColor(181, 38, 30);
  doc.setLineWidth(0.5);
  separador();

  // Número de remito y fecha
  doc.setFontSize(10);
  doc.setFont('helvetica', 'bold');
  escribir(`REMITO N° ${String(id_pedido).padStart(4,'0')}`, { alto: 5 });
  doc.setFont('helvetica', 'normal');
  doc.setFontSize(9);
  escribir(`Fecha: ${ped.fecha}`);

  // Datos del cliente
  escribir(`Cliente: ${ped.nombre}`);
  escribir(`Tel: ${ped.telefono}`);
  y += 1;
  separador();

  // Detalle de productos
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(9);
  escribir('DETALLE', { alto: 5 });

  ped.items.forEach(it => {
    doc.setFont('helvetica', 'bold');
    doc.setFontSize(9);
    escribir(`${it.cantidad}x ${it.nombre}`);
    doc.setFont('helvetica', 'normal');
    if (it.descripcion) {
      doc.setFontSize(8);
      escribir(it.descripcion, { x: margen + 3, alto: 3.5 });
    }
    doc.setFontSize(9);
    escribir(`${money(it.precio)} c/u  =  ${money(it.subtotal)}`, { x: margen + 3 });
    y += 1.5;
  });

  separador();
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(11);
  if (y > H - 12) { doc.addPage(); y = 12; }
  doc.text('TOTAL:', margen, y);
  doc.text(money(ped.total), W - margen, y, { align: 'right' }); y += 6;

  // Aclaraciones
  if (ped.notas) {
    doc.setFont('helvetica', 'bold');
    doc.setFontSize(9);
    escribir('Aclaraciones:');
    doc.setFont('helvetica', 'italic');
    doc.setFontSize(8.5);
    escribir(ped.notas, { alto: 3.8 });
    y += 1.5;
  }

  doc.setFont('helvetica', 'normal');
  separador();
  doc.setFontSize(8);
  if (y > H - 8) { doc.addPage(); y = 12; }
  doc.text('¡Gracias por elegirnos! Te contactaremos pronto.', W / 2, y, { align: 'center' });

  doc.save(`McGourmet-Remito-${String(id_pedido).padStart(4,'0')}.pdf`);
}

// ── Init ────────────────────────────────────────────────────────
cargarCatalogo();
</script>
</body>
</html>
"""

# ── Protección de rutas privadas ───────────────────────────────
def requiere_clave(f):
    """
    Exige la clave ADMIN_KEY para entrar a la ruta.
    Se puede enviar en la URL (?clave=...) o en el encabezado X-Admin-Key.
    """
    @wraps(f)
    def envoltura(*args, **kwargs):
        if not ADMIN_KEY:
            return jsonify({"ok": False, "msg": "Ruta deshabilitada: falta definir ADMIN_KEY en el servidor."}), 503
        clave = request.args.get("clave", "") or request.headers.get("X-Admin-Key", "")
        if not hmac.compare_digest(clave.encode("utf-8"), ADMIN_KEY.encode("utf-8")):
            return jsonify({"ok": False, "msg": "Acceso no autorizado."}), 401
        return f(*args, **kwargs)
    return envoltura

# ── RUTAS FLASK ────────────────────────────────────────────────
@flask_app.route("/")
def index():
    with open("index.html", encoding="utf-8") as f:
        return f.read()

@flask_app.route("/pedidos-bot")
def pedidos_bot():
    html = (HTML
            .replace("__LOGO_URL__", LOGO_URL)
            .replace("__GITHUB_IMAGES_BASE__", GITHUB_IMAGES_BASE)
            .replace("__LIMITE_UNIDADES__", str(LIMITE_UNIDADES)))
    return render_template_string(html)

@flask_app.route("/catalogo")
def api_catalogo():
    return jsonify(get_catalogo())

@flask_app.route("/pedido", methods=["POST"])
def api_pedido():
    data    = request.get_json(force=True)
    nombre  = data.get("nombre", "").strip()
    telefono= data.get("telefono", "").strip()
    notas   = data.get("notas", "").strip()
    carrito = data.get("carrito", [])
    sid     = data.get("session_id", str(uuid.uuid4()))

    if not nombre or not telefono:
        return jsonify({"ok": False, "msg": "Nombre y teléfono son requeridos."})
    if not carrito:
        return jsonify({"ok": False, "msg": "El carrito está vacío."})

    resultado = confirmar_pedido_api(sid, nombre, telefono, notas, carrito)
    return jsonify(resultado)

@flask_app.route("/pedidos")
@requiere_clave
def api_pedidos():
    conn = get_conn(); cur = get_cur(conn)
    cur.execute("SELECT * FROM tbl_PedBot ORDER BY fecha_pedido DESC")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify(rows)

@flask_app.route("/health")
def health():
    return jsonify({"status": "ok", "version": "6.4", "db": "postgresql" if USE_PG else "sqlite"})

@flask_app.route("/debug")
@requiere_clave
def debug():
    info = {"version": "6.4", "USE_PG": USE_PG, "DATABASE_URL_set": bool(DATABASE_URL)}
    try:
        conn = get_conn(); cur = conn.cursor()
        cur.execute('SELECT COUNT(*) FROM tbl_Catalogo'); info["catalogo_count"] = cur.fetchone()[0]
        cur.execute('SELECT COUNT(*) FROM tbl_PedBot');   info["pedidos_count"]  = cur.fetchone()[0]
        info["db_status"] = "OK"
        conn.close()
    except Exception as e:
        info["db_status"] = f"ERROR: {str(e)}"
    return jsonify(info)

@flask_app.route("/seed")
@requiere_clave
def seed():
    try:
        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM tbl_Catalogo")
        count = cur.fetchone()[0]
        if count > 0:
            conn.close()
            return jsonify({"status": "ok", "msg": f"Catálogo ya tiene {count} productos"})
        ph = "%s" if USE_PG else "?"
        productos = [
            ("Pasteleria", "La Eulogia",    "Alfajor negro de vino malbec, relleno dulce de leche y jalea de vino - Caja 6 unidades.", 15000.00),
            ("Pasteleria", "La Simona",     "Alfajor blanco, con crema Bariloche y pistacho - Caja de 6 unidades.",                    18000.00),
            ("Pasteleria", "La Florentina", "Alfajor negro, relleno dulce de leche y mermelada de membrillo - Caja 6 unidades.",       15000.00),
            ("Pasteleria", "La Rufina",     "Alfajor de chocolate con relleno de chocotorta - Caja de 6 unidades.",                    12000.00),
            ("Pasteleria", "La Aurora",     "Alfajor de chocolate con relleno de almendras - Caja 6 unidades.",                        12000.00),
            ("Pasteleria", "La Petrona",    "Alfajor de maicena - Caja de 12 unidades.",                                               12000.00),
            ("Pasteleria", "La Jacinta",    "Tarta con crema de limon - Caja 1 unidad.",                                               23000.00),
            ("Pasteleria", "La Imara",      "Variedad de masas gourmet - Caja 6 porciones.",                                           18000.00),
        ]
        sql = (f"INSERT INTO tbl_Catalogo (categoria,nombre_producto,descripcion,precio,disponible) VALUES ({ph},{ph},{ph},{ph},1)")
        for p in productos:
            cur.execute(sql, p)
        conn.commit(); conn.close()
        return jsonify({"status": "ok", "msg": f"Cargados {len(productos)} productos"})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    flask_app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
