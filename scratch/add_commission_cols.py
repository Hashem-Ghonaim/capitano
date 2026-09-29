from app import app, db
from sqlalchemy import text

with app.app_context():
    try:
        db.session.execute(text("ALTER TABLE product_model ADD COLUMN partner_commission FLOAT DEFAULT 14.0"))
        print("Added partner_commission to product_model")
    except Exception as e:
        print("Error on product_model:", str(e))
        db.session.rollback()

    try:
        db.session.execute(text("ALTER TABLE sale_item ADD COLUMN partner_commission FLOAT DEFAULT 14.0"))
        print("Added partner_commission to sale_item")
    except Exception as e:
        print("Error on sale_item:", str(e))
        db.session.rollback()

    db.session.commit()
    print("Done")
