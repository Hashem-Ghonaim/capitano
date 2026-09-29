import sys, os
sys.stdout.reconfigure(encoding='utf-8')
os.environ['DATABASE_URL'] = 'postgresql://postgres.ifattisspktggtshfuyb:Mostafa%23%24Hashem2026%40%40@aws-0-eu-west-2.pooler.supabase.com:6543/postgres'
from sqlalchemy import create_engine, text
db_url = os.environ['DATABASE_URL'].replace('postgresql://', 'postgresql+pg8000://')
e = create_engine(db_url)
conn = e.connect()

# نشوف كل الحركات لشهر 08 على كل المديرين - عشان نفهم الصورة الكاملة
# هنجمع بالوصف (اسم الموظف) عشان نشوف كل راتب اتوزع ازاي
print("=== كل رواتب شهر 08-2026 مجمعة بالوصف ===\n")

r = conn.execute(text("""
    SELECT pt.description, 
           array_agg(pt.partner_id ORDER BY pt.partner_id) as partner_ids,
           array_agg(pt.amount ORDER BY pt.partner_id) as amounts,
           array_agg(pt.id ORDER BY pt.partner_id) as trans_ids,
           COUNT(*) as cnt
    FROM partner_transaction pt 
    WHERE pt.description LIKE '%2026-08%'
    AND pt.type IN ('salary_expense', 'personal_salary_expense')
    GROUP BY pt.description
    ORDER BY pt.description
"""))
for row in r.fetchall():
    desc, pids, amts, tids, cnt = row
    print(f"--- {desc} ---")
    print(f"  Partners: {pids}")
    print(f"  Amounts:  {amts}")
    print(f"  IDs:      {tids}")
    print(f"  Count:    {cnt}")
    print()

conn.close()
