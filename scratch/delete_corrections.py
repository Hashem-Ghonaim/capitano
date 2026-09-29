from app import app, db, PartnerTransaction

with app.app_context():
    count = PartnerTransaction.query.filter_by(type='correction').count()
    print(f"Found {count} correction transactions. Deleting them...")
    
    PartnerTransaction.query.filter_by(type='correction').delete()
    db.session.commit()
    
    print("Deleted successfully!")
