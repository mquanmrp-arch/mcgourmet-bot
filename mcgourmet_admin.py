"""
McGourmet Admin App v2
Panel de administracion para confirmar pagos de pedidos con detalle.
Flask + PostgreSQL
"""

import os
from datetime import datetime
from flask import Flask, request, jsonify, render_template_string, session
from flask_cors import CORS

DATABASE_URL = os.environ.get("DATABASE_URL", "")
ADMIN_USER   = "admgourmet"
ADMIN_PASS   = "Silleta210928"
SECRET_KEY   = os.environ.get("SECRET_KEY", "mcgourmet-admin-secret-2026")

if DATABASE_URL:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    USE_PG = True
else:
    import sqlite3
    DB_PATH = "mcgourmet.db"
    USE_PG = False

def get_conn():
    if USE_PG:
        import time
        for intento in range(3):
            try:
                conn = psycopg2.connect(DATABASE_URL, sslmode="require", connect_timeout=10, options="-c statement_timeout=10000")
                conn.autocommit = False
                return conn
            except psycopg2.OperationalError:
                if intento < 2: time.sleep(2); continue
                raise
    return sqlite3.connect(DB_PATH)

def get_cur(conn):
    if USE_PG:
        return conn.cursor(cursor_factory=RealDictCursor)
    conn.row_factory = sqlite3.Row
    return conn.cursor()

def get_pedidos_confirmados():
    try:
        conn = get_conn(); cur = get_cur(conn)
        cur.execute("SELECT id_pedido, nombre_cliente, telefono, fecha_pedido, total FROM tbl_PedBot WHERE estado = 'Confirmado' ORDER BY fecha_pedido DESC")
        rows = [dict(r) for r in cur.fetchall()]
        conn.close(); return rows
    except Exception as e:
        print(f"Error get_pedidos_confirmados: {e}"); return []

def get_detalle_pedido(id_pedido):
    try:
        conn = get_conn(); cur = get_cur(conn)
        ph = "%s" if USE_PG else "?"
        cur.execute(f"SELECT id_pedido, nombre_cliente, telefono, fecha_pedido, total, notas, estado FROM tbl_PedBot WHERE id_pedido = {ph}", (id_pedido,))
        ped = dict(cur.fetchone())
        cur.execute(f"SELECT nombre_producto, cantidad, precio_unit, subtotal FROM tbl_PedBot_Detalle WHERE id_pedido = {ph} ORDER BY id_detalle", (id_pedido,))
        ped["items"] = [dict(r) for r in cur.fetchall()]
        conn.close(); return ped
    except Exception as e:
        print(f"Error get_detalle_pedido: {e}"); return None

def marcar_pagados(ids_pedidos):
    try:
        conn = get_conn(); cur = conn.cursor()
        ph = "%s" if USE_PG else "?"
        placeholders = ",".join([ph] * len(ids_pedidos))
        cur.execute(f"UPDATE tbl_PedBot SET estado = 'Pagado' WHERE id_pedido IN ({placeholders})", tuple(ids_pedidos))
        conn.commit(); afectados = cur.rowcount; conn.close(); return afectados
    except Exception as e:
        print(f"Error marcar_pagados: {e}"); return 0

admin_app = Flask(__name__)
admin_app.secret_key = SECRET_KEY
CORS(admin_app, supports_credentials=True)

HTML_ADMIN = """<!DOCTYPE html>
<html lang="es"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>McGourmet - Panel Administrador</title>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;900&family=Lato:wght@300;400;700&display=swap" rel="stylesheet">
<style>
:root{--brand:#5C3D2E;--brand-dk:#3E2723;--cream:#FDF6EC;--gold:#C9A84C;--olive:#6B7C45;--text:#2C1810;--muted:#8B7355;--border:#E8D5B7;--ok:#6B7C45;}
*{box-sizing:border-box;margin:0;padding:0;}
body{font-family:'Lato',sans-serif;background:var(--cream);min-height:100vh;}
.login-wrap{display:flex;align-items:center;justify-content:center;min-height:100vh;padding:20px;}
.login-box{background:#fff;border-radius:16px;padding:40px 36px;width:100%;max-width:380px;box-shadow:0 24px 80px rgba(92,61,46,.15);border:1px solid var(--border);}
.login-box h1{font-family:'Playfair Display',serif;color:var(--brand);font-size:24px;margin-bottom:4px;}
.login-box .sub{color:var(--muted);font-size:13px;margin-bottom:28px;}
.field{margin-bottom:16px;}
.field label{display:block;font-size:12px;color:var(--muted);margin-bottom:6px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;}
.field input{width:100%;border:1.5px solid var(--border);border-radius:10px;padding:11px 14px;font-size:14px;outline:none;color:var(--text);background:var(--cream);transition:border .2s;}
.field input:focus{border-color:var(--brand);}
.btn{width:100%;background:var(--brand);color:#fff;border:none;border-radius:10px;padding:13px;font-size:14px;font-weight:700;cursor:pointer;transition:background .2s;margin-top:8px;}
.btn:hover{background:var(--brand-dk);}
.error-msg{color:#B33A3A;font-size:12.5px;margin-top:12px;text-align:center;display:none;}
.panel{display:none;max-width:1000px;margin:0 auto;padding:24px 16px;}
.panel-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:24px;padding-bottom:16px;border-bottom:2px solid var(--border);}
.panel-header h1{font-family:'Playfair Display',serif;color:var(--brand);font-size:26px;}
.panel-header .sub{color:var(--muted);font-size:13px;margin-top:2px;}
.logout-btn{background:transparent;border:1.5px solid var(--brand);color:var(--brand);padding:8px 16px;border-radius:8px;font-size:13px;cursor:pointer;font-weight:700;}
.logout-btn:hover{background:var(--brand);color:#fff;}
.toolbar{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;}
.count-badge{background:var(--gold);color:var(--brand-dk);padding:5px 14px;border-radius:20px;font-size:12.5px;font-weight:700;}
.refresh-btn{background:transparent;border:1.5px solid var(--olive);color:var(--olive);padding:7px 14px;border-radius:8px;font-size:12.5px;cursor:pointer;font-weight:700;}
.refresh-btn:hover{background:var(--olive);color:#fff;}
.table-wrap{background:#fff;border-radius:14px;border:1px solid var(--border);overflow:hidden;box-shadow:0 4px 16px rgba(92,61,46,.06);}
table{width:100%;border-collapse:collapse;}
thead{background:var(--brand);}
th{color:#fff;font-size:11.5px;text-transform:uppercase;letter-spacing:.5px;padding:12px 14px;text-align:left;font-weight:700;}
th.chk-col{width:40px;text-align:center;}
td{padding:12px 14px;font-size:13px;color:var(--text);border-bottom:1px solid var(--border);}
tr:last-child td{border-bottom:none;}
tr:hover{background:var(--cream);}
td.chk-col{text-align:center;}
input[type="checkbox"]{width:18px;height:18px;cursor:pointer;accent-color:var(--brand);}
.empty-state{padding:60px 20px;text-align:center;color:var(--muted);}
.empty-state .icon{font-size:40px;margin-bottom:12px;}
.detail-btn{background:transparent;border:1.5px solid var(--brand);color:var(--brand);padding:5px 12px;border-radius:8px;font-size:12px;cursor:pointer;font-weight:700;white-space:nowrap;}
.detail-btn:hover{background:var(--brand);color:#fff;}
.action-bar{display:flex;justify-content:space-between;align-items:center;margin-top:18px;padding:14px 18px;background:#fff;border-radius:12px;border:1px solid var(--border);}
.action-bar .sel-count{font-size:13px;color:var(--muted);}
.confirm-btn{background:var(--ok);color:#fff;border:none;border-radius:10px;padding:11px 22px;font-size:13.5px;font-weight:700;cursor:pointer;transition:background .2s;}
.confirm-btn:hover{background:#566338;}
.confirm-btn:disabled{background:var(--border);cursor:not-allowed;}
.modal-overlay{position:fixed;inset:0;background:rgba(0,0,0,.5);display:none;align-items:center;justify-content:center;z-index:1000;padding:20px;}
.modal-overlay.active{display:flex;}
.modal{background:#fff;border-radius:16px;padding:28px;width:100%;max-width:540px;box-shadow:0 24px 80px rgba(0,0,0,.25);max-height:90vh;overflow-y:auto;}
.modal h2{font-family:'Playfair Display',serif;color:var(--brand);font-size:20px;margin-bottom:16px;}
.modal-info{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:18px;}
.modal-info .item{background:var(--cream);border-radius:8px;padding:10px 14px;}
.modal-info .item .label{font-size:10.5px;color:var(--muted);text-transform:uppercase;font-weight:700;letter-spacing:.5px;margin-bottom:3px;}
.modal-info .item .value{font-size:13.5px;color:var(--text);font-weight:700;}
.modal table{width:100%;border-collapse:collapse;margin-bottom:12px;}
.modal thead{background:var(--brand);}
.modal th{color:#fff;font-size:11px;padding:9px 12px;text-align:left;}
.modal td{padding:9px 12px;font-size:13px;border-bottom:1px solid var(--border);}
.modal tr:last-child td{border-bottom:none;}
.modal-total{text-align:right;font-size:15px;font-weight:700;color:var(--brand);padding:8px 0 16px;}
.modal-actions{display:flex;gap:10px;justify-content:flex-end;}
.modal-close{background:transparent;border:1.5px solid var(--border);color:var(--muted);padding:10px 20px;border-radius:10px;font-size:13px;cursor:pointer;font-weight:700;}
.modal-pay{background:var(--ok);color:#fff;border:none;border-radius:10px;padding:10px 22px;font-size:13.5px;font-weight:700;cursor:pointer;}
.modal-pay:hover{background:#566338;}
.toast{position:fixed;bottom:24px;right:24px;background:var(--brand);color:#fff;padding:14px 22px;border-radius:10px;font-size:13.5px;box-shadow:0 8px 24px rgba(0,0,0,.2);display:none;animation:slideIn .3s ease;}
@keyframes slideIn{from{transform:translateY(20px);opacity:0;}to{transform:translateY(0);opacity:1;}}
</style></head>
<body>

<div class="login-wrap" id="loginWrap">
  <div class="login-box">
    <h1>McGourmet</h1>
    <div class="sub">Panel de Administrador</div>
    <div class="field"><label>Usuario</label><input id="user" type="text" autocomplete="off" onkeydown="if(event.key==='Enter')login()"></div>
    <div class="field"><label>Clave</label><input id="pass" type="password" autocomplete="off" onkeydown="if(event.key==='Enter')login()"></div>
    <button class="btn" onclick="login()">Ingresar</button>
    <div class="error-msg" id="loginError">Usuario o clave incorrectos.</div>
  </div>
</div>

<div class="panel" id="panel">
  <div class="panel-header">
    <div><h1>Confirmar pagos</h1><div class="sub">Pedidos en estado Confirmado pendientes de pago</div></div>
    <button class="logout-btn" onclick="logout()">Salir</button>
  </div>
  <div class="toolbar">
    <div class="count-badge" id="countBadge">0 pedidos</div>
    <button class="refresh-btn" onclick="cargarPedidos()">Actualizar lista</button>
  </div>
  <div class="table-wrap" id="tableWrap"></div>
  <div class="action-bar">
    <div class="sel-count" id="selCount">0 seleccionados</div>
    <button class="confirm-btn" id="confirmBtn" onclick="confirmarPagos()" disabled>Marcar como Pagado</button>
  </div>
</div>

<div class="modal-overlay" id="modalOverlay">
  <div class="modal">
    <h2 id="modalTitle">Detalle del Remito</h2>
    <div class="modal-info" id="modalInfo"></div>
    <table><thead><tr><th>Producto</th><th>Cant.</th><th>Precio unit.</th><th>Subtotal</th></tr></thead><tbody id="modalItems"></tbody></table>
    <div class="modal-total" id="modalTotal"></div>
    <div class="modal-actions">
      <button class="modal-close" onclick="cerrarModal()">Cerrar</button>
      <button class="modal-pay" onclick="pagarDesdeModal()">Marcar como Pagado</button>
    </div>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
let pedidosActuales = [];
let modalIdPedido = null;

async function login(){
  const user = document.getElementById('user').value.trim();
  const pass = document.getElementById('pass').value.trim();
  try{
    const r = await fetch('/admin/login',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'include',body:JSON.stringify({user,pass})});
    const d = await r.json();
    if(d.ok){document.getElementById('loginWrap').style.display='none';document.getElementById('panel').style.display='block';cargarPedidos();}
    else document.getElementById('loginError').style.display='block';
  }catch(e){document.getElementById('loginError').style.display='block';}
}

function logout(){
  fetch('/admin/logout',{method:'POST',credentials:'include'});
  document.getElementById('panel').style.display='none';
  document.getElementById('loginWrap').style.display='flex';
  document.getElementById('user').value='';document.getElementById('pass').value='';
}

async function cargarPedidos(){
  try{
    const r=await fetch('/admin/pedidos',{credentials:'include'});
    if(r.status===401){logout();return;}
    const d=await r.json();pedidosActuales=d.pedidos||[];renderTabla();
  }catch(e){showToast('Error al cargar pedidos.');}
}

function renderTabla(){
  const wrap=document.getElementById('tableWrap');
  document.getElementById('countBadge').textContent=pedidosActuales.length+' pedido'+(pedidosActuales.length!==1?'s':'');
  if(pedidosActuales.length===0){wrap.innerHTML='<div class="empty-state"><div class="icon">📋</div>Sin pedidos confirmados pendientes de pago.</div>';actualizarSeleccion();return;}
  let html='<table><thead><tr><th class="chk-col"></th><th>Remito</th><th>Cliente</th><th>Telefono</th><th>Fecha</th><th>Total</th><th>Detalle</th></tr></thead><tbody>';
  for(const p of pedidosActuales){
    html+=`<tr><td class="chk-col"><input type="checkbox" value="${p.id_pedido}" onchange="actualizarSeleccion()"></td><td>#${p.id_pedido}</td><td>${p.nombre_cliente||''}</td><td>${p.telefono||''}</td><td>${p.fecha_pedido||''}</td><td>$ ${Number(p.total).toLocaleString('es-AR')}</td><td><button class="detail-btn" onclick="verDetalle(${p.id_pedido})">Ver detalle</button></td></tr>`;
  }
  html+='</tbody></table>';wrap.innerHTML=html;actualizarSeleccion();
}

function actualizarSeleccion(){
  const checks=document.querySelectorAll('#tableWrap input[type="checkbox"]:checked');
  document.getElementById('selCount').textContent=checks.length+' seleccionado'+(checks.length!==1?'s':'');
  document.getElementById('confirmBtn').disabled=checks.length===0;
}

async function verDetalle(id_pedido){
  modalIdPedido=id_pedido;
  try{
    const r=await fetch(`/admin/detalle/${id_pedido}`,{credentials:'include'});
    const d=await r.json();
    if(d.error){showToast('Error al cargar detalle.');return;}
    document.getElementById('modalTitle').textContent=`Remito #${d.id_pedido}`;
    document.getElementById('modalInfo').innerHTML=`
      <div class="item"><div class="label">Cliente</div><div class="value">${d.nombre_cliente}</div></div>
      <div class="item"><div class="label">Telefono</div><div class="value">${d.telefono}</div></div>
      <div class="item"><div class="label">Fecha</div><div class="value">${d.fecha_pedido}</div></div>
      <div class="item"><div class="label">Estado</div><div class="value">${d.estado}</div></div>
      ${d.notas?`<div class="item" style="grid-column:1/-1"><div class="label">Notas</div><div class="value">${d.notas}</div></div>`:''}
    `;
    let items_html='';
    for(const it of d.items){items_html+=`<tr><td>${it.nombre_producto}</td><td style="text-align:center">${it.cantidad}</td><td>$ ${Number(it.precio_unit).toLocaleString('es-AR')}</td><td>$ ${Number(it.subtotal).toLocaleString('es-AR')}</td></tr>`;}
    document.getElementById('modalItems').innerHTML=items_html;
    document.getElementById('modalTotal').textContent=`TOTAL: $ ${Number(d.total).toLocaleString('es-AR')}`;
    document.getElementById('modalOverlay').classList.add('active');
  }catch(e){showToast('Error al cargar detalle.');}
}

function cerrarModal(){document.getElementById('modalOverlay').classList.remove('active');modalIdPedido=null;}

async function pagarDesdeModal(){
  if(!modalIdPedido)return;
  const af=await marcarIds([modalIdPedido]);
  if(af>0){showToast(`Remito #${modalIdPedido} marcado como Pagado.`);cerrarModal();cargarPedidos();}
}

async function confirmarPagos(){
  const checks=document.querySelectorAll('#tableWrap input[type="checkbox"]:checked');
  const ids=Array.from(checks).map(c=>parseInt(c.value));
  if(ids.length===0)return;
  const af=await marcarIds(ids);
  if(af>0){showToast(`${af} pedido(s) marcado(s) como Pagado.`);cargarPedidos();}
}

async function marcarIds(ids){
  try{
    const r=await fetch('/admin/marcar-pagado',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'include',body:JSON.stringify({ids})});
    const d=await r.json();if(d.ok)return d.afectados;showToast('Error al actualizar.');return 0;
  }catch(e){showToast('Error de conexion.');return 0;}
}

function showToast(msg){const t=document.getElementById('toast');t.textContent=msg;t.style.display='block';setTimeout(()=>{t.style.display='none';},3500);}
document.addEventListener('click',e=>{if(e.target===document.getElementById('modalOverlay'))cerrarModal();});
</script>
</body></html>"""

@admin_app.route("/")
def index():
    return render_template_string(HTML_ADMIN)

@admin_app.route("/admin/login", methods=["POST"])
def login():
    data = request.get_json(force=True)
    if data.get("user","").strip() == ADMIN_USER and data.get("pass","").strip() == ADMIN_PASS:
        session["logged_in"] = True
        return jsonify({"ok": True})
    return jsonify({"ok": False}), 401

@admin_app.route("/admin/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})

@admin_app.route("/admin/pedidos")
def pedidos():
    if not session.get("logged_in"):
        return jsonify({"error": "no autorizado"}), 401
    return jsonify({"pedidos": get_pedidos_confirmados()})

@admin_app.route("/admin/detalle/<int:id_pedido>")
def detalle(id_pedido):
    if not session.get("logged_in"):
        return jsonify({"error": "no autorizado"}), 401
    ped = get_detalle_pedido(id_pedido)
    if not ped:
        return jsonify({"error": "Pedido no encontrado"}), 404
    return jsonify(ped)

@admin_app.route("/admin/marcar-pagado", methods=["POST"])
def marcar_pagado_route():
    if not session.get("logged_in"):
        return jsonify({"error": "no autorizado"}), 401
    ids = request.get_json(force=True).get("ids", [])
    if not ids:
        return jsonify({"ok": False, "afectados": 0})
    return jsonify({"ok": True, "afectados": marcar_pagados(ids)})

@admin_app.route("/admin/health")
def health():
    return jsonify({"status": "ok", "db": "postgresql" if USE_PG else "sqlite"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5002))
    admin_app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
