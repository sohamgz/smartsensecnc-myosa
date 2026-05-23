import sqlite3
import time
import random
from datetime import datetime

DB_NAME = "smartsensecnc.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sensor_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            machine_id TEXT,
            timestamp TEXT,
            vibration REAL,
            current REAL,
            state_model TEXT
        )
    """)
    conn.commit()
    conn.close()

def generate_live_data():
    init_db()
    print("Starting real-time CNC data generation... Press CTRL+C to stop.")
    
    states = ["MACHINE ON + WORKING", "MACHINE ON (Idle)", "MACHINE OFF"]
    current_state = "MACHINE ON (Idle)"
    
    while True:
        if random.random() < 0.15:
            current_state = random.choice(states)
            
        if current_state == "MACHINE ON + WORKING":
            vibration = random.uniform(2.5, 4.8)
            current = random.uniform(0.06, 0.10)
        elif current_state == "MACHINE ON (Idle)":
            vibration = random.uniform(0.1, 0.5)
            current = random.uniform(0.03, 0.05)
        else:
            vibration = random.uniform(0.0, 0.02)
            current = random.uniform(0.0, 0.005)
            
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO sensor_log (machine_id, timestamp, vibration, current, state_model)
            VALUES (?, ?, ?, ?, ?)
        """, ("CNC-01", now_str, vibration, current, current_state))
        conn.commit()
        conn.close()
        
        print(f"[{now_str}] Inserted: {current_state} | Vib: {vibration:.3f} | Cur: {current:.3f}")
        time.sleep(2)

if __name__ == "__main__":
    generate_live_data()