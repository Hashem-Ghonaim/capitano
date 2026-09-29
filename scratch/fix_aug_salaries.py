"""
إصلاح رواتب شهر 08-2026:
- حذف حصة دينا رضا (32) ودينا حمدي (33)
- إعادة توزيع المبالغ على 5 مديرين بدل 7
- الـ 5: أبو إياد (1)، ايهاب حبلص (2)، أبو مالك (3)، السيد الوكيل (4)، سميه حمدي (5)
"""
import sys, os
sys.stdout.reconfigure(encoding='utf-8')
os.environ['DATABASE_URL'] = 'postgresql://postgres.ifattisspktggtshfuyb:Mostafa%23%24Hashem2026%40%40@aws-0-eu-west-2.pooler.supabase.com:6543/postgres'
from sqlalchemy import create_engine, text
db_url = os.environ['DATABASE_URL'].replace('postgresql://', 'postgresql+pg8000://')
e = create_engine(db_url)

# الخطوة 1: جمع البيانات
conn = e.connect()

# كل رواتب 08-2026 على الدينتين
r = conn.execute(text("""
    SELECT pt.id, pt.partner_id, pt.type, pt.amount, pt.description, pt.date
    FROM partner_transaction pt 
    WHERE pt.partner_id IN (32, 33)
    AND pt.description LIKE '%2026-08%'
    AND pt.type IN ('salary_expense', 'personal_salary_expense')
    ORDER BY pt.id
"""))
dina_records = r.fetchall()
print(f"حركات الدينتين لشهر 08: {len(dina_records)}")

# كل الرواتب المميزة (بالوصف)
r = conn.execute(text("""
    SELECT DISTINCT pt.description
    FROM partner_transaction pt 
    WHERE pt.description LIKE '%2026-08%'
    AND pt.type IN ('salary_expense', 'personal_salary_expense')
    ORDER BY pt.description
"""))
distinct_salaries = [row[0] for row in r.fetchall()]
print(f"عدد الرواتب المميزة: {len(distinct_salaries)}")

# لكل راتب، نعرف المبلغ الإجمالي (7 × المبلغ الواحد)
salary_data = []
for desc in distinct_salaries:
    r = conn.execute(text("""
        SELECT pt.amount, COUNT(*)
        FROM partner_transaction pt 
        WHERE pt.description = :desc
        AND pt.type IN ('salary_expense', 'personal_salary_expense')
        GROUP BY pt.amount
    """), {"desc": desc})
    row = r.fetchone()
    per_person_old = row[0]  # المبلغ الحالي (مقسوم على 7)
    total_salary = per_person_old * 7  # الإجمالي الأصلي
    per_person_new = total_salary / 5  # المبلغ الجديد (مقسوم على 5)
    extra_per_person = per_person_new - per_person_old  # الفرق اللي هيتضاف لكل واحد من الـ 5
    
    salary_data.append({
        'desc': desc,
        'old_amount': per_person_old,
        'total': total_salary,
        'new_amount': per_person_new,
        'extra': extra_per_person
    })
    print(f"\n  {desc}")
    print(f"    القديم (/ 7): {per_person_old:.2f}")
    print(f"    الإجمالي: {total_salary:.2f}")
    print(f"    الجديد (/ 5): {per_person_new:.2f}")
    print(f"    الفرق: {extra_per_person:.2f}")

conn.close()

# الخطوة 2: تنفيذ الإصلاح
print("\n" + "="*60)
print("تنفيذ الإصلاح...")
print("="*60)

with e.begin() as conn:
    total_deleted = 0
    total_updated = 0
    
    for sal in salary_data:
        desc = sal['desc']
        new_amount = sal['new_amount']
        
        # 1. حذف حركات الدينتين (32, 33)
        result = conn.execute(text("""
            DELETE FROM partner_transaction 
            WHERE partner_id IN (32, 33)
            AND description = :desc
            AND type IN ('salary_expense', 'personal_salary_expense')
        """), {"desc": desc})
        total_deleted += result.rowcount
        
        # 2. تحديث حصة الـ 5 الباقيين (1, 2, 3, 4, 5)
        # تحديث الوصف ليعكس النسبة الجديدة
        new_desc = desc.replace('[حصة 14.28%]', '[حصة 20%]')
        new_desc = new_desc.replace('[حصة شراكة]', '[حصة 20%]')
        
        result = conn.execute(text("""
            UPDATE partner_transaction 
            SET amount = :new_amount,
                description = :new_desc
            WHERE partner_id IN (1, 2, 3, 4, 5)
            AND description = :old_desc
            AND type IN ('salary_expense', 'personal_salary_expense')
        """), {"new_amount": new_amount, "new_desc": new_desc, "old_desc": desc})
        total_updated += result.rowcount
    
    print(f"\n✅ تم حذف {total_deleted} حركة من حسابات الدينتين")
    print(f"✅ تم تحديث {total_updated} حركة للـ 5 مديرين الباقيين")

# الخطوة 3: التحقق
print("\n" + "="*60)
print("التحقق بعد الإصلاح...")
print("="*60)

conn = e.connect()

print("\n=== ملخص رواتب شهر 08-2026 بعد الإصلاح ===")
r = conn.execute(text("""
    SELECT pt.partner_id, u.fullname, COUNT(*), SUM(pt.amount)
    FROM partner_transaction pt 
    JOIN "user" u ON u.id = pt.partner_id
    WHERE pt.description LIKE '%2026-08%'
    AND pt.type IN ('salary_expense', 'personal_salary_expense')
    GROUP BY pt.partner_id, u.fullname
    ORDER BY pt.partner_id
"""))
for row in r.fetchall():
    print(row)

# تأكد إن الدينتين مفيش عندهم حاجة
print("\n=== حركات الدينتين بعد الإصلاح ===")
r = conn.execute(text("""
    SELECT COUNT(*) 
    FROM partner_transaction 
    WHERE partner_id IN (32, 33)
    AND description LIKE '%2026-08%'
    AND type IN ('salary_expense', 'personal_salary_expense')
"""))
print(f"حركات متبقية: {r.fetchone()[0]}")

conn.close()
