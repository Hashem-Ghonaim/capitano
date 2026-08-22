import os
from sqlalchemy import create_engine
from sqlalchemy.sql import text

engine = create_engine('postgresql://postgres.bhuwcszytzmujtmgvgsj:Mostafa%23%24Hashem2026%40%40@aws-0-eu-west-2.pooler.supabase.com:5432/postgres')

try:
    with engine.connect() as conn:
        with conn.begin(): # Start transaction
            # Delete the specific payment
            conn.execute(text("DELETE FROM supplier_payment WHERE id = 279;"))
            
            # Increase the supplier's balance (since a payment reduces the debt, deleting it increases the debt back)
            conn.execute(text("UPDATE supplier SET balance = balance + 15000 WHERE id = 8;"))
            
            # Increase the money account balance (return the money to the treasury)
            conn.execute(text("UPDATE money_account SET balance = balance + 15000 WHERE id = 2;"))
            
    print("Database updated successfully.")
except Exception as e:
    print(f"Error updating database: {e}")
