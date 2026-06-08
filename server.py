#!/usr/bin/env python3
"""
LabTrack Backend — Spanish UI + Auth + Google Maps
Run: python server.py  then open http://localhost:5000
"""
import sqlite3, json, uuid, os, hashlib, secrets
from flask import Flask, request, jsonify, send_from_directory
from datetime import datetime

app = Flask(__name__, static_folder="static")
DB  = os.path.join(os.path.dirname(__file__), "labtrack.db")

# ─── DB SETUP ─────────────────────────────────────────────────────────────────
def get_db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    return c

def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def init_db():
    with get_db() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'technician',
            color TEXT NOT NULL DEFAULT 'purple',
            phone TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'available',
            current_trip_id TEXT,
            rendimiento REAL DEFAULT 12,
            tipo_combustible TEXT DEFAULT 'gasolina',
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS inventory (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            model TEXT NOT NULL,
            serial TEXT DEFAULT '',
            category TEXT DEFAULT '',
            stock INTEGER NOT NULL DEFAULT 0,
            unit_cost REAL NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS clients (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            contact TEXT DEFAULT '',
            phone TEXT DEFAULT '',
            email TEXT DEFAULT '',
            city TEXT DEFAULT '',
            department TEXT DEFAULT '',
            type TEXT DEFAULT 'Clínica',
            lat REAL DEFAULT NULL,
            lng REAL DEFAULT NULL,
            address TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS trips (
            id TEXT PRIMARY KEY,
            technician_id TEXT NOT NULL,
            client_id TEXT NOT NULL,
            date TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pendiente',
            trip_type TEXT NOT NULL DEFAULT 'entrega',
            equipment_ids TEXT NOT NULL DEFAULT '[]',
            origin_lat REAL, origin_lng REAL, origin_label TEXT,
            destination_lat REAL, destination_lng REAL, destination_label TEXT,
            stops TEXT DEFAULT '[]',
            route_points TEXT DEFAULT '[]',
            start_time TEXT DEFAULT '',
            end_time TEXT DEFAULT '',
            km REAL NOT NULL DEFAULT 0,
            reimbursement REAL NOT NULL DEFAULT 0,
            notes TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (technician_id) REFERENCES users(id),
            FOREIGN KEY (client_id) REFERENCES clients(id)
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS visit_reports (
            id TEXT PRIMARY KEY,
            trip_id TEXT NOT NULL,
            technician_id TEXT NOT NULL,
            client_id TEXT NOT NULL,
            report_num TEXT NOT NULL,
            fecha TEXT NOT NULL,
            hora_llegada TEXT DEFAULT '',
            hora_salida TEXT DEFAULT '',
            marca TEXT DEFAULT '',
            modelo TEXT DEFAULT '',
            serie TEXT DEFAULT '',
            condicion TEXT DEFAULT '',
            reparaciones TEXT DEFAULT '',
            repuestos TEXT DEFAULT '',
            calibracion INTEGER DEFAULT NULL,
            control_calidad INTEGER DEFAULT NULL,
            signed INTEGER DEFAULT 0,
            sig_time TEXT DEFAULT '',
            sig_data TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (trip_id) REFERENCES trips(id),
            FOREIGN KEY (technician_id) REFERENCES users(id),
            FOREIGN KEY (client_id) REFERENCES clients(id)
        );
        """)
        db.execute("INSERT OR IGNORE INTO settings VALUES ('rate_per_km','5.0')")
        db.execute("INSERT OR IGNORE INTO settings VALUES ('maps_api_key','')")
        db.execute("INSERT OR IGNORE INTO settings VALUES ('company_name','Mi Empresa')")
        count = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if count == 0:
            seed_data(db)
        db.commit()

def seed_data(db):
    COLORS = ["purple","teal","amber","blue","coral","green"]
    users = [
        ("admin1","Administrador","admin@labtrack.hn",hash_pw("admin123"),"admin","blue","+504 9800-0001","available",None),
        ("t1","Carlos Mendoza","carlos@labtrack.hn",hash_pw("tech123"),"technician","purple","+504 9812-3456","on_route","trip1"),
        ("t2","Lucía Paz","lucia@labtrack.hn",hash_pw("tech123"),"technician","teal","+504 9823-4567","available",None),
        ("t3","Roberto Vega","roberto@labtrack.hn",hash_pw("tech123"),"technician","amber","+504 9834-5678","on_route","trip2"),
    ]
    db.executemany("INSERT INTO users (id,name,email,password_hash,role,color,phone,status,current_trip_id) VALUES (?,?,?,?,?,?,?,?,?)", users)

    inventory = [
        ("eq1","Centrífuga","XC-200","CX200-0047","Separación",4,12500),
        ("eq2","Termociclador PCR","T-100","T100-0023","Molecular",2,28000),
        ("eq3","Autoclave","ST-55","ST55-0089","Esterilización",1,8500),
        ("eq4","Analizador Hematológico","HA-5","HA5-0034","Diagnóstico",3,35000),
        ("eq5","Microscopio","OX-3","OX3-0112","Óptica",1,4200),
        ("eq6","Espectrofotómetro","SP-UV","SPUV-0056","Análisis",0,18000),
        ("eq7","Analizador de Gases","BGA-Pro","BGA-0019","Diagnóstico",2,42000),
        ("eq8","Incubadora","IC-37","IC37-0067","Cultivo",3,6800),
    ]
    db.executemany("INSERT INTO inventory (id,name,model,serial,category,stock,unit_cost) VALUES (?,?,?,?,?,?,?)", inventory)

    clients = [
        ("c1","Clínica del Norte","Dr. Ana Flores","+504 2658-1234","contacto@clinicadelnorte.hn","Choloma","Cortés","Clínica",15.6234,-87.9627,"Choloma, Cortés"),
        ("c2","Lab Central HN","Ing. Marco Ríos","+504 2237-5678","info@labcentralhn.hn","Tegucigalpa","MDC","Laboratorio",14.0818,-87.2068,"Tegucigalpa, MDC"),
        ("c3","Hospital del Valle","Dra. Sandra Mejía","+504 2669-9012","hospital@hvalle.hn","La Lima","Cortés","Hospital",15.4278,-87.9178,"La Lima, Cortés"),
        ("c4","Lab San Isidro","Lic. Pedro Cruz","+504 2647-3456","lsi@labsanisidro.hn","El Progreso","Yoro","Laboratorio",15.4397,-87.8325,"El Progreso, Yoro"),
        ("c5","Clínica Porteña","Dr. Ramón Suazo","+504 2665-7890","clinica@portena.hn","Puerto Cortés","Cortés","Clínica",15.8522,-87.9364,"Puerto Cortés, Cortés"),
    ]
    db.executemany("INSERT INTO clients (id,name,contact,phone,email,city,department,type,lat,lng,address) VALUES (?,?,?,?,?,?,?,?,?,?,?)", clients)

    trips = [
        {"id":"trip1","tid":"t1","cid":"c1","date":"2026-06-04","status":"pendiente","type":"instalación","eq":["eq1","eq5"],
         "olat":15.5044,"olng":-88.0251,"olabel":"San Pedro Sula — Almacén",
         "dlat":15.6234,"dlng":-87.9627,"dlabel":"Clínica del Norte, Choloma",
         "stops":[{"lat":15.5244,"lng":-88.0101,"label":"Parada de combustible","time":"09:22"}],
         "route":[[15.5044,-88.0251],[15.5244,-88.0101],[15.5734,-87.9827],[15.6234,-87.9627]],
         "st":"09:14","et":"10:02","km":87,"reimb":435,"notes":"Instalación completa. Cliente firmó acta de aceptación."},
        {"id":"trip2","tid":"t3","cid":"c2","date":"2026-06-02","status":"pendiente","type":"instalación","eq":["eq2"],
         "olat":15.5044,"olng":-88.0251,"olabel":"San Pedro Sula — Almacén",
         "dlat":14.0818,"dlng":-87.2068,"dlabel":"Lab Central HN, Tegucigalpa",
         "stops":[{"lat":14.8819,"lng":-87.6739,"label":"Almuerzo — Comayagua","time":"12:15"},{"lat":14.4419,"lng":-87.3739,"label":"Combustible","time":"13:40"}],
         "route":[[15.5044,-88.0251],[15.0044,-87.8251],[14.8819,-87.6739],[14.4419,-87.3739],[14.0818,-87.2068]],
         "st":"08:00","et":"15:30","km":223,"reimb":1115,"notes":"PCR instalado y calibrado. Capacitación a 2 empleados."},
        {"id":"trip3","tid":"t2","cid":"c3","date":"2026-06-01","status":"aprobado","type":"entrega","eq":["eq3"],
         "olat":15.5044,"olng":-88.0251,"olabel":"San Pedro Sula — Almacén",
         "dlat":15.4278,"dlng":-87.9178,"dlabel":"Hospital del Valle, La Lima",
         "stops":[],"route":[[15.5044,-88.0251],[15.4678,-87.9751],[15.4278,-87.9178]],
         "st":"10:30","et":"11:15","km":52,"reimb":260,"notes":"Autoclave entregado. Instalación programada para próxima visita."},
        {"id":"trip4","tid":"t1","cid":"c4","date":"2026-05-30","status":"reembolsado","type":"instalación","eq":["eq4"],
         "olat":15.5044,"olng":-88.0251,"olabel":"San Pedro Sula — Almacén",
         "dlat":15.4397,"dlng":-87.8325,"dlabel":"Lab San Isidro, El Progreso",
         "stops":[],"route":[[15.5044,-88.0251],[15.4744,-87.9251],[15.4397,-87.8325]],
         "st":"07:45","et":"09:10","km":78,"reimb":390,"notes":"Analizador hematológico instalado y operativo."},
        {"id":"trip5","tid":"t2","cid":"c5","date":"2026-05-28","status":"reembolsado","type":"entrega","eq":["eq5"],
         "olat":15.5044,"olng":-88.0251,"olabel":"San Pedro Sula — Almacén",
         "dlat":15.8522,"dlng":-87.9364,"dlabel":"Clínica Porteña, Puerto Cortés",
         "stops":[],"route":[[15.5044,-88.0251],[15.6444,-87.9851],[15.8522,-87.9364]],
         "st":"08:15","et":"09:25","km":61,"reimb":305,"notes":"Microscopio entregado en perfectas condiciones."},
    ]
    for t in trips:
        db.execute("""INSERT INTO trips
            (id,technician_id,client_id,date,status,trip_type,equipment_ids,
             origin_lat,origin_lng,origin_label,destination_lat,destination_lng,destination_label,
             stops,route_points,start_time,end_time,km,reimbursement,notes)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (t["id"],t["tid"],t["cid"],t["date"],t["status"],t["type"],json.dumps(t["eq"]),
             t["olat"],t["olng"],t["olabel"],t["dlat"],t["dlng"],t["dlabel"],
             json.dumps(t["stops"]),json.dumps(t["route"]),t["st"],t["et"],t["km"],t["reimb"],t["notes"]))

# ─── CORS ─────────────────────────────────────────────────────────────────────
@app.after_request
def cors(r):
    r.headers["Access-Control-Allow-Origin"]  = "*"
    r.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,PATCH,DELETE,OPTIONS"
    r.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
    return r

@app.route("/api/<path:p>", methods=["OPTIONS"])
def options(p): return "",200

# ─── HELPERS ──────────────────────────────────────────────────────────────────
def row2dict(row):
    if row is None: return None
    d = dict(row)
    for k in ["equipment_ids","stops","route_points"]:
        if k in d and d[k]:
            try: d[k] = json.loads(d[k])
            except: pass
    if "technician_id" in d:
        d["technicianId"]  = d.pop("technician_id")
        d["clientId"]      = d.pop("client_id")
        d["tripType"]      = d.pop("trip_type")
        d["equipmentIds"]  = d.pop("equipment_ids")
        d["startTime"]     = d.pop("start_time")
        d["endTime"]       = d.pop("end_time")
        d["routePoints"]   = d.pop("route_points")
        d["createdAt"]     = d.pop("created_at", None)
        d["origin"]        = {"lat":d.pop("origin_lat"),"lng":d.pop("origin_lng"),"label":d.pop("origin_label")}
        d["destination"]   = {"lat":d.pop("destination_lat"),"lng":d.pop("destination_lng"),"label":d.pop("destination_label")}
    if "current_trip_id" in d:
        d["currentTripId"] = d.pop("current_trip_id")
        d["createdAt"]     = d.pop("created_at", None)
        d.pop("password_hash", None)
    if "unit_cost" in d:
        d["unitCost"]      = d.pop("unit_cost")
        d["createdAt"]     = d.pop("created_at", None)
    return d

def uid(): return str(uuid.uuid4())[:8]

# ─── AUTH ─────────────────────────────────────────────────────────────────────
@app.route("/api/auth/login", methods=["POST"])
def login():
    d = request.json
    with get_db() as db:
        u = db.execute("SELECT * FROM users WHERE email=? AND password_hash=?",
                       (d.get("email","").lower().strip(), hash_pw(d.get("password","")))).fetchone()
        if not u: return jsonify({"error":"Correo o contraseña incorrectos"}), 401
        user = row2dict(u)
        user["token"] = secrets.token_hex(16)
        return jsonify(user)

@app.route("/api/auth/register", methods=["POST"])
def register():
    d = request.json
    name  = d.get("name","").strip()
    email = d.get("email","").lower().strip()
    pw    = d.get("password","")
    if not name or not email or not pw:
        return jsonify({"error":"Todos los campos son requeridos"}), 400
    if len(pw) < 6:
        return jsonify({"error":"La contraseña debe tener al menos 6 caracteres"}), 400
    with get_db() as db:
        exists = db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
        if exists: return jsonify({"error":"Este correo ya está registrado"}), 409
        color_opts = ["purple","teal","amber","blue","coral","green"]
        count = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        color = color_opts[count % len(color_opts)]
        parts = name.split()
        initials = (parts[0][0] + (parts[1][0] if len(parts)>1 else "")).upper()
        uid_ = "u" + uid()
        db.execute("INSERT INTO users (id,name,email,password_hash,role,color,phone,status) VALUES (?,?,?,?,?,?,?,?)",
                   (uid_, name, email, hash_pw(pw), "technician", color, d.get("phone",""), "available"))
        db.commit()
        u = db.execute("SELECT * FROM users WHERE id=?", (uid_,)).fetchone()
        user = row2dict(u)
        user["token"] = secrets.token_hex(16)
        return jsonify(user), 201

# ─── SETTINGS ─────────────────────────────────────────────────────────────────
@app.route("/api/settings")
def get_settings():
    with get_db() as db:
        rows = db.execute("SELECT key,value FROM settings").fetchall()
        return jsonify({r["key"]:r["value"] for r in rows})

@app.route("/api/settings", methods=["POST"])
def save_settings():
    with get_db() as db:
        for k,v in request.json.items():
            db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)",(k,str(v)))
        db.commit()
    return jsonify({"ok":True})

# ─── USERS / TECHNICIANS ──────────────────────────────────────────────────────
@app.route("/api/technicians")
def get_techs():
    with get_db() as db:
        return jsonify([row2dict(r) for r in db.execute("SELECT * FROM users ORDER BY name").fetchall()])

@app.route("/api/technicians", methods=["POST"])
def add_tech():
    d = request.json
    name = d["name"].strip()
    parts = name.split()
    initials = (parts[0][0]+(parts[1][0] if len(parts)>1 else "")).upper()
    tid = "t"+uid()
    with get_db() as db:
        db.execute("INSERT INTO users (id,name,email,password_hash,role,color,phone,status,rendimiento,tipo_combustible) VALUES (?,?,?,?,?,?,?,?,?,?)",
                   (tid, name, d.get("email","").lower(), hash_pw(d.get("password","tech123")),
                    d.get("role","technician"), d.get("color","purple"), d.get("phone",""), "available",
                    float(d.get("rendimiento",12)), d.get("tipoCombustible","gasolina")))
        db.commit()
        return jsonify(row2dict(db.execute("SELECT * FROM users WHERE id=?", (tid,)).fetchone()))

@app.route("/api/technicians/<tid>", methods=["PATCH"])
def update_tech(tid):
    d = request.json
    with get_db() as db:
        for k,v in d.items():
            col = "current_trip_id" if k=="currentTripId" else k
            db.execute(f"UPDATE users SET {col}=? WHERE id=?", (v, tid))
        db.commit()
        return jsonify(row2dict(db.execute("SELECT * FROM users WHERE id=?", (tid,)).fetchone()))

# ─── INVENTORY ────────────────────────────────────────────────────────────────
@app.route("/api/inventory")
def get_inventory():
    with get_db() as db:
        return jsonify([row2dict(r) for r in db.execute("SELECT * FROM inventory ORDER BY name").fetchall()])

@app.route("/api/inventory", methods=["POST"])
def add_inventory():
    d = request.json
    eid = "eq"+uid()
    with get_db() as db:
        db.execute("INSERT INTO inventory (id,name,model,serial,category,stock,unit_cost) VALUES (?,?,?,?,?,?,?)",
                   (eid,d["name"],d["model"],d.get("serial",""),d.get("category",""),int(d.get("stock",1)),float(d.get("unitCost",0))))
        db.commit()
        return jsonify(row2dict(db.execute("SELECT * FROM inventory WHERE id=?", (eid,)).fetchone()))

@app.route("/api/inventory/<eid>", methods=["PATCH"])
def update_inventory(eid):
    d = request.json
    with get_db() as db:
        for k,v in d.items():
            col = "unit_cost" if k=="unitCost" else k
            db.execute(f"UPDATE inventory SET {col}=? WHERE id=?", (v, eid))
        db.commit()
        return jsonify(row2dict(db.execute("SELECT * FROM inventory WHERE id=?", (eid,)).fetchone()))

# ─── CLIENTS ──────────────────────────────────────────────────────────────────
@app.route("/api/clients")
def get_clients():
    with get_db() as db:
        return jsonify([row2dict(r) for r in db.execute("SELECT * FROM clients ORDER BY name").fetchall()])

@app.route("/api/clients", methods=["POST"])
def add_client():
    d = request.json
    cid = "c"+uid()
    with get_db() as db:
        db.execute("INSERT INTO clients (id,name,contact,phone,email,city,department,type,lat,lng,address) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                   (cid,d["name"],d.get("contact",""),d.get("phone",""),d.get("email",""),
                    d.get("city",""),d.get("department",""),d.get("type","Clínica"),
                    d.get("lat"),d.get("lng"),d.get("address","")))
        db.commit()
        return jsonify(row2dict(db.execute("SELECT * FROM clients WHERE id=?", (cid,)).fetchone()))

# ─── TRIPS ────────────────────────────────────────────────────────────────────
@app.route("/api/trips")
def get_trips():
    with get_db() as db:
        return jsonify([row2dict(r) for r in db.execute("SELECT * FROM trips ORDER BY date DESC, created_at DESC").fetchall()])

@app.route("/api/trips", methods=["POST"])
def add_trip():
    d = request.json
    tid = "trip"+uid()
    with get_db() as db:
        db.execute("""INSERT INTO trips
            (id,technician_id,client_id,date,status,trip_type,equipment_ids,
             origin_lat,origin_lng,origin_label,destination_lat,destination_lng,destination_label,
             stops,route_points,start_time,end_time,km,reimbursement,notes)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (tid, d["technicianId"], d["clientId"],
             d.get("date", datetime.now().strftime("%Y-%m-%d")),
             "pendiente", d.get("tripType","entrega"),
             json.dumps(d.get("equipmentIds",[])),
             d["origin"]["lat"], d["origin"]["lng"], d["origin"]["label"],
             d["destination"]["lat"], d["destination"]["lng"], d["destination"]["label"],
             json.dumps(d.get("stops",[])), json.dumps(d.get("routePoints",[])),
             d.get("startTime",""), d.get("endTime",""),
             float(d.get("km",0)), float(d.get("reimbursement",0)),
             d.get("notes","")))
        db.execute("UPDATE users SET status='available', current_trip_id=NULL WHERE id=?", (d["technicianId"],))
        db.commit()
        return jsonify(row2dict(db.execute("SELECT * FROM trips WHERE id=?", (tid,)).fetchone()))

@app.route("/api/trips/<tid>", methods=["PATCH"])
def update_trip(tid):
    d = request.json
    with get_db() as db:
        for k,v in d.items():
            db.execute(f"UPDATE trips SET {k}=? WHERE id=?", (v, tid))
        db.commit()
        return jsonify(row2dict(db.execute("SELECT * FROM trips WHERE id=?", (tid,)).fetchone()))

# ─── SERVE FRONTEND ───────────────────────────────────────────────────────────
@app.route("/")
@app.route("/<path:path>")
def frontend(path="index.html"):
    try: return send_from_directory("static", path)
    except: return send_from_directory("static", "index.html")

@app.route("/api/reports", methods=["GET"])
def get_reports():
    tech_id = request.args.get("technicianId")
    with get_db() as db:
        if tech_id:
            rows = db.execute("SELECT * FROM visit_reports WHERE technician_id=? ORDER BY created_at DESC", (tech_id,)).fetchall()
        else:
            rows = db.execute("SELECT * FROM visit_reports ORDER BY created_at DESC").fetchall()
        reports = []
        for r in rows:
            d = dict(r)
            d["technicianId"] = d.pop("technician_id")
            d["clientId"] = d.pop("client_id")
            d["tripId"] = d.pop("trip_id")
            d["reportNum"] = d.pop("report_num")
            d["horaLlegada"] = d.pop("hora_llegada")
            d["horaSalida"] = d.pop("hora_salida")
            d["controlCalidad"] = d.pop("control_calidad")
            d["sigTime"] = d.pop("sig_time")
            d["sigData"] = d.pop("sig_data")
            d["createdAt"] = d.pop("created_at")
            reports.append(d)
        return jsonify(reports)

@app.route("/api/reports", methods=["POST"])
def save_report():
    d = request.get_json()
    rid = "rep_" + uuid.uuid4().hex[:12]
    with get_db() as db:
        # Generate sequential report number
        year = datetime.now().strftime("%Y")
        month = datetime.now().strftime("%m")
        count = db.execute("SELECT COUNT(*) FROM visit_reports WHERE report_num LIKE ?", (f"LT-{year}{month}-%",)).fetchone()[0]
        seq = count + 1
        report_num = f"LT-{year}{month}-{str(seq).zfill(3)}"
        
        db.execute("""INSERT INTO visit_reports 
            (id,trip_id,technician_id,client_id,report_num,fecha,hora_llegada,hora_salida,
             marca,modelo,serie,condicion,reparaciones,repuestos,calibracion,control_calidad,
             signed,sig_time,sig_data)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (rid, d.get("tripId",""), d.get("technicianId",""), d.get("clientId",""),
             report_num, d.get("fecha",""), d.get("horaLlegada",""), d.get("horaSalida",""),
             d.get("marca",""), d.get("modelo",""), d.get("serie",""),
             d.get("condicion",""), d.get("reparaciones",""), d.get("repuestos",""),
             1 if d.get("calibracion") else 0 if d.get("calibracion")==False else None,
             1 if d.get("controlCalidad") else 0 if d.get("controlCalidad")==False else None,
             1 if d.get("signed") else 0, d.get("sigTime",""), d.get("sigData","")))
        db.commit()
        return jsonify({"id":rid,"reportNum":report_num})

@app.route("/api/reports/<rid>/pdf")
def report_pdf(rid):
    conn = get_db()
    cur = execute(conn, "SELECT * FROM visit_reports WHERE id=?", (rid,))
    r = row2dict(cur.fetchone())
    conn.close()
    if not r:
        return "Reporte no encontrado", 404
    
    rep = map_report(r)
    
    # Get technician and client names
    conn = get_db()
    cur = execute(conn, "SELECT name FROM users WHERE id=?", (rep["technicianId"],))
    tech_row = row2dict(cur.fetchone())
    cur = execute(conn, "SELECT name, city FROM clients WHERE id=?", (rep["clientId"],))
    client_row = row2dict(cur.fetchone())
    conn.close()
    
    tech_name = tech_row["name"] if tech_row else "—"
    client_name = client_row["name"] if client_row else "—"
    client_city = client_row["city"] if client_row else ""
    
    cal = "Sí" if rep.get("calibracion") == 1 else "No" if rep.get("calibracion") == 0 else "—"
    cc = "Sí" if rep.get("controlCalidad") == 1 else "No" if rep.get("controlCalidad") == 0 else "—"
    sig_html = f'<img src="{rep["sigData"]}" style="max-width:100%;max-height:80px;"/>' if rep.get("sigData") and rep.get("signed") else "<p style='color:#999;font-style:italic;'>Sin firma</p>"
    
    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8"/>
<title>Reporte {rep['reportNum']}</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0;}}
  body{{font-family:Arial,sans-serif;padding:24px;font-size:13px;color:#222;}}
  .header{{display:flex;justify-content:space-between;align-items:center;border-bottom:2px solid #0F6E56;padding-bottom:14px;margin-bottom:18px;}}
  .logo-wrap{{display:flex;align-items:center;gap:12px;}}
  .logo img{{height:52px;}}
  .company{{font-size:11px;color:#555;}}
  .report-num{{background:#E1F5EE;color:#0F6E56;padding:6px 14px;border-radius:20px;font-weight:700;font-size:13px;font-family:monospace;}}
  .section{{border:1px solid #e0e0e0;border-radius:8px;padding:14px;margin-bottom:14px;}}
  .section-title{{font-size:10px;font-weight:700;text-transform:uppercase;color:#666;letter-spacing:0.5px;margin-bottom:10px;border-bottom:1px solid #f0f0f0;padding-bottom:6px;}}
  .grid-2{{display:grid;grid-template-columns:1fr 1fr;gap:12px;}}
  .grid-3{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;}}
  .grid-4{{display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:12px;}}
  .field-label{{font-size:10px;color:#888;margin-bottom:3px;}}
  .field-value{{background:#f7f7f7;border:1px solid #e0e0e0;border-radius:4px;padding:7px 10px;font-size:13px;font-weight:500;min-height:32px;}}
  .field-value.auto{{color:#0F6E56;}}
  .field-area{{background:#f7f7f7;border:1px solid #e0e0e0;border-radius:4px;padding:7px 10px;font-size:12px;min-height:50px;white-space:pre-wrap;}}
  .check-row{{display:flex;gap:30px;}}
  .check-group label{{font-size:11px;margin-bottom:5px;display:block;font-weight:600;color:#555;}}
  .sig-box{{border:1px dashed #0F6E56;border-radius:8px;padding:10px;text-align:center;min-height:100px;display:flex;align-items:center;justify-content:center;}}
  .footer{{text-align:center;font-size:10px;color:#aaa;border-top:1px solid #eee;padding-top:12px;margin-top:18px;}}
  @media print{{body{{padding:0;}} .no-print{{display:none;}}}}
</style>
</head>
<body>
<div class="no-print" style="text-align:right;margin-bottom:16px;">
  <button onclick="window.print()" style="background:#0F6E56;color:white;border:none;padding:8px 20px;border-radius:6px;font-size:13px;cursor:pointer;font-weight:600;">🖨️ Imprimir / Guardar PDF</button>
</div>

<div class="header">
  <div class="logo-wrap">
    <div class="logo"><img src="https://diprodi.net/public/uploads/1723666225_c80478b27ad98bae76d7.png" alt="DIPRODI" onerror="this.style.display='none'"/></div>
    <div>
      <div style="font-weight:700;font-size:16px;color:#0F6E56;">DIPRODI</div>
      <div class="company">Reporte de visita técnica</div>
    </div>
  </div>
  <div class="report-num">{rep['reportNum']}</div>
</div>

<div class="section">
  <div class="section-title">📋 Número de reporte</div>
  <div class="grid-4">
    <div><div class="field-label">Número</div><div class="field-value auto">{rep['reportNum']}</div></div>
    <div><div class="field-label">Fecha</div><div class="field-value auto">{rep['fecha']}</div></div>
    <div><div class="field-label">Hora llegada</div><div class="field-value auto">{rep['horaLlegada'] or '—'}</div></div>
    <div><div class="field-label">Hora salida</div><div class="field-value auto">{rep['horaSalida'] or '—'}</div></div>
  </div>
</div>

<div class="section">
  <div class="section-title">👤 Técnico y cliente</div>
  <div class="grid-2">
    <div><div class="field-label">Técnico</div><div class="field-value auto">✓ {tech_name}</div></div>
    <div><div class="field-label">Cliente</div><div class="field-value auto">✓ {client_name} — {client_city}</div></div>
  </div>
</div>

<div class="section">
  <div class="section-title">🔧 Equipo revisado</div>
  <div class="grid-3">
    <div><div class="field-label">Marca</div><div class="field-value">{rep['marca'] or '—'}</div></div>
    <div><div class="field-label">Modelo</div><div class="field-value">{rep['modelo'] or '—'}</div></div>
    <div><div class="field-label">No. de serie</div><div class="field-value">{rep['serie'] or '—'}</div></div>
  </div>
</div>

<div class="section">
  <div class="section-title">📝 Detalle de la visita</div>
  <div style="margin-bottom:10px;"><div class="field-label">Condición del equipo</div><div class="field-area">{rep['condicion'] or '—'}</div></div>
  <div style="margin-bottom:10px;"><div class="field-label">Reparaciones efectuadas</div><div class="field-area">{rep['reparaciones'] or '—'}</div></div>
  <div><div class="field-label">Repuestos utilizados</div><div class="field-area">{rep['repuestos'] or '—'}</div></div>
</div>

<div class="section">
  <div class="section-title">✅ Control de calidad</div>
  <div class="check-row">
    <div class="check-group"><label>Calibración</label><div>{'☑' if cal=='Sí' else '☐'} Sí &nbsp;&nbsp; {'☑' if cal=='No' else '☐'} No</div></div>
    <div class="check-group"><label>Control de calidad</label><div>{'☑' if cc=='Sí' else '☐'} Sí &nbsp;&nbsp; {'☑' if cc=='No' else '☐'} No</div></div>
  </div>
</div>

<div class="section">
  <div class="section-title">✍️ Firmas</div>
  <div class="grid-2">
    <div><div class="field-label" style="margin-bottom:6px;">Técnico encargado</div>
      <div class="sig-box"><div style="text-align:center;"><div style="font-size:13px;font-weight:600;color:#333;">{tech_name}</div><div style="font-size:10px;color:#999;margin-top:4px;">Firma del técnico</div></div></div>
    </div>
    <div><div class="field-label" style="margin-bottom:6px;">Nombre y firma del cliente</div>
      <div class="sig-box">{sig_html}<div style="font-size:10px;color:#{'0F6E56' if rep.get('signed') else '999'};margin-top:4px;">{'Firmado a las ' + rep['sigTime'] if rep.get('signed') and rep.get('sigTime') else 'Sin firma registrada'}</div></div>
    </div>
  </div>
</div>

<div class="footer">DIPRODI · Residencial Plaza, Casa No.1, Bloque 32, Tegucigalpa · Telefax: 2230-7121</div>
</body>
</html>"""
    
    from flask import Response
    return Response(html, mimetype='text/html')

if __name__ == "__main__":
    init_db()
    print("\n" + "="*54)
    print("  LabTrack corriendo en http://localhost:5000")
    print("  Credenciales de prueba:")
    print("    Admin:    admin@labtrack.hn  /  admin123")
    print("    Técnico:  carlos@labtrack.hn /  tech123")
    print("="*54 + "\n")
    app.run(host="0.0.0.0", port=5000, debug=False)
