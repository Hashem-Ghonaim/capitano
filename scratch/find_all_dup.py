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

print("Checking recent 10000 transactions across tables...")

tables_to_check = [
    'supplier_payment',
    'customer_payment',
    'partner_transaction',
    'expense',
    'financial_transaction',
    'qassa_history'
]

for tbl in tables_to_check:
    print(f"--- {tbl} ---")
    try:
        if tbl == 'expense':
            res = session.execute(text(f"SELECT * FROM {tbl} WHERE amount = 10000 ORDER BY date DESC LIMIT 5")).fetchall()
        elif tbl == 'qassa_history':
            res = session.execute(text(f"SELECT * FROM {tbl} WHERE amount = 10000 ORDER BY timestamp DESC LIMIT 5")).fetchall()
        else:
            res = session.execute(text(f"SELECT * FROM {tbl} WHERE amount = 10000 ORDER BY date DESC LIMIT 5")).fetchall()
        for r in res:
            print(dict(r._mapping))
    except Exception as e:
        print(f"Error checking {tbl}: {e}")
