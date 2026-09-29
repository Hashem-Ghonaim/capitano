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

print("Recent supplier payments:")
query = text("SELECT * FROM supplier_payment ORDER BY date DESC LIMIT 10")
res = session.execute(query).fetchall()
for r in res:
    d = dict(r._mapping)
    print(f"ID={d.get('id')}, Supplier={d.get('supplier_id')}, Amount={d.get('amount')}, Date={d.get('date')}")
