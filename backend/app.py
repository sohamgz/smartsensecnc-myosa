import sys
import os
import warnings
import datetime
import numpy as np
import joblib
from flask import Flask, request, jsonify, render_template, send_from_directory
from flask_cors import CORS
from supabase import create_client, Client

warnings.filterwarnings("ignore", category=UserWarning, module="sklearn")

app = Flask(__name__, template_folder="../dashboard")
CORS(app)

# ── Supabase ──────────────────────────────────────────────────────────────────
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ── Load Model ────────────────────────────────────────────────────────────────
try:
    bundle = joblib.load("ml-model/model.pkl")
    model  = bundle["model"]
    le     = bundle["encoder"]
except Exception as e:
    print(f"Warning loading model.pkl: {e}. Running in fallback mode.", file=sys.stderr, flush=True)
    model, le = None, None

# ── State label mapping (ESP32 sends OFF/IDLE/WORKING) ───────────────────────
STATE_MAP = {
    "OFF":     "MACHINE OFF",
    "IDLE":    "MACHINE ON (Idle)",
    "WORKING": "MACHINE ON + WORKING"
}

# ── Web UI ────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("dashboard.html")

# ── POST: ESP32 sends sensor data here ───────────────────────────────────────
@app.route("/predict", methods=["POST"])
def predict():
    data = request.get_json(force=True)

    machine_id   = data.get("machine_id", "CNC-01")
    vibration    = float(data.get("vibration", 0))
    current      = float(data.get("current", 0))
    state_esp32  = data.get("state", "OFF")

    # ML prediction (if model loaded)
    if model and le:
        features    = np.array([[vibration, current]])
        pred_label  = le.inverse_transform(model.predict(features))[0]
        state_model = pred_label
    else:
        # Fallback: use ESP32 state mapped to full label
        state_model = STATE_MAP.get(state_esp32, state_esp32)

    timestamp = datetime.datetime.utcnow().isoformat()

    # Insert into Supabase
    supabase.table("sensor_log").insert({
        "machine_id":  machine_id,
        "vibration":   vibration,
        "current":     current,
        "state_model": state_model,
        "state_esp32": state_esp32,
        "timestamp":   timestamp
    }).execute()

    print(f"[PREDICT] {machine_id} | {state_model} | Cur:{current:.3f} Vib:{vibration:.3f}", flush=True)

    return jsonify({"state": state_model, "timestamp": timestamp})

# ── GET: Latest reading ───────────────────────────────────────────────────────
@app.route("/api/latest")
def latest():
    machine_id = request.args.get("machine_id", "CNC-01")

    result = (
        supabase.table("sensor_log")
        .select("vibration, current, state_model, timestamp")
        .eq("machine_id", machine_id)
        .order("id", desc=True)
        .limit(1)
        .execute()
    )

    if not result.data:
        return jsonify({"error": "no data yet"}), 404

    row = result.data[0]
    print(f"[API/latest] {machine_id} -> {row['state_model']}", flush=True)
    return jsonify(row)

# ── GET: History for charts ───────────────────────────────────────────────────
@app.route("/api/history")
def history():
    machine_id = request.args.get("machine_id", "CNC-01")
    limit      = int(request.args.get("limit", 60))

    result = (
        supabase.table("sensor_log")
        .select("vibration, current, state_model, timestamp")
        .eq("machine_id", machine_id)
        .order("id", desc=True)
        .limit(limit)
        .execute()
    )

    rows = list(reversed(result.data))
    print(f"[API/history] {machine_id} -> {len(rows)} points", flush=True)
    return jsonify(rows)

# ── GET: Summary / downtime metrics ──────────────────────────────────────────
@app.route("/api/summary")
def summary():
    machine_id = request.args.get("machine_id", "CNC-01")

    result = (
        supabase.table("sensor_log")
        .select("state_model")
        .eq("machine_id", machine_id)
        .execute()
    )

    states = [r["state_model"] for r in result.data]
    total  = len(states)
    counts = {s: states.count(s) for s in set(states)}
    seconds_dict = {k: int(v * 5) for k, v in counts.items()}

    print(f"[API/summary] {machine_id} -> {seconds_dict}", flush=True)
    return jsonify({"total_readings": total, "counts": counts, "seconds": seconds_dict})

# ── GET: Machine list ─────────────────────────────────────────────────────────
@app.route("/api/machines")
def machines():
    result = supabase.table("sensor_log").select("machine_id").execute()
    ids    = list({r["machine_id"] for r in result.data})
    return jsonify(ids)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True, use_reloader=False)