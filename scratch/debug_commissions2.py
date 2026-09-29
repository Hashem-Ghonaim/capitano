import sys, os
sys.stdout.reconfigure(encoding='utf-8')
os.environ['DATABASE_URL'] = 'postgresql://postgres.ifattisspktggtshfuyb:Mostafa%23%24Hashem2026%40%40@aws-0-eu-west-2.pooler.supabase.com:6543/postgres'
from sqlalchemy import create_engine, text
db_url = os.environ['DATABASE_URL'].replace('postgresql://', 'postgresql+pg8000://')
e = create_engine(db_url)
conn = e.connect()

print("=== الموظفين اللي salary_method = split_4 ===")
r = conn.execute(text("""
    SELECT id, fullname, username, role, salary_method, manager_id 
    FROM "user" 
    WHERE salary_method = 'split_4'
    ORDER BY id
"""))
for row in r.fetchall():
    print(row)

print("\n=== الحركات الخاطئة (order_id = NULL مع sub_commission) سبتمبر ===")
r = conn.execute(text("""
    SELECT pt.id, pt.partner_id, u.fullname as partner_name, pt.description, pt.amount, pt.date
    FROM partner_transaction pt 
    JOIN "user" u ON u.id = pt.partner_id 
    WHERE pt.type = 'sub_commission' 
    AND pt.order_id IS NULL
    AND pt.date >= '2026-09-01' AND pt.date < '2026-10-01' 
    ORDER BY pt.description, pt.partner_id
"""))
results = r.fetchall()
for row in results:
    print(row)
print(f"\nTotal bad records: {len(results)}")

# Check what invoices these are about - check the descriptions
print("\n=== فواتير مشتركة في الخطأ ===")
r = conn.execute(text("""
    SELECT DISTINCT pt.description, COUNT(DISTINCT pt.partner_id) as manager_count
    FROM partner_transaction pt 
    WHERE pt.type = 'sub_commission' 
    AND pt.order_id IS NULL
    AND pt.date >= '2026-09-01' AND pt.date < '2026-10-01' 
    GROUP BY pt.description
    ORDER BY pt.description
"""))
for row in r.fetchall():
    print(row)

conn.close()
