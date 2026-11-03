from sqlalchemy import text
from database import engine

query = text("""
    SELECT hospital_id, department, doctor, appointment_date,
           token_number, COUNT(*) AS duplicate_count
    FROM tokens
    GROUP BY hospital_id, department, doctor, appointment_date, token_number
    HAVING COUNT(*) > 1
    ORDER BY appointment_date DESC
    LIMIT 20
""")

with engine.connect() as connection:
    rows = connection.execute(query).fetchall()

if rows:
    print("Existing duplicate token numbers found:")
    for row in rows:
        print(row)
else:
    print("No duplicate token numbers found in the checked records.")
