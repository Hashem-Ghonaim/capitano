import os
from sqlalchemy import create_engine, MetaData, text
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
    db.drop_all()
    db.create_all()
    print("✅ تم تفريغ وإنشاء الجداول بنجاح.")

    # عكس الجداول باستخدام SQLAlchemy لنقل البيانات بشكل ديناميكي
    sqlite_metadata = MetaData()
    sqlite_metadata.reflect(bind=sqlite_engine)
    
    pg_metadata = MetaData()
    pg_metadata.reflect(bind=pg_engine)
    
    print("\n⏳ جاري نقل البيانات من SQLite إلى PostgreSQL...")
    for table in sqlite_metadata.sorted_tables:
        table_name = table.name
        print(f"نقل بيانات الجدول: {table_name} ...")
        
        # التأكد من أن الجدول موجود في PostgreSQL
        if table_name not in pg_metadata.tables:
            print(f"   الجدول غير موجود في PostgreSQL، سيتم تخطيه.")
            continue
            
        pg_table = pg_metadata.tables[table_name]
        valid_columns = set(c.name for c in pg_table.columns)
        
        # قراءة جميع البيانات من جدول SQLite
        with sqlite_engine.connect() as sqlite_conn:
            records = sqlite_conn.execute(table.select()).fetchall()
            
            if records:
                keys = records[0]._mapping.keys() if hasattr(records[0], '_mapping') else records[0].keys()
                # فلترة البيانات لتشمل فقط الأعمدة الموجودة في PostgreSQL
                data_to_insert = [{k: v for k, v in zip(keys, row) if k in valid_columns} for row in records]
                
                with pg_engine.connect() as pg_conn:
                    pg_conn.execute(text("SET session_replication_role = 'replica';"))
                    pg_conn.execute(pg_table.insert(), data_to_insert)
                    pg_conn.execute(text("SET session_replication_role = 'origin';"))
                    pg_conn.commit()
                print(f"   تم نقل {len(records)} سجلات.")
            else:
                print(f"   الجدول فارغ.")

    print("\n🎉 تم اكتمال نقل جميع البيانات بنجاح!")
