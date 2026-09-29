import os
from dotenv import load_dotenv
load_dotenv()
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

database_url = os.environ.get('DATABASE_URL')
if database_url:
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql+pg8000://", 1)
    elif database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+pg8000://", 1)

engine = create_engine(database_url)
Session = sessionmaker(bind=engine)
session = Session()

tables = ['supplier_payment', 'customer_payment', 'partner_transaction', 'expense']

for tbl in tables:
    query = text(f"""
        SELECT date
        FROM {tbl}
        WHERE amount = 10000
        GROUP BY date
        HAVING COUNT(*) > 1
    """)
    try:
        res = session.execute(query).fetchall()
        for r in res:
            print(f"DUPLICATE FOUND in {tbl} at date {r[0]}")
            # Fetch the actual rows
            rows = session.execute(text(f"SELECT id, amount, date FROM {tbl} WHERE date = :d"), {'d': r[0]}).fetchall()
            for row in rows:
                print(dict(row._mapping))
    except Exception as e:
        print(f"Error on {tbl}: {e}")

