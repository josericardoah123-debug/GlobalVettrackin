#!/usr/bin/env python3
"""LabTrack Backend — PostgreSQL + SQLite fallback"""
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
DB = os.path.join(os.path.dirname(__file__), "labtrack.db")
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
            "CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, role TEXT DEFAULT 'technician', color TEXT DEFAULT 'purple', phone TEXT DEFAULT '', status TEXT DEFAULT 'available', current_trip_id TEXT, rendimiento REAL DEFAULT 12, tipo_combustible TEXT DEFAULT 'gasolina', created_at TEXT DEFAULT current_timestamp)",
            "CREATE TABLE IF NOT EXISTS inventory (id TEXT PRIMARY KEY, name TEXT NOT NULL, model TEXT NOT NULL, serial TEXT DEFAULT '', category TEXT DEFAULT '', stock INTEGER DEFAULT 0, unit_cost REAL DEFAULT 0, created_at TEXT DEFAULT current_timestamp)",
            "CREATE TABLE IF NOT EXISTS clients (id TEXT PRIMARY KEY, name TEXT NOT NULL, contact TEXT DEFAULT '', phone TEXT DEFAULT '', email TEXT DEFAULT '', city TEXT DEFAULT '', department TEXT DEFAULT '', type TEXT DEFAULT 'Clínica', lat REAL, lng REAL, address TEXT DEFAULT '', created_at TEXT DEFAULT current_timestamp)",
            "CREATE TABLE IF NOT EXISTS trips (id TEXT PRIMARY KEY, technician_id TEXT NOT NULL, client_id TEXT NOT NULL, date TEXT NOT NULL, status TEXT DEFAULT 'pendiente', trip_type TEXT DEFAULT 'entrega', equipment_ids TEXT DEFAULT '[]', origin_lat REAL, origin_lng REAL, origin_label TEXT, destination_lat REAL, destination_lng REAL, destination_label TEXT, stops TEXT DEFAULT '[]', route_points TEXT DEFAULT '[]', start_time TEXT DEFAULT '', end_time TEXT DEFAULT '', km REAL DEFAULT 0, reimbursement REAL DEFAULT 0, notes TEXT DEFAULT '', report_id TEXT, report_num TEXT, created_at TEXT DEFAULT current_timestamp)",
            "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS visit_reports (id TEXT PRIMARY KEY, trip_id TEXT, technician_id TEXT, client_id TEXT, report_num TEXT, fecha TEXT, hora_llegada TEXT DEFAULT '', hora_salida TEXT DEFAULT '', marca TEXT DEFAULT '', modelo TEXT DEFAULT '', serie TEXT DEFAULT '', condicion TEXT DEFAULT '', reparaciones TEXT DEFAULT '', repuestos TEXT DEFAULT '', calibracion INTEGER, control_calidad INTEGER, signed INTEGER DEFAULT 0, sig_time TEXT DEFAULT '', sig_data TEXT DEFAULT '', created_at TEXT DEFAULT current_timestamp)",
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
        CREATE TABLE IF NOT EXISTS clients(id TEXT PRIMARY KEY,name TEXT NOT NULL,contact TEXT DEFAULT '',phone TEXT DEFAULT '',email TEXT DEFAULT '',city TEXT DEFAULT '',department TEXT DEFAULT '',type TEXT DEFAULT 'Clínica',lat REAL,lng REAL,address TEXT DEFAULT '',created_at TEXT DEFAULT(datetime('now')));
        CREATE TABLE IF NOT EXISTS trips(id TEXT PRIMARY KEY,technician_id TEXT NOT NULL,client_id TEXT NOT NULL,date TEXT NOT NULL,status TEXT DEFAULT 'pendiente',trip_type TEXT DEFAULT 'entrega',equipment_ids TEXT DEFAULT '[]',origin_lat REAL,origin_lng REAL,origin_label TEXT,destination_lat REAL,destination_lng REAL,destination_label TEXT,stops TEXT DEFAULT '[]',route_points TEXT DEFAULT '[]',start_time TEXT DEFAULT '',end_time TEXT DEFAULT '',km REAL DEFAULT 0,reimbursement REAL DEFAULT 0,notes TEXT DEFAULT '',report_id TEXT,report_num TEXT,created_at TEXT DEFAULT(datetime('now')));
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS visit_reports(id TEXT PRIMARY KEY,trip_id TEXT,technician_id TEXT,client_id TEXT,report_num TEXT,fecha TEXT,hora_llegada TEXT DEFAULT '',hora_salida TEXT DEFAULT '',marca TEXT DEFAULT '',modelo TEXT DEFAULT '',serie TEXT DEFAULT '',condicion TEXT DEFAULT '',reparaciones TEXT DEFAULT '',repuestos TEXT DEFAULT '',calibracion INTEGER,control_calidad INTEGER,signed INTEGER DEFAULT 0,sig_time TEXT DEFAULT '',sig_data TEXT DEFAULT '',created_at TEXT DEFAULT(datetime('now')));
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
                  ("address","address"),("lat","lat"),("lng","lng")]:
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
    cur=ex(conn,"SELECT COUNT(*) as c FROM visit_reports WHERE report_num LIKE ?",(f"LT-{year}{month}-%",))
    row=r2d(cur.fetchone()); count=int(row.get("c") or row.get("count") or 0)
    rnum=f"LT-{year}{month}-{str(count+1).zfill(3)}"
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

# ─── STATIC ───────────────────────────────────────────────────────────────────
@app.route("/")
def index(): return send_from_directory("static","index.html")

@app.route("/<path:path>")
def static_files(path): return send_from_directory("static",path)

init_db()

if __name__=="__main__":
    port=int(os.environ.get("PORT",5000))
    print(f"LabTrack en http://localhost:{port} — {'PostgreSQL' if is_pg() else 'SQLite'}",flush=True)
    app.run(host="0.0.0.0",port=port,debug=False)
