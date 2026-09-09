import os
import sys
from datetime import datetime

from app import app, db, PartnerTransaction, User

def run_fix():
    with app.app_context():
        # Find all transactions from Sept 1, 2026 onwards related to 20% shares
        start_date = datetime(2026, 9, 1)
        transactions = PartnerTransaction.query.filter(
            PartnerTransaction.date >= start_date,
            PartnerTransaction.description.like('%20%%')
        ).all()

        print(f"Found {len(transactions)} transactions matching '20%' since {start_date}")

        # Group by the exact datetime and base description
        groups = {}
        for t in transactions:
            desc = t.description
            if "حصة (20%): " in desc:
                base_desc = desc.replace("حصة (20%): ", "").strip()
            elif " [حصة 20%]" in desc:
                base_desc = desc.replace(" [حصة 20%]", "").strip()
            else:
                base_desc = desc
            
            key = (base_desc, abs(t.amount))
            if key not in groups:
                groups[key] = []
            groups[key].append(t)

        print(f"Found {len(groups)} unique expense/salary events.")

        all_split_users = ['Elsayd_Elwekel', 'SMSM_Hamdy', 'Ehab_habls', 'Dina_hamdy', 'Dina_reda', 'Abo_Eyad', 'Abo_malek']

        total_correction = 0.0

        for (base_desc, old_share), tx_list in groups.items():
            original_total = old_share * 5
            new_share = original_total / 7
            
            paid_users = {t.partner_id: abs(t.amount) for t in tx_list}
            
            for m_username in all_split_users:
                mgr = User.query.filter_by(username=m_username).first()
                if not mgr and m_username == 'Abo_Eyad':
                    mgr = User.query.filter_by(role='general_manager').first()
                
                if not mgr:
                    continue
                    
                already_paid = paid_users.get(mgr.id, 0.0)
                correction = already_paid - new_share
                
                if abs(correction) > 0.01:  # to avoid floating point zero issues
                    correction_tx = PartnerTransaction(
                        partner_id=mgr.id,
                        type='correction',
                        amount=correction,
                        description=f"تسوية تعديل نسبة الخصم (لـ 7 شركاء): {base_desc}",
                        date=datetime.now()
                    )
                    db.session.add(correction_tx)
                    total_correction += correction

        # Commit changes
        db.session.commit()
        print(f"Net correction (should be very close to 0): {total_correction}")
        print("Done. Uncomment db.session.commit() in the script to apply to DB.")

if __name__ == '__main__':
    run_fix()
