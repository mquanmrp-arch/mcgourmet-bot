"""
McGourmet Admin App v2
Panel de administracion para confirmar pagos de pedidos con detalle.
Flask + PostgreSQL
flujo completo: Confirmado → Pagado → Ingresado → Entregado
Version Oct-2026
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

def get_pedidos_por_estado(estado):
    try:
        conn = get_conn(); cur = get_cur(conn)
        ph = "%s" if USE_PG else "?"
        cur.execute(f"SELECT id_pedido, nombre_cliente, telefono, fecha_pedido, total FROM tbl_PedBot WHERE estado = {ph} ORDER BY fecha_pedido DESC", (estado,))
        rows = [dict(r) for r in cur.fetchall()]
        conn.close(); return rows
    except Exception as e:
        print(f"Error get_pedidos_por_estado: {e}"); return []

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

def cambiar_estado(ids_pedidos, nuevo_estado):
    try:
        conn = get_conn(); cur = conn.cursor()
        ph = "%s" if USE_PG else "?"
        placeholders = ",".join([ph] * len(ids_pedidos))
        cur.execute(f"UPDATE tbl_PedBot SET estado = {ph} WHERE id_pedido IN ({placeholders})", (nuevo_estado, *ids_pedidos))
        conn.commit(); afectados = cur.rowcount; conn.close(); return afectados
    except Exception as e:
        print(f"Error cambiar_estado: {e}"); return 0

admin_app = Flask(__name__)
admin_app.secret_key = SECRET_KEY
CORS(admin_app, supports_credentials=True)

HTML_ADMIN = """<!DOCTYPE html>
<html lang="es"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>McGourmet - Panel Administrador</title>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;900&family=Lato:wght@300;400;700&display=swap" rel="stylesheet">
<style>
:root{--brand:#5C3D2E;--brand-dk:#3E2723;--cream:#FDF6EC;--gold:#C9A84C;--olive:#6B7C45;--text:#2C1810;--muted:#8B7355;--border:#E8D5B7;--ok:#6B7C45;--azul:#2563EB;--violeta:#7C3AED;}
*{box-sizing:border-box;margin:0;padding:0;}
body{font-family:'Lato',sans-serif;background:var(--cream);min-height:100vh;}
/* LOGIN */
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
/* PANEL */
.panel{display:none;max-width:1060px;margin:0 auto;padding:24px 16px;}
.panel-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;padding-bottom:16px;border-bottom:2px solid var(--border);}
.panel-header h1{font-family:'Playfair Display',serif;color:var(--brand);font-size:26px;}
.panel-header .sub{color:var(--muted);font-size:13px;margin-top:2px;}
.logout-btn{background:transparent;border:1.5px solid var(--brand);color:var(--brand);padding:8px 16px;border-radius:8px;font-size:13px;cursor:pointer;font-weight:700;}
.logout-btn:hover{background:var(--brand);color:#fff;}
/* TABS */
.tabs{display:flex;gap:6px;margin-bottom:18px;border-bottom:2px solid var(--border);padding-bottom:0;}
.tab-btn{padding:9px 18px;font-size:13px;font-weight:700;color:var(--muted);background:none;border:none;border-bottom:3px solid transparent;cursor:pointer;transition:color .2s;margin-bottom:-2px;}
.tab-btn.active{color:var(--brand);border-bottom-color:var(--brand);}
.tab-btn .tbadge{background:var(--gold);color:var(--brand-dk);border-radius:10px;font-size:10.5px;padding:1px 7px;margin-left:5px;font-weight:700;}
.tab-btn.active .tbadge{background:var(--brand);color:#fff;}
/* SECCIÓN */
.tab-section{display:none;}
.tab-section.active{display:block;}
/* TOOLBAR */
.toolbar{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;}
.count-badge{background:var(--gold);color:var(--brand-dk);padding:5px 14px;border-radius:20px;font-size:12.5px;font-weight:700;}
.refresh-btn{background:transparent;border:1.5px solid var(--olive);color:var(--olive);padding:7px 14px;border-radius:8px;font-size:12.5px;cursor:pointer;font-weight:700;}
.refresh-btn:hover{background:var(--olive);color:#fff;}
/* TABLA */
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
/* BADGE ESTADO */
.estado-badge{display:inline-block;padding:3px 10px;border-radius:12px;font-size:11px;font-weight:700;}
.estado-Confirmado{background:#FEF9C3;color:#854D0E;}
.estado-Pagado{background:#DCFCE7;color:#166534;}
.estado-Ingresado{background:#DBEAFE;color:#1E40AF;}
.estado-Entregado{background:#EDE9FE;color:#5B21B6;}
/* BOTONES ACCIÓN */
.detail-btn{background:transparent;border:1.5px solid var(--brand);color:var(--brand);padding:5px 12px;border-radius:8px;font-size:12px;cursor:pointer;font-weight:700;white-space:nowrap;}
.detail-btn:hover{background:var(--brand);color:#fff;}
.action-bar{display:flex;justify-content:space-between;align-items:center;margin-top:18px;padding:14px 18px;background:#fff;border-radius:12px;border:1px solid var(--border);}
.action-bar .sel-count{font-size:13px;color:var(--muted);}
.action-btn{border:none;border-radius:10px;padding:11px 22px;font-size:13.5px;font-weight:700;cursor:pointer;transition:background .2s;color:#fff;}
.action-btn:disabled{background:var(--border)!important;cursor:not-allowed;}
.btn-pagar{background:var(--ok);}
.btn-pagar:hover:not(:disabled){background:#566338;}
.btn-ingresar{background:var(--azul);}
.btn-ingresar:hover:not(:disabled){background:#1D4ED8;}
.btn-entregar{background:var(--violeta);}
.btn-entregar:hover:not(:disabled){background:#6D28D9;}
/* MODAL */
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
.modal-actions{display:flex;gap:10px;justify-content:flex-end;flex-wrap:wrap;}
.modal-close{background:transparent;border:1.5px solid var(--border);color:var(--muted);padding:10px 20px;border-radius:10px;font-size:13px;cursor:pointer;font-weight:700;}
/* TOAST */
.toast{position:fixed;bottom:24px;right:24px;background:var(--brand);color:#fff;padding:14px 22px;border-radius:10px;font-size:13.5px;box-shadow:0 8px 24px rgba(0,0,0,.2);display:none;animation:slideIn .3s ease;}
@keyframes slideIn{from{transform:translateY(20px);opacity:0;}to{transform:translateY(0);opacity:1;}}
</style></head>
<body>

<!-- LOGIN -->
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

<!-- PANEL -->
<div class="panel" id="panel">
  <div class="panel-header">
    <div><h1>McGourmet Admin</h1><div class="sub">Gestión de pedidos</div></div>
    <button class="logout-btn" onclick="logout()">Salir</button>
  </div>

  <!-- TABS -->
  <div class="tabs">
    <button class="tab-btn active" onclick="mostrarTab('confirmado')" id="tab-confirmado">
      💳 Cobro <span class="tbadge" id="badge-confirmado">0</span>
    </button>
    <button class="tab-btn" onclick="mostrarTab('pagado')" id="tab-pagado">
      🍳 Cocina <span class="tbadge" id="badge-pagado">0</span>
    </button>
    <button class="tab-btn" onclick="mostrarTab('ingresado')" id="tab-ingresado">
      🚚 Entrega <span class="tbadge" id="badge-ingresado">0</span>
    </button>
    <button class="tab-btn" onclick="mostrarTab('entregado')" id="tab-entregado">
      ✅ Cerrados <span class="tbadge" id="badge-entregado">0</span>
    </button>
  </div>

  <!-- TAB: COBRO (Confirmado → Pagado) -->
  <div class="tab-section active" id="sec-confirmado">
    <div class="toolbar">
      <div class="count-badge" id="count-confirmado">0 pedidos</div>
      <button class="refresh-btn" onclick="cargarTodo()">Actualizar</button>
    </div>
    <div class="table-wrap" id="wrap-confirmado"></div>
    <div class="action-bar">
      <div class="sel-count" id="sel-confirmado">0 seleccionados</div>
      <button class="action-btn btn-pagar" id="btn-confirmado" onclick="cambiarEstadoSeleccionados('confirmado','Pagado')" disabled>💰 Marcar como Pagado</button>
    </div>
  </div>

  <!-- TAB: COCINA (Pagado → Ingresado) -->
  <div class="tab-section" id="sec-pagado">
    <div class="toolbar">
      <div class="count-badge" id="count-pagado">0 pedidos</div>
      <button class="refresh-btn" onclick="cargarTodo()">Actualizar</button>
    </div>
    <div class="table-wrap" id="wrap-pagado"></div>
    <div class="action-bar">
      <div class="sel-count" id="sel-pagado">0 seleccionados</div>
      <button class="action-btn btn-ingresar" id="btn-pagado" onclick="cambiarEstadoSeleccionados('pagado','Ingresado')" disabled>🍳 Ingresar a Cocina</button>
    </div>
  </div>

  <!-- TAB: ENTREGA (Ingresado → Entregado) -->
  <div class="tab-section" id="sec-ingresado">
    <div class="toolbar">
      <div class="count-badge" id="count-ingresado">0 pedidos</div>
      <button class="refresh-btn" onclick="cargarTodo()">Actualizar</button>
    </div>
    <div class="table-wrap" id="wrap-ingresado"></div>
    <div class="action-bar">
      <div class="sel-count" id="sel-ingresado">0 seleccionados</div>
      <button class="action-btn btn-entregar" id="btn-ingresado" onclick="cambiarEstadoSeleccionados('ingresado','Entregado')" disabled>🚚 Marcar como Entregado</button>
    </div>
  </div>

  <!-- TAB: CERRADOS (Entregado — solo lectura) -->
  <div class="tab-section" id="sec-entregado">
    <div class="toolbar">
      <div class="count-badge" id="count-entregado">0 pedidos</div>
      <button class="refresh-btn" onclick="cargarTodo()">Actualizar</button>
    </div>
    <div class="table-wrap" id="wrap-entregado"></div>
  </div>
</div>

<!-- MODAL DETALLE -->
<div class="modal-overlay" id="modalOverlay">
  <div class="modal">
    <h2 id="modalTitle">Detalle del Remito</h2>
    <div class="modal-info" id="modalInfo"></div>
    <table><thead><tr><th>Producto</th><th>Cant.</th><th>Precio unit.</th><th>Subtotal</th></tr></thead><tbody id="modalItems"></tbody></table>
    <div class="modal-total" id="modalTotal"></div>
    <div class="modal-actions" id="modalActions">
      <button class="modal-close" onclick="cerrarModal()">Cerrar</button>
    </div>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
// ── Config de cada tab ──────────────────────────────────────────
const TABS = {
  confirmado: { estado:'Confirmado', siguiente:'Pagado',   label:'💰 Marcar como Pagado',      color:'btn-pagar'    },
  pagado:     { estado:'Pagado',     siguiente:'Ingresado', label:'🍳 Ingresar a Cocina',       color:'btn-ingresar' },
  ingresado:  { estado:'Ingresado',  siguiente:'Entregado', label:'🚚 Marcar como Entregado',   color:'btn-entregar' },
  entregado:  { estado:'Entregado',  siguiente:null,        label:null,                          color:null           },
};

let datos = { confirmado:[], pagado:[], ingresado:[], entregado:[] };
let tabActiva = 'confirmado';
let modalIdPedido = null;
let modalEstado   = null;

// ── Login / Logout ──────────────────────────────────────────────
async function login(){
  const user = document.getElementById('user').value.trim();
  const pass = document.getElementById('pass').value.trim();
  try{
    const r = await fetch('/admin/login',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'include',body:JSON.stringify({user,pass})});
    const d = await r.json();
    if(d.ok){
      document.getElementById('loginWrap').style.display='none';
      document.getElementById('panel').style.display='block';
      cargarTodo();
    } else document.getElementById('loginError').style.display='block';
  }catch(e){document.getElementById('loginError').style.display='block';}
}

function logout(){
  fetch('/admin/logout',{method:'POST',credentials:'include'});
  document.getElementById('panel').style.display='none';
  document.getElementById('loginWrap').style.display='flex';
  document.getElementById('user').value=''; document.getElementById('pass').value='';
}

// ── Tabs ────────────────────────────────────────────────────────
function mostrarTab(tab){
  tabActiva = tab;
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-section').forEach(s => s.classList.remove('active'));
  document.getElementById('tab-'+tab).classList.add('active');
  document.getElementById('sec-'+tab).classList.add('active');
}

// ── Carga todos los estados ─────────────────────────────────────
async function cargarTodo(){
  try{
    const r = await fetch('/admin/pedidos-todos',{credentials:'include'});
    if(r.status===401){logout();return;}
    const d = await r.json();
    datos.confirmado = d.Confirmado || [];
    datos.pagado     = d.Pagado     || [];
    datos.ingresado  = d.Ingresado  || [];
    datos.entregado  = d.Entregado  || [];
    ['confirmado','pagado','ingresado','entregado'].forEach(t => renderTabla(t));
  }catch(e){showToast('Error al cargar pedidos.');}
}

// ── Render tabla de un tab ──────────────────────────────────────
function renderTabla(tab){
  const lista   = datos[tab];
  const cfg     = TABS[tab];
  const wrap    = document.getElementById('wrap-'+tab);
  const soloLec = !cfg.siguiente;

  // badge y contador
  document.getElementById('badge-'+tab).textContent = lista.length;
  const cntEl = document.getElementById('count-'+tab);
  if(cntEl) cntEl.textContent = lista.length+' pedido'+(lista.length!==1?'s':'');

  if(lista.length===0){
    wrap.innerHTML='<div class="empty-state"><div class="icon">📋</div>Sin pedidos en este estado.</div>';
    actualizarSeleccion(tab); return;
  }

  let html = '<table><thead><tr>'
    + (soloLec ? '' : '<th class="chk-col"></th>')
    + '<th>Remito</th><th>Cliente</th><th>Telefono</th><th>Fecha</th><th>Total</th><th>Estado</th><th>Detalle</th>'
    + '</tr></thead><tbody>';

  for(const p of lista){
    const badge = `<span class="estado-badge estado-${p.estado||cfg.estado}">${p.estado||cfg.estado}</span>`;
    html += `<tr>`
      + (soloLec ? '' : `<td class="chk-col"><input type="checkbox" value="${p.id_pedido}" onchange="actualizarSeleccion('${tab}')"></td>`)
      + `<td>#${p.id_pedido}</td><td>${p.nombre_cliente||''}</td><td>${p.telefono||''}</td>`
      + `<td>${(p.fecha_pedido||'').substring(0,16)}</td>`
      + `<td>$ ${Number(p.total).toLocaleString('es-AR')}</td>`
      + `<td>${badge}</td>`
      + `<td><button class="detail-btn" onclick="verDetalle(${p.id_pedido},'${cfg.estado}')">Ver detalle</button></td>`
      + `</tr>`;
  }
  html += '</tbody></table>';
  wrap.innerHTML = html;
  actualizarSeleccion(tab);
}

// ── Selección checkboxes ────────────────────────────────────────
function actualizarSeleccion(tab){
  if(!tab) tab = tabActiva;
  const checks = document.querySelectorAll(`#wrap-${tab} input[type="checkbox"]:checked`);
  const selEl  = document.getElementById('sel-'+tab);
  const btnEl  = document.getElementById('btn-'+tab);
  if(selEl) selEl.textContent = checks.length+' seleccionado'+(checks.length!==1?'s':'');
  if(btnEl) btnEl.disabled = checks.length===0;
}

// ── Cambiar estado de seleccionados ────────────────────────────
async function cambiarEstadoSeleccionados(tab, nuevoEstado){
  const checks = document.querySelectorAll(`#wrap-${tab} input[type="checkbox"]:checked`);
  const ids    = Array.from(checks).map(c => parseInt(c.value));
  if(!ids.length) return;
  const af = await postCambiarEstado(ids, nuevoEstado);
  if(af>0){ showToast(`${af} pedido(s) → ${nuevoEstado}.`); cargarTodo(); }
}

// ── Modal detalle ───────────────────────────────────────────────
async function verDetalle(id_pedido, estadoActual){
  modalIdPedido = id_pedido;
  modalEstado   = estadoActual;
  try{
    const r = await fetch(`/admin/detalle/${id_pedido}`,{credentials:'include'});
    const d = await r.json();
    if(d.error){showToast('Error al cargar detalle.');return;}
    document.getElementById('modalTitle').textContent = `Remito #${d.id_pedido}`;
    document.getElementById('modalInfo').innerHTML = `
      <div class="item"><div class="label">Cliente</div><div class="value">${d.nombre_cliente}</div></div>
      <div class="item"><div class="label">Telefono</div><div class="value">${d.telefono}</div></div>
      <div class="item"><div class="label">Fecha</div><div class="value">${(d.fecha_pedido||'').substring(0,16)}</div></div>
      <div class="item"><div class="label">Estado</div><div class="value"><span class="estado-badge estado-${d.estado}">${d.estado}</span></div></div>
      ${d.notas?`<div class="item" style="grid-column:1/-1"><div class="label">Notas</div><div class="value">${d.notas}</div></div>`:''}`;
    let ih='';
    for(const it of d.items) ih+=`<tr><td>${it.nombre_producto}</td><td style="text-align:center">${it.cantidad}</td><td>$ ${Number(it.precio_unit).toLocaleString('es-AR')}</td><td>$ ${Number(it.subtotal).toLocaleString('es-AR')}</td></tr>`;
    document.getElementById('modalItems').innerHTML = ih;
    document.getElementById('modalTotal').textContent = `TOTAL: $ ${Number(d.total).toLocaleString('es-AR')}`;

    // Botones de acción según el estado actual
    const cfg = Object.values(TABS).find(c => c.estado === estadoActual);
    let botonesHtml = '<button class="modal-close" onclick="cerrarModal()">Cerrar</button>';
    if(cfg && cfg.siguiente){
      botonesHtml += `<button class="action-btn ${cfg.color}" onclick="accionDesdeModal('${cfg.siguiente}')">${cfg.label}</button>`;
    }
    document.getElementById('modalActions').innerHTML = botonesHtml;
    document.getElementById('modalOverlay').classList.add('active');
  }catch(e){showToast('Error al cargar detalle.');}
}

function cerrarModal(){document.getElementById('modalOverlay').classList.remove('active');modalIdPedido=null;modalEstado=null;}

async function accionDesdeModal(nuevoEstado){
  if(!modalIdPedido) return;
  const af = await postCambiarEstado([modalIdPedido], nuevoEstado);
  if(af>0){ showToast(`Remito #${modalIdPedido} → ${nuevoEstado}.`); cerrarModal(); cargarTodo(); }
}

// ── API call cambiar estado ─────────────────────────────────────
async function postCambiarEstado(ids, nuevoEstado){
  try{
    const r = await fetch('/admin/cambiar-estado',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'include',body:JSON.stringify({ids, estado:nuevoEstado})});
    const d = await r.json();
    if(d.ok) return d.afectados;
    showToast('Error al actualizar.'); return 0;
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

@admin_app.route("/admin/pedidos-todos")
def pedidos_todos():
    if not session.get("logged_in"):
        return jsonify({"error": "no autorizado"}), 401
    return jsonify({
        "Confirmado": get_pedidos_por_estado("Confirmado"),
        "Pagado":     get_pedidos_por_estado("Pagado"),
        "Ingresado":  get_pedidos_por_estado("Ingresado"),
        "Entregado":  get_pedidos_por_estado("Entregado"),
    })

@admin_app.route("/admin/detalle/<int:id_pedido>")
def detalle(id_pedido):
    if not session.get("logged_in"):
        return jsonify({"error": "no autorizado"}), 401
    ped = get_detalle_pedido(id_pedido)
    if not ped:
        return jsonify({"error": "Pedido no encontrado"}), 404
    return jsonify(ped)

@admin_app.route("/admin/cambiar-estado", methods=["POST"])
def cambiar_estado_route():
    if not session.get("logged_in"):
        return jsonify({"error": "no autorizado"}), 401
    data   = request.get_json(force=True)
    ids    = data.get("ids", [])
    estado = data.get("estado", "")
    if not ids or estado not in ("Pagado", "Ingresado", "Entregado"):
        return jsonify({"ok": False, "afectados": 0})
    return jsonify({"ok": True, "afectados": cambiar_estado(ids, estado)})

@admin_app.route("/admin/health")
def health():
    return jsonify({"status": "ok", "db": "postgresql" if USE_PG else "sqlite"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5002))
    admin_app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
