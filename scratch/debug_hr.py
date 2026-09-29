from app import app, db, User, PartnerTransaction, HRTransaction
from sqlalchemy import func

with app.app_context():
    p = User.query.filter_by(fullname='دينا حمدي').first()
    
    pt_sum = db.session.query(func.sum(PartnerTransaction.amount)).filter_by(partner_id=p.id).scalar() or 0.0
    hr_bonus_lt = db.session.query(func.sum(HRTransaction.amount)).filter_by(user_id=p.id, type='bonus').scalar() or 0.0
    hr_draws_lt = db.session.query(func.sum(HRTransaction.amount)).filter(HRTransaction.user_id==p.id, HRTransaction.type.in_(['advance', 'deduction'])).scalar() or 0.0
    
    print(f"PT sum: {pt_sum}")
    print(f"HR bonus sum: {hr_bonus_lt}")
    print(f"HR draws sum: {hr_draws_lt}")
    
    # Dump HR Transactions
    hrs = HRTransaction.query.filter_by(user_id=p.id).all()
    print("HR Transactions:")
    for hr in hrs:
        print(f"{hr.date} | {hr.type} | {hr.amount}")
