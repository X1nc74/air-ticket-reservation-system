"""Initialize an empty database with the schema and fictional demo accounts."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import get_db_connection
from werkzeug.security import generate_password_hash


def initialize():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SHOW TABLES")
    if cur.fetchall():
        cur.close()
        conn.close()
        raise RuntimeError("Database is not empty. Choose a new empty demo database.")
    schema = (ROOT / "database/schema.sql").read_text()
    schema = "\n".join(line for line in schema.splitlines() if not line.lstrip().startswith("--"))
    for statement in schema.split(";"):
        if statement.strip():
            cur.execute(statement)

    password = os.environ.get("DEMO_PASSWORD", "DemoFlights2026!")
    hashed = generate_password_hash(password)
    cur.execute("INSERT INTO airline VALUES ('Demo Air'), ('Other Air')")
    cur.execute("INSERT INTO airport VALUES ('JFK','Demo New York Airport','New York','USA'), ('PVG','Demo Shanghai Airport','Shanghai','China')")
    cur.execute("INSERT INTO airplane (airline_name,model,total_seats) VALUES ('Demo Air','Demo aircraft',10)")
    plane_id = cur.lastrowid
    cur.execute("INSERT INTO seat_class VALUES ('ECON','Economy'), ('BUS','Business')")
    for name, permission in [("demo_admin", "admin"), ("demo_operator", "operator")]:
        cur.execute("INSERT INTO airline_staff (username,password_hash,first_name,last_name,airline_name) VALUES (%s,%s,'Demo','Staff','Demo Air')", (name, hashed))
        cur.execute("INSERT INTO staff_permission VALUES (%s,%s)", (name, permission))
    for email, name in [("customer@example.invalid", "Demo Customer"), ("second@example.invalid", "Second Customer")]:
        cur.execute("INSERT INTO customer (email,name,password_hash) VALUES (%s,%s,%s)", (email,name,hashed))
    cur.execute("INSERT INTO booking_agent (email,password_hash) VALUES ('agent@example.invalid',%s)", (hashed,))
    cur.execute("INSERT INTO agent_works_for VALUES ('agent@example.invalid','Demo Air')")
    flight_ids = []
    for num, days, status in [("D101",30,"upcoming"),("D102",45,"delayed"),("D100",-10,"completed")]:
        cur.execute("""INSERT INTO flight (airline_name,flight_num,departure_airport,departure_time,
            arrival_airport,arrival_time,base_price,status,airplane_id)
            VALUES ('Demo Air',%s,'JFK',DATE_ADD(NOW(),INTERVAL %s DAY),'PVG',
            DATE_ADD(DATE_ADD(NOW(),INTERVAL %s DAY),INTERVAL 12 HOUR),500,%s,%s)""", (num,days,days,status,plane_id))
        flight_id = cur.lastrowid
        flight_ids.append(flight_id)
        cur.execute("INSERT INTO flight_seat_inventory VALUES (%s,'ECON',8,500),(%s,'BUS',2,900)", (flight_id,flight_id))
    for flight_id, agent in [(flight_ids[0],None),(flight_ids[2],"agent@example.invalid")]:
        cur.execute("INSERT INTO ticket (flight_id,class_code) VALUES (%s,'ECON')", (flight_id,))
        cur.execute("INSERT INTO purchases VALUES (%s,'customer@example.invalid',%s,NOW(),500)", (cur.lastrowid,agent))
    conn.commit()
    cur.close()
    conn.close()
    print("Initialized fictional demo data. Accounts and local-demo password are documented in README.md.")


if __name__ == "__main__":
    initialize()
