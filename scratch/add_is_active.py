from app import app, db
from sqlalchemy import text

with app.app_context():
    try:
        db.session.execute(text("ALTER TABLE \"user\" ADD COLUMN is_active BOOLEAN DEFAULT TRUE"))
        db.session.commit()
        print("Added is_active to user table")
    except Exception as e:
        print("Error:", str(e))
        db.session.rollback()
