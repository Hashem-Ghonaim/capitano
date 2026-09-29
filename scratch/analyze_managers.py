from app import app, db, User, PartnerTransaction
from collections import defaultdict
import json

with app.app_context():
    managers = ['ايهاب حبلص', 'السيد الوكيل', 'سميه حمدي', 'دينا حمدي', 'دينا رضا']
    
    results = {}
    for name in managers:
        u = User.query.filter_by(fullname=name).first()
        if not u:
            continue
            
        pts = PartnerTransaction.query.filter_by(partner_id=u.id).all()
        total_balance = sum(pt.amount for pt in pts)
        
        types_sum = defaultdict(float)
        for pt in pts:
            types_sum[pt.type] += pt.amount
            
        # Also group by month
        month_sum = defaultdict(float)
        for pt in pts:
            month = pt.date.strftime('%Y-%m')
            month_sum[month] += pt.amount
            
        results[name] = {
            'total_balance': total_balance,
            'types_sum': dict(types_sum),
            'month_sum': dict(month_sum)
        }
        
    with open('scratch/manager_analysis.json', 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
