from app import app, db, User, PartnerTransaction
from sqlalchemy import cast, Date
import json
from datetime import date, datetime

def json_serial(obj):
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")

with app.app_context():
    users = ['دينا حمدي', 'دينا رضا']
    
    with open('scratch/dina_history.txt', 'w', encoding='utf-8') as f:
        for u_name in users:
            u = User.query.filter_by(fullname=u_name).first()
            if not u:
                continue
                
            cols = {c.name: getattr(u, c.name) for c in u.__table__.columns if c.name != 'password'}
            f.write(f"User: {u.fullname}\nColumns: {json.dumps(cols, default=json_serial, ensure_ascii=False)}\n\n")
            
            old_pts = PartnerTransaction.query.filter(
                PartnerTransaction.partner_id == u.id,
                cast(PartnerTransaction.date, Date) < cast('2026-09-01', Date)
            ).all()
            
            f.write(f"Transactions before 2026-09-01 for {u_name}:\n")
            for pt in old_pts:
                f.write(f"  - Date: {pt.date} | Type: {pt.type} | Amount: {pt.amount} | Desc: {pt.description}\n")
            
            f.write("\n==================================\n")
