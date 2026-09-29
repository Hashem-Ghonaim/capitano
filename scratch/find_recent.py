import os
from dotenv import load_dotenv
load_dotenv()
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import datetime

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

print("Recent 10000 transactions:")
for tbl in tables:
    query = text(f"SELECT * FROM {tbl} WHERE amount = 10000 ORDER BY date DESC LIMIT 3")
    try:
        res = session.execute(query).fetchall()
        for r in res:
            d = dict(r._mapping)
            print(f"{tbl}: ID={d.get('id')}, Date={d.get('date')}")
    except Exception as e:
        pass
