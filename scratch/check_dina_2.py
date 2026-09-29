from app import app, db, User, PartnerTransaction, HRTransaction
import sys

with app.app_context():
    u = User.query.filter_by(username='Dina_Hamdy').first()
    if not u:
        u = User.query.filter_by(fullname='دينا حمدي').first()
    
    with open('scratch/dina_test.txt', 'w', encoding='utf-8') as f:
        f.write(f"User: {u.fullname}\n")
        pts = PartnerTransaction.query.filter_by(partner_id=u.id).order_by(PartnerTransaction.date).all()
        f.write(f"PTs: {len(pts)}\n")
        for pt in pts[:5]:
            f.write(f"{pt.date} | {pt.type} | {pt.amount} | {pt.description}\n")
        f.write("...\n")
        for pt in pts[-5:]:
            f.write(f"{pt.date} | {pt.type} | {pt.amount} | {pt.description}\n")
            
        hrs = HRTransaction.query.filter_by(user_id=u.id).order_by(HRTransaction.date).all()
        f.write(f"HRs: {len(hrs)}\n")
        for hr in hrs:
            f.write(f"{hr.date} | {hr.type} | {hr.amount} | {hr.note}\n")
