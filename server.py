#!/usr/bin/env python3
"""
LabTrack Backend — PostgreSQL version
"""
import os, json, uuid, hashlib, sqlite3, traceback, sys
import logging
logging.basicConfig(level=logging.DEBUG, stream=sys.stdout)
from flask import Flask, request, jsonify, send_from_directory
from datetime import datetime

try:
    import psycopg2
    import psycopg2.extras
    USE_PG = True
except ImportError:
    import sqlite3
    USE_PG = False

app = Flask(__name__, static_folder="static")

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

SQLITE_DB = os.path.join(os.path.dirname(__file__), "labtrack.db")

def get_db():
    if DATABASE_URL and USE_PG:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
        return conn
    else:
        c = sqlite3.connect(SQLITE_DB)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        return c

def is_pg():
    return bool(DATABASE_URL and USE_PG)

def ph(n):
    """Placeholder — %s for postgres, ? for sqlite"""
    return "%s" if is_pg() else "?"

def P(n=1):
    """Return n placeholders"""
    p = ph(1)
    return ",".join([p]*n)

def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def row2dict(row):
    if row is None:
        return None
    if is_pg():
        return dict(row)
    return dict(zip(row.keys(), tuple(row)))

def rows2list(rows):
    return [row2dict(r) for r in rows]

def execute(conn, sql, params=()):
    cur = conn.cursor()
    # Convert ? to %s for postgres
    if is_pg():
        sql = sql.replace("?", "%s")
    cur.execute(sql, params)
    return cur

def init_db():
    conn = get_db()
    cur = conn.cursor()
    if is_pg():
        cur.execute("""
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
            created_at TEXT DEFAULT current_timestamp
        );
        CREATE TABLE IF NOT EXISTS inventory (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            model TEXT NOT NULL,
            serial TEXT DEFAULT '',
            category TEXT DEFAULT '',
            stock INTEGER NOT NULL DEFAULT 0,
            unit_cost REAL NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT current_timestamp
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
            created_at TEXT DEFAULT current_timestamp
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
            created_at TEXT DEFAULT current_timestamp
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
            created_at TEXT DEFAULT current_timestamp
        );
        """)
        cur.execute("INSERT INTO settings (key,value) VALUES ('rate_per_km','5.0') ON CONFLICT (key) DO NOTHING")
        cur.execute("INSERT INTO settings (key,value) VALUES ('maps_api_key','') ON CONFLICT (key) DO NOTHING")
        cur.execute("INSERT INTO settings (key,value) VALUES ('company_name','DIPRODI') ON CONFLICT (key) DO NOTHING")
        cur.execute("INSERT INTO settings (key,value) VALUES ('fuel_gas_price','95.0') ON CONFLICT (key) DO NOTHING")
        cur.execute("INSERT INTO settings (key,value) VALUES ('fuel_diesel_price','85.0') ON CONFLICT (key) DO NOTHING")
        cur.execute("SELECT COUNT(*) as c FROM users")
        count = cur.fetchone()["c"]
    else:
        cur.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'technician',
            color TEXT NOT NULL DEFAULT 'purple', phone TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'available', current_trip_id TEXT,
            rendimiento REAL DEFAULT 12, tipo_combustible TEXT DEFAULT 'gasolina',
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS inventory (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, model TEXT NOT NULL,
            serial TEXT DEFAULT '', category TEXT DEFAULT '',
            stock INTEGER NOT NULL DEFAULT 0, unit_cost REAL NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS clients (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, contact TEXT DEFAULT '',
            phone TEXT DEFAULT '', email TEXT DEFAULT '', city TEXT DEFAULT '',
            department TEXT DEFAULT '', type TEXT DEFAULT 'Clínica',
            lat REAL DEFAULT NULL, lng REAL DEFAULT NULL, address TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS trips (
            id TEXT PRIMARY KEY, technician_id TEXT NOT NULL, client_id TEXT NOT NULL,
            date TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pendiente',
            trip_type TEXT NOT NULL DEFAULT 'entrega', equipment_ids TEXT NOT NULL DEFAULT '[]',
            origin_lat REAL, origin_lng REAL, origin_label TEXT,
            destination_lat REAL, destination_lng REAL, destination_label TEXT,
            stops TEXT DEFAULT '[]', route_points TEXT DEFAULT '[]',
            start_time TEXT DEFAULT '', end_time TEXT DEFAULT '',
            km REAL NOT NULL DEFAULT 0, reimbursement REAL NOT NULL DEFAULT 0,
            notes TEXT DEFAULT '', created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS visit_reports (
            id TEXT PRIMARY KEY, trip_id TEXT NOT NULL, technician_id TEXT NOT NULL,
            client_id TEXT NOT NULL, report_num TEXT NOT NULL, fecha TEXT NOT NULL,
            hora_llegada TEXT DEFAULT '', hora_salida TEXT DEFAULT '',
            marca TEXT DEFAULT '', modelo TEXT DEFAULT '', serie TEXT DEFAULT '',
            condicion TEXT DEFAULT '', reparaciones TEXT DEFAULT '', repuestos TEXT DEFAULT '',
            calibracion INTEGER DEFAULT NULL, control_calidad INTEGER DEFAULT NULL,
            signed INTEGER DEFAULT 0, sig_time TEXT DEFAULT '', sig_data TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now'))
        );
        """)
        cur.execute("INSERT OR IGNORE INTO settings VALUES ('rate_per_km','5.0')")
        cur.execute("INSERT OR IGNORE INTO settings VALUES ('maps_api_key','')")
        cur.execute("INSERT OR IGNORE INTO settings VALUES ('company_name','DIPRODI')")
        cur.execute("INSERT OR IGNORE INTO settings VALUES ('fuel_gas_price','95.0')")
        cur.execute("INSERT OR IGNORE INTO settings VALUES ('fuel_diesel_price','85.0')")
        count = cur.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    if count == 0:
        # Only create admin user — no simulation data
        admin_id = "admin_" + uuid.uuid4().hex[:8]
        if is_pg():
            cur.execute(
                "INSERT INTO users (id,name,email,password_hash,role,color,phone,status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                (admin_id, "Administrador", "admin@diprodi.hn", hash_pw("admin123"), "admin", "blue", "", "available")
            )
        else:
            cur.execute(
                "INSERT INTO users (id,name,email,password_hash,role,color,phone,status) VALUES (?,?,?,?,?,?,?,?)",
                (admin_id, "Administrador", "admin@diprodi.hn", hash_pw("admin123"), "admin", "blue", "", "available")
            )

    conn.commit()
    conn.close()

# ─── HELPERS ──────────────────────────────────────────────────────────────────
def map_user(d):
    d["currentTripId"] = d.pop("current_trip_id", None)
    d["createdAt"] = d.pop("created_at", None)
    d.pop("password_hash", None)
    if "tipo_combustible" in d:
        d["tipoCombustible"] = d.pop("tipo_combustible")
    return d

def map_trip(d):
    d["technicianId"]    = d.pop("technician_id")
    d["clientId"]        = d.pop("client_id")
    d["tripType"]        = d.pop("trip_type")
    d["equipmentIds"]    = json.loads(d.pop("equipment_ids", "[]"))
    d["origin"]          = {"lat": d.pop("origin_lat"), "lng": d.pop("origin_lng"), "label": d.pop("origin_label","")}
    d["destination"]     = {"lat": d.pop("destination_lat"), "lng": d.pop("destination_lng"), "label": d.pop("destination_label","")}
    d["routePoints"]     = json.loads(d.pop("route_points", "[]"))
    d["startTime"]       = d.pop("start_time","")
    d["endTime"]         = d.pop("end_time","")
    d["stops"]           = json.loads(d.pop("stops","[]"))
    d["createdAt"]       = d.pop("created_at",None)
    d["reimbursement"]   = float(d.get("reimbursement",0))
    d["km"]              = float(d.get("km",0))
    return d

def map_report(d):
    d["technicianId"]  = d.pop("technician_id")
    d["clientId"]      = d.pop("client_id")
    d["tripId"]        = d.pop("trip_id")
    d["reportNum"]     = d.pop("report_num")
    d["horaLlegada"]   = d.pop("hora_llegada","")
    d["horaSalida"]    = d.pop("hora_salida","")
    d["controlCalidad"]= d.pop("control_calidad",None)
    d["sigTime"]       = d.pop("sig_time","")
    d["sigData"]       = d.pop("sig_data","")
    d["createdAt"]     = d.pop("created_at",None)
    return d

# ─── AUTH ─────────────────────────────────────────────────────────────────────
@app.route("/api/login", methods=["POST"])
def login():
    d = request.get_json()
    conn = get_db()
    cur = execute(conn, "SELECT * FROM users WHERE email=?", (d.get("email","").lower(),))
    row = row2dict(cur.fetchone())
    conn.close()
    if not row or row["password_hash"] != hash_pw(d.get("password","")):
        return jsonify({"error": "Credenciales incorrectas"}), 401
    return jsonify(map_user(row))

@app.route("/api/register", methods=["POST"])
def register():
    d = request.get_json()
    uid = "u_" + uuid.uuid4().hex[:10]
    conn = get_db()
    try:
        execute(conn, "INSERT INTO users (id,name,email,password_hash,role,color,phone,status,rendimiento,tipo_combustible) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (uid, d["name"], d["email"].lower(), hash_pw(d.get("password","user123")),
             d.get("role","technician"), d.get("color","purple"), d.get("phone",""), "available",
             float(d.get("rendimiento",12)), d.get("tipoCombustible","gasolina")))
        conn.commit()
        cur = execute(conn, "SELECT * FROM users WHERE id=?", (uid,))
        row = map_user(row2dict(cur.fetchone()))
        conn.close()
        return jsonify(row)
    except Exception as e:
        conn.close()
        return jsonify({"error": str(e)}), 400

# ─── USERS ────────────────────────────────────────────────────────────────────
@app.route("/api/users")
def get_users():
    conn = get_db()
    cur = execute(conn, "SELECT * FROM users ORDER BY name")
    rows = rows2list(cur.fetchall())
    conn.close()
    return jsonify([map_user(r) for r in rows])

@app.route("/api/users/<uid>", methods=["PATCH"])
def update_user(uid):
    d = request.get_json()
    conn = get_db()
    fields = []
    vals = []
    for k,col in [("name","name"),("phone","phone"),("status","status"),("color","color"),
                  ("rendimiento","rendimiento"),("tipoCombustible","tipo_combustible")]:
        if k in d:
            fields.append(f"{col}=?")
            vals.append(d[k])
    if fields:
        vals.append(uid)
        execute(conn, f"UPDATE users SET {','.join(fields)} WHERE id=?", vals)
        conn.commit()
    cur = execute(conn, "SELECT * FROM users WHERE id=?", (uid,))
    row = map_user(row2dict(cur.fetchone()))
    conn.close()
    return jsonify(row)

@app.route("/api/users/<uid>", methods=["DELETE"])
def delete_user(uid):
    conn = get_db()
    execute(conn, "DELETE FROM users WHERE id=?", (uid,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

# ─── INVENTORY ────────────────────────────────────────────────────────────────
@app.route("/api/inventory")
def get_inventory():
    conn = get_db()
    cur = execute(conn, "SELECT * FROM inventory ORDER BY name")
    rows = rows2list(cur.fetchall())
    conn.close()
    return jsonify([{**r,"unitCost":r.pop("unit_cost",0),"createdAt":r.pop("created_at",None)} for r in rows])

@app.route("/api/inventory", methods=["POST"])
def add_inventory():
    d = request.get_json()
    iid = "eq_" + uuid.uuid4().hex[:10]
    conn = get_db()
    execute(conn, "INSERT INTO inventory (id,name,model,serial,category,stock,unit_cost) VALUES (?,?,?,?,?,?,?)",
        (iid,d["name"],d.get("model",""),d.get("serial",""),d.get("category",""),int(d.get("stock",0)),float(d.get("unitCost",0))))
    conn.commit()
    cur = execute(conn, "SELECT * FROM inventory WHERE id=?", (iid,))
    r = row2dict(cur.fetchone())
    conn.close()
    return jsonify({**r,"unitCost":r.pop("unit_cost",0),"createdAt":r.pop("created_at",None)})

@app.route("/api/inventory/<iid>", methods=["PATCH"])
def update_inventory(iid):
    d = request.get_json()
    conn = get_db()
    fields,vals = [],[]
    for k,col in [("name","name"),("model","model"),("serial","serial"),("category","category"),("stock","stock"),("unitCost","unit_cost")]:
        if k in d:
            fields.append(f"{col}=?")
            vals.append(d[k])
    if fields:
        vals.append(iid)
        execute(conn, f"UPDATE inventory SET {','.join(fields)} WHERE id=?", vals)
        conn.commit()
    cur = execute(conn, "SELECT * FROM inventory WHERE id=?", (iid,))
    r = row2dict(cur.fetchone())
    conn.close()
    return jsonify({**r,"unitCost":r.pop("unit_cost",0),"createdAt":r.pop("created_at",None)})

@app.route("/api/inventory/<iid>", methods=["DELETE"])
def delete_inventory(iid):
    conn = get_db()
    execute(conn, "DELETE FROM inventory WHERE id=?", (iid,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

# ─── CLIENTS ──────────────────────────────────────────────────────────────────
@app.route("/api/clients")
def get_clients():
    conn = get_db()
    cur = execute(conn, "SELECT * FROM clients ORDER BY name")
    rows = rows2list(cur.fetchall())
    conn.close()
    return jsonify([{**r,"createdAt":r.pop("created_at",None)} for r in rows])

@app.route("/api/clients", methods=["POST"])
def add_client():
    d = request.get_json()
    cid = "c_" + uuid.uuid4().hex[:10]
    conn = get_db()
    execute(conn, "INSERT INTO clients (id,name,contact,phone,email,city,department,type,lat,lng,address) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (cid,d["name"],d.get("contact",""),d.get("phone",""),d.get("email",""),
         d.get("city",""),d.get("department",""),d.get("type","Clínica"),
         d.get("lat"),d.get("lng"),d.get("address","")))
    conn.commit()
    cur = execute(conn, "SELECT * FROM clients WHERE id=?", (cid,))
    r = row2dict(cur.fetchone())
    conn.close()
    return jsonify({**r,"createdAt":r.pop("created_at",None)})

@app.route("/api/clients/<cid>", methods=["DELETE"])
def delete_client(cid):
    conn = get_db()
    execute(conn, "DELETE FROM clients WHERE id=?", (cid,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

# ─── TRIPS ────────────────────────────────────────────────────────────────────
@app.route("/api/trips")
def get_trips():
    conn = get_db()
    cur = execute(conn, "SELECT * FROM trips ORDER BY created_at DESC")
    rows = rows2list(cur.fetchall())
    conn.close()
    return jsonify([map_trip(r) for r in rows])

@app.route("/api/trips", methods=["POST"])
def add_trip():
    d = request.get_json()
    tid = "trip_" + uuid.uuid4().hex[:10]
    o = d.get("origin",{})
    dest = d.get("destination",{})
    conn = get_db()
    execute(conn, """INSERT INTO trips
        (id,technician_id,client_id,date,trip_type,equipment_ids,
         origin_lat,origin_lng,origin_label,destination_lat,destination_lng,destination_label,
         stops,route_points,start_time,end_time,km,reimbursement,notes)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (tid,d["technicianId"],d["clientId"],d["date"],d.get("tripType","entrega"),
         json.dumps(d.get("equipmentIds",[])),
         o.get("lat"),o.get("lng"),o.get("label",""),
         dest.get("lat"),dest.get("lng"),dest.get("label",""),
         json.dumps(d.get("stops",[])),json.dumps(d.get("routePoints",[])),
         d.get("startTime",""),d.get("endTime",""),
         float(d.get("km",0)),float(d.get("reimbursement",0)),d.get("notes","")))
    # Update technician status
    execute(conn, "UPDATE users SET status='available', current_trip_id=NULL WHERE id=?", (d["technicianId"],))
    conn.commit()
    cur = execute(conn, "SELECT * FROM trips WHERE id=?", (tid,))
    row = map_trip(row2dict(cur.fetchone()))
    conn.close()
    return jsonify(row)

@app.route("/api/trips/<tid>", methods=["PATCH"])
def update_trip(tid):
    d = request.get_json()
    conn = get_db()
    fields,vals = [],[]
    for k,col in [("status","status"),("km","km"),("reimbursement","reimbursement"),("notes","notes"),("endTime","end_time")]:
        if k in d:
            fields.append(f"{col}=?")
            vals.append(d[k])
    if fields:
        vals.append(tid)
        execute(conn, f"UPDATE trips SET {','.join(fields)} WHERE id=?", vals)
        conn.commit()
    cur = execute(conn, "SELECT * FROM trips WHERE id=?", (tid,))
    row = map_trip(row2dict(cur.fetchone()))
    conn.close()
    return jsonify(row)

# ─── SETTINGS ─────────────────────────────────────────────────────────────────
@app.route("/api/settings")
def get_settings():
    conn = get_db()
    cur = execute(conn, "SELECT * FROM settings")
    rows = rows2list(cur.fetchall())
    conn.close()
    return jsonify({r["key"]: r["value"] for r in rows})

@app.route("/api/settings", methods=["POST"])
def save_settings():
    d = request.get_json()
    conn = get_db()
    for k, v in d.items():
        if is_pg():
            execute(conn, "INSERT INTO settings (key,value) VALUES (%s,%s) ON CONFLICT (key) DO UPDATE SET value=%s", (k, str(v), str(v)))
        else:
            execute(conn, "INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", (k, str(v)))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

# ─── REPORTS ──────────────────────────────────────────────────────────────────
@app.route("/api/reports")
def get_reports():
    tech_id = request.args.get("technicianId")
    conn = get_db()
    if tech_id:
        cur = execute(conn, "SELECT * FROM visit_reports WHERE technician_id=? ORDER BY created_at DESC", (tech_id,))
    else:
        cur = execute(conn, "SELECT * FROM visit_reports ORDER BY created_at DESC")
    rows = rows2list(cur.fetchall())
    conn.close()
    return jsonify([map_report(r) for r in rows])

@app.route("/api/reports", methods=["POST"])
def save_report():
    d = request.get_json()
    rid = "rep_" + uuid.uuid4().hex[:12]
    now = datetime.now()
    year = now.strftime("%Y")
    month = now.strftime("%m")
    conn = get_db()
    cur = execute(conn, "SELECT COUNT(*) as c FROM visit_reports WHERE report_num LIKE ?", (f"LT-{year}{month}-%",))
    row = row2dict(cur.fetchone())
    count = row.get("c") or row.get("count") or 0
    seq = int(count) + 1
    report_num = f"LT-{year}{month}-{str(seq).zfill(3)}"
    execute(conn, """INSERT INTO visit_reports
        (id,trip_id,technician_id,client_id,report_num,fecha,hora_llegada,hora_salida,
         marca,modelo,serie,condicion,reparaciones,repuestos,calibracion,control_calidad,
         signed,sig_time,sig_data)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (rid,d.get("tripId",""),d.get("technicianId",""),d.get("clientId",""),
         report_num,d.get("fecha",""),d.get("horaLlegada",""),d.get("horaSalida",""),
         d.get("marca",""),d.get("modelo",""),d.get("serie",""),
         d.get("condicion",""),d.get("reparaciones",""),d.get("repuestos",""),
         1 if d.get("calibracion")==True else 0 if d.get("calibracion")==False else None,
         1 if d.get("controlCalidad")==True else 0 if d.get("controlCalidad")==False else None,
         1 if d.get("signed") else 0,d.get("sigTime",""),d.get("sigData","")))
    conn.commit()
    conn.close()
    return jsonify({"id":rid,"reportNum":report_num})

# ─── STATIC ───────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory("static", "index.html")

@app.route("/<path:path>")
def static_files(path):
    return send_from_directory("static", path)

try:
    init_db()
    print("DB initialized OK", flush=True)
except Exception as e:
    print("DB ERROR:", e, flush=True)
    traceback.print_exc()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print("="*50)
    print(f"LabTrack corriendo en http://localhost:{port}")
    print(f"Base de datos: {'PostgreSQL' if is_pg() else 'SQLite'}")
    print("Credenciales admin: admin@diprodi.hn / admin123")
    print("="*50)
    app.run(host="0.0.0.0", port=port, debug=False)
