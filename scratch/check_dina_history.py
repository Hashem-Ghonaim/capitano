from app import app, db, User, PartnerTransaction, Order

with app.app_context():
    users = ['دينا حمدي', 'دينا رضا']
    
    for u_name in users:
        u = User.query.filter_by(fullname=u_name).first()
        if not u:
            print(f"User {u_name} not found.")
            continue
            
        print("="*50)
        print(f"User: {u.fullname} | Username: {u.username} | Role: {u.role} | ID: {u.id}")
        
        # Check if they have a date created field or similar
        # Since I don't know the exact schema, I'll print dict of columns
        cols = {c.name: getattr(u, c.name) for c in u.__table__.columns if c.name != 'password'}
        print(f"Columns: {cols}")
        
        # Get all transactions before 2026-09-01
        print(f"\nTransactions before 2026-09-01 for {u_name}:")
        old_pts = PartnerTransaction.query.filter(
            PartnerTransaction.partner_id == u.id,
            PartnerTransaction.date < '2026-09-01'
        ).all()
        
        for pt in old_pts:
            print(f"  - Date: {pt.date} | Type: {pt.type} | Amount: {pt.amount} | Desc: {pt.description}")
            
            # If it's a commission, it might mention an order ID
            if 'فاتورة' in pt.description:
                # Try to extract order ID or just say it's an order
                pass
