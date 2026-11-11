"""Create demo reference data (synthetic). Password comes from SEED_PASSWORD, never from source code."""
import os, sys
from werkzeug.security import generate_password_hash
sys.path.insert(0, os.path.dirname(__file__))
from app import db

def seed(c, password):
    db.init_schema(c)
    if c.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
        return False
    h = generate_password_hash(password)
    for u, n, r in [("admin", "Asha Admin", "admin"), ("fm", "Farid Facility Manager", "facility_manager"),
                    ("tech1", "Tara Technician", "technician"), ("tech2", "Tomas Technician", "technician"),
                    ("approver", "Anita Approver", "approver"), ("faculty1", "Dr. Fiona Faculty", "faculty"),
                    ("faculty2", "Dr. Felix Faculty", "faculty"), ("student1", "Sam Student", "student")]:
        c.execute("INSERT INTO users(username,display_name,role,password_hash) VALUES(?,?,?,?)", (u, n, r, h))
    for code, n, k, cap, res, campus in [("LAB-101", "Chemistry Lab 101", "lab", 30, 1, "North"), ("LAB-102", "Computer Lab 102", "lab", 40, 0, "North"),
            ("HALL-A", "Seminar Hall A", "hall", 200, 0, "Central"), ("RM-201", "Classroom 201", "room", 60, 0, "Central"),
            ("RM-305", "Classroom 305", "room", 45, 0, "East"), ("LAB-ROBO", "Robotics Lab", "lab", 25, 1, "East")]:
        c.execute("INSERT INTO facilities(code,name,kind,capacity,restricted,campus) VALUES(?,?,?,?,?,?)", (code, n, k, cap, res, campus))
    for n, f in [("Projector kit P-1", 3), ("Oscilloscope O-7", 1), ("Laptop trolley L-2", 2)]:
        c.execute("INSERT INTO equipment(name,facility_id) VALUES(?,?)", (n, f))
    return True

if __name__ == "__main__":
    pw = os.environ.get("SEED_PASSWORD")
    if not pw:
        sys.exit("SEED_PASSWORD is not set (see .env.example)")
    conn = db.connect()
    print("seeded" if seed(conn, pw) else "already seeded")
