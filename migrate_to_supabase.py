import os
from sqlalchemy import create_engine, MetaData
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.automap import automap_base

# إعداد قاعدة البيانات المحلية SQLite
SQLITE_URL = 'sqlite:///erp_crm.db'
sqlite_engine = create_engine(SQLITE_URL)
sqlite_session = sessionmaker(bind=sqlite_engine)()

# إعداد قاعدة بيانات PostgreSQL (Supabase)
POSTGRES_URL = os.environ.get('DATABASE_URL')
if not POSTGRES_URL:
    print("❌ خطأ: يرجى إضافة رابط قاعدة بيانات Supabase في المتغير DATABASE_URL")
    exit(1)

if POSTGRES_URL.startswith("postgres://"):
    POSTGRES_URL = POSTGRES_URL.replace("postgres://", "postgresql://", 1)

pg_engine = create_engine(POSTGRES_URL)
pg_session = sessionmaker(bind=pg_engine)()

# استيراد النماذج من التطبيق
from app import db, app

print("🚀 جاري إنشاء الجداول في قاعدة بيانات PostgreSQL...")
with app.app_context():
    # تأكد أن قاعدة البيانات فارغة وجاهزة للبيانات الجديدة
    db.engine.url = pg_engine.url
    db.create_all()
    print("✅ تم إنشاء الجداول بنجاح.")

    # عكس الجداول باستخدام SQLAlchemy لنقل البيانات بشكل ديناميكي
    metadata = MetaData()
    metadata.reflect(bind=sqlite_engine)
    
    print("\n⏳ جاري نقل البيانات من SQLite إلى PostgreSQL...")
    for table_name in metadata.tables:
        table = metadata.tables[table_name]
        print(f"نقل بيانات الجدول: {table_name} ...")
        
        # قراءة جميع البيانات من جدول SQLite
        records = sqlite_engine.execute(table.select()).fetchall()
        
        if records:
            # تحويل البيانات إلى قواميس للتمكن من إدراجها
            data_to_insert = [dict(row) for row in records]
            # إدراج البيانات في PostgreSQL
            pg_engine.execute(table.insert(), data_to_insert)
            print(f"   تم نقل {len(records)} سجلات.")
        else:
            print(f"   الجدول فارغ.")

    print("\n🎉 تم اكتمال نقل جميع البيانات بنجاح!")
