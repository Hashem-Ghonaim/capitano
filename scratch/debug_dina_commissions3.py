import sys, os
sys.stdout.reconfigure(encoding='utf-8')
os.environ['DATABASE_URL'] = 'postgresql://postgres.ifattisspktggtshfuyb:Mostafa%23%24Hashem2026%40%40@aws-0-eu-west-2.pooler.supabase.com:6543/postgres'
from sqlalchemy import create_engine, text
db_url = os.environ['DATABASE_URL'].replace('postgresql://', 'postgresql+pg8000://')
e = create_engine(db_url)
conn = e.connect()

print("=== حركات (120 قطعة) محمد حمدي ===")
r = conn.execute(text("""
    SELECT pt.partner_id, pt.amount, pt.type, pt.order_id
    FROM partner_transaction pt 
    WHERE pt.description = 'عمولة (120 قطعة) - فاتورة مبيعات (محمد حمدي)'
"""))
for row in r.fetchall():
    print(row)

print("\n=== حركات سالبة بدون order_id لـ commission_gross ===")
r = conn.execute(text("""
    SELECT pt.partner_id, pt.amount, pt.description
    FROM partner_transaction pt 
    WHERE pt.type = 'commission_gross'
    AND pt.amount < 0
    AND pt.order_id IS NULL
"""))
for row in r.fetchall():
    print(row)

conn.close()
