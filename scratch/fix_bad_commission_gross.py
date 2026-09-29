import sys, os
sys.stdout.reconfigure(encoding='utf-8')
os.environ['DATABASE_URL'] = 'postgresql://postgres.ifattisspktggtshfuyb:Mostafa%23%24Hashem2026%40%40@aws-0-eu-west-2.pooler.supabase.com:6543/postgres'
from sqlalchemy import create_engine, text
db_url = os.environ['DATABASE_URL'].replace('postgresql://', 'postgresql+pg8000://')
e = create_engine(db_url)
conn = e.connect()
trans = conn.begin()

try:
    print("=== البحث عن العمولات الغريبة وحذفها ===")
    
    # تحديد الحركات الخاطئة
    res = conn.execute(text("""
        SELECT pt.id, pt.partner_id, pt.amount, pt.description
        FROM partner_transaction pt 
        WHERE pt.type = 'commission_gross'
        AND pt.amount < 0
        AND pt.order_id IS NULL
    """))
    bad_rows = res.fetchall()
    
    print(f"تم العثور على {len(bad_rows)} حركة خاطئة (سالبه وبدون order_id لـ commission_gross).")
    
    for row in bad_rows:
        print(f"ID: {row[0]}, Partner: {row[1]}, Amount: {row[2]}, Desc: {row[3]}")
        
    # حذفها
    if len(bad_rows) > 0:
        res = conn.execute(text("""
            DELETE FROM partner_transaction
            WHERE type = 'commission_gross'
            AND amount < 0
            AND order_id IS NULL
        """))
        print(f"تم مسح {res.rowcount} حركة بنجاح!")
    
    trans.commit()
    print("تم الحفظ في الداتا بيز ✅")
except Exception as e:
    trans.rollback()
    print("❌ خطأ:", e)
finally:
    conn.close()
