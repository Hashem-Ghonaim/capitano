# سكريبت تنظيف الحركات الخاطئة + إعادة حساب العمولات الصحيحة
# الحركات الخاطئة: sub_commission with order_id IS NULL
# هذه حركات تم تسجيلها على كل المديرين بالخطأ (مقسومة على 7)
# بدلاً من تسجيلها على المدير المباشر فقط

import sys, os
sys.stdout.reconfigure(encoding='utf-8')
os.environ['DATABASE_URL'] = 'postgresql://postgres.ifattisspktggtshfuyb:Mostafa%23%24Hashem2026%40%40@aws-0-eu-west-2.pooler.supabase.com:6543/postgres'
from sqlalchemy import create_engine, text
db_url = os.environ['DATABASE_URL'].replace('postgresql://', 'postgresql+pg8000://')
e = create_engine(db_url)

with e.begin() as conn:
    # 1. حذف الحركات الخاطئة
    result = conn.execute(text("""
        DELETE FROM partner_transaction 
        WHERE type = 'sub_commission' AND order_id IS NULL
    """))
    print(f"تم حذف {result.rowcount} حركة خاطئة")

print("\n=== التحقق بعد الحذف ===")
conn = e.connect()
r = conn.execute(text("""
    SELECT COUNT(*) FROM partner_transaction 
    WHERE type = 'sub_commission' AND order_id IS NULL
"""))
print(f"الحركات المتبقية بدون order_id: {r.fetchone()[0]}")

r = conn.execute(text("""
    SELECT pt.partner_id, u.fullname, COUNT(*), SUM(pt.amount) 
    FROM partner_transaction pt 
    JOIN "user" u ON u.id = pt.partner_id 
    WHERE pt.type = 'sub_commission' 
    AND pt.date >= '2026-09-01' AND pt.date < '2026-10-01' 
    GROUP BY pt.partner_id, u.fullname
    ORDER BY pt.partner_id
"""))
print("\n=== العمولات بعد التنظيف (سبتمبر) ===")
for row in r.fetchall():
    print(row)
conn.close()
