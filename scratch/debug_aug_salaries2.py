import sys, os
sys.stdout.reconfigure(encoding='utf-8')
os.environ['DATABASE_URL'] = 'postgresql://postgres.ifattisspktggtshfuyb:Mostafa%23%24Hashem2026%40%40@aws-0-eu-west-2.pooler.supabase.com:6543/postgres'
from sqlalchemy import create_engine, text
db_url = os.environ['DATABASE_URL'].replace('postgresql://', 'postgresql+pg8000://')
e = create_engine(db_url)
conn = e.connect()

# أول حاجة نشوف كل حركات دينا رضا عشان نعرف الوصف بالظبط
print("=== كل حركات salary_expense لدينا رضا (32) ===")
r = conn.execute(text("""
    SELECT pt.id, pt.type, pt.amount, pt.description, pt.date
    FROM partner_transaction pt 
    WHERE pt.partner_id = 32
    AND pt.type IN ('salary_expense', 'personal_salary_expense')
    ORDER BY pt.date, pt.id
"""))
for row in r.fetchall():
    print(row)

print("\n=== كل حركات salary_expense لدينا حمدي (33) ===")
r = conn.execute(text("""
    SELECT pt.id, pt.type, pt.amount, pt.description, pt.date
    FROM partner_transaction pt 
    WHERE pt.partner_id = 33
    AND pt.type IN ('salary_expense', 'personal_salary_expense')
    ORDER BY pt.date, pt.id
"""))
for row in r.fetchall():
    print(row)

conn.close()
