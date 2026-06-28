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

live_positions = {}
ws_clients = {}
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
            "CREATE TABLE IF NOT EXISTS clients (id TEXT PRIMARY KEY, name TEXT NOT NULL, contact TEXT DEFAULT '', phone TEXT DEFAULT '', email TEXT DEFAULT '', city TEXT DEFAULT '', department TEXT DEFAULT '', type TEXT DEFAULT 'Clinica', lat REAL, lng REAL, address TEXT DEFAULT '', rtn TEXT DEFAULT '', company_id TEXT DEFAULT 'diprodi', created_at TEXT DEFAULT current_timestamp)",
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
            "CREATE TABLE IF NOT EXISTS invitations (id TEXT PRIMARY KEY, company_id TEXT NOT NULL, code TEXT UNIQUE NOT NULL, email TEXT DEFAULT '', role TEXT DEFAULT 'technician', used INTEGER DEFAULT 0, created_at TEXT DEFAULT current_timestamp)",
        ]
        for t in tbls:
            try: cur.execute(t)
            except: pass
        for k,v in [('rate_per_km','5.0'),('maps_api_key',''),('company_name','DIPRODI'),('fuel_gas_price','95.0'),('fuel_diesel_price','85.0')]:
            try: cur.execute("INSERT INTO settings(key,value) VALUES(%s,%s) ON CONFLICT(key) DO NOTHING",(k,v))
            except: pass
        # Create DIPRODI as first company
        try:
            cur.execute("INSERT INTO companies(id,name,slug,logo,color,plan,rubro,phone,address) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING",
               ("diprodi","DIPRODI","diprodi","https://diprodi.net/public/uploads/1723666225_c80478b27ad98bae76d7.png",
                "#0F6E56","enterprise","veterinaria","2230-7121","Residencial Plaza, Casa 1, Bloque 32, Tegucigalpa"))
        except: pass
        cur.execute("SELECT COUNT(*) as c FROM users")
        count=cur.fetchone()["c"]
    else:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS companies(id TEXT PRIMARY KEY,name TEXT NOT NULL,slug TEXT UNIQUE NOT NULL,logo TEXT DEFAULT '',color TEXT DEFAULT '#0F6E56',plan TEXT DEFAULT 'basic',rubro TEXT DEFAULT 'general',rtn TEXT DEFAULT '',phone TEXT DEFAULT '',address TEXT DEFAULT '',active INTEGER DEFAULT 1,created_at TEXT DEFAULT(datetime('now')));
        CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,name TEXT NOT NULL,email TEXT UNIQUE NOT NULL,password_hash TEXT NOT NULL,role TEXT DEFAULT 'technician',color TEXT DEFAULT 'purple',phone TEXT DEFAULT '',status TEXT DEFAULT 'available',current_trip_id TEXT,rendimiento REAL DEFAULT 12,tipo_combustible TEXT DEFAULT 'gasolina',company_id TEXT DEFAULT 'diprodi',created_at TEXT DEFAULT(datetime('now')));
        CREATE TABLE IF NOT EXISTS inventory(id TEXT PRIMARY KEY,name TEXT NOT NULL,model TEXT NOT NULL,serial TEXT DEFAULT '',category TEXT DEFAULT '',stock INTEGER DEFAULT 0,unit_cost REAL DEFAULT 0,created_at TEXT DEFAULT(datetime('now')));
        CREATE TABLE IF NOT EXISTS clients(id TEXT PRIMARY KEY,name TEXT NOT NULL,contact TEXT DEFAULT '',phone TEXT DEFAULT '',email TEXT DEFAULT '',city TEXT DEFAULT '',department TEXT DEFAULT '',type TEXT DEFAULT 'Clinica',lat REAL,lng REAL,address TEXT DEFAULT '',rtn TEXT DEFAULT '',company_id TEXT DEFAULT 'diprodi',created_at TEXT DEFAULT(datetime('now')));
        CREATE TABLE IF NOT EXISTS trips(id TEXT PRIMARY KEY,technician_id TEXT NOT NULL,client_id TEXT NOT NULL,date TEXT NOT NULL,status TEXT DEFAULT 'pendiente',trip_type TEXT DEFAULT 'entrega',equipment_ids TEXT DEFAULT '[]',origin_lat REAL,origin_lng REAL,origin_label TEXT,destination_lat REAL,destination_lng REAL,destination_label TEXT,stops TEXT DEFAULT '[]',route_points TEXT DEFAULT '[]',start_time TEXT DEFAULT '',end_time TEXT DEFAULT '',km REAL DEFAULT 0,reimbursement REAL DEFAULT 0,notes TEXT DEFAULT '',report_id TEXT,report_num TEXT,company_id TEXT DEFAULT 'diprodi',created_at TEXT DEFAULT(datetime('now')));
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
        CREATE TABLE IF NOT EXISTS invitations(id TEXT PRIMARY KEY,company_id TEXT NOT NULL,code TEXT UNIQUE NOT NULL,email TEXT DEFAULT '',role TEXT DEFAULT 'technician',used INTEGER DEFAULT 0,created_at TEXT DEFAULT(datetime('now')));
        CREATE TABLE IF NOT EXISTS invoices(id TEXT PRIMARY KEY,invoice_num TEXT NOT NULL,client_id TEXT,client_name TEXT DEFAULT '',client_rtn TEXT DEFAULT '',client_address TEXT DEFAULT '',items TEXT DEFAULT '[]',subtotal REAL DEFAULT 0,isv_rate REAL DEFAULT 15,isv REAL DEFAULT 0,total REAL DEFAULT 0,status TEXT DEFAULT 'pendiente',payment_method TEXT DEFAULT 'efectivo',cai TEXT DEFAULT '',notes TEXT DEFAULT '',technician_id TEXT DEFAULT '',trip_id TEXT DEFAULT '',company_id TEXT DEFAULT 'diprodi',created_at TEXT DEFAULT(datetime('now')));
        CREATE TABLE IF NOT EXISTS invoice_sequence(id TEXT PRIMARY KEY,year INTEGER,month INTEGER,last_num INTEGER DEFAULT 0);
        """)
        conn.execute("INSERT OR IGNORE INTO companies(id,name,slug,color,plan,rubro,phone,address) VALUES(?,?,?,?,?,?,?,?)",
            ("diprodi","DIPRODI","diprodi","#0F6E56","enterprise","veterinaria","2230-7121","Residencial Plaza, Casa 1, Bloque 32, Tegucigalpa"))
        for k,v in [('rate_per_km','5.0'),('maps_api_key',''),('company_name','DIPRODI'),('fuel_gas_price','95.0'),('fuel_diesel_price','85.0')]:
            conn.execute("INSERT OR IGNORE INTO settings VALUES(?,?)",(k,v))
        count=conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if count==0:
        aid="admin_"+uuid.uuid4().hex[:8]
        ex(conn,"INSERT INTO users(id,name,email,password_hash,role,color,phone,status,company_id) VALUES(?,?,?,?,?,?,?,?,?)",
           (aid,"Administrador","admin@diprodi.hn",hash_pw("admin123"),"admin","blue","","available","diprodi"))
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


# ─── AUTH ───────────────────────────────────────────────────────────────────
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
    company_id = d.get("companyId","diprodi")
    conn=get_db()
    try:
        ex(conn,"INSERT INTO users(id,name,email,password_hash,role,color,phone,status,rendimiento,tipo_combustible,company_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
           ("u"+uid_,d["name"],d["email"].lower(),hash_pw(d.get("password","user123")),d.get("role","technician"),d.get("color","purple"),d.get("phone",""),"available",float(d.get("rendimiento",12)),d.get("tipoCombustible","gasolina"),company_id))
        if d.get("inviteCode"):
            ex(conn,"UPDATE invitations SET used=1 WHERE code=?",(d["inviteCode"],))
        conn.commit()
        cur=ex(conn,"SELECT * FROM users WHERE email=?",(d["email"].lower(),))
        row=mu(r2d(cur.fetchone())); conn.close()
        return jsonify(row)
    except Exception as e: conn.close(); return jsonify({"error":str(e)}),400

# ─── USERS ───────────────────────────────────────────────────────────────────
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
    for k,col in [("name","name"),("phone","phone"),("status","status"),("color","color"),("rendimiento","rendimiento"),("tipoCombustible","tipo_combustible"),("currentTripId","current_trip_id"),("role","role")]:
        if k in d: fields.append(f"{col}=?"); vals.append(d[k])
    if fields:
        vals.append(uid); ex(conn,f"UPDATE users SET {','.join(fields)} WHERE id=?",vals); conn.commit()
    cur=ex(conn,"SELECT * FROM users WHERE id=?",(uid,))
    row=mu(r2d(cur.fetchone())); conn.close(); return jsonify(row)

@app.route("/api/users/<uid>",methods=["DELETE"])
def delete_user(uid):
    conn=get_db(); ex(conn,"DELETE FROM users WHERE id=?",(uid,)); conn.commit(); conn.close()
    return jsonify({"ok":True})

# ─── INVENTORY ───────────────────────────────────────────────────────────────
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

# ─── CLIENTS ───────────────────────────────────────────────────────────────
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
    ex(conn,"INSERT INTO clients(id,name,contact,phone,email,city,department,type,lat,lng,address,rtn,company_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
       (cid,d["name"],d.get("contact",""),d.get("phone",""),d.get("email",""),d.get("city",""),d.get("department",""),d.get("type","Clinica"),d.get("lat"),d.get("lng"),d.get("address",""),d.get("rtn",""),d.get("companyId","diprodi")))
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

@app.route("/api/clients/deleteall", methods=["POST"])
def delete_all_clients():
    conn=get_db(); ex(conn,"DELETE FROM clients"); conn.commit(); conn.close()
    return jsonify({"ok":True})

@app.route("/api/clients/<cid>/history")
def client_history(cid):
    conn = get_db()
    cur = ex(conn, "SELECT * FROM trips WHERE client_id=? ORDER BY date DESC", (cid,))
    trips = [mt(r) for r in rlist(cur.fetchall())]
    cur2 = ex(conn, "SELECT * FROM visit_reports WHERE client_id=? ORDER BY created_at DESC", (cid,))
    reports = [mrep(r) for r in rlist(cur2.fetchall())]
    cur3 = ex(conn, "SELECT * FROM invoices WHERE client_id=? ORDER BY created_at DESC", (cid,))
    invoices = rlist(cur3.fetchall())
    conn.close()
    return jsonify({"trips":trips,"reports":reports,"invoices":invoices})


# ─── TRIPS ───────────────────────────────────────────────────────────────────
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
    cur_tech = ex(conn, "SELECT rendimiento, tipo_combustible FROM users WHERE id=?", (d["technicianId"],))
    tech_data = r2d(cur_tech.fetchone()) or {}
    rendimiento = float(tech_data.get("rendimiento") or 12)
    tipo_comb = tech_data.get("tipo_combustible") or "gasolina"
    cur_set = ex(conn, "SELECT value FROM settings WHERE key=?", (f"fuel_{tipo_comb}_price",))
    price_row = r2d(cur_set.fetchone())
    fuel_price = float(price_row["value"]) if price_row else 95.0
    litros = km / rendimiento if rendimiento > 0 else 0
    reimbursement = round(litros * fuel_price, 2)
    ex(conn,"INSERT INTO trips(id,technician_id,client_id,date,trip_type,equipment_ids,origin_lat,origin_lng,origin_label,destination_lat,destination_lng,destination_label,stops,route_points,start_time,end_time,km,reimbursement,notes) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
       (tid,d["technicianId"],d["clientId"],d["date"],d.get("tripType","entrega"),json.dumps(d.get("equipmentIds",[])),o.get("lat"),o.get("lng"),o.get("label",""),dest.get("lat"),dest.get("lng"),dest.get("label",""),json.dumps(d.get("stops",[])),json.dumps(d.get("routePoints",[])),d.get("startTime",""),d.get("endTime",""),km,reimbursement,d.get("notes","")))
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

# ─── SETTINGS ────────────────────────────────────────────────────────────────
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

# ─── REPORTS ─────────────────────────────────────────────────────────────────
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
    ex(conn,"INSERT INTO visit_reports(id,trip_id,technician_id,client_id,report_num,fecha,hora_llegada,hora_salida,marca,modelo,serie,condicion,reparaciones,repuestos,calibracion,control_calidad,signed,sig_time,sig_data) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
       (rid,d.get("tripId",""),tech_id,d.get("clientId",""),rnum,d.get("fecha",""),d.get("horaLlegada",""),d.get("horaSalida",""),d.get("marca",""),d.get("modelo",""),d.get("serie",""),d.get("condicion",""),d.get("reparaciones",""),d.get("repuestos",""),cal,cc,1 if d.get("signed") else 0,d.get("sigTime",""),d.get("sigData","")))
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
    html=f"""<!DOCTYPE html><html><head><meta charset="UTF-8"/><title>{rep['reportNum']}</title>
<style>body{{font-family:Arial,sans-serif;padding:24px;font-size:13px;}}
.header{{display:flex;justify-content:space-between;border-bottom:2px solid #0F6E56;padding-bottom:14px;margin-bottom:18px;}}
.rnum{{background:#E1F5EE;color:#0F6E56;padding:6px 14px;border-radius:20px;font-weight:700;font-family:monospace;}}
.sec{{border:1px solid #e0e0e0;border-radius:8px;padding:14px;margin-bottom:14px;}}
.g2{{display:grid;grid-template-columns:1fr 1fr;gap:12px;}}
.fl{{font-size:10px;color:#888;margin-bottom:3px;}}.fv{{background:#f7f7f7;border:1px solid #e0e0e0;border-radius:4px;padding:7px 10px;min-height:30px;}}
.fa{{background:#f7f7f7;border:1px solid #e0e0e0;border-radius:4px;padding:7px 10px;min-height:50px;}}
.sig{{border:1px dashed #0F6E56;border-radius:8px;padding:10px;text-align:center;min-height:100px;display:flex;align-items:center;justify-content:center;}}
.btn{{background:#0F6E56;color:white;border:none;padding:8px 20px;border-radius:6px;font-size:13px;cursor:pointer;}}
@media print{{.np{{display:none;}}}}</style></head>
<body>
<div class="np" style="text-align:right;margin-bottom:16px;"><button class="btn" onclick="window.print()">🖨️ Imprimir / PDF</button></div>
<div class="header">
<div style="display:flex;align-items:center;gap:12px;"><img src="https://diprodi.net/public/uploads/1723666225_c80478b27ad98bae76d7.png" style="height:50px;" onerror="this.style.display='none'"/>
<div><div style="font-weight:700;font-size:16px;color:#0F6E56;">DIPRODI</div><div style="font-size:11px;color:#555;">Reporte de visita técnica</div></div></div>
<div class="rnum">{rep['reportNum']}</div></div>
<div class="sec"><div class="g2">
<div><div class="fl">Fecha</div><div class="fv">{rep['fecha']}</div></div>
<div><div class="fl">Técnico</div><div class="fv">{tname}</div></div>
<div><div class="fl">Cliente</div><div class="fv">{cname} — {ccity}</div></div>
<div><div class="fl">Hora llegada / salida</div><div class="fv">{rep['horaLlegada']} / {rep['horaSalida']}</div></div>
</div></div>
<div class="sec"><div class="g2">
<div><div class="fl">Marca</div><div class="fv">{rep.get('marca','—')}</div></div>
<div><div class="fl">Modelo</div><div class="fv">{rep.get('modelo','—')}</div></div>
<div><div class="fl">No. de serie</div><div class="fv">{rep.get('serie','—')}</div></div>
</div></div>
<div class="sec"><div style="margin-bottom:10px;"><div class="fl">Condición</div><div class="fa">{rep.get('condicion','—')}</div></div>
<div style="margin-bottom:10px;"><div class="fl">Reparaciones</div><div class="fa">{rep.get('reparaciones','—')}</div></div>
<div><div class="fl">Repuestos</div><div class="fa">{rep.get('repuestos','—')}</div></div></div>
<div class="sec"><div style="display:flex;gap:30px;"><div><b>Calibración:</b> {cal}</div><div><b>Control calidad:</b> {cc}</div></div></div>
<div class="sec"><div class="g2">
<div><div class="fl">Técnico</div><div class="sig"><div>{tname}</div></div></div>
<div><div class="fl">Cliente</div><div class="sig">{sig}<div style="font-size:10px;margin-top:4px;">{'Firmado: '+rep['sigTime'] if rep.get('signed') else 'Sin firma'}</div></div></div>
</div></div>
<div style="text-align:center;font-size:10px;color:#aaa;border-top:1px solid #eee;padding-top:12px;">DIPRODI · Residencial Plaza, Casa 1, Bloque 32, Tegucigalpa · Tel: 2230-7121</div>
</body></html>"""
    return Response(html, mimetype='text/html')

# ─── GPS ─────────────────────────────────────────────────────────────────────
@app.route("/api/gps/update", methods=["POST"])
def update_gps():
    d = request.get_json()
    tech_id = d.get("technicianId")
    if not tech_id: return jsonify({"error": "No technicianId"}), 400
    live_positions[tech_id] = {"technicianId":tech_id,"lat":d.get("lat"),"lng":d.get("lng"),"km":d.get("km",0),"destName":d.get("destName",""),"tripType":d.get("tripType",""),"clientName":d.get("clientName",""),"status":"en_ruta","timestamp":datetime.now().isoformat()}
    return jsonify({"ok": True})

@app.route("/api/gps/clear", methods=["POST"])
def clear_gps():
    d = request.get_json()
    tech_id = d.get("technicianId")
    if tech_id and tech_id in live_positions: del live_positions[tech_id]
    return jsonify({"ok": True})

@app.route("/api/gps/live")
def get_live():
    return jsonify(list(live_positions.values()))


# ─── SALES GOALS ─────────────────────────────────────────────────────────────
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
    cur = ex(conn, "SELECT id FROM sales_goals WHERE user_id=? AND mes=?", (uid, mes))
    existing = r2d(cur.fetchone())
    if existing:
        ex(conn, "UPDATE sales_goals SET meta=? WHERE id=?", (d.get("meta", 0), existing["id"]))
    else:
        ex(conn, "INSERT INTO sales_goals(id,user_id,mes,meta) VALUES(?,?,?,?)", ("goal_"+uuid.uuid4().hex[:10], uid, mes, d.get("meta", 0)))
    conn.commit(); conn.close()
    return jsonify({"ok": True})

@app.route("/api/sales/records", methods=["POST"])
def add_sale():
    d = request.get_json()
    mes = datetime.now().strftime("%Y-%m")
    conn = get_db()
    ex(conn, "INSERT INTO sales_records(id,user_id,mes,monto,descripcion,cliente,fecha) VALUES(?,?,?,?,?,?,?)",
       ("sale_"+uuid.uuid4().hex[:10], d.get("userId",""), mes, float(d.get("monto",0)), d.get("descripcion",""), d.get("cliente",""), datetime.now().strftime("%Y-%m-%d")))
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
    if uid: cur = ex(conn, "SELECT * FROM sales_records WHERE user_id=? AND mes=? ORDER BY created_at DESC", (uid, mes))
    else: cur = ex(conn, "SELECT * FROM sales_records WHERE mes=? ORDER BY created_at DESC", (mes,))
    rows = rlist(cur.fetchall()); conn.close()
    return jsonify(rows)

# ─── ODOMETER ────────────────────────────────────────────────────────────────
@app.route("/api/odometer")
def get_odometer():
    uid = request.args.get("userId")
    mes = request.args.get("mes", datetime.now().strftime("%Y-%m"))
    conn = get_db()
    cur = ex(conn, "SELECT * FROM odometer_records WHERE user_id=? AND mes=? ORDER BY created_at DESC LIMIT 1", (uid, mes))
    row = r2d(cur.fetchone())
    cur2 = ex(conn, "SELECT SUM(km) as total FROM trips WHERE technician_id=? AND date LIKE ?", (uid, f"{mes}%"))
    km_laborales = float(r2d(cur2.fetchone()).get("total") or 0)
    conn.close()
    return jsonify({"record": row, "kmLaborales": km_laborales})

@app.route("/api/odometer", methods=["POST"])
def save_odometer():
    d = request.get_json()
    mes = d.get("mes", datetime.now().strftime("%Y-%m"))
    uid = d.get("userId")
    conn = get_db()
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
        ex(conn, "INSERT INTO odometer_records(id,user_id,mes,km_inicio,km_fin,factura_monto,km_laborales,reembolso) VALUES(?,?,?,?,?,?,?,?)",
           ("odo_"+uuid.uuid4().hex[:10], uid, mes, km_inicio, km_fin, factura, km_laborales, round(reembolso, 2)))
    conn.commit(); conn.close()
    return jsonify({"ok": True, "reembolso": round(reembolso, 2), "porcentaje": round(pct, 1)})

# ─── DIPRODI INVENTORY ───────────────────────────────────────────────────────
@app.route("/api/diprodi/equipos")
def get_equipos():
    estado = request.args.get("estado")
    conn = get_db()
    sql = "SELECT * FROM diprodi_equipos WHERE 1=1"
    params = []
    if estado: sql += " AND estado=?"; params.append(estado)
    sql += " ORDER BY num"
    cur = ex(conn, sql, params)
    rows = rlist(cur.fetchall()); conn.close()
    return jsonify(rows)

@app.route("/api/diprodi/equipos", methods=["POST"])
def add_equipo():
    d = request.get_json(); eid = "eq_" + uuid.uuid4().hex[:10]
    conn = get_db()
    ex(conn, "INSERT INTO diprodi_equipos(id,num,localizacion,cliente,tipo,modelo,serie,fecha_ingreso,fecha_instalacion,version_sw,comentarios,estado,modalidad,categoria) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
       (eid,d.get("num",0),d.get("localizacion",""),d.get("cliente",""),d.get("tipo",""),d.get("modelo",""),d.get("serie",""),d.get("fechaIngreso",""),d.get("fechaInstalacion",""),d.get("versionSw",""),d.get("comentarios",""),d.get("estado","instalado"),d.get("modalidad","leasing"),d.get("categoria","equipo")))
    conn.commit()
    cur = ex(conn, "SELECT * FROM diprodi_equipos WHERE id=?", (eid,))
    row = r2d(cur.fetchone()); conn.close()
    return jsonify(row)

@app.route("/api/diprodi/equipos/<eid>", methods=["PATCH"])
def update_equipo(eid):
    d = request.get_json(); conn = get_db(); fields, vals = [], []
    for k,col in [("estado","estado"),("modalidad","modalidad"),("contratoInicio","contrato_inicio"),("contratoMeses","contrato_meses"),("contratoValor","contrato_valor"),("cuotaMensual","cuota_mensual"),("prima","prima"),("interes","interes"),("comentarios","comentarios"),("versionSw","version_sw"),("fechaInstalacion","fecha_instalacion")]:
        if k in d: fields.append(f"{col}=?"); vals.append(d[k])
    if fields:
        vals.append(eid); ex(conn, f"UPDATE diprodi_equipos SET {','.join(fields)} WHERE id=?", vals); conn.commit()
    cur = ex(conn, "SELECT * FROM diprodi_equipos WHERE id=?", (eid,))
    row = r2d(cur.fetchone()); conn.close()
    return jsonify(row)

@app.route("/api/diprodi/bulk", methods=["POST"])
def bulk_import():
    d = request.get_json(); conn = get_db()
    equipos = d.get("equipos", []); accesorios = d.get("accesorios", []); repuestos = d.get("repuestos", [])
    imported = {"equipos": 0, "accesorios": 0, "repuestos": 0}
    for e in equipos:
        eid = "eq_" + uuid.uuid4().hex[:10]
        estado = "bodega" if e.get("cliente","").lower() in ["globalvet","bodega",""] else "instalado"
        try:
            ex(conn, "INSERT INTO diprodi_equipos(id,num,localizacion,cliente,tipo,modelo,serie,fecha_ingreso,fecha_instalacion,version_sw,comentarios,estado,categoria) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (eid,e.get("num",0),e.get("localizacion",""),e.get("cliente",""),e.get("tipo",""),e.get("modelo",""),e.get("serie",""),e.get("fechaIngreso",""),e.get("fechaInstalacion",""),e.get("versionSw",""),e.get("comentarios",""),estado,"equipo"))
            imported["equipos"] += 1
        except: pass
    for a in accesorios:
        try:
            ex(conn, "INSERT INTO diprodi_accesorios(id,tipo,modelo,serie,cantidad,cliente,localizacion,estado,categoria) VALUES(?,?,?,?,?,?,?,?,?)",
               ("acc_"+uuid.uuid4().hex[:10],a.get("tipo",""),a.get("modelo",""),a.get("serie",""),a.get("cantidad",1),a.get("cliente",""),a.get("localizacion","Bodega"),"instalado" if a.get("cliente") else "disponible","accesorio"))
            imported["accesorios"] += 1
        except: pass
    for r in repuestos:
        try:
            ex(conn, "INSERT INTO diprodi_repuestos(id,num,localizacion,cliente,equipo,modelo,num_parte,nombre,cantidad,fecha_ingreso,categoria) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
               ("rep_"+uuid.uuid4().hex[:10],r.get("num",0),r.get("localizacion","Bodega"),r.get("cliente","GlobalVet"),r.get("equipo",""),r.get("modelo",""),r.get("numParte",""),r.get("nombre",""),r.get("cantidad",1),r.get("fechaIngreso",""),"repuesto"))
            imported["repuestos"] += 1
        except: pass
    conn.commit(); conn.close()
    return jsonify({"ok": True, "imported": imported})

@app.route("/api/diprodi/repuestos")
def get_repuestos():
    conn = get_db()
    cur = ex(conn, "SELECT * FROM diprodi_repuestos ORDER BY num")
    rows = rlist(cur.fetchall()); conn.close()
    return jsonify(rows)

@app.route("/api/diprodi/accesorios")
def get_accesorios():
    conn = get_db()
    cur = ex(conn, "SELECT * FROM diprodi_accesorios ORDER BY tipo")
    rows = rlist(cur.fetchall()); conn.close()
    return jsonify(rows)

@app.route("/api/diprodi/stats")
def get_inventory_stats():
    conn = get_db()
    stats = {}
    cur = ex(conn, "SELECT estado, COUNT(*) as c FROM diprodi_equipos GROUP BY estado")
    stats["byEstado"] = {r["estado"]: r["c"] for r in rlist(cur.fetchall())}
    cur = ex(conn, "SELECT COUNT(*) as c FROM diprodi_equipos"); stats["totalEquipos"] = r2d(cur.fetchone())["c"]
    cur = ex(conn, "SELECT COUNT(*) as c FROM diprodi_accesorios"); stats["totalAccesorios"] = r2d(cur.fetchone())["c"]
    cur = ex(conn, "SELECT COUNT(*) as c FROM diprodi_repuestos"); stats["totalRepuestos"] = r2d(cur.fetchone())["c"]
    cur = ex(conn, "SELECT COUNT(*) as c FROM diprodi_equipos WHERE estado='bodega'"); stats["enBodega"] = r2d(cur.fetchone())["c"]
    conn.close()
    return jsonify(stats)

@app.route("/api/diprodi/export")
def export_inventory():
    import io, csv
    conn = get_db()
    cur = ex(conn, "SELECT * FROM diprodi_equipos ORDER BY num")
    equipos = rlist(cur.fetchall()); conn.close()
    output = io.StringIO(); writer = csv.writer(output)
    writer.writerow(["#","Localizacion","Cliente","Tipo","Modelo","Serie","Fecha Ingreso","Fecha Instalacion","Version SW","Estado","Comentarios"])
    for e in equipos:
        writer.writerow([e.get("num",""),e.get("localizacion",""),e.get("cliente",""),e.get("tipo",""),e.get("modelo",""),e.get("serie",""),e.get("fecha_ingreso",""),e.get("fecha_instalacion",""),e.get("version_sw",""),e.get("estado",""),e.get("comentarios","")])
    return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition":"attachment;filename=inventario_diprodi.csv"})


# ─── INVOICES ────────────────────────────────────────────────────────────────
@app.route("/api/invoices")
def get_invoices():
    conn = get_db()
    cur = ex(conn, "SELECT * FROM invoices ORDER BY created_at DESC")
    rows = rlist(cur.fetchall()); conn.close()
    result = []
    for r in rows:
        r["items"] = json.loads(r.get("items","[]"))
        result.append(r)
    return jsonify(result)

@app.route("/api/invoices", methods=["POST"])
def create_invoice():
    d = request.get_json(); iid = "inv_" + uuid.uuid4().hex[:10]
    now = datetime.now(); year, month = now.year, now.month
    conn = get_db()
    cur = ex(conn, "SELECT last_num FROM invoice_sequence WHERE year=? AND month=?", (year, month))
    seq_row = r2d(cur.fetchone())
    if seq_row:
        new_num = int(seq_row["last_num"]) + 1
        ex(conn, "UPDATE invoice_sequence SET last_num=? WHERE year=? AND month=?", (new_num, year, month))
    else:
        new_num = 1
        ex(conn, "INSERT INTO invoice_sequence(id,year,month,last_num) VALUES(?,?,?,?)", (f"seq_{year}_{month}", year, month, 1))
    invoice_num = f"FAC-{year}{str(month).zfill(2)}-{str(new_num).zfill(4)}"
    items = d.get("items", [])
    subtotal = sum(float(i.get("qty",1)) * float(i.get("price",0)) for i in items)
    isv_rate = float(d.get("isvRate", 15))
    isv = round(subtotal * (isv_rate/100), 2)
    total = round(subtotal + isv, 2)
    client_name = d.get("clientName",""); client_rtn = d.get("clientRtn",""); client_address = d.get("clientAddress","")
    if d.get("clientId"):
        cur2 = ex(conn, "SELECT name,rtn,address,city FROM clients WHERE id=?", (d["clientId"],))
        cl = r2d(cur2.fetchone())
        if cl:
            client_name = client_name or cl.get("name","")
            client_rtn = client_rtn or cl.get("rtn","")
            client_address = client_address or f"{cl.get('address','')} {cl.get('city','')}".strip()
    ex(conn, "INSERT INTO invoices(id,invoice_num,client_id,client_name,client_rtn,client_address,items,subtotal,isv_rate,isv,total,status,payment_method,cai,notes,technician_id,trip_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
       (iid,invoice_num,d.get("clientId",""),client_name,client_rtn,client_address,json.dumps(items),subtotal,isv_rate,isv,total,d.get("status","pendiente"),d.get("paymentMethod","efectivo"),d.get("cai",""),d.get("notes",""),d.get("technicianId",""),d.get("tripId","")))
    conn.commit(); conn.close()
    return jsonify({"id":iid,"invoiceNum":invoice_num,"total":total})

@app.route("/api/invoices/<iid>", methods=["PATCH"])
def update_invoice(iid):
    d = request.get_json(); conn = get_db(); fields, vals = [], []
    for k,col in [("status","status"),("paymentMethod","payment_method"),("notes","notes")]:
        if k in d: fields.append(f"{col}=?"); vals.append(d[k])
    if fields:
        vals.append(iid); ex(conn, f"UPDATE invoices SET {','.join(fields)} WHERE id=?", vals); conn.commit()
    conn.close()
    return jsonify({"ok":True})

@app.route("/api/invoices/<iid>/pdf")
def invoice_pdf(iid):
    conn = get_db()
    cur = ex(conn, "SELECT * FROM invoices WHERE id=?", (iid,))
    inv = r2d(cur.fetchone())
    cur2 = ex(conn, "SELECT key,value FROM settings WHERE key IN ('company_name','company_address','company_phone','company_rtn')")
    settings = {r["key"]:r["value"] for r in rlist(cur2.fetchall())}
    conn.close()
    if not inv: return "Factura no encontrada", 404
    items = json.loads(inv.get("items","[]"))
    company = settings.get("company_name","DIPRODI")
    address = settings.get("company_address","Residencial Plaza, Casa 1, Bloque 32, Tegucigalpa")
    phone = settings.get("company_phone","2230-7121")
    rtn_co = settings.get("company_rtn","")
    fmt = lambda n: f"L.{float(n):,.2f}"
    items_html = "".join([f"<tr><td style='padding:8px;border-bottom:1px solid #eee;'>{i.get('description','')}</td><td style='padding:8px;text-align:center;border-bottom:1px solid #eee;'>{i.get('qty',1)}</td><td style='padding:8px;text-align:right;border-bottom:1px solid #eee;font-family:monospace;'>L.{float(i.get('price',0)):,.2f}</td><td style='padding:8px;text-align:right;border-bottom:1px solid #eee;font-family:monospace;font-weight:600;'>L.{float(i.get('qty',1))*float(i.get('price',0)):,.2f}</td></tr>" for i in items])
    html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8"/><title>Factura {inv['invoice_num']}</title>
<style>*{{box-sizing:border-box;margin:0;padding:0;}}body{{font-family:Arial,sans-serif;padding:30px;font-size:13px;}}
.header{{display:flex;justify-content:space-between;border-bottom:3px solid #0F6E56;padding-bottom:16px;margin-bottom:20px;}}
table{{width:100%;border-collapse:collapse;margin-bottom:16px;}}thead{{background:#0F6E56;color:white;}}thead th{{padding:10px;text-align:left;}}
.totals{{margin-left:auto;width:260px;}}.total-row{{display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid #eee;}}
.total-final{{display:flex;justify-content:space-between;padding:10px 0;font-size:16px;font-weight:800;color:#0F6E56;border-top:2px solid #0F6E56;}}
.btn{{background:#0F6E56;color:white;border:none;padding:8px 20px;border-radius:6px;cursor:pointer;}}
@media print{{.np{{display:none;}}}}</style></head>
<body>
<div class="np" style="text-align:right;margin-bottom:16px;"><button class="btn" onclick="window.print()">🖨️ Imprimir / PDF</button></div>
<div class="header">
<div><h1 style="color:#0F6E56;font-size:22px;">{company}</h1><p style="color:#666;font-size:12px;">{address} · Tel: {phone}{f' · RTN: {rtn_co}' if rtn_co else ''}</p></div>
<div style="text-align:right;"><div style="background:#E1F5EE;color:#0F6E56;padding:8px 16px;border-radius:20px;font-weight:800;font-family:monospace;">{inv['invoice_num']}</div>
<p style="margin-top:8px;font-size:12px;color:#666;">Fecha: {inv['created_at'][:10]}</p>
{f'<p style="font-size:11px;color:#888;">CAI: {inv["cai"]}</p>' if inv.get('cai') else ''}</div></div>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:20px;">
<div style="background:#f8f8f8;border-radius:8px;padding:14px;"><p><strong>{inv.get('client_name','—')}</strong><br/>{f'RTN: {inv["client_rtn"]}' if inv.get('client_rtn') else ''}<br/>{inv.get('client_address','')}</p></div>
<div style="background:#f8f8f8;border-radius:8px;padding:14px;"><p>Método: <strong>{inv.get('payment_method','—').title()}</strong><br/>ISV: {inv.get('isv_rate',15)}%</p></div></div>
<table><thead><tr><th>Descripción</th><th style="text-align:center;">Cant.</th><th style="text-align:right;">Precio unit.</th><th style="text-align:right;">Total</th></tr></thead><tbody>{items_html}</tbody></table>
<div class="totals">
<div class="total-row"><span>Subtotal</span><span style="font-family:monospace;">{fmt(inv['subtotal'])}</span></div>
<div class="total-row"><span>ISV ({inv['isv_rate']}%)</span><span style="font-family:monospace;">{fmt(inv['isv'])}</span></div>
<div class="total-final"><span>TOTAL</span><span style="font-family:monospace;">{fmt(inv['total'])}</span></div></div>
{f'<div style="margin-top:16px;padding:10px;background:#f8f8f8;border-radius:8px;font-size:12px;"><strong>Notas:</strong> {inv["notes"]}</div>' if inv.get('notes') else ''}
<div style="text-align:center;font-size:11px;color:#aaa;border-top:1px solid #eee;padding-top:12px;margin-top:20px;">{company} · {address} · Generado por Servvoo</div>
</body></html>"""
    return Response(html, mimetype="text/html")

# ─── AI ──────────────────────────────────────────────────────────────────────
import os as _os
ANTHROPIC_KEY = _os.environ.get("ANTHROPIC_API_KEY","")

@app.route("/api/ai/chat", methods=["POST"])
def ai_chat():
    import urllib.request as _req
    d = request.get_json()
    if not ANTHROPIC_KEY: return jsonify({"error": "API key no configurada"}), 400
    try:
        conn = get_db()
        company_id = d.get("companyId","diprodi")
        cur = ex(conn, "SELECT COUNT(*) as c FROM trips WHERE company_id=?", (company_id,)); trip_count = int(r2d(cur.fetchone()).get("c") or 0)
        cur = ex(conn, "SELECT COUNT(*) as c FROM clients WHERE company_id=?", (company_id,)); client_count = int(r2d(cur.fetchone()).get("c") or 0)
        cur = ex(conn, "SELECT SUM(total) as t FROM invoices WHERE company_id=?", (company_id,)); revenue = float(r2d(cur.fetchone()).get("t") or 0)
        cur = ex(conn, "SELECT name,rubro FROM companies WHERE id=?", (company_id,)); co = r2d(cur.fetchone()) or {}
        conn.close()
        system_prompt = f"""Eres el asistente de negocios de Servvoo para la empresa "{co.get('name','')}" en el rubro {co.get('rubro','general')}. Datos: {trip_count} viajes, {client_count} clientes, L.{revenue:,.2f} ingresos. Eres experto en negocios de Honduras y Centroamerica. Respondes en español, eres conciso y práctico."""
        payload = json.dumps({"model":"claude-sonnet-4-6","max_tokens":1000,"system":system_prompt,"messages":[{"role":"user","content":d.get("message","")}]}).encode()
        req = _req.Request("https://api.anthropic.com/v1/messages",data=payload,headers={"Content-Type":"application/json","x-api-key":ANTHROPIC_KEY,"anthropic-version":"2023-06-01"})
        with _req.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            return jsonify({"response": result["content"][0]["text"]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ─── CALENDAR ────────────────────────────────────────────────────────────────
@app.route("/api/calendar/events")
def get_events():
    company_id = request.args.get("companyId","diprodi")
    month = request.args.get("month", datetime.now().strftime("%Y-%m"))
    conn = get_db()
    cur = ex(conn, "SELECT id,client_name,date,time,tipo_servicio,status FROM bookings WHERE date LIKE ? ORDER BY date,time", (f"{month}%",))
    bookings = rlist(cur.fetchall())
    try:
        cur2 = ex(conn, "SELECT * FROM calendar_events WHERE company_id=? AND date LIKE ? ORDER BY date,time", (company_id, f"{month}%"))
        manual = rlist(cur2.fetchall())
    except: manual = []
    conn.close()
    events = [{"id":b["id"],"title":f"{b['client_name']} - {b['tipo_servicio']}","date":b["date"],"time":b["time"],"type":"booking","status":b["status"],"color":"#185FA5"} for b in bookings]
    events += [{"id":e["id"],"title":e.get("title",""),"date":e.get("date",""),"time":e.get("time",""),"type":"manual","color":e.get("color","#EF9F27"),"notes":e.get("notes","")} for e in manual]
    return jsonify(events)

@app.route("/api/calendar/events", methods=["POST"])
def create_event():
    d = request.get_json(); eid = "evt_" + uuid.uuid4().hex[:10]; company_id = d.get("companyId","diprodi")
    conn = get_db()
    ex(conn, "INSERT INTO calendar_events(id,company_id,title,date,time,color,all_day,notes,blocks_booking) VALUES(?,?,?,?,?,?,?,?,?)",
       (eid,company_id,d.get("title",""),d.get("date",""),d.get("time",""),d.get("color","#EF9F27"),1 if d.get("allDay") else 0,d.get("notes",""),1 if d.get("blocksBooking") else 0))
    conn.commit(); conn.close()
    return jsonify({"id":eid,"ok":True})

@app.route("/api/calendar/events/<eid>", methods=["DELETE"])
def delete_event(eid):
    conn = get_db(); ex(conn, "DELETE FROM calendar_events WHERE id=?", (eid,)); conn.commit(); conn.close()
    return jsonify({"ok":True})

# ─── FINANCE ─────────────────────────────────────────────────────────────────
@app.route("/api/finance/summary")
def finance_summary():
    company_id = request.args.get("companyId","diprodi")
    month = request.args.get("month", datetime.now().strftime("%Y-%m"))
    conn = get_db()
    cur = ex(conn, "SELECT SUM(total) as t,COUNT(*) as c FROM invoices WHERE company_id=? AND created_at LIKE ? AND status='pagada'", (company_id, f"{month}%"))
    rev = r2d(cur.fetchone())
    cur2 = ex(conn, "SELECT SUM(total) as t FROM invoices WHERE company_id=? AND created_at LIKE ? AND status='pendiente'", (company_id, f"{month}%"))
    pend = r2d(cur2.fetchone())
    cur3 = ex(conn, "SELECT SUM(reimbursement) as t FROM trips WHERE company_id=? AND date LIKE ?", (company_id, f"{month}%"))
    reimb = r2d(cur3.fetchone())
    cur4 = ex(conn, "SELECT tipo_servicio,COUNT(*) as c FROM bookings WHERE created_at LIKE ? GROUP BY tipo_servicio ORDER BY c DESC LIMIT 5", (f"{month}%",))
    top_services = rlist(cur4.fetchall())
    cur5 = ex(conn, "SELECT COUNT(*) as c FROM clients WHERE company_id=? AND created_at LIKE ?", (company_id, f"{month}%"))
    new_clients = int(r2d(cur5.fetchone()).get("c") or 0)
    conn.close()
    income = float(rev.get("t") or 0); expenses = float(reimb.get("t") or 0)
    return jsonify({"income":income,"invoiceCount":int(rev.get("c") or 0),"pending":float(pend.get("t") or 0),"expenses":expenses,"profit":income-expenses,"topServices":top_services,"newClients":new_clients})


# ─── INVITATIONS ─────────────────────────────────────────────────────────────
@app.route("/api/invitations", methods=["POST"])
def create_invitation():
    import secrets as _secrets
    d = request.get_json(); code = _secrets.token_urlsafe(8); company_id = d.get("companyId","diprodi")
    conn = get_db()
    ex(conn, "INSERT INTO invitations(id,company_id,code,email,role) VALUES(?,?,?,?,?)", ("inv_"+uuid.uuid4().hex[:8], company_id, code, d.get("email",""), d.get("role","technician")))
    conn.commit(); conn.close()
    invite_url = f"{request.host_url}unirse/{code}"
    return jsonify({"code":code,"url":invite_url})

@app.route("/api/invitations")
def get_invitations():
    company_id = request.args.get("companyId","diprodi")
    conn = get_db()
    cur = ex(conn, "SELECT * FROM invitations WHERE company_id=? ORDER BY created_at DESC", (company_id,))
    rows = rlist(cur.fetchall()); conn.close()
    return jsonify(rows)

@app.route("/api/invitations/<code>/validate")
def validate_invitation(code):
    conn = get_db()
    cur = ex(conn, "SELECT * FROM invitations WHERE code=? AND used=0", (code,))
    inv = r2d(cur.fetchone()); conn.close()
    if not inv: return jsonify({"valid":False,"error":"Código inválido o ya utilizado"}), 400
    return jsonify({"valid":True,"companyId":inv["company_id"],"role":inv["role"],"email":inv["email"]})

@app.route("/unirse/<code>")
def join_page(code):
    html = f"""<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Unirse a Servvoo</title>
<style>*{{box-sizing:border-box;margin:0;padding:0;}}body{{font-family:Arial,sans-serif;background:linear-gradient(135deg,#0C447C,#1D9E75);min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px;}}
.card{{background:white;border-radius:20px;padding:32px 28px;width:100%;max-width:400px;box-shadow:0 24px 64px rgba(0,0,0,.3);}}
h1{{font-size:28px;font-weight:800;background:linear-gradient(135deg,#185FA5,#0F6E56);-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:4px;}}
p{{color:#666;font-size:13px;margin-bottom:20px;}}.field{{margin-bottom:12px;}}
.field label{{display:block;font-size:12px;color:#666;margin-bottom:4px;font-weight:600;}}
.field input{{width:100%;padding:10px 12px;border:1px solid #ddd;border-radius:8px;font-size:14px;}}
.btn{{width:100%;background:linear-gradient(135deg,#185FA5,#0F6E56);color:white;border:none;border-radius:10px;padding:14px;font-size:15px;font-weight:700;cursor:pointer;margin-top:8px;}}
.btn:disabled{{opacity:0.5;cursor:not-allowed;}}.error{{background:#FCEBEB;color:#C0392B;border-radius:8px;padding:10px;font-size:13px;margin-bottom:10px;display:none;}}
</style></head><body><div class="card">
<h1>Servvoo</h1><p>Te han invitado a unirte. Crea tu cuenta para continuar.</p>
<div id="error" class="error"></div>
<div class="field"><label>Nombre completo</label><input id="name" type="text" placeholder="Ej: Juan Pérez"/></div>
<div class="field"><label>Teléfono</label><input id="phone" type="tel" placeholder="+504 9xxx-xxxx"/></div>
<div class="field"><label>Correo electrónico</label><input id="email" type="email" placeholder="correo@empresa.com"/></div>
<div class="field"><label>Contraseña</label><input id="password" type="password" placeholder="Mínimo 6 caracteres"/></div>
<div class="field"><label>Confirmar contraseña</label><input id="confirm" type="password" placeholder="Repetir contraseña"/></div>
<button class="btn" id="submitBtn" onclick="register()">✅ Crear mi cuenta</button>
</div>
<script>
async function register(){{
  const err = document.getElementById('error');err.style.display='none';
  const name=document.getElementById('name').value.trim(),phone=document.getElementById('phone').value.trim(),email=document.getElementById('email').value.trim(),password=document.getElementById('password').value,confirm=document.getElementById('confirm').value;
  if(!name||!email||!password){{err.textContent='Completa todos los campos';err.style.display='block';return;}}
  if(password!==confirm){{err.textContent='Las contraseñas no coinciden';err.style.display='block';return;}}
  document.getElementById('submitBtn').disabled=true;document.getElementById('submitBtn').textContent='Creando...';
  try{{
    const val=await fetch('/api/invitations/{code}/validate').then(r=>r.json());
    if(!val.valid){{err.textContent=val.error||'Código inválido';err.style.display='block';document.getElementById('submitBtn').disabled=false;document.getElementById('submitBtn').textContent='✅ Crear mi cuenta';return;}}
    const res=await fetch('/api/register',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{name,phone,email,password,role:val.role,companyId:val.companyId,inviteCode:'{code}'}})}});
    const data=await res.json();
    if(data.id){{document.querySelector('.card').innerHTML='<div style="text-align:center;padding:20px;"><div style="font-size:48px;">🎉</div><h2 style="color:#0F6E56;margin:12px 0;">¡Cuenta creada!</h2><p>Ya puedes entrar a <a href="https://servvoo.com/app" style="color:#185FA5;">servvoo.com/app</a></p></div>';}}
    else{{err.textContent=data.error||'Error al crear cuenta';err.style.display='block';document.getElementById('submitBtn').disabled=false;document.getElementById('submitBtn').textContent='✅ Crear mi cuenta';}}
  }}catch(e){{err.textContent='Error de conexión';err.style.display='block';document.getElementById('submitBtn').disabled=false;document.getElementById('submitBtn').textContent='✅ Crear mi cuenta';}}
}}
</script></body></html>"""
    return Response(html, mimetype='text/html')

# ─── COMPANIES ───────────────────────────────────────────────────────────────
@app.route("/api/companies")
def get_companies():
    conn=get_db(); cur=ex(conn,"SELECT * FROM companies ORDER BY name"); rows=rlist(cur.fetchall()); conn.close()
    return jsonify(rows)

@app.route("/api/companies", methods=["POST"])
def create_company():
    d=request.get_json(); cid="co_"+uuid.uuid4().hex[:8]; slug=d.get("name","").lower().replace(" ","_")[:20]
    conn=get_db()
    ex(conn,"INSERT INTO companies(id,name,slug,color,plan,rubro,phone,address,rtn) VALUES(?,?,?,?,?,?,?,?,?)",
       (cid,d["name"],slug,d.get("color","#185FA5"),d.get("plan","basic"),d.get("rubro","general"),d.get("phone",""),d.get("address",""),d.get("rtn","")))
    uid="u_"+uuid.uuid4().hex[:8]
    ex(conn,"INSERT INTO users(id,name,email,password_hash,role,color,status,company_id) VALUES(?,?,?,?,?,?,?,?)",
       (uid,d.get("adminName","Administrador"),d.get("adminEmail",""),hash_pw(d.get("adminPassword","admin123")),"admin","blue","available",cid))
    conn.commit(); cur=ex(conn,"SELECT * FROM companies WHERE id=?",(cid,)); row=r2d(cur.fetchone()); conn.close()
    return jsonify({"company":row,"userId":uid})

@app.route("/api/companies/<cid>", methods=["PATCH"])
def update_company(cid):
    d=request.get_json(); conn=get_db(); fields,vals=[],[]
    for k,col in [("name","name"),("plan","plan"),("rubro","rubro"),("phone","phone"),("address","address"),("rtn","rtn"),("active","active")]:
        if k in d: fields.append(f"{col}=?"); vals.append(d[k])
    if fields:
        vals.append(cid); ex(conn,f"UPDATE companies SET {','.join(fields)} WHERE id=?",vals); conn.commit()
    cur=ex(conn,"SELECT * FROM companies WHERE id=?",(cid,)); row=r2d(cur.fetchone()); conn.close()
    return jsonify(row)

@app.route("/api/superadmin/stats")
def superadmin_stats():
    conn=get_db()
    cur=ex(conn,"SELECT COUNT(*) as c FROM companies WHERE active=1"); companies=int(r2d(cur.fetchone()).get("c") or 0)
    cur=ex(conn,"SELECT COUNT(*) as c FROM users"); users=int(r2d(cur.fetchone()).get("c") or 0)
    cur=ex(conn,"SELECT COUNT(*) as c FROM trips"); trips=int(r2d(cur.fetchone()).get("c") or 0)
    cur=ex(conn,"SELECT COUNT(*) as c FROM invoices"); invoices=int(r2d(cur.fetchone()).get("c") or 0)
    conn.close()
    return jsonify({"companies":companies,"users":users,"trips":trips,"invoices":invoices})

# ─── BOOKING ─────────────────────────────────────────────────────────────────
@app.route("/api/booking/slots")
def get_slots():
    from datetime import timedelta
    conn = get_db(); today = datetime.now().date(); slots = []
    for i in range(1, 8):
        d = today + timedelta(days=i)
        if d.weekday() < 5:
            date_str = d.strftime("%Y-%m-%d")
            for hour in ["08:00","09:00","10:00","11:00","14:00","15:00","16:00"]:
                cur2 = ex(conn, "SELECT id FROM bookings WHERE date=? AND time=? AND status!='cancelado'", (date_str, hour))
                booked = r2d(cur2.fetchone())
                slots.append({"date":date_str,"time":hour,"available":booked is None})
    conn.close()
    return jsonify(slots)

@app.route("/api/booking", methods=["POST"])
def create_booking():
    d = request.get_json(); bid = "book_" + uuid.uuid4().hex[:10]; conn = get_db()
    cur = ex(conn, "SELECT id FROM bookings WHERE date=? AND time=? AND status!='cancelado'", (d.get("date",""), d.get("time","")))
    if r2d(cur.fetchone()): conn.close(); return jsonify({"error":"Horario no disponible"}), 400
    ex(conn, "INSERT INTO bookings(id,client_name,client_phone,client_email,equipo,tipo_servicio,modalidad,date,time,status,notas) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
       (bid,d.get("clientName",""),d.get("clientPhone",""),d.get("clientEmail",""),d.get("equipo",""),d.get("tipoServicio","mantenimiento"),d.get("modalidad","presencial"),d.get("date",""),d.get("time",""),"pendiente",d.get("notas","")))
    conn.commit(); conn.close()
    return jsonify({"ok":True,"id":bid})

@app.route("/api/booking", methods=["GET"])
def get_bookings():
    conn = get_db()
    cur = ex(conn, "SELECT * FROM bookings ORDER BY date, time")
    rows = rlist(cur.fetchall()); conn.close()
    return jsonify(rows)

@app.route("/api/booking/<bid>", methods=["PATCH"])
def update_booking(bid):
    d = request.get_json(); conn = get_db(); fields, vals = [], []
    for k,col in [("status","status"),("technicianId","technician_id"),("notas","notas"),("videoLink","video_link"),("acceptedAt","accepted_at"),("completedAt","completed_at")]:
        if k in d: fields.append(f"{col}=?"); vals.append(d[k])
    if d.get("status")=="confirmado": fields.append("accepted_at=?"); vals.append(datetime.now().isoformat())
    if d.get("status")=="completado": fields.append("completed_at=?"); vals.append(datetime.now().isoformat())
    if fields:
        vals.append(bid); ex(conn, f"UPDATE bookings SET {','.join(fields)} WHERE id=?", vals); conn.commit()
    cur = ex(conn, "SELECT * FROM bookings WHERE id=?", (bid,)); row = r2d(cur.fetchone()); conn.close()
    return jsonify(row or {"ok":True})

@app.route("/api/booking/tech/<tech_id>")
def get_tech_bookings(tech_id):
    conn = get_db()
    cur = ex(conn, "SELECT * FROM bookings WHERE technician_id=? AND status NOT IN ('cancelado','completado') ORDER BY date,time", (tech_id,))
    rows = rlist(cur.fetchall()); conn.close()
    return jsonify(rows)

@app.route("/cancelar/<bid>")
def cancel_page(bid):
    conn = get_db()
    cur = ex(conn, "SELECT * FROM bookings WHERE id=?", (bid,))
    b = r2d(cur.fetchone())
    if not b: conn.close(); return "<h2>Cita no encontrada</h2>", 404
    if b["status"] in ("cancelado","completado"):
        conn.close()
        msg = "completada" if b["status"]=="completado" else "cancelada"
        return f"<html><body style='font-family:Arial;text-align:center;padding:40px;'><h2>Esta cita ya fue {msg}</h2><a href='/agendar'>Agendar nueva cita</a></body></html>", 200
    ex(conn, "UPDATE bookings SET status='cancelado' WHERE id=?", (bid,)); conn.commit(); conn.close()
    return f"<html><body style='font-family:Arial;text-align:center;padding:40px;background:#f0f4f8;'><div style='background:white;border-radius:12px;padding:24px;max-width:400px;margin:0 auto;'><div style='font-size:48px;'>✅</div><h2 style='color:#0F6E56;'>Cita cancelada</h2><p>Tu cita del {b['date']} a las {b['time']} fue cancelada.</p><a href='/agendar' style='color:#185FA5;'>Reagendar</a></div></body></html>", 200

@app.route("/agendar")
@app.route("/agendar/<company>")
def booking_page(company="DIPRODI"):
    return send_from_directory("static","agendar.html") if os.path.exists("static/agendar.html") else Response("<h2>Página de agenda próximamente</h2>", mimetype='text/html')

# ─── STATIC ──────────────────────────────────────────────────────────────────
@app.route("/")
def landing():
    response = send_from_directory("static","landing.html")
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response

@app.route("/app")
def app_page():
    response = send_from_directory("static","index.html")
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

@app.route("/<path:path>")
def static_files(path): return send_from_directory("static",path)

init_db()

def migrate_db():
    if not is_pg(): return
    conn = get_db(); cur = conn.cursor()
    for sql in [
        "ALTER TABLE trips ADD COLUMN IF NOT EXISTS report_id TEXT",
        "ALTER TABLE trips ADD COLUMN IF NOT EXISTS report_num TEXT",
        "ALTER TABLE trips ADD COLUMN IF NOT EXISTS company_id TEXT DEFAULT 'diprodi'",
        "ALTER TABLE clients ADD COLUMN IF NOT EXISTS rtn TEXT DEFAULT ''",
        "ALTER TABLE clients ADD COLUMN IF NOT EXISTS company_id TEXT DEFAULT 'diprodi'",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS company_id TEXT DEFAULT 'diprodi'",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS company_id TEXT DEFAULT 'diprodi'",
        "ALTER TABLE diprodi_equipos ADD COLUMN IF NOT EXISTS cuota_mensual REAL",
        "ALTER TABLE diprodi_equipos ADD COLUMN IF NOT EXISTS prima REAL",
        "ALTER TABLE diprodi_equipos ADD COLUMN IF NOT EXISTS interes REAL",
        "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS modalidad TEXT DEFAULT 'presencial'",
        "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS accepted_at TEXT DEFAULT ''",
        "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS completed_at TEXT DEFAULT ''",
        "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS video_link TEXT DEFAULT ''",
        "CREATE TABLE IF NOT EXISTS calendar_events (id TEXT PRIMARY KEY, company_id TEXT DEFAULT 'diprodi', title TEXT DEFAULT '', date TEXT NOT NULL, time TEXT DEFAULT '', color TEXT DEFAULT '#EF9F27', all_day INTEGER DEFAULT 0, notes TEXT DEFAULT '', blocks_booking INTEGER DEFAULT 0, created_at TEXT DEFAULT current_timestamp)",
        "CREATE TABLE IF NOT EXISTS invitations (id TEXT PRIMARY KEY, company_id TEXT NOT NULL, code TEXT UNIQUE NOT NULL, email TEXT DEFAULT '', role TEXT DEFAULT 'technician', used INTEGER DEFAULT 0, created_at TEXT DEFAULT current_timestamp)",
        "CREATE TABLE IF NOT EXISTS companies (id TEXT PRIMARY KEY, name TEXT NOT NULL, slug TEXT UNIQUE NOT NULL, logo TEXT DEFAULT '', color TEXT DEFAULT '#0F6E56', plan TEXT DEFAULT 'basic', rubro TEXT DEFAULT 'general', rtn TEXT DEFAULT '', phone TEXT DEFAULT '', address TEXT DEFAULT '', active INTEGER DEFAULT 1, created_at TEXT DEFAULT current_timestamp)",
    ]:
        try: cur.execute(sql); print(f"✓ {sql[:50]}", flush=True)
        except Exception as e: print(f"skip: {e}", flush=True)
    # Ensure DIPRODI company exists
    try:
        cur.execute("INSERT INTO companies(id,name,slug,color,plan,rubro) VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING",
            ("diprodi","DIPRODI","diprodi","#0F6E56","enterprise","veterinaria"))
    except: pass
    conn.commit(); conn.close()

migrate_db()

if __name__=="__main__":
    port=int(os.environ.get("PORT",5000))
    print(f"Servvoo en http://localhost:{port} — {'PostgreSQL' if is_pg() else 'SQLite'}",flush=True)
    app.run(host="0.0.0.0",port=port,debug=False)
