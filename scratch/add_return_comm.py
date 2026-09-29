from app import app, db
from sqlalchemy import text

with app.app_context():
    try:
        db.session.execute(text("ALTER TABLE return_invoice ADD COLUMN returned_partner_commission FLOAT DEFAULT 0.0"))
        db.session.commit()
        print("Added returned_partner_commission")
    except Exception as e:
        print("Error:", str(e))
        db.session.rollback()
