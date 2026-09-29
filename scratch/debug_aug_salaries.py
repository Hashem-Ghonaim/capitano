import sys, os
sys.stdout.reconfigure(encoding='utf-8')
os.environ['DATABASE_URL'] = 'postgresql://postgres.ifattisspktggtshfuyb:Mostafa%23%24Hashem2026%40%40@aws-0-eu-west-2.pooler.supabase.com:6543/postgres'
from sqlalchemy import create_engine, text
db_url = os.environ['DATABASE_URL'].replace('postgresql://', 'postgresql+pg8000://')
e = create_engine(db_url)
conn = e.connect()

# 1. كل حركات الرواتب لشهر 08-2026 على حساب دينا رضا (32)
print("=== حركات رواتب شهر 08-2026 على دينا رضا (ID=32) ===")
r = conn.execute(text("""
    SELECT pt.id, pt.partner_id, pt.type, pt.amount, pt.description, pt.date
    FROM partner_transaction pt 
    WHERE pt.partner_id = 32
    AND pt.description LIKE '%08-2026%'
    AND pt.type IN ('salary_expense', 'personal_salary_expense')
    ORDER BY pt.id
"""))
dina_reda_records = r.fetchall()
for row in dina_reda_records:
    print(row)
print(f"Total: {len(dina_reda_records)} records, Sum: {sum(r[3] for r in dina_reda_records)}")

# 2. كل حركات الرواتب لشهر 08-2026 على حساب دينا حمدي (33)
print("\n=== حركات رواتب شهر 08-2026 على دينا حمدي (ID=33) ===")
r = conn.execute(text("""
    SELECT pt.id, pt.partner_id, pt.type, pt.amount, pt.description, pt.date
    FROM partner_transaction pt 
    WHERE pt.partner_id = 33
    AND pt.description LIKE '%08-2026%'
    AND pt.type IN ('salary_expense', 'personal_salary_expense')
    ORDER BY pt.id
"""))
dina_hamdy_records = r.fetchall()
for row in dina_hamdy_records:
    print(row)
print(f"Total: {len(dina_hamdy_records)} records, Sum: {sum(r[3] for r in dina_hamdy_records)}")

# 3. كل حركات الرواتب لشهر 08-2026 على كل المديرين
print("\n=== ملخص رواتب شهر 08-2026 حسب المدير ===")
r = conn.execute(text("""
    SELECT pt.partner_id, u.fullname, COUNT(*), SUM(pt.amount)
    FROM partner_transaction pt 
    JOIN "user" u ON u.id = pt.partner_id
    WHERE pt.description LIKE '%08-2026%'
    AND pt.type IN ('salary_expense', 'personal_salary_expense')
    GROUP BY pt.partner_id, u.fullname
    ORDER BY pt.partner_id
"""))
for row in r.fetchall():
    print(row)

# 4. تفاصيل كل راتب - نشوف كل موظف اتسجلت رواتبه على مين
print("\n=== تفصيل: كل راتب شهر 08-2026 واتسجل على مين ===")
r = conn.execute(text("""
    SELECT pt.description, pt.partner_id, u.fullname as manager, pt.amount, pt.id
    FROM partner_transaction pt
    JOIN "user" u ON u.id = pt.partner_id
    WHERE pt.description LIKE '%08-2026%'
    AND pt.type IN ('salary_expense', 'personal_salary_expense')
    ORDER BY pt.description, pt.partner_id
"""))
for row in r.fetchall():
    print(row)

conn.close()
