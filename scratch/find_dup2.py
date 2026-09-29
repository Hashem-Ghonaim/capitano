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

res = session.execute(text("""
    SELECT id, supplier_id, amount, date, account_id 
    FROM supplier_payment 
    WHERE amount = 10000 
    ORDER BY date DESC
""")).fetchall()

for r in res:
    print(dict(r._mapping))
