import sys
import sqlite3
import warnings
import datetime
import numpy as np
import joblib
from flask import Flask, request, jsonify, render_template

# Suppress scikit-learn version mismatch alerts
warnings.filterwarnings("ignore", category=UserWarning, module="sklearn")

app = Flask(__name__)

# ── Load Model Bundle ─────────────────────────────────────────────────────────
try:
    bundle = joblib.load("model.pkl")
    model  = bundle["model"]
    le     = bundle["encoder"]
except Exception as e:
    print("Warning loading model.pkl: Running app in fallback mode.", file=sys.stderr, flush=True)
    model, le = None, None

DB = "smartsensecnc.db"

# ── Database Initialization ───────────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sensor_log (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            machine_id   TEXT,
            vibration    REAL,
            current      REAL,
            state_model  TEXT,
            state_esp32  TEXT,
            timestamp    TEXT
        )
    """)
    conn.commit()
    conn.close()

# ── Web UI Route ──────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("dashboard.html")

# ── API: History (For Live Charts) ────────────────────────────────────────────
@app.route("/api/history")
def history():
    machine_id = request.args.get("machine_id", "CNC-01")
    limit = int(request.args.get("limit", 60))
    
    conn = sqlite3.connect(DB)
    rows = conn.execute("""
        SELECT vibration, current, state_model, timestamp 
        FROM sensor_log WHERE machine_id=? 
        ORDER BY id DESC LIMIT ?
    """, (machine_id, limit)).fetchall()
    conn.close()
    
    rows.reverse()
    
    # FORCED SYSTEM TERMINAL LOG
    print(f"[WEB API LOG] -> Chart History updated for {machine_id} ({len(rows)} points)", file=sys.stdout, flush=True)
    
    return jsonify([
        {
            "vibration": r[0],
            "current": r[1],
            "state_model": r[2],
            "timestamp": r[3]
        } for r in rows
    ])

# ── API: Summary Metrics (Calculated in Raw Seconds) ─────────────────────────
@app.route("/api/summary")
def summary():
    machine_id = request.args.get("machine_id", "CNC-01")
    conn = sqlite3.connect(DB)
    rows = conn.execute(
        "SELECT state_model FROM sensor_log WHERE machine_id=?",
        (machine_id,)
    ).fetchall()
    conn.close()

    states = [r[0] for r in rows]
    total = len(states)
    counts = {s: states.count(s) for s in set(states)}
    seconds_dict = {k: int(v * 5) for k, v in counts.items()}

    # FORCED SYSTEM TERMINAL LOG
    print(f"[WEB API LOG] -> Summary Totals recalculating: {seconds_dict}", file=sys.stdout, flush=True)

    return jsonify({
        "total_readings": total,
        "counts": counts,
        "seconds": seconds_dict
    })

# ── API: Available Machines ───────────────────────────────────────────────────
@app.route("/api/machines")
def machines():
    conn = sqlite3.connect(DB)
    rows = conn.execute("SELECT DISTINCT machine_id FROM sensor_log").fetchall()
    conn.close()
    return jsonify([r[0] for r in rows])

# ── API: Latest Single Reading (Dashboard Cards) ──────────────────────────────
@app.route("/api/latest")
def latest():
    machine_id = request.args.get("machine_id", "CNC-01")
    conn = sqlite3.connect(DB)
    row = conn.execute("""
        SELECT vibration, current, state_model, timestamp 
        FROM sensor_log WHERE machine_id=? 
        ORDER BY id DESC LIMIT 1
    """, (machine_id,)).fetchone()
    conn.close()
    
    if not row:
        print(f"[WEB API LOG] -> Latest data requested for {machine_id}, but database is empty!", file=sys.stdout, flush=True)
        return jsonify({"error": "no data yet"}), 404
        
    # FORCED SYSTEM TERMINAL LOG
    print(f"[WEB API LOG] -> Card Sync -> State: {row[2]} | Cur: {row[1]} A | Vib: {row[0]} m/s²", file=sys.stdout, flush=True)
        
    return jsonify({
        "vibration": row[0],
        "current": row[1],
        "state_model": row[2],
        "timestamp": row[3]
    })

if __name__ == "__main__":
    init_db()
    # Setting use_reloader=False forces terminal prints to show immediately without getting cut off
    app.run(host="0.0.0.0", port=5001, debug=True, use_reloader=False)