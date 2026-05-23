import sqlite3
import serial
import time
from datetime import datetime

DB_NAME = "smartsensecnc.db"
SERIAL_PORT = "/dev/cu.usbserial-130" 
BAUD_RATE = 115200  

# ── Robust Rolling Smoothing Configuration ──
SMOOTHING_WINDOW = 5
current_history = []
vibration_history = []

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
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

def parse_and_save():
    global current_history, vibration_history
    init_db()
    print(f"🔌 Connecting to board on {SERIAL_PORT}...")
    
    last_raw_current = 0.0
    last_raw_vibration = 0.0
    state_val = "MACHINE OFF"

    try:
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
        time.sleep(2)  
        print("Successfully connected! Listening for real CNC data...")
        
        while True:
            if ser.in_waiting > 0:
                # Read line and normalize encoding safely
                line = ser.readline().decode('utf-8', errors='ignore').strip()
                if not line:
                    continue
                
                print(f"Raw Serial Line: {line}")
                
                # ── 1. BULLETPROOF CURRENT PARSING ──
                if "Current:" in line:
                    try:
                        # Extract everything after "Current:", remove unit labels, and strip space
                        raw_val = line.split("Current:")[1].replace("A", "").strip()
                        if raw_val:
                            last_raw_current = float(raw_val)
                    except (IndexError, ValueError):
                        pass
                
                # ── 2. BULLETPROOF VIBRATION PARSING ──
                # Instead of matching the '²' symbol, we strip text patterns safely
                if "Vibration:" in line:
                    try:
                        raw_val = line.split("Vibration:")[1].strip()
                        # Clean out common unit strings to isolate the floating number
                        for unit in ["m/s²", "m/s2", "m/s"]:
                            raw_val = raw_val.replace(unit, "")
                        raw_val = raw_val.strip()
                        if raw_val:
                            last_raw_vibration = float(raw_val)
                    except (IndexError, ValueError):
                        pass
                
                # ── 3. FLEXIBLE STATE PARSING ──
                # Matches both "State: IDLE" and "Machine State: MACHINE OFF" securely
                if "State:" in line:
                    try:
                        raw_state = line.split("State:")[1].strip().upper()
                        
                        if "OFF" in raw_state:
                            state_val = "MACHINE OFF"
                        elif "IDLE" in raw_state:
                            state_val = "MACHINE ON (Idle)"
                        elif "WORK" in raw_state or "RUN" in raw_state:
                            state_val = "MACHINE ON + WORKING"
                    except IndexError:
                        pass
                
                # ── 4. PACKET FRAME SEPARATOR AND STABILIZATION ──
                if "---" in line:
                    current_history.append(last_raw_current)
                    vibration_history.append(last_raw_vibration)
                    
                    if len(current_history) > SMOOTHING_WINDOW:
                        current_history.pop(0)
                    if len(vibration_history) > SMOOTHING_WINDOW:
                        vibration_history.pop(0)
                        
                    # Calculate rolling averages to stabilize interface graphs
                    smooth_current = round(sum(current_history) / len(current_history), 3)
                    smooth_vibration = round(sum(vibration_history) / len(vibration_history), 3)
                    
                    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    
                    conn = sqlite3.connect(DB_NAME)
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT INTO sensor_log (machine_id, vibration, current, state_model, state_esp32, timestamp)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, ("CNC-01", smooth_vibration, smooth_current, state_val, state_val, now_str))
                    conn.commit()
                    conn.close()
                    
                    print(f"[STABILIZED & LOCKED] -> Vib: {smooth_vibration}, Cur: {smooth_current}, State: {state_val}")
                    
            time.sleep(0.05)
            
    except serial.SerialException as e:
        print(f"Serial Error: Could not open port {SERIAL_PORT}.")
    except KeyboardInterrupt:
        print("\nStopping serial reader.")

if __name__ == "__main__":
    parse_and_save()