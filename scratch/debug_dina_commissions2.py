import sys, os
sys.stdout.reconfigure(encoding='utf-8')
os.environ['DATABASE_URL'] = 'postgresql://postgres.ifattisspktggtshfuyb:Mostafa%23%24Hashem2026%40%40@aws-0-eu-west-2.pooler.supabase.com:6543/postgres'
from sqlalchemy import create_engine, text
db_url = os.environ['DATABASE_URL'].replace('postgresql://', 'postgresql+pg8000://')
e = create_engine(db_url)
conn = e.connect()

print("=== حركات العمولة الغريبة عند دينا رضا (32) ===")
r = conn.execute(text("""
    SELECT pt.id, pt.type, pt.amount, pt.description, pt.date, pt.order_id
    FROM partner_transaction pt 
    WHERE pt.partner_id = 32
    AND pt.description LIKE 'عمولة (%قطعة)%'
    ORDER BY pt.date DESC
"""))
for row in r.fetchall():
    print(row)

print("=== حركات العمولة الغريبة عند دينا حمدي (33) ===")
r = conn.execute(text("""
    SELECT pt.id, pt.type, pt.amount, pt.description, pt.date, pt.order_id
    FROM partner_transaction pt 
    WHERE pt.partner_id = 33
    AND pt.description LIKE 'عمولة (%قطعة)%'
    ORDER BY pt.date DESC
"""))
for row in r.fetchall():
    print(row)

conn.close()
