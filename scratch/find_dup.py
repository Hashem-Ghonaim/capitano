import os
from dotenv import load_dotenv
load_dotenv()
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import collections

database_url = os.environ.get('DATABASE_URL')
if database_url:
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql+pg8000://", 1)
    elif database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+pg8000://", 1)

engine = create_engine(database_url)
Session = sessionmaker(bind=engine)
session = Session()

print("--- Supplier Payments ---")
res = session.execute(text("""
    SELECT id, supplier_id, amount, date, account_id 
    FROM supplier_payment 
    WHERE amount = 10000 
    ORDER BY date DESC
""")).fetchall()

dates = collections.defaultdict(list)
for row in res:
    # truncating to second for matching
    dt = str(row.date).split('.')[0]
    dates[dt].append(dict(row._mapping))

for dt, rows in dates.items():
    if len(rows) > 1:
        print(f"DUPLICATE FOUND on {dt}:")
        for r in rows:
            print(r)

print("--- Partner Transactions (Transfers) ---")
res2 = session.execute(text("""
    SELECT id, partner_id, amount, date, type
    FROM partner_transaction
    WHERE amount = 10000
    ORDER BY date DESC
""")).fetchall()

dates2 = collections.defaultdict(list)
for row in res2:
    dt = str(row.date).split('.')[0]
    dates2[dt].append(dict(row._mapping))

for dt, rows in dates2.items():
    if len(rows) > 1:
        print(f"DUPLICATE FOUND on {dt}:")
        for r in rows:
            print(r)

print("--- Financial Transactions ---")
res3 = session.execute(text("""
    SELECT id, transaction_type, amount, date
    FROM financial_transaction
    WHERE amount = 10000
    ORDER BY date DESC
""")).fetchall()
dates3 = collections.defaultdict(list)
for row in res3:
    dt = str(row.date).split('.')[0]
    dates3[dt].append(dict(row._mapping))

for dt, rows in dates3.items():
    if len(rows) > 1:
        print(f"DUPLICATE FOUND on {dt}:")
        for r in rows:
            print(r)

