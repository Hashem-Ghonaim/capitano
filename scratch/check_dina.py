from app import db, User, PartnerTransaction, HRTransaction
from flask import Flask
from app import app

with app.app_context():
    users = User.query.filter(User.username.like('%dina%') | User.username.like('%samia%') | User.fullname.like('%دينا%') | User.fullname.like('%سميه%')).all()
    with open('scratch/dina_output.txt', 'w', encoding='utf-8') as f:
        for u in users:
            f.write(f"User: {u.id} - {u.username} - {u.fullname}\n")
            pts = PartnerTransaction.query.filter_by(partner_id=u.id).order_by(PartnerTransaction.date).all()
            for pt in pts:
                f.write(f"  PT: {pt.date} | {pt.type} | {pt.amount} | {pt.description}\n")
            hrs = HRTransaction.query.filter_by(user_id=u.id).order_by(HRTransaction.date).all()
            for hr in hrs:
                f.write(f"  HR: {hr.date} | {hr.type} | {hr.amount} | {hr.note}\n")
