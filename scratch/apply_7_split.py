import os
from datetime import datetime
from app import app, db, PartnerTransaction, User

def apply_7_split():
    with app.app_context():
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
            
            # The key is base_desc and the timestamp, but timestamps might differ slightly (by milliseconds)
            # if they were created in a loop.
            # Instead, let's group by description and date truncated to minute or second.
            key = (base_desc, t.date.replace(microsecond=0))
            if key not in groups:
                groups[key] = []
            groups[key].append(t)

        print(f"Found {len(groups)} unique expense/salary events.")

        all_7_users = ['Elsayd_Elwekel', 'SMSM_Hamdy', 'Ehab_habls', 'Dina_hamdy', 'Dina_reda', 'Abo_Eyad', 'Abo_malek']
        user_map = {}
        for username in all_7_users:
            u = User.query.filter_by(username=username).first()
            if not u and username == 'Abo_Eyad':
                u = User.query.filter_by(role='general_manager').first()
            if u:
                user_map[username] = u.id

        total_adjusted = 0
        total_created = 0

        for (base_desc, date_key), tx_list in groups.items():
            # Check how many unique partners were charged for this event
            paid_partners = {t.partner_id: t for t in tx_list}
            
            # If the count is 5, it means it was divided by 5
            # Actually, even if it's already 7, we can just recalculate the total and update all 7
            
            # Calculate total amount
            # Since the amount is split, the total amount is sum of absolute amounts
            original_total = sum(abs(t.amount) for t in tx_list)
            
            # If it was split on 5, but maybe some are missing?
            # Usually it's better to find ONE amount, and multiply by the number of people it was split on.
            # Let's see what the old script did:
            # old_share = abs(tx_list[0].amount)
            # original_total = old_share * 5
            
            # Let's find the max amount in the group to avoid tiny floating point differences
            old_share = max(abs(t.amount) for t in tx_list)
            
            # If the group already has 7 partners, maybe it was already divided by 7?
            if len(paid_partners) == 7:
                # It's already 7, let's just make sure the amounts are correct
                new_share = old_share  # Assume it's already correct if it's 7
            else:
                original_total = old_share * 5
                new_share = original_total / 7.0

            # Now, update existing and create missing
            for username in all_7_users:
                uid = user_map.get(username)
                if not uid: continue
                
                if uid in paid_partners:
                    # Update existing
                    t = paid_partners[uid]
                    t.amount = -new_share
                    t.description = t.description.replace("20%", "14.28%") # Update the text to reflect 1/7
                    total_adjusted += 1
                else:
                    # Create new for the missing partners (like Dina and Dina)
                    # We copy the type and date from an existing one
                    sample = tx_list[0]
                    new_t = PartnerTransaction(
                        partner_id=uid,
                        type=sample.type,
                        amount=-new_share,
                        description=sample.description.replace("20%", "14.28%"),
                        date=sample.date
                    )
                    db.session.add(new_t)
                    total_created += 1

        db.session.commit()
        print(f"Adjusted {total_adjusted} existing transactions.")
        print(f"Created {total_created} new transactions for the new partners.")
        
if __name__ == '__main__':
    apply_7_split()
