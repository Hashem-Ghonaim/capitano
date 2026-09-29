# خطة الإصلاح:
# 1. حذف الحركات الخاطئة (sub_commission with order_id=NULL) اللي مقسومة على كل المديرين
# 2. إصلاح كود update_monthly_commissions عشان يفلتر بـ partner_id عند الحذف
# 3. إعادة حساب العمولات الصحيحة

import sys, os
sys.stdout.reconfigure(encoding='utf-8')
os.environ['DATABASE_URL'] = 'postgresql://postgres.ifattisspktggtshfuyb:Mostafa%23%24Hashem2026%40%40@aws-0-eu-west-2.pooler.supabase.com:6543/postgres'
from sqlalchemy import create_engine, text
db_url = os.environ['DATABASE_URL'].replace('postgresql://', 'postgresql+pg8000://')
e = create_engine(db_url)
conn = e.connect()

# فحص: عدد الحركات الخاطئة الإجمالي (كل الأشهر)
print("=== الحركات الخاطئة (sub_commission + order_id IS NULL) كل الأشهر ===")
r = conn.execute(text("""
    SELECT COUNT(*), SUM(amount) 
    FROM partner_transaction 
    WHERE type = 'sub_commission' AND order_id IS NULL
"""))
print(r.fetchone())

print("\n=== تفصيل حسب الشهر ===")
r = conn.execute(text("""
    SELECT to_char(date, 'YYYY-MM') as month, COUNT(*), SUM(amount) 
    FROM partner_transaction 
    WHERE type = 'sub_commission' AND order_id IS NULL
    GROUP BY to_char(date, 'YYYY-MM')
    ORDER BY month
"""))
for row in r.fetchall():
    print(row)

print("\n=== تفصيل حسب المدير (كل الأشهر) ===")
r = conn.execute(text("""
    SELECT pt.partner_id, u.fullname, COUNT(*), SUM(pt.amount) 
    FROM partner_transaction pt 
    JOIN "user" u ON u.id = pt.partner_id 
    WHERE pt.type = 'sub_commission' AND pt.order_id IS NULL
    GROUP BY pt.partner_id, u.fullname
    ORDER BY pt.partner_id
"""))
for row in r.fetchall():
    print(row)

conn.close()
