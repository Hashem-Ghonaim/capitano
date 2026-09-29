from app import app, db, User, PartnerTransaction, HRTransaction
from sqlalchemy import func, cast, Date

with app.app_context():
    p = User.query.filter_by(fullname='دينا حمدي').first()
    start_date_str = '2026-09-01'
    end_date_str = '2026-09-25'
    
    current_balance = db.session.query(func.sum(PartnerTransaction.amount)).filter_by(partner_id=p.id).scalar() or 0.0
    hr_bonus_lt = db.session.query(func.sum(HRTransaction.amount)).filter_by(user_id=p.id, type='bonus').scalar() or 0.0
    hr_draws_lt = db.session.query(func.sum(HRTransaction.amount)).filter(HRTransaction.user_id==p.id, HRTransaction.type.in_(['advance', 'deduction'])).scalar() or 0.0
    hr_draws_lt = abs(hr_draws_lt)
    current_balance = current_balance + hr_bonus_lt - hr_draws_lt

    opening_balance = db.session.query(func.sum(PartnerTransaction.amount)).filter_by(partner_id=p.id, type='opening_balance').scalar() or 0.0

    period_trans = PartnerTransaction.query.filter(
        PartnerTransaction.partner_id == p.id,
        cast(PartnerTransaction.date, Date) >= cast(start_date_str, Date),
        cast(PartnerTransaction.date, Date) <= cast(end_date_str, Date)
    ).all()
    hr_period_trans = HRTransaction.query.filter(
        HRTransaction.user_id == p.id,
        cast(HRTransaction.date, Date) >= cast(start_date_str, Date),
        cast(HRTransaction.date, Date) <= cast(end_date_str, Date)
    ).all()
    
    gross_comm = sum(t.amount for t in period_trans if t.type == 'commission_gross')
    sales_rep_comm = sum(t.amount for t in period_trans if t.type == 'sub_commission')
    discounts = sum(t.amount for t in period_trans if t.type == 'discount_deduction')
    returns = sum(t.amount for t in period_trans if t.type == 'return_penalty')
    expenses = sum(t.amount for t in period_trans if t.type == 'expense_share')
    staff_costs_total = sum(t.amount for t in period_trans if t.type == 'staff_expense')
    salary_expenses = sum(t.amount for t in period_trans if t.type == 'salary_expense')
    period_personal_bonus = sum(t.amount for t in hr_period_trans if t.type == 'bonus')
    period_hr_draws = sum(t.amount for t in hr_period_trans if t.type in ['advance', 'deduction'])
    period_hr_draws = abs(period_hr_draws)
    
    withdrawals_period = sum(t.amount for t in period_trans if t.type in ['withdrawal', 'personal_expense_share', 'personal_salary_expense', 'partner_bonus', 'partner_deduction']) - period_hr_draws
    period_net_profit = gross_comm + sales_rep_comm + discounts + returns + expenses + staff_costs_total + salary_expenses + period_personal_bonus
    period_net_cash = period_net_profit + withdrawals_period
    
    past_balance = current_balance - period_net_cash - opening_balance
    
    print(f"current_balance: {current_balance}")
    print(f"period_net_cash: {period_net_cash}")
    print(f"opening_balance: {opening_balance}")
    print(f"past_balance (calculated): {past_balance}")
    
    # What transactions are missing?
    # All before Sep 1
    before = PartnerTransaction.query.filter(PartnerTransaction.partner_id == p.id, cast(PartnerTransaction.date, Date) < cast(start_date_str, Date)).all()
    print("Before Sep 1 transactions:")
    for b in before: print(f"{b.date} | {b.type} | {b.amount}")
    
    after = PartnerTransaction.query.filter(PartnerTransaction.partner_id == p.id, cast(PartnerTransaction.date, Date) > cast(end_date_str, Date)).all()
    print("After Sep 25 transactions:")
    for a in after: print(f"{a.date} | {a.type} | {a.amount}")
