#!/usr/bin/env python3
"""Servvoo Backend — PostgreSQL + SQLite fallback"""
import sqlite3, json, uuid, os, hashlib
from flask import Flask, request, jsonify, send_from_directory, Response
from datetime import datetime

try:
    import psycopg2, psycopg2.extras
    HAS_PG = True
except ImportError:
    HAS_PG = False

try:
    from flask_sock import Sock
    HAS_WS = True
except ImportError:
    HAS_WS = False

app = Flask(__name__, static_folder="static")
if HAS_WS:
    sock = Sock(app)

# In-memory store for live positions
# {tech_id: {lat, lng, heading, km, destName, tripType, timestamp}}
live_positions = {}
ws_clients = {}  # {tech_id: [ws_connections]}
DB = os.path.join(os.path.dirname(__file__), "servvoo.db")
DATABASE_URL = os.environ.get("DATABASE_URL","")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://","postgresql://",1)

def is_pg(): return bool(DATABASE_URL and HAS_PG)
def hash_pw(pw): return hashlib.sha256(pw.encode()).hexdigest()

def get_db():
    if is_pg():
        return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    c = sqlite3.connect(DB); c.row_factory=sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL"); return c

def ex(conn, sql, params=()):
    if is_pg(): sql=sql.replace("?","%s")
    cur=conn.cursor(); cur.execute(sql,params); return cur

def r2d(row):
    if row is None: return None
    return dict(row) if is_pg() else dict(zip(row.keys(),tuple(row)))

def rlist(rows): return [r2d(r) for r in (rows or [])]

def init_db():
    conn=get_db()
    if is_pg():
        cur=conn.cursor()
        tbls=[
            "CREATE TABLE IF NOT EXISTS companies (id TEXT PRIMARY KEY, name TEXT NOT NULL, slug TEXT UNIQUE NOT NULL, logo TEXT DEFAULT '', color TEXT DEFAULT '#0F6E56', plan TEXT DEFAULT 'basic', rubro TEXT DEFAULT 'general', rtn TEXT DEFAULT '', phone TEXT DEFAULT '', address TEXT DEFAULT '', active INTEGER DEFAULT 1, created_at TEXT DEFAULT current_timestamp)",
            "CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, role TEXT DEFAULT 'technician', color TEXT DEFAULT 'purple', phone TEXT DEFAULT '', status TEXT DEFAULT 'available', current_trip_id TEXT, rendimiento REAL DEFAULT 12, tipo_combustible TEXT DEFAULT 'gasolina', company_id TEXT DEFAULT 'diprodi', created_at TEXT DEFAULT current_timestamp)",
            "CREATE TABLE IF NOT EXISTS inventory (id TEXT PRIMARY KEY, name TEXT NOT NULL, model TEXT NOT NULL, serial TEXT DEFAULT '', category TEXT DEFAULT '', stock INTEGER DEFAULT 0, unit_cost REAL DEFAULT 0, created_at TEXT DEFAULT current_timestamp)",
            "CREATE TABLE IF NOT EXISTS clients (id TEXT PRIMARY KEY, name TEXT NOT NULL, contact TEXT DEFAULT '', phone TEXT DEFAULT '', email TEXT DEFAULT '', city TEXT DEFAULT '', department TEXT DEFAULT '', type TEXT DEFAULT 'Clínica', lat REAL, lng REAL, address TEXT DEFAULT '', rtn TEXT DEFAULT '', company_id TEXT DEFAULT 'diprodi', created_at TEXT DEFAULT current_timestamp)",
            "CREATE TABLE IF NOT EXISTS trips (id TEXT PRIMARY KEY, technician_id TEXT NOT NULL, client_id TEXT NOT NULL, date TEXT NOT NULL, status TEXT DEFAULT 'pendiente', trip_type TEXT DEFAULT 'entrega', equipment_ids TEXT DEFAULT '[]', origin_lat REAL, origin_lng REAL, origin_label TEXT, destination_lat REAL, destination_lng REAL, destination_label TEXT, stops TEXT DEFAULT '[]', route_points TEXT DEFAULT '[]', start_time TEXT DEFAULT '', end_time TEXT DEFAULT '', km REAL DEFAULT 0, reimbursement REAL DEFAULT 0, notes TEXT DEFAULT '', report_id TEXT, report_num TEXT, company_id TEXT DEFAULT 'diprodi', created_at TEXT DEFAULT current_timestamp)",
            "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS visit_reports (id TEXT PRIMARY KEY, trip_id TEXT, technician_id TEXT, client_id TEXT, report_num TEXT, fecha TEXT, hora_llegada TEXT DEFAULT '', hora_salida TEXT DEFAULT '', marca TEXT DEFAULT '', modelo TEXT DEFAULT '', serie TEXT DEFAULT '', condicion TEXT DEFAULT '', reparaciones TEXT DEFAULT '', repuestos TEXT DEFAULT '', calibracion INTEGER, control_calidad INTEGER, signed INTEGER DEFAULT 0, sig_time TEXT DEFAULT '', sig_data TEXT DEFAULT '', created_at TEXT DEFAULT current_timestamp)",
            "CREATE TABLE IF NOT EXISTS diprodi_equipos (id TEXT PRIMARY KEY, num INTEGER, localizacion TEXT DEFAULT '', cliente TEXT DEFAULT '', tipo TEXT DEFAULT '', modelo TEXT DEFAULT '', serie TEXT DEFAULT '', fecha_ingreso TEXT DEFAULT '', fecha_instalacion TEXT DEFAULT '', version_sw TEXT DEFAULT '', comentarios TEXT DEFAULT '', estado TEXT DEFAULT 'instalado', modalidad TEXT DEFAULT 'leasing', contrato_inicio TEXT, contrato_meses INTEGER, contrato_valor REAL, cuota_mensual REAL, prima REAL, interes REAL, categoria TEXT DEFAULT 'equipo', created_at TEXT DEFAULT current_timestamp)",
            "CREATE TABLE IF NOT EXISTS diprodi_accesorios (id TEXT PRIMARY KEY, tipo TEXT DEFAULT '', modelo TEXT DEFAULT '', serie TEXT DEFAULT '', cantidad INTEGER DEFAULT 1, cliente TEXT DEFAULT '', localizacion TEXT DEFAULT '', estado TEXT DEFAULT 'disponible', categoria TEXT DEFAULT 'accesorio', created_at TEXT DEFAULT current_timestamp)",
            "CREATE TABLE IF NOT EXISTS diprodi_repuestos (id TEXT PRIMARY KEY, num INTEGER, localizacion TEXT DEFAULT '', cliente TEXT DEFAULT '', equipo TEXT DEFAULT '', modelo TEXT DEFAULT '', num_parte TEXT DEFAULT '', nombre TEXT DEFAULT '', cantidad INTEGER DEFAULT 0, fecha_ingreso TEXT DEFAULT '', categoria TEXT DEFAULT 'repuesto', created_at TEXT DEFAULT current_timestamp)",
            "CREATE TABLE IF NOT EXISTS sales_goals (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, mes TEXT NOT NULL, meta REAL DEFAULT 0, created_at TEXT DEFAULT current_timestamp)",
            "CREATE TABLE IF NOT EXISTS sales_records (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, mes TEXT NOT NULL, monto REAL DEFAULT 0, descripcion TEXT DEFAULT '', cliente TEXT DEFAULT '', fecha TEXT DEFAULT '', created_at TEXT DEFAULT current_timestamp)",
            "CREATE TABLE IF NOT EXISTS odometer_records (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, mes TEXT NOT NULL, km_inicio REAL DEFAULT 0, km_fin REAL DEFAULT 0, factura_monto REAL DEFAULT 0, km_laborales REAL DEFAULT 0, reembolso REAL DEFAULT 0, created_at TEXT DEFAULT current_timestamp)",
            "CREATE TABLE IF NOT EXISTS bookings (id TEXT PRIMARY KEY, client_name TEXT DEFAULT '', client_phone TEXT DEFAULT '', client_email TEXT DEFAULT '', equipo TEXT DEFAULT '', tipo_servicio TEXT DEFAULT 'mantenimiento', modalidad TEXT DEFAULT 'presencial', date TEXT NOT NULL, time TEXT NOT NULL, status TEXT DEFAULT 'pendiente', notas TEXT DEFAULT '', technician_id TEXT DEFAULT '', accepted_at TEXT DEFAULT '', completed_at TEXT DEFAULT '', video_link TEXT DEFAULT '', created_at TEXT DEFAULT current_timestamp)",
            "CREATE TABLE IF NOT EXISTS invoices (id TEXT PRIMARY KEY, invoice_num TEXT NOT NULL, client_id TEXT, client_name TEXT DEFAULT '', client_rtn TEXT DEFAULT '', client_address TEXT DEFAULT '', items TEXT DEFAULT '[]', subtotal REAL DEFAULT 0, isv_rate REAL DEFAULT 15, isv REAL DEFAULT 0, total REAL DEFAULT 0, status TEXT DEFAULT 'pendiente', payment_method TEXT DEFAULT 'efectivo', cai TEXT DEFAULT '', notes TEXT DEFAULT '', technician_id TEXT DEFAULT '', trip_id TEXT DEFAULT '', company_id TEXT DEFAULT 'diprodi', created_at TEXT DEFAULT current_timestamp)",
            "CREATE TABLE IF NOT EXISTS invoice_sequence (id TEXT PRIMARY KEY, year INTEGER, month INTEGER, last_num INTEGER DEFAULT 0)",
            "CREATE TABLE IF NOT EXISTS calendar_events (id TEXT PRIMARY KEY, company_id TEXT DEFAULT 'diprodi', title TEXT DEFAULT '', date TEXT NOT NULL, time TEXT DEFAULT '', color TEXT DEFAULT '#EF9F27', all_day INTEGER DEFAULT 0, notes TEXT DEFAULT '', blocks_booking INTEGER DEFAULT 0, created_at TEXT DEFAULT current_timestamp)",
        ]
        for t in tbls:
            try: cur.execute(t)
            except: pass
        for k,v in [('rate_per_km','5.0'),('maps_api_key',''),('company_name','DIPRODI'),('fuel_gas_price','95.0'),('fuel_diesel_price','85.0')]:
            try: cur.execute("INSERT INTO settings(key,value) VALUES(%s,%s) ON CONFLICT(key) DO NOTHING",(k,v))
            except: pass
        cur.execute("SELECT COUNT(*) as c FROM users")
        count=cur.fetchone()["c"]
    else:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,name TEXT NOT NULL,email TEXT UNIQUE NOT NULL,password_hash TEXT NOT NULL,role TEXT DEFAULT 'technician',color TEXT DEFAULT 'purple',phone TEXT DEFAULT '',status TEXT DEFAULT 'available',current_trip_id TEXT,rendimiento REAL DEFAULT 12,tipo_combustible TEXT DEFAULT 'gasolina',created_at TEXT DEFAULT(datetime('now')));
        CREATE TABLE IF NOT EXISTS inventory(id TEXT PRIMARY KEY,name TEXT NOT NULL,model TEXT NOT NULL,serial TEXT DEFAULT '',category TEXT DEFAULT '',stock INTEGER DEFAULT 0,unit_cost REAL DEFAULT 0,created_at TEXT DEFAULT(datetime('now')));
        CREATE TABLE IF NOT EXISTS clients(id TEXT PRIMARY KEY,name TEXT NOT NULL,contact TEXT DEFAULT '',phone TEXT DEFAULT '',email TEXT DEFAULT '',city TEXT DEFAULT '',department TEXT DEFAULT '',type TEXT DEFAULT 'Clínica',lat REAL,lng REAL,address TEXT DEFAULT '',rtn TEXT DEFAULT '',created_at TEXT DEFAULT(datetime('now')));
        CREATE TABLE IF NOT EXISTS trips(id TEXT PRIMARY KEY,technician_id TEXT NOT NULL,client_id TEXT NOT NULL,date TEXT NOT NULL,status TEXT DEFAULT 'pendiente',trip_type TEXT DEFAULT 'entrega',equipment_ids TEXT DEFAULT '[]',origin_lat REAL,origin_lng REAL,origin_label TEXT,destination_lat REAL,destination_lng REAL,destination_label TEXT,stops TEXT DEFAULT '[]',route_points TEXT DEFAULT '[]',start_time TEXT DEFAULT '',end_time TEXT DEFAULT '',km REAL DEFAULT 0,reimbursement REAL DEFAULT 0,notes TEXT DEFAULT '',report_id TEXT,report_num TEXT,created_at TEXT DEFAULT(datetime('now')));
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS visit_reports(id TEXT PRIMARY KEY,trip_id TEXT,technician_id TEXT,client_id TEXT,report_num TEXT,fecha TEXT,hora_llegada TEXT DEFAULT '',hora_salida TEXT DEFAULT '',marca TEXT DEFAULT '',modelo TEXT DEFAULT '',serie TEXT DEFAULT '',condicion TEXT DEFAULT '',reparaciones TEXT DEFAULT '',repuestos TEXT DEFAULT '',calibracion INTEGER,control_calidad INTEGER,signed INTEGER DEFAULT 0,sig_time TEXT DEFAULT '',sig_data TEXT DEFAULT '',created_at TEXT DEFAULT(datetime('now')));
        CREATE TABLE IF NOT EXISTS diprodi_equipos(id TEXT PRIMARY KEY,num INTEGER,localizacion TEXT DEFAULT '',cliente TEXT DEFAULT '',tipo TEXT DEFAULT '',modelo TEXT DEFAULT '',serie TEXT DEFAULT '',fecha_ingreso TEXT DEFAULT '',fecha_instalacion TEXT DEFAULT '',version_sw TEXT DEFAULT '',comentarios TEXT DEFAULT '',estado TEXT DEFAULT 'instalado',modalidad TEXT DEFAULT 'leasing',contrato_inicio TEXT,contrato_meses INTEGER,contrato_valor REAL,cuota_mensual REAL,prima REAL,interes REAL,categoria TEXT DEFAULT 'equipo',created_at TEXT DEFAULT(datetime('now')));
        CREATE TABLE IF NOT EXISTS diprodi_accesorios(id TEXT PRIMARY KEY,tipo TEXT DEFAULT '',modelo TEXT DEFAULT '',serie TEXT DEFAULT '',cantidad INTEGER DEFAULT 1,cliente TEXT DEFAULT '',localizacion TEXT DEFAULT '',estado TEXT DEFAULT 'disponible',categoria TEXT DEFAULT 'accesorio',created_at TEXT DEFAULT(datetime('now')));
        CREATE TABLE IF NOT EXISTS diprodi_repuestos(id TEXT PRIMARY KEY,num INTEGER,localizacion TEXT DEFAULT '',cliente TEXT DEFAULT '',equipo TEXT DEFAULT '',modelo TEXT DEFAULT '',num_parte TEXT DEFAULT '',nombre TEXT DEFAULT '',cantidad INTEGER DEFAULT 0,fecha_ingreso TEXT DEFAULT '',categoria TEXT DEFAULT 'repuesto',created_at TEXT DEFAULT(datetime('now')));
        CREATE TABLE IF NOT EXISTS sales_goals(id TEXT PRIMARY KEY,user_id TEXT NOT NULL,mes TEXT NOT NULL,meta REAL DEFAULT 0,created_at TEXT DEFAULT(datetime('now')));
        CREATE TABLE IF NOT EXISTS sales_records(id TEXT PRIMARY KEY,user_id TEXT NOT NULL,mes TEXT NOT NULL,monto REAL DEFAULT 0,descripcion TEXT DEFAULT '',cliente TEXT DEFAULT '',fecha TEXT DEFAULT '',created_at TEXT DEFAULT(datetime('now')));
        CREATE TABLE IF NOT EXISTS odometer_records(id TEXT PRIMARY KEY,user_id TEXT NOT NULL,mes TEXT NOT NULL,km_inicio REAL DEFAULT 0,km_fin REAL DEFAULT 0,factura_monto REAL DEFAULT 0,km_laborales REAL DEFAULT 0,reembolso REAL DEFAULT 0,created_at TEXT DEFAULT(datetime('now')));
        CREATE TABLE IF NOT EXISTS bookings(id TEXT PRIMARY KEY,client_name TEXT DEFAULT '',client_phone TEXT DEFAULT '',client_email TEXT DEFAULT '',equipo TEXT DEFAULT '',tipo_servicio TEXT DEFAULT 'mantenimiento',modalidad TEXT DEFAULT 'presencial',date TEXT NOT NULL,time TEXT NOT NULL,status TEXT DEFAULT 'pendiente',notas TEXT DEFAULT '',technician_id TEXT DEFAULT '',accepted_at TEXT DEFAULT '',completed_at TEXT DEFAULT '',video_link TEXT DEFAULT '',created_at TEXT DEFAULT(datetime('now')));
        CREATE TABLE IF NOT EXISTS calendar_events(id TEXT PRIMARY KEY,company_id TEXT DEFAULT 'diprodi',title TEXT DEFAULT '',date TEXT NOT NULL,time TEXT DEFAULT '',color TEXT DEFAULT '#EF9F27',all_day INTEGER DEFAULT 0,notes TEXT DEFAULT '',blocks_booking INTEGER DEFAULT 0,created_at TEXT DEFAULT(datetime('now')));
        CREATE TABLE IF NOT EXISTS invoices(id TEXT PRIMARY KEY,invoice_num TEXT NOT NULL,client_id TEXT,client_name TEXT DEFAULT '',client_rtn TEXT DEFAULT '',client_address TEXT DEFAULT '',items TEXT DEFAULT '[]',subtotal REAL DEFAULT 0,isv_rate REAL DEFAULT 15,isv REAL DEFAULT 0,total REAL DEFAULT 0,status TEXT DEFAULT 'pendiente',payment_method TEXT DEFAULT 'efectivo',cai TEXT DEFAULT '',notes TEXT DEFAULT '',technician_id TEXT DEFAULT '',trip_id TEXT DEFAULT '',created_at TEXT DEFAULT(datetime('now')));
        CREATE TABLE IF NOT EXISTS invoice_sequence(id TEXT PRIMARY KEY,year INTEGER,month INTEGER,last_num INTEGER DEFAULT 0);
        """)
        for k,v in [('rate_per_km','5.0'),('maps_api_key',''),('company_name','DIPRODI'),('fuel_gas_price','95.0'),('fuel_diesel_price','85.0')]:
            conn.execute("INSERT OR IGNORE INTO settings VALUES(?,?)",(k,v))
        count=conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if count==0:
        aid="admin_"+uuid.uuid4().hex[:8]
        ex(conn,"INSERT INTO users(id,name,email,password_hash,role,color,phone,status) VALUES(?,?,?,?,?,?,?,?)",
           (aid,"Administrador","admin@diprodi.hn",hash_pw("admin123"),"admin","blue","","available"))
    conn.commit(); conn.close()
    print(f"DB ready — {'PostgreSQL' if is_pg() else 'SQLite'}", flush=True)

def mu(d):
    d["currentTripId"]=d.pop("current_trip_id",None)
    d["createdAt"]=d.pop("created_at",None)
    d.pop("password_hash",None)
    if "tipo_combustible" in d: d["tipoCombustible"]=d.pop("tipo_combustible")
    return d

def mt(d):
    d["technicianId"]=d.pop("technician_id")
    d["clientId"]=d.pop("client_id")
    d["tripType"]=d.pop("trip_type")
    d["equipmentIds"]=json.loads(d.pop("equipment_ids","[]"))
    d["origin"]={"lat":d.pop("origin_lat"),"lng":d.pop("origin_lng"),"label":d.pop("origin_label","")}
    d["destination"]={"lat":d.pop("destination_lat"),"lng":d.pop("destination_lng"),"label":d.pop("destination_label","")}
    d["routePoints"]=json.loads(d.pop("route_points","[]"))
    d["startTime"]=d.pop("start_time","")
    d["endTime"]=d.pop("end_time","")
    d["stops"]=json.loads(d.pop("stops","[]"))
    d["createdAt"]=d.pop("created_at",None)
    d["reimbursement"]=float(d.get("reimbursement",0))
    d["km"]=float(d.get("km",0))
    d["reportId"]=d.pop("report_id",None)
    d["reportNum"]=d.pop("report_num",None)
    return d

def mrep(d):
    d["technicianId"]=d.pop("technician_id","")
    d["clientId"]=d.pop("client_id","")
    d["tripId"]=d.pop("trip_id","")
    d["reportNum"]=d.pop("report_num","")
    d["horaLlegada"]=d.pop("hora_llegada","")
    d["horaSalida"]=d.pop("hora_salida","")
    d["controlCalidad"]=d.pop("control_calidad",None)
    d["sigTime"]=d.pop("sig_time","")
    d["sigData"]=d.pop("sig_data","")
    d["createdAt"]=d.pop("created_at",None)
    return d

# ─── AUTH ─────────────────────────────────────────────────────────────────────
@app.route("/api/login",methods=["POST"])
def login():
    d=request.get_json()
    conn=get_db()
    cur=ex(conn,"SELECT * FROM users WHERE email=?",(d.get("email","").lower(),))
    row=r2d(cur.fetchone()); conn.close()
    if not row or row["password_hash"]!=hash_pw(d.get("password","")): return jsonify({"error":"Credenciales incorrectas"}),401
    return jsonify(mu(row))

@app.route("/api/register",methods=["POST"])
def register():
    d=request.get_json()
    uid_=str(uuid.uuid4())[:8]
    conn=get_db()
    try:
        ex(conn,"INSERT INTO users(id,name,email,password_hash,role,color,phone,status,rendimiento,tipo_combustible) VALUES(?,?,?,?,?,?,?,?,?,?)",
           ("u"+uid_,d["name"],d["email"].lower(),hash_pw(d.get("password","user123")),d.get("role","technician"),d.get("color","purple"),d.get("phone",""),"available",float(d.get("rendimiento",12)),d.get("tipoCombustible","gasolina")))
        conn.commit()
        cur=ex(conn,"SELECT * FROM users WHERE email=?",(d["email"].lower(),))
        row=mu(r2d(cur.fetchone())); conn.close()
        return jsonify(row)
    except Exception as e: conn.close(); return jsonify({"error":str(e)}),400

# ─── USERS ────────────────────────────────────────────────────────────────────
@app.route("/api/users")
def get_users():
    conn=get_db()
    cur=ex(conn,"SELECT * FROM users ORDER BY name")
    rows=[mu(r) for r in rlist(cur.fetchall())]; conn.close()
    return jsonify(rows)

@app.route("/api/users",methods=["POST"])
def add_user():
    d=request.get_json()
    tid="u"+uuid.uuid4().hex[:10]
    conn=get_db()
    try:
        ex(conn,"INSERT INTO users(id,name,email,password_hash,role,color,phone,status,rendimiento,tipo_combustible) VALUES(?,?,?,?,?,?,?,?,?,?)",
           (tid,d["name"],d.get("email","").lower(),hash_pw(d.get("password","tech123")),d.get("role","technician"),d.get("color","purple"),d.get("phone",""),"available",float(d.get("rendimiento",12)),d.get("tipoCombustible","gasolina")))
        conn.commit()
        cur=ex(conn,"SELECT * FROM users WHERE id=?",(tid,))
        row=mu(r2d(cur.fetchone())); conn.close()
        return jsonify(row)
    except Exception as e: conn.close(); return jsonify({"error":str(e)}),400

@app.route("/api/users/<uid>",methods=["PATCH"])
def update_user(uid):
    d=request.get_json()
    conn=get_db(); fields,vals=[],[]
    for k,col in [("name","name"),("phone","phone"),("status","status"),("color","color"),("rendimiento","rendimiento"),("tipoCombustible","tipo_combustible"),("currentTripId","current_trip_id")]:
        if k in d: fields.append(f"{col}=?"); vals.append(d[k])
    if fields:
        vals.append(uid); ex(conn,f"UPDATE users SET {','.join(fields)} WHERE id=?",vals); conn.commit()
    cur=ex(conn,"SELECT * FROM users WHERE id=?",(uid,))
    row=mu(r2d(cur.fetchone())); conn.close(); return jsonify(row)

@app.route("/api/users/<uid>",methods=["DELETE"])
def delete_user(uid):
    conn=get_db(); ex(conn,"DELETE FROM users WHERE id=?",(uid,)); conn.commit(); conn.close()
    return jsonify({"ok":True})

# ─── INVENTORY ────────────────────────────────────────────────────────────────
@app.route("/api/inventory")
def get_inventory():
    conn=get_db()
    cur=ex(conn,"SELECT * FROM inventory ORDER BY name")
    rows=rlist(cur.fetchall()); conn.close()
    return jsonify([{**r,"unitCost":r.pop("unit_cost",0),"createdAt":r.pop("created_at",None)} for r in rows])

@app.route("/api/inventory",methods=["POST"])
def add_inventory():
    d=request.get_json(); iid="eq_"+uuid.uuid4().hex[:10]
    conn=get_db()
    ex(conn,"INSERT INTO inventory(id,name,model,serial,category,stock,unit_cost) VALUES(?,?,?,?,?,?,?)",
       (iid,d["name"],d.get("model",""),d.get("serial",""),d.get("category",""),int(d.get("stock",0)),float(d.get("unitCost",0))))
    conn.commit()
    cur=ex(conn,"SELECT * FROM inventory WHERE id=?",(iid,))
    r=r2d(cur.fetchone()); conn.close()
    return jsonify({**r,"unitCost":r.pop("unit_cost",0),"createdAt":r.pop("created_at",None)})

@app.route("/api/inventory/<iid>",methods=["PATCH"])
def update_inventory(iid):
    d=request.get_json(); conn=get_db(); fields,vals=[],[]
    for k,col in [("name","name"),("model","model"),("serial","serial"),("category","category"),("stock","stock"),("unitCost","unit_cost")]:
        if k in d: fields.append(f"{col}=?"); vals.append(d[k])
    if fields:
        vals.append(iid); ex(conn,f"UPDATE inventory SET {','.join(fields)} WHERE id=?",vals); conn.commit()
    cur=ex(conn,"SELECT * FROM inventory WHERE id=?",(iid,))
    r=r2d(cur.fetchone()); conn.close()
    return jsonify({**r,"unitCost":r.pop("unit_cost",0),"createdAt":r.pop("created_at",None)})

@app.route("/api/inventory/<iid>",methods=["DELETE"])
def delete_inventory(iid):
    conn=get_db(); ex(conn,"DELETE FROM inventory WHERE id=?",(iid,)); conn.commit(); conn.close()
    return jsonify({"ok":True})

# ─── CLIENTS ──────────────────────────────────────────────────────────────────
@app.route("/api/clients")
def get_clients():
    conn=get_db()
    cur=ex(conn,"SELECT * FROM clients ORDER BY name")
    rows=rlist(cur.fetchall()); conn.close()
    return jsonify([{**r,"createdAt":r.pop("created_at",None)} for r in rows])

@app.route("/api/clients",methods=["POST"])
def add_client():
    d=request.get_json(); cid="c_"+uuid.uuid4().hex[:10]
    conn=get_db()
    ex(conn,"INSERT INTO clients(id,name,contact,phone,email,city,department,type,lat,lng,address) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
       (cid,d["name"],d.get("contact",""),d.get("phone",""),d.get("email",""),d.get("city",""),d.get("department",""),d.get("type","Clínica"),d.get("lat"),d.get("lng"),d.get("address","")))
    conn.commit()
    cur=ex(conn,"SELECT * FROM clients WHERE id=?",(cid,))
    r=r2d(cur.fetchone()); conn.close()
    return jsonify({**r,"createdAt":r.pop("created_at",None)})

@app.route("/api/clients/<cid>",methods=["PATCH"])
def update_client(cid):
    d=request.get_json(); conn=get_db(); fields,vals=[],[]
    for k,col in [("name","name"),("contact","contact"),("phone","phone"),("email","email"),
                  ("city","city"),("department","department"),("type","type"),
                  ("address","address"),("lat","lat"),("lng","lng"),("rtn","rtn")]:
        if k in d: fields.append(f"{col}=?"); vals.append(d[k])
    if fields:
        vals.append(cid); ex(conn,f"UPDATE clients SET {','.join(fields)} WHERE id=?",vals); conn.commit()
    cur=ex(conn,"SELECT * FROM clients WHERE id=?",(cid,))
    r=r2d(cur.fetchone()); conn.close()
    return jsonify({**r,"createdAt":r.pop("created_at",None)})

@app.route("/api/clients/<cid>",methods=["DELETE"])
def delete_client(cid):
    conn=get_db(); ex(conn,"DELETE FROM clients WHERE id=?",(cid,)); conn.commit(); conn.close()
    return jsonify({"ok":True})

# ─── TRIPS ────────────────────────────────────────────────────────────────────
@app.route("/api/trips")
def get_trips():
    conn=get_db()
    cur=ex(conn,"SELECT * FROM trips ORDER BY created_at DESC")
    rows=[mt(r) for r in rlist(cur.fetchall())]; conn.close()
    return jsonify(rows)

@app.route("/api/trips",methods=["POST"])
def add_trip():
    d=request.get_json(); tid="trip_"+uuid.uuid4().hex[:10]
    o=d.get("origin",{}); dest=d.get("destination",{})
    conn=get_db()
    km = float(d.get("km",0))
    # Get technician vehicle data for fuel calculation
    cur_tech = ex(conn, "SELECT rendimiento, tipo_combustible FROM users WHERE id=?", (d["technicianId"],))
    tech_data = r2d(cur_tech.fetchone()) or {}
    rendimiento = float(tech_data.get("rendimiento") or 12)
    tipo_comb = tech_data.get("tipo_combustible") or "gasolina"
    # Get fuel price from settings
    cur_set = ex(conn, "SELECT value FROM settings WHERE key=?", (f"fuel_{tipo_comb}_price",))
    price_row = r2d(cur_set.fetchone())
    fuel_price = float(price_row["value"]) if price_row else 95.0
    # Calculate: km / rendimiento * price_per_liter
    litros = km / rendimiento if rendimiento > 0 else 0
    reimbursement = round(litros * fuel_price, 2)
    
    ex(conn,"INSERT INTO trips(id,technician_id,client_id,date,trip_type,equipment_ids,origin_lat,origin_lng,origin_label,destination_lat,destination_lng,destination_label,stops,route_points,start_time,end_time,km,reimbursement,notes) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
       (tid,d["technicianId"],d["clientId"],d["date"],d.get("tripType","entrega"),json.dumps(d.get("equipmentIds",[])),o.get("lat"),o.get("lng"),o.get("label",""),dest.get("lat"),dest.get("lng"),dest.get("label",""),json.dumps(d.get("stops",[])),json.dumps(d.get("routePoints",[])),d.get("startTime",""),d.get("endTime",""),km,reimbursement,d.get("notes","")))
    
    # Auto-link most recent report from this technician today that is NOT yet linked to a trip
    today = datetime.now().strftime("%Y-%m-%d")
    cur_rep = ex(conn, "SELECT id, report_num FROM visit_reports WHERE technician_id=? AND fecha LIKE ? AND (trip_id IS NULL OR trip_id='') ORDER BY created_at DESC LIMIT 1", (d["technicianId"], f"%{today}%"))
    rep_row = r2d(cur_rep.fetchone())
    if rep_row:
        ex(conn, "UPDATE trips SET report_id=?, report_num=? WHERE id=?", (rep_row["id"], rep_row["report_num"], tid))
        ex(conn, "UPDATE visit_reports SET trip_id=? WHERE id=?", (tid, rep_row["id"]))
    
    ex(conn,"UPDATE users SET status='available',current_trip_id=NULL WHERE id=?",(d["technicianId"],))
    conn.commit()
    cur=ex(conn,"SELECT * FROM trips WHERE id=?",(tid,))
    row=mt(r2d(cur.fetchone())); conn.close()
    return jsonify(row)

@app.route("/api/trips/<tid>",methods=["PATCH"])
def update_trip(tid):
    d=request.get_json(); conn=get_db(); fields,vals=[],[]
    for k,col in [("status","status"),("km","km"),("reimbursement","reimbursement"),("notes","notes"),("endTime","end_time"),("reportId","report_id"),("reportNum","report_num")]:
        if k in d: fields.append(f"{col}=?"); vals.append(d[k])
    if fields:
        vals.append(tid); ex(conn,f"UPDATE trips SET {','.join(fields)} WHERE id=?",vals); conn.commit()
    cur=ex(conn,"SELECT * FROM trips WHERE id=?",(tid,))
    row=mt(r2d(cur.fetchone())); conn.close()
    return jsonify(row)

# ─── SETTINGS ─────────────────────────────────────────────────────────────────
@app.route("/api/settings")
def get_settings():
    conn=get_db()
    cur=ex(conn,"SELECT * FROM settings")
    rows=rlist(cur.fetchall()); conn.close()
    return jsonify({r["key"]:r["value"] for r in rows})

@app.route("/api/settings",methods=["POST"])
def save_settings():
    d=request.get_json(); conn=get_db()
    for k,v in d.items():
        if is_pg(): ex(conn,"INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=?",(k,str(v),str(v)))
        else: ex(conn,"INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)",(k,str(v)))
    conn.commit(); conn.close()
    return jsonify({"ok":True})

# ─── REPORTS ──────────────────────────────────────────────────────────────────
@app.route("/api/reports")
def get_reports():
    tech_id=request.args.get("technicianId")
    conn=get_db()
    if tech_id: cur=ex(conn,"SELECT * FROM visit_reports WHERE technician_id=? ORDER BY created_at DESC",(tech_id,))
    else: cur=ex(conn,"SELECT * FROM visit_reports ORDER BY created_at DESC")
    rows=[mrep(r) for r in rlist(cur.fetchall())]; conn.close()
    return jsonify(rows)

@app.route("/api/reports",methods=["POST"])
def save_report():
    d=request.get_json(); rid="rep_"+uuid.uuid4().hex[:12]
    now=datetime.now(); year=now.strftime("%Y"); month=now.strftime("%m")
    conn=get_db()
    cur=ex(conn,"SELECT COUNT(*) as c FROM visit_reports WHERE report_num LIKE ?",(f"SV-{year}{month}-%",))
    row=r2d(cur.fetchone()); count=int(row.get("c") or row.get("count") or 0)
    rnum=f"SV-{year}{month}-{str(count+1).zfill(3)}"
    cal=1 if d.get("calibracion")==True else (0 if d.get("calibracion")==False else None)
    cc=1 if d.get("controlCalidad")==True else (0 if d.get("controlCalidad")==False else None)
    tech_id = d.get("technicianId","")
    # Find latest trip from this technician that doesn't have a report yet
    cur2 = ex(conn, "SELECT id FROM trips WHERE technician_id=? AND (report_id IS NULL OR report_id='') ORDER BY created_at DESC LIMIT 1", (tech_id,))
    latest_trip = r2d(cur2.fetchone())
    auto_trip_id = latest_trip["id"] if latest_trip else d.get("tripId","")
    
    ex(conn,"INSERT INTO visit_reports(id,trip_id,technician_id,client_id,report_num,fecha,hora_llegada,hora_salida,marca,modelo,serie,condicion,reparaciones,repuestos,calibracion,control_calidad,signed,sig_time,sig_data) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
       (rid,auto_trip_id,tech_id,d.get("clientId",""),rnum,d.get("fecha",""),d.get("horaLlegada",""),d.get("horaSalida",""),d.get("marca",""),d.get("modelo",""),d.get("serie",""),d.get("condicion",""),d.get("reparaciones",""),d.get("repuestos",""),cal,cc,1 if d.get("signed") else 0,d.get("sigTime",""),d.get("sigData","")))
    
    # Also update the trip with the reportId
    if auto_trip_id:
        ex(conn, "UPDATE trips SET report_id=?, report_num=? WHERE id=?", (rid, rnum, auto_trip_id))
    
    conn.commit(); conn.close()
    return jsonify({"id":rid,"reportNum":rnum})

@app.route("/api/reports/<rid>/pdf")
def report_pdf(rid):
    conn=get_db()
    cur=ex(conn,"SELECT * FROM visit_reports WHERE id=?",(rid,))
    rep=mrep(r2d(cur.fetchone()))
    if not rep: conn.close(); return "No encontrado",404
    cur2=ex(conn,"SELECT name FROM users WHERE id=?",(rep["technicianId"],))
    t=r2d(cur2.fetchone())
    cur3=ex(conn,"SELECT name,city FROM clients WHERE id=?",(rep["clientId"],))
    c=r2d(cur3.fetchone()); conn.close()
    tname=t["name"] if t else "—"
    cname=c["name"] if c else "—"
    ccity=c["city"] if c else ""
    cal="Sí" if rep.get("calibracion")==1 else "No" if rep.get("calibracion")==0 else "—"
    cc="Sí" if rep.get("controlCalidad")==1 else "No" if rep.get("controlCalidad")==0 else "—"
    sig=f'<img src="{rep["sigData"]}" style="max-width:100%;max-height:80px;"/>' if rep.get("sigData") and rep.get("signed") else "<p style='color:#999'>Sin firma</p>"
    # Check how many equipment items were in this visit
    conn2 = get_db()
    # Get trip equipment IDs
    trip_equips = []
    if rep.get("tripId"):
        cur_trip = ex(conn2, "SELECT equipment_ids FROM trips WHERE id=?", (rep.get("tripId",""),))
        trip_row = r2d(cur_trip.fetchone())
        if trip_row:
            import json as _json
            trip_equips = _json.loads(trip_row.get("equipment_ids","[]"))
    # Get equipment details
    equip_details = []
    for eq_id in trip_equips:
        cur_eq = ex(conn2, "SELECT * FROM inventory WHERE id=?", (eq_id,))
        eq = r2d(cur_eq.fetchone())
        if eq: equip_details.append(eq)
    conn2.close()
    
    # If no equipment from trip, use the report's marca/modelo/serie
    if not equip_details:
        equip_details = [{"name": rep.get("marca",""), "model": rep.get("modelo",""), "serial": rep.get("serie","")}]

    html=f"""<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8"/><title>Reporte {rep['reportNum']}</title>
<style>*{{box-sizing:border-box;margin:0;padding:0;}}body{{font-family:Arial,sans-serif;padding:24px;font-size:13px;color:#222;}}
.header{{display:flex;justify-content:space-between;align-items:center;border-bottom:2px solid #0F6E56;padding-bottom:14px;margin-bottom:18px;}}
.logo{{display:flex;align-items:center;gap:12px;}}img.logo-img{{height:50px;}}
.rnum{{background:#E1F5EE;color:#0F6E56;padding:6px 14px;border-radius:20px;font-weight:700;font-family:monospace;}}
.sec{{border:1px solid #e0e0e0;border-radius:8px;padding:14px;margin-bottom:14px;}}
.st{{font-size:10px;font-weight:700;text-transform:uppercase;color:#666;letter-spacing:0.5px;margin-bottom:10px;}}
.g2{{display:grid;grid-template-columns:1fr 1fr;gap:12px;}}.g3{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;}}
.g4{{display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:12px;}}
.fl{{font-size:10px;color:#888;margin-bottom:3px;}}.fv{{background:#f7f7f7;border:1px solid #e0e0e0;border-radius:4px;padding:7px 10px;font-size:13px;font-weight:500;min-height:30px;}}
.fa{{background:#f7f7f7;border:1px solid #e0e0e0;border-radius:4px;padding:7px 10px;font-size:12px;min-height:50px;white-space:pre-wrap;}}
.sig{{border:1px dashed #0F6E56;border-radius:8px;padding:10px;text-align:center;min-height:100px;display:flex;align-items:center;justify-content:center;flex-direction:column;}}
.footer{{text-align:center;font-size:10px;color:#aaa;border-top:1px solid #eee;padding-top:12px;margin-top:18px;}}
.btn{{background:#0F6E56;color:white;border:none;padding:8px 20px;border-radius:6px;font-size:13px;cursor:pointer;font-weight:600;}}
@media print{{.np{{display:none;}}}}</style></head><body>
<div class="np" style="text-align:right;margin-bottom:16px;">
  <button class="btn" onclick="window.print()" style="margin-right:8px;">🖨️ Imprimir / Guardar PDF</button>
  <button class="btn" onclick="window.close()" style="background:#666;">✕ Cerrar</button>
</div>
<script>
// Auto-trigger print dialog after page loads
window.addEventListener('load', function() {{
  // Small delay to ensure everything renders
  setTimeout(function() {{
    window.focus();
  }}, 500);
}});
</script>
<div class="header"><div class="logo"><img class="logo-img" src="https://diprodi.net/public/uploads/1723666225_c80478b27ad98bae76d7.png" alt="DIPRODI" onerror="this.style.display='none'"/><div><div style="font-weight:700;font-size:16px;color:#0F6E56;">DIPRODI</div><div style="font-size:11px;color:#555;">Reporte de visita técnica</div></div></div><div class="rnum">{rep['reportNum']}</div></div>
<div class="sec"><div class="st">📋 Número de reporte</div><div class="g4"><div><div class="fl">Número</div><div class="fv" style="color:#0F6E56;">{rep['reportNum']}</div></div><div><div class="fl">Fecha</div><div class="fv">{rep['fecha']}</div></div><div><div class="fl">Hora llegada</div><div class="fv">{rep['horaLlegada'] or '—'}</div></div><div><div class="fl">Hora salida</div><div class="fv">{rep['horaSalida'] or '—'}</div></div></div></div>
<div class="sec"><div class="st">👤 Técnico y cliente</div><div class="g2"><div><div class="fl">Técnico</div><div class="fv" style="color:#0F6E56;">✓ {tname}</div></div><div><div class="fl">Cliente</div><div class="fv" style="color:#0F6E56;">✓ {cname} — {ccity}</div></div></div></div>
{"".join([f'''<div class="sec" style="page-break-inside:avoid;"><div class="st">🔧 Equipo revisado {f"({i+1} de {len(equip_details)})" if len(equip_details)>1 else ""}</div><div class="g3"><div><div class="fl">Marca</div><div class="fv">{eq.get("name","—")}</div></div><div><div class="fl">Modelo</div><div class="fv">{eq.get("model","—")}</div></div><div><div class="fl">No. de serie</div><div class="fv">{eq.get("serial","—")}</div></div></div></div>{"<div style=\'page-break-after:always;\'></div>" if i<len(equip_details)-1 and len(equip_details)>1 else ""}''' for i,eq in enumerate(equip_details)])}
<div class="sec"><div class="st">📝 Detalle de la visita</div><div style="margin-bottom:10px;"><div class="fl">Condición del equipo</div><div class="fa">{rep['condicion'] or '—'}</div></div><div style="margin-bottom:10px;"><div class="fl">Reparaciones efectuadas</div><div class="fa">{rep['reparaciones'] or '—'}</div></div><div><div class="fl">Repuestos utilizados</div><div class="fa">{rep['repuestos'] or '—'}</div></div></div>
<div class="sec"><div class="st">✅ Control de calidad</div><div style="display:flex;gap:40px;"><div><div style="font-size:11px;font-weight:600;margin-bottom:5px;">Calibración</div><div>{'☑' if cal=='Sí' else '☐'} Sí &nbsp; {'☑' if cal=='No' else '☐'} No</div></div><div><div style="font-size:11px;font-weight:600;margin-bottom:5px;">Control de calidad</div><div>{'☑' if cc=='Sí' else '☐'} Sí &nbsp; {'☑' if cc=='No' else '☐'} No</div></div></div></div>
<div class="sec"><div class="st">✍️ Firmas</div><div class="g2"><div><div class="fl" style="margin-bottom:6px;">Técnico encargado</div><div class="sig"><div style="font-size:13px;font-weight:600;">{tname}</div></div></div><div><div class="fl" style="margin-bottom:6px;">Firma del cliente</div><div class="sig">{sig}<div style="font-size:10px;color:#{'0F6E56' if rep.get('signed') else '999'};margin-top:4px;">{'Firmado: '+rep['sigTime'] if rep.get('signed') else 'Sin firma'}</div></div></div></div></div>
<div class="footer">DIPRODI · Residencial Plaza, Casa No.1, Bloque 32, Tegucigalpa · Telefax: 2230-7121</div>
</body></html>"""
    return Response(html, mimetype='text/html')

# ─── GPS TRACKING ─────────────────────────────────────────────────────────────
@app.route("/api/gps/update", methods=["POST"])
def update_gps():
    """Technician sends their live position"""
    d = request.get_json()
    tech_id = d.get("technicianId")
    if not tech_id:
        return jsonify({"error": "No technicianId"}), 400
    
    pos = {
        "technicianId": tech_id,
        "lat": d.get("lat"),
        "lng": d.get("lng"),
        "km": d.get("km", 0),
        "destName": d.get("destName", ""),
        "tripType": d.get("tripType", ""),
        "clientName": d.get("clientName", ""),
        "status": "en_ruta",
        "timestamp": datetime.now().isoformat()
    }
    live_positions[tech_id] = pos
    return jsonify({"ok": True})

@app.route("/api/gps/clear", methods=["POST"])
def clear_gps():
    """Technician finished trip — remove from live"""
    d = request.get_json()
    tech_id = d.get("technicianId")
    if tech_id and tech_id in live_positions:
        del live_positions[tech_id]
    return jsonify({"ok": True})

@app.route("/api/gps/live")
def get_live():
    """Admin polls for all live technician positions"""
    return jsonify(list(live_positions.values()))



# ─── SALES GOALS & RECORDS ────────────────────────────────────────────────────
@app.route("/api/sales/goals")
def get_goals():
    mes = request.args.get("mes", datetime.now().strftime("%Y-%m"))
    conn = get_db()
    cur = ex(conn, "SELECT * FROM sales_goals WHERE mes=?", (mes,))
    goals = {r["user_id"]: r for r in rlist(cur.fetchall())}
    cur2 = ex(conn, "SELECT user_id, SUM(monto) as total FROM sales_records WHERE mes=? GROUP BY user_id", (mes,))
    totals = {r["user_id"]: float(r["total"] or 0) for r in rlist(cur2.fetchall())}
    conn.close()
    return jsonify({"goals": goals, "totals": totals, "mes": mes})

@app.route("/api/sales/goals", methods=["POST"])
def save_goal():
    d = request.get_json()
    mes = d.get("mes", datetime.now().strftime("%Y-%m"))
    uid = d.get("userId")
    conn = get_db()
    # Check if goal exists
    cur = ex(conn, "SELECT id FROM sales_goals WHERE user_id=? AND mes=?", (uid, mes))
    existing = r2d(cur.fetchone())
    if existing:
        ex(conn, "UPDATE sales_goals SET meta=? WHERE id=?", (d.get("meta", 0), existing["id"]))
    else:
        gid = "goal_" + uuid.uuid4().hex[:10]
        ex(conn, "INSERT INTO sales_goals(id,user_id,mes,meta) VALUES(?,?,?,?)",
           (gid, uid, mes, d.get("meta", 0)))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@app.route("/api/sales/records", methods=["POST"])
def add_sale():
    d = request.get_json()
    sid = "sale_" + uuid.uuid4().hex[:10]
    mes = datetime.now().strftime("%Y-%m")
    conn = get_db()
    ex(conn, "INSERT INTO sales_records(id,user_id,mes,monto,descripcion,cliente,fecha) VALUES(?,?,?,?,?,?,?)",
       (sid, d.get("userId",""), mes, float(d.get("monto",0)), d.get("descripcion",""), d.get("cliente",""), datetime.now().strftime("%Y-%m-%d")))
    conn.commit()
    cur = ex(conn, "SELECT SUM(monto) as total FROM sales_records WHERE user_id=? AND mes=?", (d.get("userId",""), mes))
    total = float(r2d(cur.fetchone()).get("total") or 0)
    conn.close()
    return jsonify({"ok": True, "newTotal": total})

@app.route("/api/sales/records")
def get_sales():
    uid = request.args.get("userId")
    mes = request.args.get("mes", datetime.now().strftime("%Y-%m"))
    conn = get_db()
    if uid:
        cur = ex(conn, "SELECT * FROM sales_records WHERE user_id=? AND mes=? ORDER BY created_at DESC", (uid, mes))
    else:
        cur = ex(conn, "SELECT * FROM sales_records WHERE mes=? ORDER BY created_at DESC", (mes,))
    rows = rlist(cur.fetchall())
    conn.close()
    return jsonify(rows)

# ─── ODOMETER ─────────────────────────────────────────────────────────────────
@app.route("/api/odometer")
def get_odometer():
    uid = request.args.get("userId")
    mes = request.args.get("mes", datetime.now().strftime("%Y-%m"))
    conn = get_db()
    cur = ex(conn, "SELECT * FROM odometer_records WHERE user_id=? AND mes=? ORDER BY created_at DESC LIMIT 1", (uid, mes))
    row = r2d(cur.fetchone())
    # Get km from trips this month
    cur2 = ex(conn, "SELECT SUM(km) as total FROM trips WHERE technician_id=? AND date LIKE ?", (uid, f"{mes}%"))
    km_row = r2d(cur2.fetchone())
    km_laborales = float(km_row.get("total") or 0)
    conn.close()
    return jsonify({"record": row, "kmLaborales": km_laborales})

@app.route("/api/odometer", methods=["POST"])
def save_odometer():
    d = request.get_json()
    mes = d.get("mes", datetime.now().strftime("%Y-%m"))
    uid = d.get("userId")
    conn = get_db()
    # Calculate reimbursement
    km_inicio = float(d.get("kmInicio", 0))
    km_fin = float(d.get("kmFin", 0))
    km_total = km_fin - km_inicio if km_fin > km_inicio else 0
    km_laborales = float(d.get("kmLaborales", 0))
    factura = float(d.get("facturaMonto", 0))
    pct = (km_laborales / km_total * 100) if km_total > 0 else 0
    reembolso = factura * (pct / 100)
    
    cur = ex(conn, "SELECT id FROM odometer_records WHERE user_id=? AND mes=?", (uid, mes))
    existing = r2d(cur.fetchone())
    if existing:
        ex(conn, "UPDATE odometer_records SET km_inicio=?,km_fin=?,factura_monto=?,km_laborales=?,reembolso=? WHERE id=?",
           (km_inicio, km_fin, factura, km_laborales, round(reembolso, 2), existing["id"]))
    else:
        oid = "odo_" + uuid.uuid4().hex[:10]
        ex(conn, "INSERT INTO odometer_records(id,user_id,mes,km_inicio,km_fin,factura_monto,km_laborales,reembolso) VALUES(?,?,?,?,?,?,?,?)",
           (oid, uid, mes, km_inicio, km_fin, factura, km_laborales, round(reembolso, 2)))
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "reembolso": round(reembolso, 2), "porcentaje": round(pct, 1)})

# ─── DIPRODI INVENTORY ────────────────────────────────────────────────────────
@app.route("/api/diprodi/equipos")
def get_equipos():
    tipo = request.args.get("tipo")
    estado = request.args.get("estado")
    cliente = request.args.get("cliente")
    conn = get_db()
    sql = "SELECT * FROM diprodi_equipos WHERE 1=1"
    params = []
    if tipo: sql += " AND tipo=?"; params.append(tipo)
    if estado: sql += " AND estado=?"; params.append(estado)
    if cliente: sql += " AND cliente ILIKE ?" if is_pg() else " AND cliente LIKE ?"; params.append(f"%{cliente}%")
    sql += " ORDER BY num"
    cur = ex(conn, sql, params)
    rows = rlist(cur.fetchall())
    conn.close()
    return jsonify(rows)

@app.route("/api/diprodi/equipos", methods=["POST"])
def add_equipo():
    d = request.get_json()
    eid = "eq_" + uuid.uuid4().hex[:10]
    conn = get_db()
    ex(conn, """INSERT INTO diprodi_equipos(id,num,localizacion,cliente,tipo,modelo,serie,fecha_ingreso,fecha_instalacion,version_sw,comentarios,estado,modalidad,contrato_inicio,contrato_meses,contrato_valor,categoria)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
       (eid,d.get("num",0),d.get("localizacion",""),d.get("cliente",""),d.get("tipo",""),
        d.get("modelo",""),d.get("serie",""),d.get("fechaIngreso",""),d.get("fechaInstalacion",""),
        d.get("versionSw",""),d.get("comentarios",""),d.get("estado","instalado"),
        d.get("modalidad","leasing"),d.get("contratoInicio",""),d.get("contratoMeses"),
        d.get("contratoValor"),d.get("categoria","equipo")))
    conn.commit()
    cur = ex(conn, "SELECT * FROM diprodi_equipos WHERE id=?", (eid,))
    row = r2d(cur.fetchone())
    conn.close()
    return jsonify(row)

@app.route("/api/diprodi/equipos/<eid>", methods=["PATCH"])
def update_equipo(eid):
    d = request.get_json()
    conn = get_db()
    fields, vals = [], []
    for k,col in [("estado","estado"),("modalidad","modalidad"),("contratoInicio","contrato_inicio"),
                  ("contratoMeses","contrato_meses"),("contratoValor","contrato_valor"),
                  ("cuotaMensual","cuota_mensual"),("prima","prima"),("interes","interes"),
                  ("comentarios","comentarios"),("versionSw","version_sw"),
                  ("fechaInstalacion","fecha_instalacion")]:
        if k in d: fields.append(f"{col}=?"); vals.append(d[k])
    if fields:
        vals.append(eid)
        ex(conn, f"UPDATE diprodi_equipos SET {','.join(fields)} WHERE id=?", vals)
        conn.commit()
    cur = ex(conn, "SELECT * FROM diprodi_equipos WHERE id=?", (eid,))
    row = r2d(cur.fetchone())
    conn.close()
    return jsonify(row)

@app.route("/api/diprodi/bulk", methods=["POST"])
def bulk_import():
    """Import all DIPRODI inventory in one call"""
    d = request.get_json()
    conn = get_db()
    equipos = d.get("equipos", [])
    accesorios = d.get("accesorios", [])
    repuestos = d.get("repuestos", [])
    imported = {"equipos": 0, "accesorios": 0, "repuestos": 0}
    
    for e in equipos:
        eid = "eq_" + uuid.uuid4().hex[:10]
        # Determine estado
        estado = "bodega" if e.get("cliente","").lower() in ["globalvet","bodega",""] else "instalado"
        if "financiado" in e.get("comentarios","").lower(): estado = "financiado"
        if "contado" in e.get("comentarios","").lower(): estado = "contado"
        try:
            ex(conn, """INSERT INTO diprodi_equipos(id,num,localizacion,cliente,tipo,modelo,serie,fecha_ingreso,fecha_instalacion,version_sw,comentarios,estado,categoria)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
               (eid,e.get("num",0),e.get("localizacion",""),e.get("cliente",""),e.get("tipo",""),
                e.get("modelo",""),e.get("serie",""),e.get("fechaIngreso",""),e.get("fechaInstalacion",""),
                e.get("versionSw",""),e.get("comentarios",""),estado,"equipo"))
            imported["equipos"] += 1
        except: pass

    for a in accesorios:
        aid = "acc_" + uuid.uuid4().hex[:10]
        try:
            ex(conn, "INSERT INTO diprodi_accesorios(id,tipo,modelo,serie,cantidad,cliente,localizacion,estado,categoria) VALUES(?,?,?,?,?,?,?,?,?)",
               (aid,a.get("tipo",""),a.get("modelo",""),a.get("serie",""),a.get("cantidad",1),
                a.get("cliente",""),a.get("localizacion","Bodega"),
                "instalado" if a.get("cliente") else "disponible","accesorio"))
            imported["accesorios"] += 1
        except: pass

    for r in repuestos:
        rid = "rep_" + uuid.uuid4().hex[:10]
        try:
            ex(conn, "INSERT INTO diprodi_repuestos(id,num,localizacion,cliente,equipo,modelo,num_parte,nombre,cantidad,fecha_ingreso,categoria) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
               (rid,r.get("num",0),r.get("localizacion","Bodega"),r.get("cliente","GlobalVet"),
                r.get("equipo",""),r.get("modelo",""),r.get("numParte",""),r.get("nombre",""),
                r.get("cantidad",1),r.get("fechaIngreso",""),"repuesto"))
            imported["repuestos"] += 1
        except: pass

    conn.commit()
    conn.close()
    return jsonify({"ok": True, "imported": imported})

@app.route("/api/diprodi/repuestos")
def get_repuestos():
    conn = get_db()
    cur = ex(conn, "SELECT * FROM diprodi_repuestos ORDER BY num")
    rows = rlist(cur.fetchall())
    conn.close()
    return jsonify(rows)

@app.route("/api/diprodi/accesorios")
def get_accesorios():
    conn = get_db()
    cur = ex(conn, "SELECT * FROM diprodi_accesorios ORDER BY tipo")
    rows = rlist(cur.fetchall())
    conn.close()
    return jsonify(rows)

@app.route("/api/diprodi/stats")
def get_inventory_stats():
    """Summary stats for dashboard"""
    conn = get_db()
    stats = {}
    # Equipment by status
    cur = ex(conn, "SELECT estado, COUNT(*) as c FROM diprodi_equipos GROUP BY estado")
    stats["byEstado"] = {r["estado"]: r["c"] for r in rlist(cur.fetchall())}
    # Equipment by type
    cur = ex(conn, "SELECT tipo, COUNT(*) as c FROM diprodi_equipos GROUP BY tipo ORDER BY c DESC")
    stats["byTipo"] = rlist(cur.fetchall())
    # Total counts
    cur = ex(conn, "SELECT COUNT(*) as c FROM diprodi_equipos"); stats["totalEquipos"] = r2d(cur.fetchone())["c"]
    cur = ex(conn, "SELECT COUNT(*) as c FROM diprodi_accesorios"); stats["totalAccesorios"] = r2d(cur.fetchone())["c"]
    cur = ex(conn, "SELECT COUNT(*) as c FROM diprodi_repuestos"); stats["totalRepuestos"] = r2d(cur.fetchone())["c"]
    cur = ex(conn, "SELECT COUNT(*) as c FROM diprodi_equipos WHERE estado='bodega'"); stats["enBodega"] = r2d(cur.fetchone())["c"]
    conn.close()
    return jsonify(stats)

@app.route("/api/clients/deleteall", methods=["POST"])
def delete_all_clients():
    conn=get_db()
    ex(conn,"DELETE FROM clients")
    conn.commit(); conn.close()
    return jsonify({"ok":True})

@app.route("/api/diprodi/export")
def export_inventory():
    """Export inventory as CSV"""
    conn = get_db()
    cur = ex(conn, "SELECT * FROM diprodi_equipos ORDER BY num")
    equipos = rlist(cur.fetchall())
    conn.close()
    
    import io, csv
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["#","Localización","Cliente","Tipo","Modelo","Serie","Fecha Ingreso","Fecha Instalación","Version SW","Estado","Comentarios"])
    for e in equipos:
        writer.writerow([e.get("num",""),e.get("localizacion",""),e.get("cliente",""),
            e.get("tipo",""),e.get("modelo",""),e.get("serie",""),
            e.get("fecha_ingreso",""),e.get("fecha_instalacion",""),
            e.get("version_sw",""),e.get("estado",""),e.get("comentarios","")])
    
    from flask import Response
    return Response(output.getvalue(), mimetype="text/csv",
        headers={"Content-Disposition":"attachment;filename=inventario_diprodi.csv"})

# ─── INVOICES ────────────────────────────────────────────────────────────────
@app.route("/api/invoices")
def get_invoices():
    client_id = request.args.get("clientId")
    conn = get_db()
    if client_id:
        cur = ex(conn, "SELECT * FROM invoices WHERE client_id=? ORDER BY created_at DESC", (client_id,))
    else:
        cur = ex(conn, "SELECT * FROM invoices ORDER BY created_at DESC")
    rows = rlist(cur.fetchall())
    conn.close()
    result = []
    for r in rows:
        r["items"] = __import__("json").loads(r.get("items","[]"))
        result.append(r)
    return jsonify(result)

@app.route("/api/invoices", methods=["POST"])
def create_invoice():
    import json as _json
    d = request.get_json()
    iid = "inv_" + uuid.uuid4().hex[:10]
    now = datetime.now()
    year, month = now.year, now.month
    conn = get_db()
    # Generate sequential invoice number
    cur = ex(conn, "SELECT last_num FROM invoice_sequence WHERE year=? AND month=?", (year, month))
    seq_row = r2d(cur.fetchone())
    if seq_row:
        new_num = int(seq_row["last_num"]) + 1
        ex(conn, "UPDATE invoice_sequence SET last_num=? WHERE year=? AND month=?", (new_num, year, month))
    else:
        new_num = 1
        ex(conn, "INSERT INTO invoice_sequence(id,year,month,last_num) VALUES(?,?,?,?)",
           (f"seq_{year}_{month}", year, month, 1))
    invoice_num = f"FAC-{year}{str(month).zfill(2)}-{str(new_num).zfill(4)}"
    items = d.get("items", [])
    subtotal = sum(float(i.get("qty",1)) * float(i.get("price",0)) for i in items)
    isv_rate = float(d.get("isvRate", 15))
    isv = round(subtotal * (isv_rate/100), 2)
    total = round(subtotal + isv, 2)
    # Get client info if clientId provided
    client_name = d.get("clientName","")
    client_rtn = d.get("clientRtn","")
    client_address = d.get("clientAddress","")
    if d.get("clientId"):
        cur2 = ex(conn, "SELECT name,rtn,address,city FROM clients WHERE id=?", (d["clientId"],))
        cl = r2d(cur2.fetchone())
        if cl:
            client_name = client_name or cl.get("name","")
            client_rtn = client_rtn or cl.get("rtn","")
            client_address = client_address or f"{cl.get('address','')} {cl.get('city','')}".strip()
    ex(conn, """INSERT INTO invoices(id,invoice_num,client_id,client_name,client_rtn,client_address,items,subtotal,isv_rate,isv,total,status,payment_method,cai,notes,technician_id,trip_id)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
       (iid, invoice_num, d.get("clientId",""), client_name, client_rtn, client_address,
        _json.dumps(items), subtotal, isv_rate, isv, total,
        d.get("status","pendiente"), d.get("paymentMethod","efectivo"),
        d.get("cai",""), d.get("notes",""), d.get("technicianId",""), d.get("tripId","")))
    # Update inventory stock for product items
    for item in items:
        if item.get("inventoryId") and item.get("qty"):
            ex(conn, "UPDATE diprodi_repuestos SET cantidad=cantidad-? WHERE id=? AND cantidad>=?",
               (int(item["qty"]), item["inventoryId"], int(item["qty"])))
    conn.commit()
    conn.close()
    return jsonify({"id":iid,"invoiceNum":invoice_num,"total":total})

@app.route("/api/invoices/<iid>", methods=["PATCH"])
def update_invoice(iid):
    d = request.get_json()
    conn = get_db()
    fields, vals = [], []
    for k,col in [("status","status"),("paymentMethod","payment_method"),("notes","notes")]:
        if k in d: fields.append(f"{col}=?"); vals.append(d[k])
    if fields:
        vals.append(iid)
        ex(conn, f"UPDATE invoices SET {','.join(fields)} WHERE id=?", vals)
        conn.commit()
    conn.close()
    return jsonify({"ok":True})

@app.route("/api/invoices/<iid>/pdf")
def invoice_pdf(iid):
    import json as _json
    conn = get_db()
    cur = ex(conn, "SELECT * FROM invoices WHERE id=?", (iid,))
    inv = r2d(cur.fetchone())
    # Get company settings
    cur2 = ex(conn, "SELECT key,value FROM settings WHERE key IN ('company_name','company_address','company_phone','company_rtn','company_logo')")
    settings = {r["key"]:r["value"] for r in rlist(cur2.fetchall())}
    conn.close()
    if not inv: return "Factura no encontrada", 404
    items = _json.loads(inv.get("items","[]"))
    company = settings.get("company_name","DIPRODI")
    logo = settings.get("company_logo","https://diprodi.net/public/uploads/1723666225_c80478b27ad98bae76d7.png")
    address = settings.get("company_address","Residencial Plaza, Casa 1, Bloque 32, Tegucigalpa")
    phone = settings.get("company_phone","2230-7121")
    rtn = settings.get("company_rtn","")
    fmt = lambda n: f"L.{float(n):,.2f}"
    items_html = "".join([f"""<tr><td style='padding:8px 10px;border-bottom:1px solid #f0f0f0;'>{i.get('description','')}</td>
        <td style='padding:8px 10px;border-bottom:1px solid #f0f0f0;text-align:center;'>{i.get('qty',1)}</td>
        <td style='padding:8px 10px;border-bottom:1px solid #f0f0f0;text-align:right;font-family:monospace;'>L.{float(i.get('price',0)):,.2f}</td>
        <td style='padding:8px 10px;border-bottom:1px solid #f0f0f0;text-align:right;font-family:monospace;font-weight:600;'>L.{float(i.get('qty',1))*float(i.get('price',0)):,.2f}</td></tr>""" for i in items])
    html = f"""<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8"/>
<title>Factura {inv['invoice_num']}</title>
<style>*{{box-sizing:border-box;margin:0;padding:0;}}body{{font-family:Arial,sans-serif;padding:30px;font-size:13px;color:#222;}}
.header{{display:flex;justify-content:space-between;align-items:flex-start;border-bottom:3px solid #0F6E56;padding-bottom:16px;margin-bottom:20px;}}
.logo{{height:55px;}}h1{{color:#0F6E56;font-size:22px;margin-bottom:4px;}}.inv-num{{background:#E1F5EE;color:#0F6E56;padding:8px 16px;border-radius:20px;font-weight:800;font-size:15px;font-family:monospace;}}
.grid-2{{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:20px;}}.box{{background:#f8f8f8;border-radius:8px;padding:14px;}}.box h3{{font-size:11px;text-transform:uppercase;color:#888;letter-spacing:0.5px;margin-bottom:8px;}}
.box p{{font-size:13px;color:#333;line-height:1.7;}}table{{width:100%;border-collapse:collapse;margin-bottom:16px;}}
thead{{background:#0F6E56;color:white;}}thead th{{padding:10px;text-align:left;font-size:12px;}}
.totals{{margin-left:auto;width:260px;}}.total-row{{display:flex;justify-content:space-between;padding:6px 0;font-size:13px;color:#555;border-bottom:1px solid #eee;}}
.total-final{{display:flex;justify-content:space-between;padding:10px 0;font-size:16px;font-weight:800;color:#0F6E56;border-top:2px solid #0F6E56;margin-top:4px;}}
.status-badge{{display:inline-block;padding:4px 12px;border-radius:20px;font-size:12px;font-weight:700;background:{'#E1F5EE' if inv['status']=='pagada' else '#FFF3E0'};color:{'#0F6E56' if inv['status']=='pagada' else '#EF9F27'};}}
.footer{{text-align:center;font-size:11px;color:#aaa;border-top:1px solid #eee;padding-top:12px;margin-top:20px;}}
.btn{{background:#0F6E56;color:white;border:none;padding:8px 20px;border-radius:6px;font-size:13px;cursor:pointer;font-weight:600;}}
@media print{{.np{{display:none;}};@page{{margin:15mm;}}}}</style></head>
<body>
<div class="np" style="text-align:right;margin-bottom:16px;"><button class="btn" onclick="window.print()">🖨️ Imprimir / PDF</button></div>
<div class="header">
  <div style="display:flex;align-items:center;gap:14px;">
    <img src="{logo}" class="logo" alt="{company}" onerror="this.style.display='none'"/>
    <div><h1>{company}</h1><p style="color:#666;font-size:12px;">{address}</p><p style="color:#666;font-size:12px;">Tel: {phone}{f' · RTN: {rtn}' if rtn else ''}</p></div>
  </div>
  <div style="text-align:right;">
    <div class="inv-num">{inv['invoice_num']}</div>
    <p style="margin-top:8px;font-size:12px;color:#666;">Fecha: {inv['created_at'][:10]}</p>
    <p style="margin-top:4px;"><span class="status-badge">{inv['status'].upper()}</span></p>
    {f'<p style="font-size:11px;color:#888;margin-top:4px;">CAI: {inv["cai"]}</p>' if inv.get('cai') else ''}
  </div>
</div>
<div class="grid-2">
  <div class="box"><h3>Facturar a</h3><p><strong>{inv['client_name'] or '—'}</strong><br/>{f'RTN: {inv["client_rtn"]}' if inv.get('client_rtn') else ''}<br/>{inv.get('client_address','')}</p></div>
  <div class="box"><h3>Detalles de pago</h3><p>Método: <strong>{inv['payment_method'].title()}</strong><br/>Subtotal: {fmt(inv['subtotal'])}<br/>ISV ({inv['isv_rate']}%): {fmt(inv['isv'])}</p></div>
</div>
<table><thead><tr><th>Descripción</th><th style="text-align:center;">Cant.</th><th style="text-align:right;">Precio unit.</th><th style="text-align:right;">Total</th></tr></thead>
<tbody>{items_html}</tbody></table>
<div class="totals">
  <div class="total-row"><span>Subtotal</span><span style="font-family:monospace;">{fmt(inv['subtotal'])}</span></div>
  <div class="total-row"><span>ISV ({inv['isv_rate']}%)</span><span style="font-family:monospace;">{fmt(inv['isv'])}</span></div>
  <div class="total-final"><span>TOTAL</span><span style="font-family:monospace;">{fmt(inv['total'])}</span></div>
</div>
{f'<div style="margin-top:16px;padding:10px 14px;background:#f8f8f8;border-radius:8px;font-size:12px;color:#555;"><strong>Notas:</strong> {inv["notes"]}</div>' if inv.get('notes') else ''}
<div class="footer">{company} · {address} · Tel: {phone} · Factura generada por Servvoo</div>
</body></html>"""
    from flask import Response
    return Response(html, mimetype="text/html")


# ─── AI ASSISTANT ────────────────────────────────────────────────────────────
import os as _os
ANTHROPIC_KEY = _os.environ.get("ANTHROPIC_API_KEY","")

@app.route("/api/ai/chat", methods=["POST"])
def ai_chat():
    """AI assistant for business insights"""
    import json as _json
    d = request.get_json()
    if not ANTHROPIC_KEY:
        return jsonify({"error": "API key no configurada"}), 400
    
    try:
        import urllib.request as _req
        # Get business context
        conn = get_db()
        company_id = d.get("companyId","diprodi")
        cur = ex(conn, "SELECT COUNT(*) as c FROM trips WHERE company_id=?", (company_id,))
        trip_count = int(r2d(cur.fetchone()).get("c") or 0)
        cur = ex(conn, "SELECT COUNT(*) as c FROM clients WHERE company_id=?", (company_id,))
        client_count = int(r2d(cur.fetchone()).get("c") or 0)
        cur = ex(conn, "SELECT SUM(total) as t FROM invoices WHERE company_id=?", (company_id,))
        revenue = float(r2d(cur.fetchone()).get("t") or 0)
        cur = ex(conn, "SELECT name,rubro FROM companies WHERE id=?", (company_id,))
        co = r2d(cur.fetchone()) or {}
        conn.close()

        system_prompt = f"""Eres el asistente de negocios de Servvoo para la empresa "{co.get('name','')}" 
        en el rubro de {co.get('rubro','general')}.
        
        Datos actuales del negocio:
        - Viajes realizados: {trip_count}
        - Clientes activos: {client_count}  
        - Ingresos totales: L.{revenue:,.2f}
        - País: Honduras (usa Lempiras, días festivos de Honduras)
        
        Eres experto en negocios de Honduras y Centroamérica. Das consejos prácticos, 
        específicos y accionables. Respondes en español. Eres conciso pero útil.
        Cuando detectes oportunidades de negocio, días festivos próximos o tendencias,
        proactivamente sugieres acciones."""

        payload = _json.dumps({
            "model": "claude-sonnet-4-6",
            "max_tokens": 1000,
            "system": system_prompt,
            "messages": [{"role": "user", "content": d.get("message","")}]
        }).encode()

        req = _req.Request(
            "https://api.anthropic.com/v1/messages",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "x-api-key": ANTHROPIC_KEY,
                "anthropic-version": "2023-06-01"
            }
        )
        with _req.urlopen(req, timeout=30) as resp:
            result = _json.loads(resp.read())
            text = result["content"][0]["text"]
            return jsonify({"response": text})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/ai/onboard", methods=["POST"])
def ai_onboard():
    """AI recommends modules based on business description"""
    import json as _json
    d = request.get_json()
    if not ANTHROPIC_KEY:
        # Fallback: rule-based recommendations
        rubro = d.get("rubro","general")
        recommendations = {
            "veterinaria": ["viajes","inventario","reportes","facturacion","agenda","tracking","leasing"],
            "medico": ["agenda","clientes","reportes","facturacion","calendario","expedientes"],
            "bufete": ["clientes","agenda","facturacion","calendario","expedientes","horas"],
            "construccion": ["viajes","inventario","tracking","facturacion","reportes"],
            "general": ["viajes","clientes","agenda","facturacion","reportes"]
        }
        return jsonify({"modules": recommendations.get(rubro, recommendations["general"]), "reason": "Seleccionado por rubro"})
    
    try:
        import urllib.request as _req
        prompt = f"""Una empresa llamada "{d.get('name','')}" en el rubro "{d.get('rubro','')}" 
        con esta descripción: "{d.get('description','')}"
        
        Recomienda qué módulos de Servvoo necesitan. Responde SOLO con JSON así:
        {{"modules": ["viajes","inventario","agenda","facturacion","reportes","tracking","leasing","expedientes","calendario","ventas"], "reason": "explicación breve"}}
        
        Módulos disponibles: viajes, inventario, agenda, facturacion, reportes, tracking, leasing, expedientes, calendario, ventas
        Solo incluye los relevantes para su rubro."""

        payload = _json.dumps({
            "model": "claude-sonnet-4-6",
            "max_tokens": 500,
            "messages": [{"role": "user", "content": prompt}]
        }).encode()

        req = _req.Request(
            "https://api.anthropic.com/v1/messages",
            data=payload,
            headers={"Content-Type":"application/json","x-api-key":ANTHROPIC_KEY,"anthropic-version":"2023-06-01"}
        )
        with _req.urlopen(req, timeout=30) as resp:
            result = _json.loads(resp.read())
            text = result["content"][0]["text"]
            # Parse JSON from response
            import re
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                data = _json.loads(match.group())
                return jsonify(data)
            return jsonify({"modules":["viajes","agenda","facturacion","reportes"],"reason":text})
    except Exception as e:
        return jsonify({"modules":["viajes","agenda","facturacion","reportes"],"reason":"Módulos básicos recomendados"})

# ─── CALENDAR ────────────────────────────────────────────────────────────────
@app.route("/api/calendar/events")
def get_events():
    company_id = request.args.get("companyId","diprodi")
    month = request.args.get("month", datetime.now().strftime("%Y-%m"))
    conn = get_db()
    # Get bookings as events
    cur = ex(conn, "SELECT id,client_name,date,time,tipo_servicio,status,technician_id FROM bookings WHERE date LIKE ? ORDER BY date,time", (f"{month}%",))
    bookings = rlist(cur.fetchall())
    # Get manual events
    try:
        cur2 = ex(conn, "SELECT * FROM calendar_events WHERE company_id=? AND date LIKE ? ORDER BY date,time", (company_id, f"{month}%"))
        manual = rlist(cur2.fetchall())
    except:
        manual = []
    conn.close()
    
    events = []
    for b in bookings:
        events.append({"id":b["id"],"title":f"{b['client_name']} - {b['tipo_servicio']}",
            "date":b["date"],"time":b["time"],"type":"booking","status":b["status"],"color":"#185FA5"})
    for e in manual:
        events.append({"id":e["id"],"title":e.get("title",""),"date":e.get("date",""),
            "time":e.get("time",""),"type":"manual","color":e.get("color","#EF9F27"),
            "allDay":e.get("all_day",False),"notes":e.get("notes","")})
    return jsonify(events)

@app.route("/api/calendar/events", methods=["POST"])
def create_event():
    d = request.get_json()
    eid = "evt_" + uuid.uuid4().hex[:10]
    company_id = d.get("companyId","diprodi")
    conn = get_db()
    ex(conn, "INSERT INTO calendar_events(id,company_id,title,date,time,color,all_day,notes,blocks_booking) VALUES(?,?,?,?,?,?,?,?,?)",
       (eid,company_id,d.get("title",""),d.get("date",""),d.get("time",""),
        d.get("color","#EF9F27"),1 if d.get("allDay") else 0,
        d.get("notes",""),1 if d.get("blocksBooking") else 0))
    conn.commit()
    conn.close()
    return jsonify({"id":eid,"ok":True})

@app.route("/api/calendar/events/<eid>", methods=["DELETE"])
def delete_event(eid):
    conn = get_db()
    ex(conn, "DELETE FROM calendar_events WHERE id=?", (eid,))
    conn.commit()
    conn.close()
    return jsonify({"ok":True})

# ─── CLIENT PROFILES ─────────────────────────────────────────────────────────
@app.route("/api/clients/<cid>/history")
def client_history(cid):
    conn = get_db()
    cur = ex(conn, "SELECT * FROM trips WHERE client_id=? ORDER BY date DESC", (cid,))
    trips = [mt(r) for r in rlist(cur.fetchall())]
    cur2 = ex(conn, "SELECT * FROM visit_reports WHERE client_id=? ORDER BY created_at DESC", (cid,))
    reports = [mrep(r) for r in rlist(cur2.fetchall())]
    cur3 = ex(conn, "SELECT * FROM invoices WHERE client_id=? ORDER BY created_at DESC", (cid,))
    invoices = rlist(cur3.fetchall())
    cur4 = ex(conn, "SELECT * FROM bookings WHERE client_name=(SELECT name FROM clients WHERE id=?) ORDER BY date DESC LIMIT 10", (cid,))
    bookings = rlist(cur4.fetchall())
    conn.close()
    return jsonify({"trips":trips,"reports":reports,"invoices":invoices,"bookings":bookings})

# ─── FINANCIAL SUMMARY ───────────────────────────────────────────────────────
@app.route("/api/finance/summary")
def finance_summary():
    company_id = request.args.get("companyId","diprodi")
    month = request.args.get("month", datetime.now().strftime("%Y-%m"))
    conn = get_db()
    # Revenue
    cur = ex(conn, "SELECT SUM(total) as t,COUNT(*) as c FROM invoices WHERE company_id=? AND created_at LIKE ? AND status='pagada'", (company_id, f"{month}%"))
    rev = r2d(cur.fetchone())
    # Pending
    cur2 = ex(conn, "SELECT SUM(total) as t FROM invoices WHERE company_id=? AND created_at LIKE ? AND status='pendiente'", (company_id, f"{month}%"))
    pend = r2d(cur2.fetchone())
    # Reimbursements (expenses)
    cur3 = ex(conn, "SELECT SUM(reimbursement) as t FROM trips WHERE company_id=? AND date LIKE ?", (company_id, f"{month}%"))
    reimb = r2d(cur3.fetchone())
    # Top services
    cur4 = ex(conn, "SELECT tipo_servicio,COUNT(*) as c FROM bookings WHERE created_at LIKE ? GROUP BY tipo_servicio ORDER BY c DESC LIMIT 5", (f"{month}%",))
    top_services = rlist(cur4.fetchall())
    # New clients
    cur5 = ex(conn, "SELECT COUNT(*) as c FROM clients WHERE company_id=? AND created_at LIKE ?", (company_id, f"{month}%"))
    new_clients = int(r2d(cur5.fetchone()).get("c") or 0)
    conn.close()
    income = float(rev.get("t") or 0)
    expenses = float(reimb.get("t") or 0)
    return jsonify({
        "income": income, "invoiceCount": int(rev.get("c") or 0),
        "pending": float(pend.get("t") or 0),
        "expenses": expenses, "profit": income - expenses,
        "topServices": top_services, "newClients": new_clients
    })

# ─── COMPANIES (MULTI-TENANT) ────────────────────────────────────────────────
@app.route("/api/companies")
def get_companies():
    conn=get_db()
    cur=ex(conn,"SELECT * FROM companies ORDER BY name")
    rows=rlist(cur.fetchall()); conn.close()
    return jsonify(rows)

@app.route("/api/companies", methods=["POST"])
def create_company():
    d=request.get_json()
    cid="co_"+uuid.uuid4().hex[:8]
    slug=d.get("name","").lower().replace(" ","_")[:20]
    conn=get_db()
    ex(conn,"INSERT INTO companies(id,name,slug,logo,color,plan,rubro,phone,address,rtn) VALUES(?,?,?,?,?,?,?,?,?,?)",
       (cid,d["name"],slug,d.get("logo",""),d.get("color","#185FA5"),d.get("plan","basic"),
        d.get("rubro","general"),d.get("phone",""),d.get("address",""),d.get("rtn","")))
    # Create admin user for new company
    uid="u_"+uuid.uuid4().hex[:8]
    ex(conn,"INSERT INTO users(id,name,email,password_hash,role,color,status,company_id) VALUES(?,?,?,?,?,?,?,?)",
       (uid,d.get("adminName","Administrador"),d.get("adminEmail",""),
        hash_pw(d.get("adminPassword","admin123")),"admin","blue","available",cid))
    conn.commit()
    cur=ex(conn,"SELECT * FROM companies WHERE id=?",(cid,))
    row=r2d(cur.fetchone()); conn.close()
    return jsonify({"company":row,"userId":uid})

@app.route("/api/companies/<cid>", methods=["PATCH"])
def update_company(cid):
    d=request.get_json(); conn=get_db(); fields,vals=[],[]
    for k,col in [("name","name"),("logo","logo"),("color","color"),("plan","plan"),
                  ("rubro","rubro"),("phone","phone"),("address","address"),("rtn","rtn"),("active","active")]:
        if k in d: fields.append(f"{col}=?"); vals.append(d[k])
    if fields:
        vals.append(cid); ex(conn,f"UPDATE companies SET {','.join(fields)} WHERE id=?",vals); conn.commit()
    cur=ex(conn,"SELECT * FROM companies WHERE id=?",(cid,))
    row=r2d(cur.fetchone()); conn.close()
    return jsonify(row)

# ─── SUPER ADMIN ─────────────────────────────────────────────────────────────
@app.route("/api/superadmin/stats")
def superadmin_stats():
    conn=get_db()
    cur=ex(conn,"SELECT COUNT(*) as c FROM companies WHERE active=1")
    companies=int(r2d(cur.fetchone()).get("c") or 0)
    cur=ex(conn,"SELECT COUNT(*) as c FROM users")
    users=int(r2d(cur.fetchone()).get("c") or 0)
    cur=ex(conn,"SELECT COUNT(*) as c FROM trips")
    trips=int(r2d(cur.fetchone()).get("c") or 0)
    cur=ex(conn,"SELECT COUNT(*) as c FROM invoices")
    invoices=int(r2d(cur.fetchone()).get("c") or 0)
    conn.close()
    return jsonify({"companies":companies,"users":users,"trips":trips,"invoices":invoices})

# ─── CLIENT BOOKING ──────────────────────────────────────────────────────────
@app.route("/api/booking/slots")
def get_slots():
    """Get available booking slots for next 7 days"""
    conn = get_db()
    # Get existing bookings for next 7 days
    from datetime import timedelta
    today = datetime.now().date()
    slots = []
    for i in range(1, 8):
        d = today + timedelta(days=i)
        if d.weekday() < 5:  # Monday-Friday only
            date_str = d.strftime("%Y-%m-%d")
            cur = ex(conn, "SELECT COUNT(*) as c FROM bookings WHERE date=?", (date_str,))
            row = r2d(cur.fetchone())
            count = int(row.get("c") or 0)
            for hour in ["08:00","09:00","10:00","11:00","14:00","15:00","16:00"]:
                cur2 = ex(conn, "SELECT id FROM bookings WHERE date=? AND time=? AND status!='cancelado'", (date_str, hour))
                booked = r2d(cur2.fetchone())
                slots.append({"date": date_str, "time": hour, "available": booked is None})
    conn.close()
    return jsonify(slots)

@app.route("/api/booking", methods=["POST"])
def create_booking():
    d = request.get_json()
    bid = "book_" + uuid.uuid4().hex[:10]
    conn = get_db()
    # Check slot is still available
    cur = ex(conn, "SELECT id FROM bookings WHERE date=? AND time=? AND status!='cancelado'", (d.get("date",""), d.get("time","")))
    if r2d(cur.fetchone()):
        conn.close()
        return jsonify({"error": "Este horario ya no está disponible"}), 400
    ex(conn, """INSERT INTO bookings(id,client_name,client_phone,client_email,equipo,tipo_servicio,modalidad,date,time,status,notas)
        VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
       (bid, d.get("clientName",""), d.get("clientPhone",""), d.get("clientEmail",""),
        d.get("equipo",""), d.get("tipoServicio","mantenimiento"), d.get("modalidad","presencial"),
        d.get("date",""), d.get("time",""), "pendiente", d.get("notas","")))
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "id": bid})

@app.route("/api/booking", methods=["GET"])
def get_bookings():
    conn = get_db()
    cur = ex(conn, "SELECT * FROM bookings ORDER BY date, time")
    rows = rlist(cur.fetchall())
    conn.close()
    return jsonify(rows)

@app.route("/api/booking/<bid>", methods=["PATCH"])
def update_booking(bid):
    d = request.get_json()
    conn = get_db()
    fields, vals = [], []
    for k,col in [("status","status"),("technicianId","technician_id"),("notas","notas"),
                  ("videoLink","video_link"),("acceptedAt","accepted_at"),("completedAt","completed_at")]:
        if k in d: fields.append(f"{col}=?"); vals.append(d[k])
    # Auto-set timestamps
    if d.get("status") == "confirmado" and "accepted_at" not in d:
        fields.append("accepted_at=?"); vals.append(datetime.now().isoformat())
    if d.get("status") == "completado" and "completed_at" not in d:
        fields.append("completed_at=?"); vals.append(datetime.now().isoformat())
    if fields:
        vals.append(bid)
        ex(conn, f"UPDATE bookings SET {','.join(fields)} WHERE id=?", vals)
        conn.commit()
    cur = ex(conn, "SELECT * FROM bookings WHERE id=?", (bid,))
    row = r2d(cur.fetchone())
    conn.close()
    return jsonify(row or {"ok": True})

@app.route("/api/booking/tech/<tech_id>")
def get_tech_bookings(tech_id):
    """Get bookings assigned to a technician"""
    conn = get_db()
    cur = ex(conn, "SELECT * FROM bookings WHERE technician_id=? AND status NOT IN ('cancelado','completado') ORDER BY date,time", (tech_id,))
    rows = rlist(cur.fetchall())
    conn.close()
    return jsonify(rows)

@app.route("/agendar")
@app.route("/agendar/<company>")
def booking_page(company="DIPRODI"):
    """Public booking page for clients"""
    html = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Agendar servicio técnico — DIPRODI</title>
<style>
*{box-sizing:border-box;margin:0;padding:0;}
body{font-family:Arial,sans-serif;background:#f0f4f8;min-height:100vh;padding:20px 16px;}
.container{max-width:480px;margin:0 auto;}
.header{background:linear-gradient(135deg,#0C447C,#1D9E75);border-radius:16px;padding:24px;text-align:center;color:white;margin-bottom:20px;}
.logo{height:50px;margin-bottom:12px;}
h1{font-size:20px;font-weight:700;margin-bottom:4px;}
.subtitle{font-size:13px;opacity:0.85;}
.card{background:white;border-radius:12px;padding:20px;margin-bottom:16px;box-shadow:0 2px 8px rgba(0,0,0,0.08);}
.card h2{font-size:15px;font-weight:700;color:#185FA5;margin-bottom:14px;}
.field{margin-bottom:12px;}
.field label{display:block;font-size:12px;color:#666;margin-bottom:4px;font-weight:600;}
.field input,.field select,.field textarea{width:100%;padding:10px 12px;border:1px solid #ddd;border-radius:8px;font-size:14px;color:#333;font-family:inherit;background:white;}
.field textarea{resize:vertical;min-height:70px;}
.modal-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:12px;}
.modal-btn{padding:12px 8px;border-radius:10px;border:2px solid #ddd;background:white;font-size:13px;cursor:pointer;text-align:center;transition:all 0.15s;font-weight:500;}
.modal-btn:hover{border-color:#185FA5;background:#f0f7ff;}
.modal-btn.selected{border-color:#185FA5;background:#185FA5;color:white;font-weight:700;}
.modal-btn.selected-green{border-color:#1D9E75;background:#1D9E75;color:white;font-weight:700;}
.slot-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;}
.slot-date{font-weight:700;font-size:13px;color:#333;margin:10px 0 6px;border-top:1px solid #eee;padding-top:10px;}
.slot-date:first-child{border-top:none;margin-top:0;}
.slot-btn{padding:10px 8px;border-radius:8px;border:1px solid #ddd;background:white;font-size:12px;cursor:pointer;text-align:center;transition:all 0.15s;}
.slot-btn:hover:not(:disabled){border-color:#185FA5;background:#E6F1FB;color:#185FA5;}
.slot-btn.selected{background:#185FA5;color:white;border-color:#185FA5;font-weight:700;}
.slot-btn:disabled{opacity:0.4;cursor:not-allowed;background:#f5f5f5;color:#999;}
.btn-submit{width:100%;background:#1D9E75;color:white;border:none;border-radius:10px;padding:14px;font-size:15px;font-weight:700;cursor:pointer;margin-top:4px;transition:opacity 0.2s;}
.btn-submit:disabled{opacity:0.4;cursor:not-allowed;}
.success{background:#E1F5EE;border:1px solid #5DCAA5;border-radius:12px;padding:24px;text-align:center;display:none;}
.success h2{color:#0F6E56;font-size:18px;margin-bottom:8px;}
.success p{color:#085041;font-size:14px;line-height:1.6;}
.cancel-link{display:block;margin-top:12px;padding:10px;background:#FCEBEB;border-radius:8px;color:#C0392B;font-size:12px;text-decoration:none;border:1px solid #F5C6CB;}
.info-box{background:#E6F1FB;border-radius:8px;padding:10px 12px;margin-bottom:12px;font-size:12px;color:#185FA5;border:1px solid #B8D4EF;}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <img src="https://diprodi.net/public/uploads/1723666225_c80478b27ad98bae76d7.png" class="logo" alt="DIPRODI" onerror="this.style.display='none'"/>
    <h1>Agendar servicio técnico</h1>
    <div class="subtitle">DIPRODI Honduras — Equipos médico-veterinarios</div>
  </div>

  <!-- STEP 1: Service type -->
  <div class="card" id="card1">
    <h2>📋 Tipo de servicio</h2>
    <div class="modal-grid">
      <button class="modal-btn" onclick="selectTipo('mantenimiento',this)">🔧<br/>Mantenimiento<br/>preventivo</button>
      <button class="modal-btn" onclick="selectTipo('reparacion',this)">🛠️<br/>Reparación /<br/>Emergencia</button>
      <button class="modal-btn" onclick="selectTipo('instalacion',this)">⚙️<br/>Instalación<br/>de equipo</button>
      <button class="modal-btn" onclick="selectTipo('capacitacion',this)">📚<br/>Capacitación</button>
      <button class="modal-btn" onclick="selectTipo('videollamada',this)">📹<br/>Consulta por<br/>WhatsApp/Video</button>
      <button class="modal-btn" onclick="selectTipo('otro',this)">📋<br/>Otro</button>
    </div>
    <div class="field">
      <label>Modalidad</label>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:4px;">
        <button class="modal-btn selected-green" id="btnPresencial" onclick="selectModalidad('presencial')">🏥 Visita presencial</button>
        <button class="modal-btn" id="btnVideo" onclick="selectModalidad('videollamada')">📱 WhatsApp / Video</button>
      </div>
    </div>
    <div id="videoInfo" class="info-box" style="display:none;">📱 Un técnico te contactará por WhatsApp para coordinar la videollamada en el horario seleccionado.</div>
    <div class="field">
      <label>Equipo (opcional)</label>
      <input type="text" id="equipo" placeholder="Ej: Analizador BC-20 Vet, Ultrasonido Z-60..."/>
    </div>
  </div>

  <!-- STEP 2: Date/time -->
  <div class="card">
    <h2>📅 Selecciona fecha y hora</h2>
    <div id="slots"><div style="text-align:center;padding:20px;color:#999;font-size:13px;">Cargando horarios disponibles...</div></div>
  </div>

  <!-- STEP 3: Client data -->
  <div class="card">
    <h2>👤 Tus datos</h2>
    <div class="field"><label>Nombre completo *</label><input type="text" id="clientName" placeholder="Ej: Dr. Juan Pérez"/></div>
    <div class="field"><label>Teléfono / WhatsApp *</label><input type="tel" id="clientPhone" placeholder="+504 9xxx-xxxx"/></div>
    <div class="field"><label>Correo electrónico (opcional)</label><input type="email" id="clientEmail" placeholder="correo@veterinaria.hn"/></div>
    <div class="field"><label>Nombre de la veterinaria / clínica</label><input type="text" id="clientClinica" placeholder="Ej: Veterinaria San José"/></div>
    <div class="field"><label>Notas adicionales</label><textarea id="notas" placeholder="Describe el problema, síntoma del equipo o lo que necesitas..."></textarea></div>
    <button class="btn-submit" id="submitBtn" onclick="submitBooking()" disabled>📅 Confirmar cita</button>
    <div style="font-size:11px;color:#999;margin-top:8px;text-align:center;">Al enviar, recibirás un número de cita para poder cancelarla si es necesario.</div>
  </div>

  <!-- SUCCESS -->
  <div class="success" id="successCard">
    <div style="font-size:48px;margin-bottom:12px;">✅</div>
    <h2>¡Cita agendada!</h2>
    <p id="successMsg"></p>
    <div id="cancelSection" style="margin-top:12px;"></div>
    <div style="margin-top:16px;font-size:11px;color:#085041;">DIPRODI · Residencial Plaza, Casa 1, Bloque 32, Tegucigalpa · Tel: 2230-7121</div>
  </div>
</div>

<script>
let selectedSlot = null;
let selectedTipoVal = '';
let selectedModalidad = 'presencial';
const days = ["Dom","Lun","Mar","Mié","Jue","Vie","Sáb"];
const months = ["ene","feb","mar","abr","may","jun","jul","ago","sep","oct","nov","dic"];

function selectTipo(tipo, btn){
  document.querySelectorAll('#card1 .modal-btn').forEach(b=>{
    if(b.id!=='btnPresencial'&&b.id!=='btnVideo') b.classList.remove('selected');
  });
  btn.classList.add('selected');
  selectedTipoVal = tipo;
  // Auto-select videollamada modalidad if tipo is videollamada
  if(tipo==='videollamada') selectModalidad('videollamada');
}

function selectModalidad(mod){
  selectedModalidad = mod;
  document.getElementById('btnPresencial').className = 'modal-btn' + (mod==='presencial'?' selected-green':'');
  document.getElementById('btnVideo').className = 'modal-btn' + (mod==='videollamada'?' selected':'');
  document.getElementById('videoInfo').style.display = mod==='videollamada'?'block':'none';
}

async function loadSlots(){
  try{
    const res = await fetch('/api/booking/slots');
    const slots = await res.json();
    const byDate = {};
    slots.forEach(s => { if(!byDate[s.date]) byDate[s.date]=[]; byDate[s.date].push(s); });
    let html = '';
    for(const date in byDate){
      const d = new Date(date+'T12:00:00');
      html += `<div class="slot-date">${days[d.getDay()]} ${d.getDate()} de ${months[d.getMonth()]}</div><div class="slot-grid">`;
      byDate[date].forEach(s => {
        const id = `slot-${s.date}-${s.time.replace(':','')}`;
        html += `<button class="slot-btn" id="${id}" ${!s.available?'disabled title="Ocupado"':''} onclick="selectSlot('${s.date}','${s.time}','${id}')">
          ${s.time}${!s.available?' ✗':''}
        </button>`;
      });
      html += '</div>';
    }
    document.getElementById('slots').innerHTML = html || '<p style="color:#999;text-align:center;padding:20px">No hay horarios disponibles esta semana. Contáctanos directamente: 2230-7121</p>';
  }catch(e){
    document.getElementById('slots').innerHTML = '<p style="color:#e74c3c;text-align:center;padding:20px">Error al cargar horarios. Recarga la página.</p>';
  }
}

function selectSlot(date, time, id){
  document.querySelectorAll('.slot-btn').forEach(b=>b.classList.remove('selected'));
  document.getElementById(id).classList.add('selected');
  selectedSlot = {date, time};
  document.getElementById('submitBtn').disabled = false;
}

async function submitBooking(){
  const name = document.getElementById('clientName').value.trim();
  const phone = document.getElementById('clientPhone').value.trim();
  if(!name){alert('Por favor ingresa tu nombre completo.');return;}
  if(!phone){alert('Por favor ingresa tu teléfono/WhatsApp.');return;}
  if(!selectedSlot){alert('Por favor selecciona una fecha y hora.');return;}
  if(!selectedTipoVal){alert('Por favor selecciona el tipo de servicio.');return;}

  const btn = document.getElementById('submitBtn');
  btn.disabled = true;
  btn.textContent = 'Enviando...';

  try{
    const res = await fetch('/api/booking', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({
        clientName: name,
        clientPhone: phone,
        clientEmail: document.getElementById('clientEmail').value.trim(),
        equipo: document.getElementById('equipo').value.trim(),
        tipoServicio: selectedTipoVal,
        modalidad: selectedModalidad,
        date: selectedSlot.date,
        time: selectedSlot.time,
        notas: document.getElementById('notas').value.trim() + (document.getElementById('clientClinica').value?' | Clínica: '+document.getElementById('clientClinica').value:'')
      })
    });
    const data = await res.json();
    if(data.ok){
      document.querySelectorAll('.card').forEach(c=>c.style.display='none');
      const sc = document.getElementById('successCard');
      sc.style.display='block';
      document.getElementById('successMsg').innerHTML = `
        Tu cita ha sido solicitada para el <strong>${selectedSlot.date}</strong> a las <strong>${selectedSlot.time}</strong>.<br/><br/>
        ${selectedModalidad==='videollamada'?'📱 Un técnico te contactará por <strong>WhatsApp</strong> para coordinar la videollamada.':'🏥 Un técnico irá a visitarte en el horario indicado.'}<br/><br/>
        Te contactaremos al <strong>${phone}</strong> para confirmar tu cita.<br/>
        <strong>N° de cita: ${data.id}</strong>
      `;
      // Cancel link
      document.getElementById('cancelSection').innerHTML = `
        <a href="/cancelar/${data.id}" class="cancel-link">¿Necesitas cancelar? Haz clic aquí → Cancelar mi cita</a>
      `;
    } else {
      alert(data.error || 'Error al agendar. Intenta de nuevo.');
      btn.disabled = false;
      btn.textContent = '📅 Confirmar cita';
    }
  }catch(e){
    alert('Error de conexión. Intenta de nuevo.');
    btn.disabled = false;
    btn.textContent = '📅 Confirmar cita';
  }
}

loadSlots();
</script>
</body>
</html>"""
    from flask import Response
    return Response(html, mimetype='text/html')

# ─── STATIC ───────────────────────────────────────────────────────────────────
@app.route("/cancelar/<bid>")
def cancel_page(bid):
    conn = get_db()
    cur = ex(conn, "SELECT * FROM bookings WHERE id=?", (bid,))
    b = r2d(cur.fetchone())
    if not b:
        conn.close()
        return "<h2>Cita no encontrada</h2>", 404
    if b["status"] in ("cancelado","completado"):
        conn.close()
        return f"""<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/><title>Cita</title>
        <style>body{{font-family:Arial;background:#f0f4f8;padding:30px;text-align:center;}}
        .card{{background:white;border-radius:12px;padding:24px;max-width:400px;margin:0 auto;box-shadow:0 2px 8px rgba(0,0,0,0.1);}}</style></head>
        <body><div class="card"><div style="font-size:40px;margin-bottom:12px;">{'✅' if b['status']=='completado' else '❌'}</div>
        <h2 style="color:{'#0F6E56' if b['status']=='completado' else '#C0392B'};">Esta cita ya fue {'completada' if b['status']=='completado' else 'cancelada'}</h2>
        <p style="color:#666;margin-top:8px;">Para agendar una nueva cita: <a href="/agendar">haz clic aquí</a></p></div></body></html>""", 200
    ex(conn, "UPDATE bookings SET status='cancelado' WHERE id=?", (bid,))
    conn.commit()
    conn.close()
    return f"""<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/><title>Cita cancelada</title>
    <style>body{{font-family:Arial;background:#f0f4f8;padding:30px;text-align:center;}}
    .card{{background:white;border-radius:12px;padding:24px;max-width:400px;margin:0 auto;box-shadow:0 2px 8px rgba(0,0,0,0.1);}}</style></head>
    <body><div class="card">
    <div style="font-size:48px;margin-bottom:12px;">✅</div>
    <h2 style="color:#0F6E56;">Cita cancelada exitosamente</h2>
    <p style="color:#666;margin-top:8px;">Tu cita del <strong>{b['date']}</strong> a las <strong>{b['time']}</strong> ha sido cancelada.</p>
    <p style="color:#666;margin-top:8px;">Si necesitas reagendar: <a href="/agendar" style="color:#185FA5;">haz clic aquí</a></p>
    <p style="color:#999;font-size:12px;margin-top:16px;">DIPRODI · Tel: 2230-7121</p>
    </div></body></html>""", 200

@app.route("/")
def index(): 
    response = send_from_directory("static","index.html")
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

@app.route("/<path:path>")
def static_files(path): return send_from_directory("static",path)

init_db()

def migrate_db():
    """Add missing columns to existing PostgreSQL tables"""
    if not is_pg(): return
    conn = get_db()
    cur = conn.cursor()
    migrations = [
        "ALTER TABLE trips ADD COLUMN IF NOT EXISTS report_id TEXT",
        "ALTER TABLE trips ADD COLUMN IF NOT EXISTS report_num TEXT",
        "ALTER TABLE clients ADD COLUMN IF NOT EXISTS rtn TEXT DEFAULT ''",
        "ALTER TABLE diprodi_equipos ADD COLUMN IF NOT EXISTS cuota_mensual REAL",
        "ALTER TABLE diprodi_equipos ADD COLUMN IF NOT EXISTS prima REAL",
        "ALTER TABLE diprodi_equipos ADD COLUMN IF NOT EXISTS interes REAL",
        "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS modalidad TEXT DEFAULT 'presencial'",
        "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS accepted_at TEXT DEFAULT ''",
        "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS completed_at TEXT DEFAULT ''",
        "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS video_link TEXT DEFAULT ''",
            "CREATE TABLE IF NOT EXISTS calendar_events (id TEXT PRIMARY KEY, company_id TEXT DEFAULT 'diprodi', title TEXT DEFAULT '', date TEXT NOT NULL, time TEXT DEFAULT '', color TEXT DEFAULT '#EF9F27', all_day INTEGER DEFAULT 0, notes TEXT DEFAULT '', blocks_booking INTEGER DEFAULT 0, created_at TEXT DEFAULT current_timestamp)",
    ]
    for sql in migrations:
        try:
            cur.execute(sql)
            print(f"✓ {sql[:60]}", flush=True)
        except Exception as e:
            print(f"skip: {e}", flush=True)
    conn.commit()
    conn.close()

migrate_db()

if __name__=="__main__":
    port=int(os.environ.get("PORT",5000))
    print(f"Servvoo en http://localhost:{port} — {'PostgreSQL' if is_pg() else 'SQLite'}",flush=True)
    app.run(host="0.0.0.0",port=port,debug=False)
# Servvoo v26 - Multi-tenant - 2026
