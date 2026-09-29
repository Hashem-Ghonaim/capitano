import sys, os
sys.stdout.reconfigure(encoding='utf-8')
os.environ['DATABASE_URL'] = 'postgresql://postgres.ifattisspktggtshfuyb:Mostafa%23%24Hashem2026%40%40@aws-0-eu-west-2.pooler.supabase.com:6543/postgres'
from sqlalchemy import create_engine, text
db_url = os.environ['DATABASE_URL'].replace('postgresql://', 'postgresql+pg8000://')
e = create_engine(db_url)
conn = e.connect()

print("=== sub_commission بتاريخ سبتمبر 2026 حسب المدير ===")
r = conn.execute(text("""
    SELECT pt.partner_id, u.fullname, u.username, COUNT(*) as cnt, SUM(pt.amount) as total
    FROM partner_transaction pt 
    JOIN "user" u ON u.id = pt.partner_id 
    WHERE pt.type = 'sub_commission' 
    AND pt.date >= '2026-09-01' AND pt.date < '2026-10-01' 
    GROUP BY pt.partner_id, u.fullname, u.username 
    ORDER BY pt.partner_id
"""))
for row in r.fetchall():
    print(row)

print("\n=== كل المديرين وأدوارهم ===")
r = conn.execute(text("""
    SELECT id, fullname, username, role, manager_id 
    FROM "user" 
    WHERE role IN ('manager', 'general_manager', 'partner')
    ORDER BY id
"""))
for row in r.fetchall():
    print(row)

print("\n=== كل السيلز وتبعيتهم ===")
r = conn.execute(text("""
    SELECT id, fullname, username, role, manager_id 
    FROM "user" 
    WHERE role = 'sales'
    ORDER BY manager_id, id
"""))
for row in r.fetchall():
    print(row)

print("\n=== تفاصيل عمولات سبتمبر ===")
r = conn.execute(text("""
    SELECT pt.partner_id, u.fullname as partner_name, pt.description, pt.amount, pt.order_id
    FROM partner_transaction pt 
    JOIN "user" u ON u.id = pt.partner_id 
    WHERE pt.type = 'sub_commission' 
    AND pt.date >= '2026-09-01' AND pt.date < '2026-10-01' 
    ORDER BY pt.partner_id, pt.id
"""))
for row in r.fetchall():
    print(row)

conn.close()
