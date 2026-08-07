import os
import json
import pytz
import math
import random
import string
from datetime import datetime, date, timedelta
import calendar
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

def round_half(value):
    if value is None:
        return 0.0
    return round(float(value) * 2) / 2

from werkzeug.utils import secure_filename
from sqlalchemy import func, cast, Date, text, inspect, or_, event
import re  # تأكد أن هذا السطر موجود في أول الملف مع الـ imports
app = Flask(__name__)
import traceback
@app.errorhandler(Exception)
def handle_exception(e):
    # return the traceback as text
    return '<pre>' + traceback.format_exc() + '</pre>', 500

app.config['SECRET_KEY'] = 'master_erp_pro_2025'
# --- Configuration ---
basedir = os.path.abspath(os.path.dirname(__file__))
database_url = os.environ.get('DATABASE_URL')
if database_url:
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
else:
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'erp_crm.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# تحسين أداء الاتصال بقاعدة البيانات في بيئة السيرفرليس (Vercel)
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,
    'pool_recycle': 300,
    'pool_timeout': 20,
}
app.config['UPLOAD_FOLDER'] = os.path.join(basedir, 'static/uploads')

import urllib.request
import urllib.error

def save_uploaded_file(file_obj, filename):
    supabase_url = os.environ.get('SUPABASE_URL')
    supabase_key = os.environ.get('SUPABASE_SECRET_KEY')
    
    if supabase_url and supabase_key:
        try:
            url = f"{supabase_url}/storage/v1/object/uploads/{filename}"
            headers = {
                "Authorization": f"Bearer {supabase_key}",
                "apikey": supabase_key,
                "Content-Type": getattr(file_obj, 'mimetype', 'application/octet-stream'),
                "x-upsert": "true"
            }
            file_content = file_obj.read()
            req = urllib.request.Request(url, data=file_content, headers=headers, method='POST')
            with urllib.request.urlopen(req) as response:
                pass
            return True
        except Exception as e:
            print(f"Error uploading to Supabase: {e}")
            file_obj.seek(0)
            file_obj.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            return False
    else:
        file_obj.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        return True

app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# --- Constants ---
FACTORY_LAT = 30.817600
FACTORY_LNG = 31.004114
ALLOWED_RADIUS = 35 # meters (diameter 70m)

# ==========================================
#               DATABASE MODELS
# ==========================================
def cairo_now():
    return datetime.now(pytz.timezone('Africa/Cairo')).replace(tzinfo=None)
class SystemSetting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(100), default="My ERP")
    company_logo = db.Column(db.String(150), default="default_logo.png") # اسم ملف الصورة
    theme_color = db.Column(db.String(255), default="#0d6efd") # لون النظام

class AttendanceSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    grace_period = db.Column(db.Integer, default=15)  # فترة السماح (دقيقة)
    # شرائح الجزاءات - 4 مستويات
    tier1_max_mins = db.Column(db.Integer, default=30)  # حد شريحة 1
    tier1_penalty = db.Column(db.Float, default=0.25)    # جزاء شريحة 1 (نسبة من اليوم)
    tier2_max_mins = db.Column(db.Integer, default=60)
    tier2_penalty = db.Column(db.Float, default=0.5)
    tier3_max_mins = db.Column(db.Integer, default=120)
    tier3_penalty = db.Column(db.Float, default=1.0)
    tier4_penalty = db.Column(db.Float, default=2.0)     # أكثر من شريحة 3
    # جزاء الغياب
    absent_no_excuse = db.Column(db.Float, default=1.0)  # غياب بدون إذن (نسبة من اليوم)
    absent_excused = db.Column(db.Float, default=0.5)     # غياب بإذن (نسبة من اليوم)
    absent_full_day_excuse = db.Column(db.Float, default=0.0) # إذن يوم كامل
    # عدم تسجيل انصراف
    no_checkout_penalty = db.Column(db.Float, default=2.0) # جزاء عدم تسجيل انصراف (نسبة)
    # أيام الإجازة (تخطيها)
    skip_friday = db.Column(db.Boolean, default=True)
    skip_saturday = db.Column(db.Boolean, default=False)

# === كلاس المستخدم الموحد (ضعه مرة واحدة فقط) ===
# === كلاس المستخدم (النسخة النهائية الكاملة) ===
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    fullname = db.Column(db.String(100), nullable=False)
    username = db.Column(db.String(255), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(255), nullable=False)
    phone = db.Column(db.String(255))
    base_salary = db.Column(db.Float, default=0.0)
    job_type = db.Column(db.String(255), default='fixed')
    emp_code = db.Column(db.String(255), unique=True)
    permissions = db.Column(db.Text, default="")
    manager = db.relationship('User', remote_side=[id], backref='subordinates')
    manager_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    shift_start = db.Column(db.String(255), default='13:00')
    shift_end = db.Column(db.String(255), default='17:00')
    working_hours = db.Column(db.Float, default=8.0)  # عدد ساعات العمل اليومية
    work_from_home = db.Column(db.Boolean, default=False)  # هل يعمل من المنزل؟

    # الأعمدة التي كانت ناقصة وسببت المشكلة 👇
    commission_value = db.Column(db.Float, default=0.0) # قيمة العمولة الثابتة
    commission_rules = db.Column(db.Text, nullable=True) # قواعد الشرائح (JSON)
    salary_method = db.Column(db.String(30), default='direct_manager')
    # القيم: 'partnership' | 'split_4' | 'direct_manager'

    def has_perm(self, perm):
        if self.role == 'general_manager':
            return True
        if not self.permissions:
            return False
        return perm in self.permissions.split(',')
class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    date = db.Column(db.Date, default=date.today)
    check_in = db.Column(db.DateTime, nullable=True)
    check_out = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(255), default='present')
    user = db.relationship('User', backref='attendance_records')
# في ملف app.py - داخل كلاس User


class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), unique=True, nullable=False)

class ProductModel(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'))
    image = db.Column(db.String(150), default='default.png')
    category = db.relationship('Category', backref='products')
    variants = db.relationship('ProductVariant', backref='model', lazy=True, cascade="all, delete-orphan")
class EmployeeExcuse(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    date = db.Column(db.Date, default=date.today)
    type = db.Column(db.String(255)) # 'day' أو 'hours'
    hours = db.Column(db.Float, default=0.0)
    note = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=cairo_now)

    user = db.relationship('User', backref='excuses')
class ProductVariant(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    model_id = db.Column(db.Integer, db.ForeignKey('product_model.id'))
    barcode = db.Column(db.String(255), unique=True)
    cost_price = db.Column(db.Float)
    sell_price = db.Column(db.Float)
    stock = db.Column(db.Integer, default=0)

class Qassa(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_model_id = db.Column(db.Integer, db.ForeignKey('product_model.id'), nullable=True)
    custom_name = db.Column(db.String(150), nullable=True) # في حالة عدم اختيار منتج من المخزن
    custom_image = db.Column(db.String(150), default='default.png') # في حالة رفع صورة يدوية
    code = db.Column(db.String(100)) # كود القطعة المخصص للقصة
    factory = db.Column(db.String(150))
    quantity = db.Column(db.Integer, default=1)
    status = db.Column(db.String(255), default='جار التصنيع') # 'جار التصنيع' أو 'تم الاستلام'
    created_at = db.Column(db.DateTime, default=cairo_now)
    
    product_model = db.relationship('ProductModel')
    history = db.relationship('QassaHistory', backref='qassa', lazy=True, cascade="all, delete-orphan")

class QassaHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    qassa_id = db.Column(db.Integer, db.ForeignKey('qassa.id'))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    action_detail = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=cairo_now)
    
    user = db.relationship('User')
class Supplier(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(255))
    balance = db.Column(db.Float, default=0.0)
# جدول جديد لتسجيل حركات الشركاء بالتفصيل الممل
class PartnerTransaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    partner_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    order_id = db.Column(db.Integer, db.ForeignKey('sale_order.id'), nullable=True)
    type = db.Column(db.String(255))
    amount = db.Column(db.Float)
    description = db.Column(db.String(255))
    date = db.Column(db.DateTime, default=cairo_now)

    # العلاقات
    # لاحظ: نحدد foreign_keys هنا لأن الجدول فيه علاقة مع User
    partner = db.relationship('User', foreign_keys=[partner_id], backref='transactions')
    order = db.relationship('SaleOrder')
class SupplierPayment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'))
    amount = db.Column(db.Float, nullable=False)
    date = db.Column(db.DateTime, default=cairo_now)
    receipt_image = db.Column(db.String(150))
    notes = db.Column(db.String(200))

    # === الإضافة الجديدة: ربط الدفع بالخزينة ===
    account_id = db.Column(db.Integer, db.ForeignKey('money_account.id'))

    supplier = db.relationship('Supplier', backref='payments')
    account = db.relationship('MoneyAccount') # عشان نقدر نجيب اسم الخزنة

class PurchaseOrder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'))
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    date = db.Column(db.DateTime, default=cairo_now)
    total_cost = db.Column(db.Float, default=0.0)
    status = db.Column(db.String(255), default='received')
    supplier = db.relationship('Supplier', backref='orders')
    items = db.relationship('PurchaseItem', backref='purchase_order', lazy=True, cascade="all, delete-orphan")

class PurchaseItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    purchase_id = db.Column(db.Integer, db.ForeignKey('purchase_order.id'))
    variant_id = db.Column(db.Integer, db.ForeignKey('product_variant.id'))
    quantity = db.Column(db.Integer)
    unit_cost = db.Column(db.Float)
    total_cost = db.Column(db.Float)
    variant = db.relationship('ProductVariant')

class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(255), unique=True, nullable=False)
    address = db.Column(db.String(200))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=cairo_now)
    created_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_by = db.relationship('User', foreign_keys=[created_by_id])
    orders = db.relationship('SaleOrder', backref='customer', lazy=True)
    balance = db.Column(db.Float, default=0.0) # رصيد العميل (مديونيته)
class CustomerPayment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'))
    amount = db.Column(db.Float, nullable=False)
    date = db.Column(db.DateTime, default=cairo_now)
    account_id = db.Column(db.Integer, db.ForeignKey('money_account.id'))
    notes = db.Column(db.String(200))

    customer = db.relationship('Customer', backref='payments_received')
    account = db.relationship('MoneyAccount')

class ShippingCompany(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(255))
    cs_number = db.Column(db.String(255))
    fee_first_1k = db.Column(db.Float, default=0.0)
    fee_extra_1k = db.Column(db.Float, default=0.0)
    orders = db.relationship('SaleOrder', backref='courier', lazy=True)

class SaleOrder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=True)
    date = db.Column(db.DateTime, default=cairo_now)
    total_amount = db.Column(db.Float)
    discount = db.Column(db.Float, default=0.0)
    final_total = db.Column(db.Float)
    sales_rep_code = db.Column(db.String(255))
    packer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    packer = db.relationship('User', foreign_keys=[packer_id])
    is_shipping = db.Column(db.Boolean, default=False)
    shipping_company_id = db.Column(db.Integer, db.ForeignKey('shipping_company.id'), nullable=True)
    shipping_fee = db.Column(db.Float, default=0.0)
    shipping_paid_by = db.Column(db.String(255), default='customer')  # 'customer' or 'manager'
    paid_upfront = db.Column(db.Float, default=0.0)
    amount_due = db.Column(db.Float, default=0.0)
    waybill_no = db.Column(db.String(255), nullable=True)
    shipping_status = db.Column(db.String(255), default='none')
    is_proforma = db.Column(db.Boolean, default=False)
    is_reviewed = db.Column(db.Boolean, default=False)
    shipping_notes = db.Column(db.String(255), nullable=True)
    items = db.relationship('SaleItem', backref='order', lazy=True, cascade="all, delete-orphan")
    sales_rep = db.relationship('User', backref='sales', foreign_keys=[user_id])

class SaleItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('sale_order.id'))
    variant_id = db.Column(db.Integer, db.ForeignKey('product_variant.id'))
    quantity = db.Column(db.Integer)
    unit_price = db.Column(db.Float)
    total_price = db.Column(db.Float)
    variant = db.relationship('ProductVariant')
class FinancialTransaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(255), nullable=False)
    category = db.Column(db.String(100))
    amount = db.Column(db.Float, nullable=False)
    description = db.Column(db.Text)
    # Always store treasury timestamps in Cairo local time for consistent ordering/display.
    date = db.Column(db.DateTime, default=cairo_now)
    created_by_id = db.Column(db.Integer, db.ForeignKey('user.id'))

    # === الإضافة الجديدة 👇 ===
    account_id = db.Column(db.Integer, db.ForeignKey('money_account.id'), nullable=True)

    created_by = db.relationship('User', foreign_keys=[created_by_id])
    account = db.relationship('MoneyAccount', backref='transactions')

class PendingFinancialAction(db.Model):
    """إجراء مالي معلق في انتظار موافقة المدير العام"""
    __tablename__ = 'pending_financial_action'
    id = db.Column(db.Integer, primary_key=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    target_emp_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    action_type = db.Column(db.String(255), nullable=False)  # advance / bonus / deduction
    amount = db.Column(db.Float, nullable=False)
    account_id = db.Column(db.Integer, db.ForeignKey('money_account.id'), nullable=True)
    note = db.Column(db.Text)
    date = db.Column(db.DateTime, default=datetime.now)
    status = db.Column(db.String(255), default='pending')  # pending / approved / rejected
    reviewed_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    reject_reason = db.Column(db.Text, nullable=True)

    creator = db.relationship('User', foreign_keys=[created_by_id])
    target_emp = db.relationship('User', foreign_keys=[target_emp_id])
    reviewer = db.relationship('User', foreign_keys=[reviewed_by_id])
    account = db.relationship('MoneyAccount')
class ReturnInvoice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('sale_order.id'), nullable=False)
    date = db.Column(db.DateTime, default=datetime.now)
    shipping_loss = db.Column(db.Float, default=0.0)
    missing_items_cost = db.Column(db.Float, default=0.0)
    missing_items_desc = db.Column(db.String(255))
    total_deduction = db.Column(db.Float, default=0.0)
    total_qty = db.Column(db.Integer, default=0) # كمية المرتجعات
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    notes = db.Column(db.Text)
    order = db.relationship('SaleOrder', backref=db.backref('return_invoices', lazy=True))
    creator = db.relationship('User')
class MoneyAccount(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    type = db.Column(db.String(255), default='cash') # cash, vodafone, bank, instapay
    account_number = db.Column(db.String(255)) # رقم الموبايل أو رقم الحساب
    balance = db.Column(db.Float, default=0.0)
class StockMovement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    variant_id = db.Column(db.Integer, db.ForeignKey('product_variant.id'))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    quantity_change = db.Column(db.Integer)
    reason = db.Column(db.String(100))
    timestamp = db.Column(db.DateTime, default=cairo_now)
    variant = db.relationship('ProductVariant', backref='movements')
    user = db.relationship('User')

class HRTransaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    type = db.Column(db.String(255))
    amount = db.Column(db.Float)
    date = db.Column(db.DateTime, default=cairo_now)
    note = db.Column(db.String(200))

class ExpenseCategory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), unique=True, nullable=False)

class Expense(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.Integer, db.ForeignKey('expense_category.id'))
    amount = db.Column(db.Float, nullable=False)
    description = db.Column(db.String(200))
    date = db.Column(db.DateTime, default=cairo_now)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    is_shared = db.Column(db.Boolean, default=False)

    # === الإضافة الجديدة ===
    account_id = db.Column(db.Integer, db.ForeignKey('money_account.id'))

    # العلاقات
    category = db.relationship('ExpenseCategory', backref='expenses')
    created_by = db.relationship('User', foreign_keys=[user_id])
    account = db.relationship('MoneyAccount') # عشان نعرف اسم الخزنة

# === سجل المحذوفات للرقابة ===
class DeletedItemLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    table_name = db.Column(db.String(100), nullable=False)
    record_id = db.Column(db.Integer, nullable=True)
    record_summary = db.Column(db.Text, nullable=True)
    deleted_by = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    deleted_at = db.Column(db.DateTime, default=cairo_now)

    deleter = db.relationship('User', foreign_keys=[deleted_by])

@event.listens_for(db.Model, 'before_delete', propagate=True)
def intercept_delete(mapper, connection, target):
    # Avoid logging deletions of the log itself
    if target.__class__.__name__ == 'DeletedItemLog': return
    
    summary = {}
    for column in target.__table__.columns:
        val = getattr(target, column.key)
        if hasattr(val, 'isoformat'): val = val.isoformat()
        summary[column.key] = str(val) if val is not None else None

    # Custom logic to capture invoice items before deletion
    if target.__class__.__name__ == 'SaleOrder':
        try:
            items_info = []
            for item in getattr(target, 'items', []):
                product_name = item.variant.model.name if item.variant and item.variant.model else 'منتج غير معروف'
                items_info.append(f"{product_name} (الكمية: {item.quantity}, السعر: {item.unit_price})")
            if items_info:
                summary['invoice_items_details'] = " | ".join(items_info)
        except Exception:
            pass
    
    # Safely get current user ID mostly
    try:
        from flask_login import current_user
        uid = current_user.id if current_user and current_user.is_authenticated else None
    except:
        uid = None

    connection.execute(
        DeletedItemLog.__table__.insert().values(
            table_name=target.__class__.__name__,
            record_id=getattr(target, 'id', None),
            record_summary=json.dumps(summary, ensure_ascii=False),
            deleted_by=uid,
            deleted_at=cairo_now()
        )
    )

# ==========================================
#               HELPERS
# ==========================================

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

@app.context_processor
def inject_global_vars():
    settings = SystemSetting.query.first()
    
    pending_reviews_count = 0
    try:
        from flask_login import current_user
        if current_user.is_authenticated and current_user.role == 'general_manager':
            pending_reviews_count = SaleOrder.query.filter_by(is_proforma=False, is_reviewed=False).count()
    except:
        pass
        
    return dict(
        company_logo=settings.company_logo if settings and settings.company_logo else 'default_logo.png',
        theme_color=settings.theme_color if settings and settings.theme_color else '#0d6efd',
        pending_reviews_count=pending_reviews_count
    )

def general_manager_required(f):
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if current_user.role != 'general_manager': return "غير مصرح (المدير العام فقط)", 403
        return f(*args, **kwargs)
    return decorated_function
@app.route('/permissions', methods=['GET', 'POST'])
@login_required
def manage_permissions():
    if current_user.role != 'general_manager':
        return "غير مصرح لك", 403

    if request.method == 'POST':
        user_id = request.form.get('user_id')
        user = User.query.get(user_id)
        if user:
            # تجميع الصلاحيات المختارة من الفورم
            # getlist تأتي بكل الـ checkboxes المختارة
            perms = request.form.getlist('perms')
            user.permissions = ",".join(perms) # تحويل القائمة لنص: "view_x,manage_x"
            db.session.commit()
            flash(f'تم تحديث صلاحيات {user.fullname} بنجاح', 'success')
        return redirect(url_for('manage_permissions'))

    users = User.query.filter(User.role != 'general_manager').all()

    # تعريف قائمة الصلاحيات المتاحة في النظام
    system_permissions = {
        'المخزون': [('view_inventory', 'رؤية المخزون'), ('manage_inventory', 'تعديل المخزون (إضافة/حذف)')],
        'الشحن': [('view_shipping', 'رؤية الشحن'), ('manage_shipping', 'إدارة الشحن (تغيير حالة)')],
        'المبيعات': [('view_invoices', 'سجل الفواتير'), ('manage_orders', 'حذف/تعديل الفواتير'), ('edit_invoice', 'تعديل أصناف الفاتورة التامة'), ('revert_to_proforma', 'إرجاع الفاتورة لمسودة')],
        'الخزينة': [('view_treasury', 'رؤية الخزينة'), ('manage_treasury', 'إدارة الأموال')],
        'العملاء': [('view_customers', 'رؤية العملاء'), ('manage_customers', 'إضافة/تعديل عملاء')],
        'الإنتاج': [('manage_qassat', 'إدارة القصات (التصنيع)')],
    }

    return render_template('permissions.html', users=users, system_perms=system_permissions)
def permission_required(perm_name):
    def decorator(f):
        @wraps(f)
        @login_required
        def decorated_function(*args, **kwargs):
            if not current_user.has_perm(perm_name):
                flash(f'عفواً، ليس لديك صلاحية: {perm_name}', 'danger')
                return redirect(request.referrer or url_for('dashboard'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371e3
    phi1 = lat1 * math.pi / 180
    phi2 = lat2 * math.pi / 180
    delta_phi = (lat2 - lat1) * math.pi / 180
    delta_lambda = (lon2 - lon1) * math.pi / 180
    a = math.sin(delta_phi/2) * math.sin(delta_phi/2) + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda/2) * math.sin(delta_lambda/2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

def calculate_user_commission(user, quantity_to_pay, total_monthly_context=None):
    """
    quantity_to_pay: عدد القطع اللي عايزين نحسب فلوسها (مثلاً 50 قطعة في الفاتورة دي)
    total_monthly_context: إجمالي مبيعات البنت في الشهر كله (عشان نحدد الشريحة)
    """
    commission = 0.0

    # لو لم يتم تمرير الإجمالي، نعتبره هو نفس الكمية الحالية (للحماية)
    if total_monthly_context is None:
        total_monthly_context = quantity_to_pay

    # 1. العمولة الثابتة (لو موجودة)
    if user.commission_value and user.commission_value > 0:
        commission += quantity_to_pay * user.commission_value

    # 2. نظام الشرائح التراكمي (Tiered Sales)
    if user.job_type == 'tiered_sales' and user.commission_rules:
        try:
            tiers = json.loads(user.commission_rules)
            selected_tier_val = 0.0

            # بنلف على الشرائح عشان نشوف "الإجمالي الشهري" يقع فين
            for tier in tiers:
                tier_min = float(tier.get('min', 0))
                tier_max = float(tier.get('max', 999999))
                tier_val = float(tier.get('val', 0)) # سعر القطعة في الشريحة دي

                # هنا بنقارن "الإجمالي الشهري" مش فاتورة دلوقتي بس
                if tier_min <= total_monthly_context <= tier_max:
                    selected_tier_val = tier_val
                    break

            # بعد ما عرفنا سعر القطعة المناسب لمجهودها الشهري، نضربه في عدد قطع الفاتورة
            if selected_tier_val > 0:
                commission += quantity_to_pay * selected_tier_val

        except Exception as e:
            print(f"Error calculating tiers: {e}")

    return commission
def get_accessible_users():
    """
    ترجع قائمة بمعرفات المستخدمين (IDs) الذين يحق للمستخدم الحالي رؤية بياناتهم.
    """
    # المدير العام أو الموظفة الخاصة EMP201 أبو مالك يشوفوا الكل
    if current_user.role == 'general_manager' or current_user.emp_code == 'EMP201' or current_user.username == 'Abo_malek':
        return [u.id for u in User.query.all()]

    elif current_user.role == 'manager':
        # مدير الفريق يرى نفسه + الموظفين الذين يدارون من قبله
        team = User.query.filter_by(manager_id=current_user.id).all()
        return [current_user.id] + [u.id for u in team]

    else:
        # الموظف العادي يرى بياناته هو فقط
        return [current_user.id]
# دالة العملاء (نزلتها زي ما هي بالظبط عشان متتأثرش)
def get_allowed_customers():
    if current_user.role in ['general_manager', 'partner']:
        return Customer.query.order_by(Customer.id.desc()).all()
    elif current_user.role == 'manager':
        subordinates_ids = [u.id for u in current_user.subordinates]
        subordinates_ids.append(current_user.id)
        return Customer.query.filter(Customer.created_by_id.in_(subordinates_ids)).order_by(Customer.id.desc()).all()
    else:
        return Customer.query.filter_by(created_by_id=current_user.id).order_by(Customer.id.desc()).all()
# ==========================================
#               ROUTES
# ==========================================
@app.route('/partners/report')
@general_manager_required
def partners_report():
    partners = User.query.filter(User.role.in_(['manager', 'general_manager', 'partner']), User.username.notin_(['Abo_Eyad', 'Abo_malek'])).all()
    report_data = []

    today = date.today()
    start_date_str = request.args.get('start_date', today.replace(day=1).strftime('%Y-%m-%d'))
    end_date_str = request.args.get('end_date', today.strftime('%Y-%m-%d'))

    grand_total_period = 0

    for p in partners:
        # 1. الحساب الحقيقي والمباشر للرصيد (الجمع الجبري لكل الحركات)
        # هذا هو الرقم النهائي الذي يحدد هل هو له أم عليه أم خالص
        current_balance = db.session.query(func.sum(PartnerTransaction.amount)).filter_by(partner_id=p.id).scalar() or 0.0

        # جلب الحركات الخاصة بالموارد البشرية التراكمية للمدير نفسه (مكافآت، سلف، جزاءات) لتوحيد الأرقام مع البروفايل
        hr_bonus_lt = db.session.query(func.sum(HRTransaction.amount)).filter_by(user_id=p.id, type='bonus').scalar() or 0.0
        hr_draws_lt = db.session.query(func.sum(HRTransaction.amount)).filter(HRTransaction.user_id==p.id, HRTransaction.type.in_(['advance', 'deduction'])).scalar() or 0.0
        hr_draws_lt = abs(hr_draws_lt)

        current_balance = current_balance + hr_bonus_lt - hr_draws_lt

        # الرصيد الافتتاحي (لعرضه في التقرير)
        opening_balance = db.session.query(func.sum(PartnerTransaction.amount)).filter_by(partner_id=p.id, type='opening_balance').scalar() or 0.0

        # 2. تفصيل المبالغ للعرض فقط
        all_trans = PartnerTransaction.query.filter_by(partner_id=p.id).all()
        # إجمالي الأرباح (كل ما هو ليس سحب أو حركة شخصية) + مكافآته الشخصية من الـ HR
        total_earned = sum(t.amount for t in all_trans if t.type not in ['withdrawal', 'personal_expense_share', 'personal_salary_expense', 'partner_bonus', 'partner_deduction']) + hr_bonus_lt
        # إجمالي المسحوبات والحركات الشخصية (في PartnerTransaction تكون سالبة ونطرح مسحوبات الموارد البشرية لنجعلها سالبة أيضاً)
        total_withdrawn = sum(t.amount for t in all_trans if t.type in ['withdrawal', 'personal_expense_share', 'personal_salary_expense', 'partner_bonus', 'partner_deduction']) - hr_draws_lt

        # 3. حساب أرقام الفترة (للتحليل المالي)
        period_trans = PartnerTransaction.query.filter(
            PartnerTransaction.partner_id == p.id,
            cast(PartnerTransaction.date, Date) >= start_date_str,
            cast(PartnerTransaction.date, Date) <= end_date_str
        ).all()
        
        hr_period_trans = HRTransaction.query.filter(
            HRTransaction.user_id == p.id,
            cast(HRTransaction.date, Date) >= start_date_str,
            cast(HRTransaction.date, Date) <= end_date_str
        ).all()

        gross_comm = sum(t.amount for t in period_trans if t.type == 'commission_gross')
        sales_rep_comm = sum(t.amount for t in period_trans if t.type == 'sub_commission')
        discounts = sum(t.amount for t in period_trans if t.type == 'discount_deduction')
        returns = sum(t.amount for t in period_trans if t.type == 'return_penalty')
        expenses = sum(t.amount for t in period_trans if t.type == 'expense_share')
        staff_costs_total = sum(t.amount for t in period_trans if t.type == 'staff_expense')
        
        staff_bonuses = sum(t.amount for t in period_trans if t.type == 'staff_expense' and 'مكافأة' in (t.description or ''))
        # الباقي من مصاريف الطاقم (سلف، جزاءات، الخ)
        staff_other = staff_costs_total - staff_bonuses

        salary_expenses = sum(t.amount for t in period_trans if t.type == 'salary_expense')
        
        # حركات فترة الموارد البشرية للمدير نفسه
        period_personal_bonus = sum(t.amount for t in hr_period_trans if t.type == 'bonus')
        period_hr_draws = sum(t.amount for t in hr_period_trans if t.type in ['advance', 'deduction'])
        period_hr_draws = abs(period_hr_draws)

        withdrawals_period = sum(t.amount for t in period_trans if t.type in ['withdrawal', 'personal_expense_share', 'personal_salary_expense', 'partner_bonus', 'partner_deduction']) - period_hr_draws

        # صافي ربح النشاط (بدون المسحوبات، مع إضافة المكافآت الشخصية)
        period_net_profit = gross_comm + sales_rep_comm + discounts + returns + expenses + staff_costs_total + salary_expenses + period_personal_bonus
        
        # صافي حركة النقدية (الربح - المسحوبات)
        period_net_cash = period_net_profit + withdrawals_period

        grand_total_period += period_net_profit

        # Helper to build detail list from transactions
        def build_details(trans_list, trans_type=None, condition=None):
            return [
                {
                    'amount': t.amount,
                    'desc': getattr(t, 'description', getattr(t, 'note', '---')) or '---',
                    'date': t.date.strftime('%Y-%m-%d'),
                    'order_id': getattr(t, 'order_id', None),
                    'invoice_label': f"فاتورة #{t.order_id}" if getattr(t, 'order_id', None) else "---"
                }
                for t in trans_list if (t.type == trans_type if trans_type else True) and (condition(t) if condition else True)
            ]

        # نجهز قائمة مدمجة للمسحوبات
        withdrawals_details = build_details(period_trans, None, lambda t: t.type in ['withdrawal', 'personal_expense_share', 'personal_salary_expense', 'partner_bonus', 'partner_deduction'])
        for ht in hr_period_trans:
            if ht.type in ['advance', 'deduction']:
                withdrawals_details.append({
                    'amount': -abs(ht.amount),
                    'desc': f"من الموارد البشرية: {ht.note or '---'}",
                    'date': ht.date.strftime('%Y-%m-%d'),
                    'order_id': None,
                    'invoice_label': '---'
                })

        # حساب القطع من الفواتير مباشرة (وليس من العمولات / 14) لضمان الدقة
        p_team_ids = [p.id] + [t.id for t in User.query.filter(User.manager_id == p.id).all()]
        p_gross_items = db.session.query(func.sum(SaleItem.quantity)).join(SaleOrder).filter(
            SaleOrder.is_proforma == False,
            SaleOrder.user_id.in_(p_team_ids),
            cast(SaleOrder.date, Date) >= start_date_str,
            cast(SaleOrder.date, Date) <= end_date_str
        ).scalar() or 0
        p_returned_items = db.session.query(func.sum(ReturnInvoice.total_qty)).join(SaleOrder).filter(
            SaleOrder.user_id.in_(p_team_ids),
            cast(ReturnInvoice.date, Date) >= start_date_str,
            cast(ReturnInvoice.date, Date) <= end_date_str
        ).scalar() or 0
        p_net_items = max(0, p_gross_items - p_returned_items)

        report_data.append({
            'id': p.id,
            'name': p.fullname,
            'sold_items': int(p_net_items),
            'gross_comm': round_half(gross_comm),
            'personal_bonuses': round_half(period_personal_bonus),
            'sales_rep_comm': round_half(sales_rep_comm),
            'discounts': round_half(discounts),
            'returns': round_half(returns),
            'expenses': round_half(expenses),
            'staff_other': round_half(staff_other),
            'staff_bonuses': round_half(staff_bonuses),
            'salary_expenses': round_half(salary_expenses),
            
            # تفاصيل كل نوع للعرض في المودال
            'gross_comm_details': build_details(period_trans, 'commission_gross'),
            'personal_bonuses_details': build_details(hr_period_trans, 'bonus'),
            'sales_comm_details': build_details(period_trans, 'sub_commission'),
            'discounts_details': build_details(period_trans, 'discount_deduction'),
            'returns_details': build_details(period_trans, 'return_penalty'),
            'expenses_details': build_details(period_trans, 'expense_share'),
            'staff_other_details': build_details(period_trans, 'staff_expense', lambda t: 'مكافأة' not in (t.description or '')),
            'staff_bonuses_details': build_details(period_trans, 'staff_expense', lambda t: 'مكافأة' in (t.description or '')),
            'salary_expenses_details': build_details(period_trans, 'salary_expense'),
            'withdrawals_details': withdrawals_details,

            'period_net_profit': round_half(period_net_profit),
            'withdrawals_period': round_half(abs(withdrawals_period)),
            'period_net_cash': round_half(period_net_cash),
            
            'total_earned': round_half(total_earned),
            'total_withdrawn': round_half(abs(total_withdrawn)),
            'opening_balance': round_half(opening_balance),
            'current_balance': round_half(current_balance)
        })
        
    # --- حسابات تصفية الشراكة الخاصة بالفريق المشترك (أبو إياد وأبو مالك) في الفترة المحددة ---
    malek_user = User.query.filter_by(username='Abo_malek').first()
    malek_id = malek_user.id if malek_user else 3
    shared_team_users = User.query.filter(
        db.or_(User.id == malek_id, User.manager_id == malek_id)
    ).all()
    shared_team_ids = [tu.id for tu in shared_team_users]
    
    # 1. عدد القطع المباعة من الفريق المشترك في الفترة
    shared_team_items = db.session.query(func.sum(SaleItem.quantity))\
        .join(SaleOrder)\
        .filter(SaleOrder.is_proforma == False,
                cast(SaleOrder.date, Date) >= start_date_str,
                cast(SaleOrder.date, Date) <= end_date_str,
                SaleOrder.user_id.in_(shared_team_ids)).scalar() or 0
                
    # 2. إجمالي الخصميات والمصاريف المشتركة للشركاء (ID 1 و 3) في الفترة المحددة
    # نجلب الخصميات التي نزلت على حساباتهم في هذه الفترة
    partners_period_deductions = PartnerTransaction.query.filter(
        PartnerTransaction.partner_id.in_([1, 3]),
        PartnerTransaction.type.in_(['discount_deduction', 'return_penalty', 'expense_share', 'staff_expense']),
        cast(PartnerTransaction.date, Date) >= start_date_str,
        cast(PartnerTransaction.date, Date) <= end_date_str
    ).all()
    
    total_period_deductions = sum(t.amount for t in partners_period_deductions)
    # نسبة التحمل ثابتة كفريق واحد مقسومة بالنص
    malek_percent = 50.0
    eyad_percent = 50.0
    malek_deduction_share = total_period_deductions * (malek_percent / 100.0)
    eyad_deduction_share = total_period_deductions * (eyad_percent / 100.0)
    
    shared_team_data = {
        'total_items': shared_team_items,
        'malek_percent': malek_percent,
        'eyad_percent': eyad_percent,
        'malek_deduction_share': round_half(abs(malek_deduction_share)),
        'eyad_deduction_share': round_half(abs(eyad_deduction_share))
    }

    # --- بيانات أصحاب الشركة للتصفية (بنفس حسابات صفحة الملف الشخصي Lifetime) ---
    # 1. إجمالي ربح المبيعات للشركة كلها (سعر البيع - سعر التكلفة) تراكمي
    lifetime_global_gross = db.session.query(
        func.sum(SaleItem.quantity * (SaleItem.unit_price - ProductVariant.cost_price))
    ).join(SaleOrder)\
     .join(ProductVariant, SaleItem.variant_id == ProductVariant.id)\
     .filter(SaleOrder.is_proforma == False).scalar() or 0.0

    # 2. المصاريف العامة تراكمي
    def get_lifetime_sum(type_name):
        val = db.session.query(func.sum(PartnerTransaction.amount)).filter(
            PartnerTransaction.type == type_name
        ).scalar()
        return abs(val) if val else 0.0

    lt_girls_comm = get_lifetime_sum('sub_commission')
    lt_discounts = get_lifetime_sum('discount_deduction')
    lt_returns = get_lifetime_sum('return_penalty')
    lt_expenses = get_lifetime_sum('expense_share')
    lt_staff_costs = get_lifetime_sum('staff_expense')
    lt_shipping_extra = get_lifetime_sum('shipping_extra_commission')
    lt_bonuses = db.session.query(func.sum(HRTransaction.amount))\
        .filter(HRTransaction.type == 'bonus').scalar() or 0.0

    lifetime_net_profit = lifetime_global_gross - (
        lt_girls_comm + lt_discounts + lt_returns + lt_expenses + lt_staff_costs + lt_shipping_extra + lt_bonuses
    )
    lifetime_partner_share = lifetime_net_profit / 2.0

    owners = User.query.filter(User.username.in_(['Abo_Eyad', 'Abo_malek'])).all()
    owners_data = []
    for o in owners:
        # سحوبات من حركات الشركاء
        o_partner_withdrawn = db.session.query(func.sum(PartnerTransaction.amount)).filter(
            PartnerTransaction.partner_id == o.id,
            PartnerTransaction.type.in_(['withdrawal', 'personal_expense_share', 'personal_salary_expense'])
        ).scalar() or 0.0
        # سلفيات وخصومات من الموارد البشرية
        o_hr_withdrawn = db.session.query(func.sum(HRTransaction.amount)).filter(
            HRTransaction.user_id == o.id,
            HRTransaction.type.in_(['advance', 'deduction'])
        ).scalar() or 0.0
        
        o_total_withdrawn = abs(o_partner_withdrawn) + abs(o_hr_withdrawn)
        o_opening = db.session.query(func.sum(PartnerTransaction.amount)).filter_by(partner_id=o.id, type='opening_balance').scalar() or 0.0
        
        # الرصيد الشخصي = حصة الشراكة + الرصيد الافتتاحي - السحوبات والمصروفات الشخصية
        o_final_net = lifetime_partner_share + o_opening - o_total_withdrawn
        
        owners_data.append({
            'id': o.id,
            'name': o.fullname,
            'total_earned': round_half(lifetime_partner_share),
            'total_withdrawn': round_half(o_total_withdrawn),
            'opening_balance': round_half(o_opening),
            'current_balance': round_half(o_final_net)
        })

    accounts = MoneyAccount.query.all()
    return render_template('partners_report.html',
                           report=report_data,
                           grand_total=round_half(grand_total_period),
                           start_date=start_date_str,
                           end_date=end_date_str,
                           accounts=accounts,
                           shared_team=shared_team_data,
                           owners=owners_data)


@app.route('/debug_profit_comparison')
@general_manager_required
def debug_profit_comparison():
    """مسار مؤقت لتشخيص الفرق بين صفحة الشراكة والملف الشخصي"""
    from sqlalchemy import func as fn

    gross = db.session.query(
        fn.sum(SaleItem.quantity * (SaleItem.unit_price - ProductVariant.cost_price))
    ).join(SaleOrder).join(ProductVariant, SaleItem.variant_id == ProductVariant.id)\
     .filter(SaleOrder.is_proforma == False).scalar() or 0.0

    def pt_sum(t):
        val = db.session.query(fn.sum(PartnerTransaction.amount)).filter(
            PartnerTransaction.type == t, PartnerTransaction.partner_id.in_([1, 3])
        ).scalar()
        return abs(val) if val else 0.0

    girls = pt_sum('sub_commission')
    disc = pt_sum('discount_deduction')
    ret = pt_sum('return_penalty')
    exp = pt_sum('expense_share')
    staff = pt_sum('staff_expense')
    sal = pt_sum('salary_expense')
    ship = pt_sum('shipping_extra_commission')

    mgr_comm = db.session.query(fn.sum(PartnerTransaction.amount)).filter(
        PartnerTransaction.type == 'commission_gross'
    ).scalar() or 0.0

    hr_bonus = db.session.query(fn.sum(HRTransaction.amount)).filter(
        HRTransaction.type == 'bonus'
    ).join(User, HRTransaction.user_id == User.id).filter(
        User.role != 'manager', User.manager_id.in_([1, 3])
    ).scalar() or 0.0

    # UNIFIED: Both pages now use the same deductions
    unified_exp = girls + disc + ret + exp + staff + sal + hr_bonus + mgr_comm + ship
    unified_net = gross - unified_exp

    result = f"""<pre dir='ltr' style='font-size:16px;font-family:monospace;padding:20px;'>
=== Profit Comparison (Lifetime) - AFTER FIX ===

Gross Markup:          {gross:>15,.2f}

--- Expense Breakdown (UNIFIED) ---
Sub Commission:        {girls:>15,.2f}
Discount Deduction:    {disc:>15,.2f}
Return Penalty:        {ret:>15,.2f}
Expense Share:         {exp:>15,.2f}
Staff Expense:         {staff:>15,.2f}
Salary Expense:        {sal:>15,.2f}  ✅ NOW in BOTH pages
Shipping Extra:        {ship:>15,.2f}
HR Bonuses:            {hr_bonus:>15,.2f}  ✅ NOW in BOTH pages
Manager Commissions:   {mgr_comm:>15,.2f}

--- Unified Result ---
Total Expenses:        {unified_exp:>15,.2f}
Net Profit:            {unified_net:>15,.2f}
Per Partner (50%):     {unified_net/2:>15,.2f}

✅ Both pages should now show the SAME numbers!
</pre>"""
    return result


@app.route('/partners/owners_report')
@general_manager_required
def owners_report():
    today = date.today()
    start_date_str = request.args.get('start_date', today.replace(day=1).strftime('%Y-%m-%d'))
    end_date_str = request.args.get('end_date', today.strftime('%Y-%m-%d'))

    # 1. عدد القطع المباعة في الشركة بالكامل في الفترة
    total_items = db.session.query(func.sum(SaleItem.quantity))\
        .join(SaleOrder)\
        .filter(SaleOrder.is_proforma == False,
                cast(SaleOrder.date, Date) >= start_date_str,
                cast(SaleOrder.date, Date) <= end_date_str).scalar() or 0

    # 2. إجمالي ربح الشركة من المكسب في القطعة (سعر البيع - سعر الشراء)
    total_markup_profit = db.session.query(
        func.sum(SaleItem.quantity * (SaleItem.unit_price - ProductVariant.cost_price))
    ).join(SaleOrder)\
     .join(ProductVariant, SaleItem.variant_id == ProductVariant.id)\
     .filter(SaleOrder.is_proforma == False,
             cast(SaleOrder.date, Date) >= start_date_str,
             cast(SaleOrder.date, Date) <= end_date_str).scalar() or 0.0

    # 3. المصروفات والخصومات المشتركة من حركات الشركاء (ID 1=أبو إياد و 3=أبو مالك) في الفترة
    deduction_types = ['sub_commission', 'discount_deduction', 'return_penalty', 'expense_share', 'staff_expense', 'salary_expense', 'shipping_extra_commission']
    period_deductions = PartnerTransaction.query.filter(
        PartnerTransaction.partner_id.in_([1, 3]),
        PartnerTransaction.type.in_(deduction_types),
        cast(PartnerTransaction.date, Date) >= start_date_str,
        cast(PartnerTransaction.date, Date) <= end_date_str
    ).all()

    # 4. عمولات المدراء العاديين (commission_gross) في نفس الفترة (قيمة موجبة في الداتا بيز، فنقوم بطرحها كخصم)
    manager_commissions_positive = db.session.query(func.sum(PartnerTransaction.amount)).filter(
        PartnerTransaction.type == 'commission_gross',
        cast(PartnerTransaction.date, Date) >= start_date_str,
        cast(PartnerTransaction.date, Date) <= end_date_str
    ).scalar() or 0.0
    
    manager_commissions_total = -abs(manager_commissions_positive) # تحويلها لسالب لتتماشى مع باقي الخصومات

    # 5. مكافآت الموظفين من الموارد البشرية (غير المديرين) في نفس الفترة
    hr_bonuses_total = db.session.query(func.sum(HRTransaction.amount)).filter(
        HRTransaction.type == 'bonus',
        cast(HRTransaction.date, Date) >= start_date_str,
        cast(HRTransaction.date, Date) <= end_date_str
    ).join(User, HRTransaction.user_id == User.id).filter(
        User.role != 'manager',
        User.manager_id.in_([1, 3])
    ).scalar() or 0.0
    hr_bonuses_negative = -abs(hr_bonuses_total) # تحويلها لسالب

    # تفاصيل المصروفات لعرضها
    sales_rep_comm_total = sum(t.amount for t in period_deductions if t.type == 'sub_commission')
    discounts_total = sum(t.amount for t in period_deductions if t.type == 'discount_deduction')
    returns_total = sum(t.amount for t in period_deductions if t.type == 'return_penalty')
    expenses_total = sum(t.amount for t in period_deductions if t.type == 'expense_share')
    staff_costs_total = sum(t.amount for t in period_deductions if t.type == 'staff_expense')
    staff_bonuses_total = sum(t.amount for t in period_deductions if t.type == 'staff_expense' and 'مكافأة' in (t.description or ''))
    staff_other_total = staff_costs_total - staff_bonuses_total
    salary_expenses_total = sum(t.amount for t in period_deductions if t.type == 'salary_expense')
    shipping_extra_total = sum(t.amount for t in period_deductions if t.type == 'shipping_extra_commission')

    # إضافة عمولات المدراء ومكافآت HR إلى إجمالي الخصومات
    total_deductions = sales_rep_comm_total + discounts_total + returns_total + expenses_total + staff_costs_total + salary_expenses_total + shipping_extra_total + manager_commissions_total + hr_bonuses_negative

    # صافي ربح الشراكة = إجمالي المكسب + إجمالي الخصومات (الخصومات سالبة)
    partnership_net_profit = total_markup_profit + total_deductions

    # تفاصيل الحركات لكل نوع (للعرض في drilldown)
    def build_deduction_details(trans_list, trans_type, condition=None):
        return [
            {
                'amount': t.amount,
                'desc': t.description or '---',
                'date': t.date.strftime('%Y-%m-%d'),
                'order_id': t.order_id,
                'invoice_label': f"فاتورة #{t.order_id}" if t.order_id else "---"
            }
            for t in trans_list if t.type == trans_type and (condition(t) if condition else True)
        ]
    
    # نسخة خاصة تجمع الحركات المتكررة (50/50 شراكة) بحيث تظهر مرة واحدة بالمبلغ الإجمالي
    def build_grouped_deduction_details(trans_list, trans_type, condition=None):
        grouped = {}
        for t in trans_list:
            if t.type != trans_type:
                continue
            if condition and not condition(t):
                continue
            # مفتاح التجميع: الوصف بدون جزء [شراكة 50%] + التاريخ
            desc = (t.description or '---').replace(' [شراكة 50%]', '').replace(' [شراكة 12.5%]', '')
            date_str = t.date.strftime('%Y-%m-%d')
            key = f"{desc}|{date_str}"
            if key in grouped:
                grouped[key]['amount'] += t.amount
            else:
                grouped[key] = {
                    'amount': t.amount,
                    'desc': desc,
                    'date': date_str,
                    'order_id': t.order_id,
                    'invoice_label': f"فاتورة #{t.order_id}" if t.order_id else "---"
                }
        return list(grouped.values())

    deduction_details = {
        'sales_comm': build_deduction_details(period_deductions, 'sub_commission'),
        'discounts': build_deduction_details(period_deductions, 'discount_deduction'),
        'returns': build_deduction_details(period_deductions, 'return_penalty'),
        'expenses': build_deduction_details(period_deductions, 'expense_share'),
        'staff_other': build_deduction_details(period_deductions, 'staff_expense', lambda t: 'مكافأة' not in (t.description or '')),
        'staff_bonuses': build_deduction_details(period_deductions, 'staff_expense', lambda t: 'مكافأة' in (t.description or '')),
        'salary': build_deduction_details(period_deductions, 'salary_expense'),
    }

    # === حساب أرباح الشراكة التراكمية (Lifetime) ===
    lifetime_global_gross = db.session.query(
        func.sum(SaleItem.quantity * (SaleItem.unit_price - ProductVariant.cost_price))
    ).join(SaleOrder)\
     .join(ProductVariant, SaleItem.variant_id == ProductVariant.id)\
     .filter(SaleOrder.is_proforma == False).scalar() or 0.0

    def get_lifetime_transaction_sum(type_name):
        val = db.session.query(func.sum(PartnerTransaction.amount)).filter(
            PartnerTransaction.type == type_name,
            PartnerTransaction.partner_id.in_([1, 3])
        ).scalar()
        return abs(val) if val else 0.0

    lifetime_global_girls_comm = get_lifetime_transaction_sum('sub_commission')
    lifetime_global_discounts = get_lifetime_transaction_sum('discount_deduction')
    lifetime_global_returns = get_lifetime_transaction_sum('return_penalty')
    lifetime_global_expenses = get_lifetime_transaction_sum('expense_share')
    lifetime_global_staff_costs = get_lifetime_transaction_sum('staff_expense')
    lifetime_global_salary_expenses = get_lifetime_transaction_sum('salary_expense')
    lifetime_global_shipping_extra = get_lifetime_transaction_sum('shipping_extra_commission')

    # مكافآت HR (غير المديرين، تابعين للشركاء فقط)
    lifetime_global_bonuses = db.session.query(func.sum(HRTransaction.amount)).filter(
        HRTransaction.type == 'bonus'
    ).join(User, HRTransaction.user_id == User.id).filter(
        User.role != 'manager',
        User.manager_id.in_([1, 3])
    ).scalar() or 0.0

    lifetime_global_manager_commissions = db.session.query(func.sum(PartnerTransaction.amount)).filter(
        PartnerTransaction.type == 'commission_gross'
    ).scalar() or 0.0

    lifetime_global_net_profit = lifetime_global_gross - (
        lifetime_global_girls_comm + lifetime_global_discounts +
        lifetime_global_returns + lifetime_global_expenses +
        lifetime_global_staff_costs + lifetime_global_salary_expenses +
        lifetime_global_bonuses + lifetime_global_manager_commissions +
        lifetime_global_shipping_extra
    )
    lifetime_partner_share = round_half(lifetime_global_net_profit / 2.0)

    # مسحوبات كل مالك
    owners = User.query.filter(User.username.in_(['Abo_Eyad', 'Abo_malek'])).all()
    owners_data = []
    for o in owners:
        def get_partner_lifetime_val(type_name):
            val = db.session.query(func.sum(PartnerTransaction.amount))\
                .filter(PartnerTransaction.partner_id == o.id, PartnerTransaction.type == type_name).scalar()
            return abs(val) if val else 0.0

        o_withdrawn = get_partner_lifetime_val('withdrawal') + get_partner_lifetime_val('personal_expense_share') + get_partner_lifetime_val('personal_salary_expense')
        opening_balance = db.session.query(func.sum(PartnerTransaction.amount)).filter_by(partner_id=o.id, type='opening_balance').scalar() or 0.0
        
        o_balance = lifetime_partner_share + opening_balance - o_withdrawn
        o_earned = lifetime_partner_share

        period_withdrawals = PartnerTransaction.query.filter(
            PartnerTransaction.partner_id == o.id,
            PartnerTransaction.type.in_(['withdrawal', 'personal_expense_share', 'personal_salary_expense', 'partner_bonus', 'partner_deduction']),
            cast(PartnerTransaction.date, Date) >= start_date_str,
            cast(PartnerTransaction.date, Date) <= end_date_str
        ).all()
        withdrawals_period = sum(t.amount for t in period_withdrawals)

        withdrawal_details = [
            {
                'amount': t.amount,
                'desc': t.description or '---',
                'date': t.date.strftime('%Y-%m-%d'),
                'order_id': t.order_id,
                'invoice_label': f"فاتورة #{t.order_id}" if t.order_id else "---"
            }
            for t in period_withdrawals
        ]

        owners_data.append({
            'id': o.id,
            'name': o.fullname,
            'total_earned': round_half(o_earned),
            'total_withdrawn': round_half(abs(o_withdrawn)),
            'current_balance': round_half(o_balance),
            'opening_balance': round_half(opening_balance),
            'withdrawals_period': round_half(abs(withdrawals_period)),
            'withdrawals_details': withdrawal_details
        })

    accounts = MoneyAccount.query.all()
    return render_template('owners_report.html',
                           owners=owners_data,
                           total_items=total_items,
                           total_markup_profit=round_half(total_markup_profit),
                           sales_rep_comm=round_half(abs(sales_rep_comm_total)),
                           discounts=round_half(abs(discounts_total)),
                           returns=round_half(abs(returns_total)),
                           expenses=round_half(abs(expenses_total)),
                           staff_other=round_half(abs(staff_other_total)),
                           staff_bonuses=round_half(abs(staff_bonuses_total)),
                           salary_expenses=round_half(abs(salary_expenses_total)),
                           shipping_extra=round_half(abs(shipping_extra_total)),
                           manager_commissions=round_half(abs(manager_commissions_total)),
                           hr_bonuses=round_half(abs(hr_bonuses_negative)),
                           total_deductions=round_half(abs(total_deductions)),
                           partnership_net_profit=round_half(partnership_net_profit),
                           per_owner_profit=round_half(partnership_net_profit / 2),
                           per_owner_deductions=round_half(abs(total_deductions) / 2),
                           deduction_details=deduction_details,
                           start_date=start_date_str,
                           end_date=end_date_str,
                           accounts=accounts)


@app.route('/partners/set_opening_balance', methods=['POST'])
@general_manager_required
def set_partner_opening_balance():
    partner_id = request.form.get('partner_id')
    amount = float(request.form.get('amount', 0))

    if not partner_id:
        flash("بيانات الشريك مفقودة", "danger")
        return redirect(url_for('partners_report'))

    partner = User.query.get(partner_id)
    if not partner:
        flash("الشريك غير موجود", "danger")
        return redirect(url_for('partners_report'))

    # Delete existing opening balance transactions
    existing = PartnerTransaction.query.filter_by(partner_id=partner.id, type='opening_balance').all()
    for tr in existing:
        db.session.delete(tr)

    # Insert new opening balance if amount != 0
    if amount != 0:
        ob_trans = PartnerTransaction(
            partner_id=partner.id,
            type='opening_balance',
            amount=amount,
            description="الرصيد الافتتاحي للمدة",
            date=date.today()
        )
        db.session.add(ob_trans)
    
    try:
        db.session.commit()
        flash("تم تعيين الرصيد الافتتاحي بنجاح", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"حدث خطأ أثناء الحفظ: {str(e)}", "danger")

    next_url = request.form.get('next') or url_for('partners_report')
    return redirect(next_url)

# دالة صرف تصفية الأرباح (يجب إضافتها لكي يعمل زر الصرف)
@app.route('/partners/settle', methods=['POST'])
@general_manager_required
def partner_settlement():
    try:
        partner_id = request.form.get('partner_id')
        amount = float(request.form.get('amount') or 0)
        account_id = request.form.get('account_id')
        notes = request.form.get('notes', 'تصفية أرباح')

        if amount <= 0 or not account_id:
            flash('بيانات التصفية غير مكتملة أو المبلغ خطأ', 'danger')
            return redirect(url_for('partners_report'))

        account = MoneyAccount.query.get(account_id)
        if not account:
            flash('الخزينة غير موجودة', 'danger')
            return redirect(url_for('partners_report'))

        # 1. خصم من الخزينة
        account.balance = round_half(account.balance - amount)

        # 2. تسجيل حركة مالية عامة في الخزينة
        db.session.add(FinancialTransaction(
            account_id=account.id,
            type='expense',
            category='تصفية شركاء',
            amount=-amount,
            description=f"صرف تصفية أرباح للشريك (ID:{partner_id})",
            created_by_id=current_user.id,
            date=cairo_now()
        ))

        # 3. تسجيل حركة "سحب" في حساب الشريك لخصمها من رصيده
        db.session.add(PartnerTransaction(
            partner_id=partner_id,
            type='withdrawal',
            amount=-amount,
            description=f"استلام تصفية: {notes}",
            date=cairo_now()
        ))

        db.session.commit()
        flash(f'تم تسجيل الصرف بنجاح وخصم {amount} ج.م من {account.name} ✅', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'حدث خطأ: {str(e)}', 'danger')

    return redirect(url_for('partners_report'))
def setup():
    with app.app_context():
        # 1. إنشاء كافة الجداول الجديدة التي لم تُنشأ بعد
        db.create_all()

        inspector = inspect(db.engine)
        existing_tables = inspector.get_table_names()

        # التأكد من إنشاء جدول الأذونات يدوياً إذا لم ينشئه db.create_all (للدقة)
        if 'employee_excuse' not in existing_tables:
            EmployeeExcuse.__table__.create(db.engine)

        with db.engine.connect() as conn:
            # --- تحديث جدول المستخدمين (User) بالأعمدة الناقصة ---
            cols_user = [c['name'] for c in inspector.get_columns('user')]
            if 'manager_id' not in cols_user:
                conn.execute(text("ALTER TABLE user ADD COLUMN manager_id INTEGER REFERENCES user(id)"))
            if 'shift_start' not in cols_user:
                conn.execute(text("ALTER TABLE user ADD COLUMN shift_start VARCHAR(10) DEFAULT '09:00'"))
            if 'shift_end' not in cols_user:
                conn.execute(text("ALTER TABLE user ADD COLUMN shift_end VARCHAR(10) DEFAULT '17:00'"))
            if 'permissions' not in cols_user:
                conn.execute(text("ALTER TABLE user ADD COLUMN permissions TEXT DEFAULT ''"))
            if 'commission_value' not in cols_user:
                conn.execute(text("ALTER TABLE user ADD COLUMN commission_value FLOAT DEFAULT 0.0"))
            if 'commission_rules' not in cols_user:
                conn.execute(text("ALTER TABLE user ADD COLUMN commission_rules TEXT"))
            if 'working_hours' not in cols_user:
                conn.execute(text("ALTER TABLE user ADD COLUMN working_hours FLOAT DEFAULT 8.0"))
            if 'work_from_home' not in cols_user:
                conn.execute(text("ALTER TABLE user ADD COLUMN work_from_home BOOLEAN DEFAULT 0"))

            # --- تحديث جدول المبيعات (SaleOrder) ---
            cols_order = [c['name'] for c in inspector.get_columns('sale_order')]
            if 'is_proforma' not in cols_order:
                conn.execute(text("ALTER TABLE sale_order ADD COLUMN is_proforma BOOLEAN DEFAULT 0"))
            if 'shipping_notes' not in cols_order:
                conn.execute(text("ALTER TABLE sale_order ADD COLUMN shipping_notes TEXT"))
            if 'packer_id' not in cols_order:
                conn.execute(text("ALTER TABLE sale_order ADD COLUMN packer_id INTEGER"))

            # --- تحديث جدول المصروفات (Expense) ---
            cols_expense = [c['name'] for c in inspector.get_columns('expense')]
            if 'is_shared' not in cols_expense:
                conn.execute(text("ALTER TABLE expense ADD COLUMN is_shared BOOLEAN DEFAULT 0"))
            if 'account_id' not in cols_expense:
                conn.execute(text("ALTER TABLE expense ADD COLUMN account_id INTEGER REFERENCES money_account(id)"))

            conn.commit()

        # 2. إنشاء المدير العام (أحمد عبد الفتاح)
        gm = User.query.filter_by(username="gm_ahmed").first()
        if not gm:
            gm = User(
                fullname="أحمد عبد الفتاح",
                username="gm_ahmed",
                password=generate_password_hash("123456"),
                role="general_manager",
                emp_code="GM-001",
                phone="01067564179",
                permissions="view_reports,manage_hr,manage_inventory,manage_shipping,manage_settings,view_pos,view_invoices,manage_orders,view_treasury,manage_treasury,view_customers,manage_customers"
            )
            db.session.add(gm)
            db.session.commit()

        # 3. إنشاء المديرين الشركاء (Partners)
        managers_data = [
            {'name': 'أحمد هشام', 'user': 'mgr_hesham', 'phone': '01010893806'},
            {'name': 'أحمد وجدي', 'user': 'mgr_wagdy', 'phone': '01026520216'},
            {'name': 'أحمد أبو اليزيد', 'user': 'mgr_yazeed', 'phone': '01012253847'},
            {'name': 'أحمد العجان', 'user': 'mgr_aggan', 'phone': '01018440860'},
        ]
        managers_objs = {}
        for m in managers_data:
            user = User.query.filter_by(username=m['user']).first()
            if not user:
                user = User(
                    fullname=m['name'], username=m['user'],
                    password=generate_password_hash("123456"),
                    role="manager", emp_code=f"MGR-{random.randint(100,999)}",
                    phone=m['phone'], manager_id=gm.id,
                    permissions="view_reports,manage_shipping,view_inventory,view_pos,view_invoices,view_customers"
                )
                db.session.add(user)
                db.session.commit()
            managers_objs[m['user']] = user

        # 4. إنشاء فريق المبيعات (Sales) وتوزيعهم على المديرين
        sales_structure = {
            'mgr_hesham': [{'name': 'منار', 'user': 'sales_manar', 'phone': '01055745413'}, {'name': 'هاجر', 'user': 'sales_hager', 'phone': '01044585698'}],
            'mgr_wagdy': [{'name': 'سلمى', 'user': 'sales_salma', 'phone': '01080841802'}],
            'mgr_yazeed': [{'name': 'سماح', 'user': 'sales_samah', 'phone': '01044582182'}, {'name': 'ندى', 'user': 'sales_nada', 'phone': '01034874947'}],
            'gm_ahmed': [{'name': 'ياسمين مجدي', 'user': 'sales_yasmin', 'phone': '01040577838'}, {'name': 'أم مليكة', 'user': 'sales_omalika', 'phone': '01044585676'}, {'name': 'ريم وائل', 'user': 'sales_reem', 'phone': '01040557328'}]
        }
        for mgr_user, sales_list in sales_structure.items():
            m_id = gm.id if mgr_user == 'gm_ahmed' else (managers_objs[mgr_user].id if mgr_user in managers_objs else None)
            if not m_id: continue
            for s in sales_list:
                if not User.query.filter_by(username=s['user']).first():
                    db.session.add(User(
                        fullname=s['name'], username=s['user'], password=generate_password_hash("123456"),
                        role="sales", emp_code=f"SAL-{random.randint(100,999)}",
                        phone=s['phone'], manager_id=m_id, permissions="view_pos,view_invoices,view_customers"
                    ))

        # 5. إنشاء العمال (Workers) المشتركين
        workers_data = [
            {'name': 'يوسف', 'user': 'w_youssef', 'phone': '01050783864'},
            {'name': 'أدهم', 'user': 'w_adham', 'phone': '01080923261'},
            {'name': 'حياة', 'user': 'Hayah', 'phone': '01152512370'},
            {'name': 'مصطفى', 'user': 'w_mostafa', 'phone': '01061039810'}
        ]
        for w in workers_data:
            if not User.query.filter_by(username=w['user']).first():
                db.session.add(User(
                    fullname=w['name'], username=w['user'], password=generate_password_hash("123456"),
                    role="worker", emp_code=f"WRK-{random.randint(100,999)}",
                    phone=w['phone'], manager_id=gm.id
                ))

        # 6. تهيئة البيانات الأساسية (تصنيفات، حسابات، شحن)
        if not Category.query.first(): db.session.add(Category(name="عام"))
        if not ExpenseCategory.query.first():
            for c in ["إيجار", "رواتب", "كهرباء", "نثريات", "نقل", "تسويق"]: db.session.add(ExpenseCategory(name=c))
        if not Customer.query.filter_by(name="عميل نقدي").first():
            db.session.add(Customer(name="عميل نقدي", phone="00000000000", address="-"))
        if not ShippingCompany.query.first():
            db.session.add(ShippingCompany(name="شركة البراق", phone="010xxxx", cs_number="19xxx", fee_first_1k=50, fee_extra_1k=10))

        # إنشاء الخزائن الافتراضية
        default_accounts = ["خزنة نقدية (درج الكاش)", "فودافون كاش", "إنستا باي", "حساب بنكي", "حساب بريد"]
        for acc_name in default_accounts:
            if not MoneyAccount.query.filter_by(name=acc_name).first():
                acc_type = 'vodafone' if 'فودافون' in acc_name else ('instapay' if 'إنستا' in acc_name else ('bank' if 'بنكي' in acc_name or 'بريد' in acc_name else 'cash'))
                db.session.add(MoneyAccount(name=acc_name, balance=0.0, type=acc_type))

        db.session.commit()
        return "تم"
@app.context_processor
def inject_settings():
    # هذا الكود يجعل متغيرات الإعدادات متاحة في كل ملفات HTML تلقائياً
    setting = SystemSetting.query.first()
    if setting:
        return dict(
            global_theme_color=setting.theme_color,
            global_company_logo=setting.company_logo
        )
    return dict(global_theme_color='#0d6efd', global_company_logo=None)
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        # البحث عن المستخدم
        user = User.query.filter_by(username=request.form['username']).first()

        # التحقق من الباسورد (تم التصحيح هنا)
        if user and check_password_hash(user.password, request.form['password']):
            login_user(user, remember=True)
            return redirect(url_for('dashboard'))

        flash('خطأ في اسم المستخدم أو كلمة المرور')
    return render_template('login.html')
@app.route('/pos')
@login_required
def pos():
    # 1. التحقق: هل يوجد رقم فاتورة للتعديل في الرابط؟ (?edit=81)
    edit_id = request.args.get('edit')
    edit_order_data = None

    if edit_id:
        try:
            order = SaleOrder.query.get(int(edit_id))
            # نتأكد إنها موجودة وإنها "عرض سعر" (مسودة)
            if order and order.is_proforma:
                edit_order_data = {
                    'id': order.id,
                    'customer_id': order.customer_id,
                    'discount': order.discount or 0,
                    'paid_upfront': order.paid_upfront or 0,
                    'items': []
                }
                for item in order.items:
                    if item.variant:
                        edit_order_data['items'].append({
                            'id': item.variant.id,
                            'name': item.variant.model.name,
                            'price': item.unit_price,
                            'qty': item.quantity,
                            'stock': item.variant.stock
                        })
        except Exception as e:
            print(f"Error fetching draft: {e}")

    # 2. البيانات العادية لصفحة البيع
    if current_user.username == 'Abo_malek' or current_user.role == 'general_manager' or current_user.emp_code == 'EMP201':
        customers = Customer.query.order_by(Customer.id.desc()).all()
    else:
        accessible_ids = get_accessible_users()
        customers = Customer.query.filter(
            or_(
                Customer.created_by_id.in_(accessible_ids),
                Customer.name == "عميل نقدي"
            )
        ).order_by(Customer.id.desc()).all()

    # 3. عرض الصفحة مع تمرير بيانات التعديل (لو وجدت)
    return render_template('pos.html',
                           categories=Category.query.all(),
                           products=ProductVariant.query.all(),
                           customers=customers,
                           shipping_companies=ShippingCompany.query.all(),
                           money_accounts=MoneyAccount.query.all(),
                           all_employees=User.query.all(),  # <--- إضافة الموظفين هنا
                           edit_order_data=edit_order_data) # <--- ده المهم عشان الجافاسكريبت يشتغل
@app.route('/treasury')
@general_manager_required
def treasury_dashboard():
    accounts = MoneyAccount.query.all()

    # تجميع الحسابات حسب النوع
    grouped = {
        'cash': [], 'vodafone': [], 'bank': [], 'instapay': []
    }
    totals = {
        'cash': 0, 'vodafone': 0, 'bank': 0, 'instapay': 0, 'all': 0
    }

    for acc in accounts:
        # لو النوع مش معروف نعتبره cash
        acc_type = acc.type if acc.type in grouped else 'cash'
        grouped[acc_type].append(acc)
        totals[acc_type] += acc.balance
        totals['all'] += acc.balance

    return render_template('treasury.html', grouped=grouped, totals=totals)

# 3. راوت تفاصيل حساب واحد (كشف حساب)
@app.route('/treasury/<int:id>')
@general_manager_required
def account_details(id):
    account = MoneyAccount.query.get_or_404(id)

    # التعديل: نجلب الحركات الخاصة بهذا الحساب فقط بناء على المعرف ID (تم حذف البحث بالاسم لتجنب ازدواجية التحويلات والمعلومات الخاطئة)
    transactions = FinancialTransaction.query.filter(
        FinancialTransaction.account_id == id
    ).order_by(FinancialTransaction.date.desc()).all()

    return render_template('account_details.html', account=account, transactions=transactions)
# --- في ملف app.py ---

# دالة حفظ تعديل بيانات الحساب
@app.route('/treasury/edit/<int:id>', methods=['POST'])
@general_manager_required
def edit_account(id):
    account = MoneyAccount.query.get_or_404(id)
    account.name = request.form['name']
    account.account_number = request.form['account_number']
    # النوع لا يفضل تعديله عشان ميبوظش التقارير، بس ممكن لو عايز

    db.session.commit()
    flash('تم تعديل بيانات الحساب بنجاح ✅', 'success')
    return redirect(url_for('account_details', id=id))

# دالة حذف الحساب (بحذر)
@app.route('/treasury/delete/<int:id>')
@general_manager_required
def delete_account(id):
    account = MoneyAccount.query.get_or_404(id)
    # لا تحذف الحساب إذا كان عليه حركات مالية (أمان)
    # ممكن نضيف شرط هنا، بس مبدئياً هنسمح بالحذف
    try:
        db.session.delete(account)
        db.session.commit()
        flash('تم حذف الحساب بنجاح 🗑️', 'warning')
        return redirect(url_for('treasury_dashboard'))
    except:
        db.session.rollback()
        flash('لا يمكن حذف هذا الحساب لوجود عمليات مرتبطة به', 'danger')
        return redirect(url_for('account_details', id=id))
# 4. إضافة حساب جديد (عشان تضيف الـ 20 رقم بسهولة)
@app.route('/treasury/add', methods=['POST'])
@general_manager_required
def add_account():
    name = request.form['name']
    acc_type = request.form['type']
    number = request.form.get('account_number', '')

    db.session.add(MoneyAccount(name=name, type=acc_type, account_number=number, balance=0.0))
    db.session.commit()
    flash('تم إضافة الحساب بنجاح', 'success')
    return redirect(url_for('treasury_dashboard'))
# === تحويل داخلي بين الخزائن ===
@app.route('/treasury/transfer', methods=['POST'])
@general_manager_required
def transfer_balance():
    try:
        from_id = request.form.get('from_account')
        to_id = request.form.get('to_account')
        amount = float(request.form.get('amount'))
        notes = request.form.get('notes', '')

        if from_id == to_id:
            flash('لا يمكن التحويل لنفس الحساب', 'warning')
            return redirect(url_for('treasury_dashboard'))

        from_acc = MoneyAccount.query.get(from_id)
        to_acc = MoneyAccount.query.get(to_id)

        if not from_acc or not to_acc:
            flash('حسابات غير صحيحة', 'danger')
            return redirect(url_for('treasury_dashboard'))

        # (اختياري) منع التحويل لو الرصيد غير كافي
        # if from_acc.balance < amount:
        #     flash('رصيد الحساب المحول منه غير كافي', 'danger')
        #     return redirect(url_for('treasury_dashboard'))

        # تنفيذ التحويل
        from_acc.balance = round_half(from_acc.balance - amount)
        to_acc.balance = round_half(to_acc.balance + amount)

        # تسجيل الحركات
        # 1. حركة خروج من المصدر
        db.session.add(FinancialTransaction(
            account_id=from_acc.id,
            type='transfer_out',
            category='تحويل داخلي',
            amount=-amount,
            description=f"تحويل صادر إلى {to_acc.name} ({notes})",
            created_by_id=current_user.id,
            date=cairo_now()
        ))

        # 2. حركة دخول للمستلم
        db.session.add(FinancialTransaction(
            account_id=to_acc.id,
            type='transfer_in',
            category='تحويل داخلي',
            amount=amount,
            description=f"تحويل وارد من {from_acc.name} ({notes})",
            created_by_id=current_user.id,
            date=cairo_now()
        ))

        db.session.commit()
        flash(f'تم تحويل {amount} ج.م من {from_acc.name} إلى {to_acc.name} بنجاح ✅', 'success')

    except Exception as e:
        db.session.rollback()
        flash(f'حدث خطأ: {str(e)}', 'danger')

    return redirect(url_for('treasury_dashboard'))
@app.route('/logout')
@login_required
def logout(): logout_user(); return redirect(url_for('login'))

@app.route('/')
@app.route('/dashboard')
@login_required
def dashboard():
    today = cairo_now().date()
    month_str = today.strftime('%Y-%m')

    # تحديد الصلاحيات
    accessible_ids = get_accessible_users()

    # === 1. حساب مبيعات اليوم الصافية ===
    # أ) إجمالي الفواتير (Gross)
    today_gross = db.session.query(func.sum(SaleOrder.final_total))\
        .filter(cast(SaleOrder.date, Date) == today,
                SaleOrder.user_id.in_(accessible_ids),
                SaleOrder.is_proforma == False).scalar() or 0.0

    # ب) المرتجعات النقدية (Refunds) - قيمتها سالبة في الداتا بيز
    today_refunds = db.session.query(func.sum(FinancialTransaction.amount))\
        .filter(cast(FinancialTransaction.date, Date) == today,
                FinancialTransaction.type == 'refund',
                FinancialTransaction.created_by_id.in_(accessible_ids)).scalar() or 0.0

    # ج) الصافي = الفواتير + المرتجعات (بما أن المرتجعات سالبة، الجمع هنا يعني طرح)
    today_net_sales = today_gross + today_refunds

    # === 2. حساب مبيعات الشهر الصافية ===
    month_gross = db.session.query(func.sum(SaleOrder.final_total))\
        .filter(func.to_char(SaleOrder.date, 'YYYY-MM') == month_str,
                SaleOrder.user_id.in_(accessible_ids),
                SaleOrder.is_proforma == False).scalar() or 0.0

    month_refunds = db.session.query(func.sum(FinancialTransaction.amount))\
        .filter(func.to_char(FinancialTransaction.date, 'YYYY-MM') == month_str,
                FinancialTransaction.type == 'refund',
                FinancialTransaction.created_by_id.in_(accessible_ids)).scalar() or 0.0

    total_net_sales = month_gross + month_refunds

    # === 3. إحصائيات خاصة (الربح والعمولة) ===
    stats = {
        'net_profit': 0.0,
        'total_deductions': 0.0,
        'net_commission': 0.0,
        'net_items': 0
    }

    # تحديد تواريخ دقيقة لحساب المخزون
    now = cairo_now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if month_start.month == 12:
        month_end = month_start.replace(year=month_start.year + 1, month=1)
    else:
        month_end = month_start.replace(month=month_start.month + 1)

    # أ) لو المستخدم مدير
    if current_user.role in ['manager', 'general_manager']:
        # نستخدم جدول PartnerTransaction لحساب صافي الربح الدقيق
        trans = PartnerTransaction.query.filter(
            PartnerTransaction.partner_id == current_user.id,
            func.to_char(PartnerTransaction.date, 'YYYY-MM') == month_str
        ).all()

        # صافي الربح = مجموع كل الحركات (الدخل بالموجب والخصم بالسالب)
        stats['net_profit'] = sum(t.amount for t in trans)
        # إجمالي الخصومات للعرض
        stats['total_deductions'] = sum(abs(t.amount) for t in trans if t.amount < 0)

    # ب) لو المستخدم موظف
    # ... inside dashboard() function ...

    # b) If User is Employee (Sales / Worker)
    else:
        # 1. Gross Items Sold
        gross_items = db.session.query(func.sum(SaleItem.quantity))\
            .join(SaleOrder)\
            .filter(SaleOrder.user_id == current_user.id,
                    SaleOrder.is_proforma == False,
                    SaleOrder.date >= month_start,
                    SaleOrder.date < month_end).scalar() or 0

        # 2. Get Returned Items count from HR Transactions (The Accurate Way)
        # This matches the logic we added to the Profile page
        hr_trans = HRTransaction.query.filter(
            HRTransaction.user_id == current_user.id,
            HRTransaction.date >= month_start,
            HRTransaction.date < month_end
        ).all()

        returned_items_count = 0
        for t in hr_trans:
            # Look for the pattern "(5 pieces)" in the note
            if t.note and ('مرتجع' in t.note or 'قطعة' in t.note):
                match = re.search(r'\((\d+)\s*قطعة\)', t.note)
                if match:
                    returned_items_count += int(match.group(1))

        # 3. Net Items and Commission
        net_items_count = int(gross_items - returned_items_count)
        if net_items_count < 0: net_items_count = 0

        stats['net_items'] = net_items_count
        stats['net_commission'] = calculate_user_commission(current_user, net_items_count, net_items_count)

    # 4. باقي البيانات
    team_members = []
    if current_user.role == 'general_manager':
        team_members = User.query.filter(User.id != current_user.id).all()
    elif current_user.role == 'manager':
        team_members = User.query.filter_by(manager_id=current_user.id).all()

    latest_orders = SaleOrder.query.filter(SaleOrder.user_id.in_(accessible_ids))\
        .order_by(SaleOrder.date.desc()).limit(5).all()

    attendance = Attendance.query.filter_by(user_id=current_user.id, date=today).first()

    return render_template('dashboard.html',
                         today_sales=round_half(today_net_sales),
                         total_sales=round_half(total_net_sales),
                         stats=stats,
                         team_members=team_members,
                         latest_orders=latest_orders,
                         attendance=attendance,
                         categories=Category.query.all(),
                         money_accounts=MoneyAccount.query.all(),
                         user=current_user)

@app.route('/fix-elwakil')
@login_required
def fix_elwakil():
    if current_user.role != 'general_manager': return "Unauthorized"
    u = User.query.filter_by(fullname='السيد الوكيل').first()
    if not u: u = User.query.filter(User.username.like('%elwakil%')).first()
    if not u: return "User not found"
    
    hr = HRTransaction.query.filter_by(user_id=u.id, type='deduction', amount=39957.0).first()
    if hr:
        db.session.delete(hr)
        db.session.commit()
        return "تم مسح خصم الـ HR (39,957) للسيد الوكيل بنجاح! ارجع للصفحة الشخصية هتلاقيه اتشال."
    return "الخصم ده اتمسح قبل كدة ومش موجود في قاعدة البيانات حاليا."

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        # Check if this is a phone number update from the GM
        if 'phone' in request.form:
            if current_user.role == 'general_manager':
                user_record = User.query.get(current_user.id)
                user_record.phone = request.form.get('phone')
                db.session.commit()
                flash('تم تحديث رقم الهاتف بنجاح ✅', 'success')
            return redirect(url_for('profile'))

        # تغيير كلمة المرور
        old_pass = request.form.get('old_password')
        new_pass = request.form.get('new_password')
        confirm_pass = request.form.get('confirm_password')
        if not check_password_hash(current_user.password, old_pass):
            flash('كلمة المرور الحالية غير صحيحة ❌', 'danger')
        elif new_pass != confirm_pass:
            flash('كلمة المرور الجديدة غير متطابقة ⚠️', 'warning')
        else:
            current_user.password = generate_password_hash(new_pass)
            db.session.commit()
            flash('تم تغيير كلمة المرور بنجاح ✅', 'success')
        return redirect(url_for('profile'))

    # السماح للمدير العام بعرض ملف أي مدير/شريك
    view_user_id = request.args.get('user_id', type=int)
    if view_user_id and current_user.role == 'general_manager':
        u = User.query.get(view_user_id)
        if not u:
            flash('المستخدم غير موجود', 'danger')
            return redirect(url_for('profile'))
    else:
        u = User.query.get(current_user.id)

    # === تحديد نطاق التاريخ بدقة (من أول لحظة لآخر لحظة) ===
    now = cairo_now()
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')

    if start_date_str and end_date_str:
        try:
            month_start = datetime.strptime(f"{start_date_str} 00:00:00", '%Y-%m-%d %H:%M:%S')
            month_end = datetime.strptime(f"{end_date_str} 23:59:59", '%Y-%m-%d %H:%M:%S')
        except:
            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            if month_start.month == 12: month_end = month_start.replace(year=month_start.year + 1, month=1)
            else: month_end = month_start.replace(month=month_start.month + 1)
            start_date_str = month_start.strftime('%Y-%m-%d')
            end_date_str = (month_end - timedelta(days=1)).strftime('%Y-%m-%d')
    else:
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if month_start.month == 12: month_end = month_start.replace(year=month_start.year + 1, month=1)
        else: month_end = month_start.replace(month=month_start.month + 1)
        start_date_str = month_start.strftime('%Y-%m-%d')
        end_date_str = (month_end - timedelta(days=1)).strftime('%Y-%m-%d')

    mgr_data = {}
    emp_data = {}

    # === أ) المدير (Manager) والمدير العام (General Manager) والشركاء (Partner) ===
    if u.role in ('manager', 'general_manager', 'partner'):
        is_partner = u.username in ['Abo_Eyad', 'Abo_malek']

        # دالة مساعدة لحساب المصاريف/الإيرادات للشركة أو المدير بناءً على المستهدف
        def get_transaction_sum(type_name, for_partner_id=None):
            query = db.session.query(func.sum(PartnerTransaction.amount)).filter(
                PartnerTransaction.type == type_name,
                PartnerTransaction.date >= month_start,
                PartnerTransaction.date < month_end
            )
            if for_partner_id:
                query = query.filter(PartnerTransaction.partner_id == for_partner_id)
            elif is_partner:
                # الشركاء (أبو إياد 1، أبو مالك 3) يحاسبون فقط على نسبة الشراكة من المصاريف العامة
                query = query.filter(PartnerTransaction.partner_id.in_([1, 3]))
            
            val = query.scalar()
            return abs(val) if val else 0.0

        if is_partner:
            # --- حسابات أصحاب الشركة (الشركاء) بناءً على صافي الربح الفعلي ---
            
            # 1. إجمالي ربح المبيعات للشركة كلها (سعر البيع - سعر التكلفة) للقطع المباعة
            global_gross = db.session.query(
                func.sum(SaleItem.quantity * (SaleItem.unit_price - ProductVariant.cost_price))
            ).join(SaleOrder)\
             .join(ProductVariant, SaleItem.variant_id == ProductVariant.id)\
             .filter(SaleOrder.is_proforma == False,
                     SaleOrder.date >= month_start,
                     SaleOrder.date < month_end).scalar() or 0.0
                     
            # لجلب عدد القطع فقط بغرض العرض
            global_team_items = db.session.query(func.sum(SaleItem.quantity))\
                .join(SaleOrder)\
                .filter(SaleOrder.is_proforma == False,
                        SaleOrder.date >= month_start,
                        SaleOrder.date < month_end).scalar() or 0

            # 2. المصاريف العامة على مستوى الشركة ككل (لا تفلتر بـ partner_id)
            global_girls_comm = get_transaction_sum('sub_commission')
            global_discounts = get_transaction_sum('discount_deduction')
            global_returns = get_transaction_sum('return_penalty')
            global_expenses = get_transaction_sum('expense_share')
            global_staff_costs = get_transaction_sum('staff_expense')
            global_salary_expenses = get_transaction_sum('salary_expense')  # المرتبات تُخصم من أرباح الشركة
            global_shipping_extra = get_transaction_sum('shipping_extra_commission')

        else:
            # --- حسابات المديرين العاديين (بناءً على 14 جنيه ثابتة) ---
            
            # الدخل الخاص بالمدير العادي يتم جلبه من جدول حركاته (commission_gross)
            # صافي الإيراد (يشمل المرتجعات السالبة) - يستخدم في حساب الأرباح وعرض القطع
            global_gross_query = db.session.query(func.sum(PartnerTransaction.amount))\
                .filter(PartnerTransaction.partner_id == u.id,
                        PartnerTransaction.type == 'commission_gross',
                        PartnerTransaction.date >= month_start,
                        PartnerTransaction.date < month_end).scalar() or 0.0
            global_gross = global_gross_query

            # عدد القطع الصافي — محسوب من الفواتير مباشرة (وليس من العمولات) لضمان الدقة
            mgr_team_ids = [u.id] + [t.id for t in User.query.filter(User.manager_id == u.id).all()]
            gross_team_items = db.session.query(func.sum(SaleItem.quantity))\
                .join(SaleOrder)\
                .filter(SaleOrder.is_proforma == False,
                        SaleOrder.date >= month_start,
                        SaleOrder.date < month_end,
                        SaleOrder.user_id.in_(mgr_team_ids)).scalar() or 0
            returned_team_items = db.session.query(func.sum(ReturnInvoice.total_qty))\
                .join(SaleOrder)\
                .filter(SaleOrder.user_id.in_(mgr_team_ids),
                        ReturnInvoice.date >= month_start,
                        ReturnInvoice.date < month_end).scalar() or 0
            global_team_items = max(0, gross_team_items - returned_team_items)

            # مصاريف تخص فريق المدير ده فقط
            global_girls_comm = get_transaction_sum('sub_commission', u.id)
            global_discounts = get_transaction_sum('discount_deduction', u.id)
            global_returns = get_transaction_sum('return_penalty', u.id)
            global_expenses = get_transaction_sum('expense_share', u.id)
            global_staff_costs = get_transaction_sum('staff_expense', u.id)
            global_salary_expenses = get_transaction_sum('salary_expense', u.id)
            global_shipping_extra = get_transaction_sum('shipping_extra_commission', u.id)


        # استبدال الاستدعاءات القديمة بالجديدة

        # إجمالي المكافآت المصروفة خلال الشهر من الموارد البشرية
        # ملاحظة: مكافآت المديرين (role=manager) تم تسجيلها بالفعل كـ staff_expense في PartnerTransaction
        # لذا نستبعدها هنا لتجنب الحساب المزدوج
        bonus_query = db.session.query(func.sum(HRTransaction.amount)).filter(
            HRTransaction.type == 'bonus',
            HRTransaction.date >= month_start,
            HRTransaction.date < month_end
        ).join(User, HRTransaction.user_id == User.id).filter(
            User.role != 'manager'  # استبعاد مكافآت المديرين (تم حسابها ضمن staff_expense)
        )
        if is_partner:
            bonus_query = bonus_query.filter(User.manager_id.in_([1, 3]))
        else:
            bonus_query = bonus_query.filter(User.manager_id == u.id)
            
        global_bonuses = bonus_query.scalar() or 0.0

        # عمولات المديرين (14 جنيه في القطعة) - بند منفصل عن مصاريف الشراكة
        if is_partner:
            global_manager_commissions = db.session.query(func.sum(PartnerTransaction.amount)).filter(
                PartnerTransaction.type == 'commission_gross',
                PartnerTransaction.date >= month_start,
                PartnerTransaction.date < month_end
            ).scalar() or 0.0
        else:
            global_manager_commissions = 0.0

        # مكافآت المدير نفسه (شخصية من HR)
        my_bonuses_val = 0.0
        if not is_partner:
            my_bonuses_val = db.session.query(func.sum(HRTransaction.amount)).filter(
                HRTransaction.user_id == u.id,
                HRTransaction.type == 'bonus',
                HRTransaction.date >= month_start,
                HRTransaction.date < month_end
            ).scalar() or 0.0

        # إجمالي الدخل/الربح بعد خصم المصروفات (مصاريف الشراكة + عمولات المديرين)
        # للمديرين: المكافآت بتتضاف على الدخل
        global_net_profit = global_gross + my_bonuses_val - (global_girls_comm + global_discounts + global_returns + global_expenses + global_staff_costs + global_salary_expenses + global_bonuses + global_manager_commissions + global_shipping_extra)

        # سحوبات الشريك الشخصية فقط
        my_withdrawals = db.session.query(func.sum(PartnerTransaction.amount))\
            .filter(PartnerTransaction.partner_id == u.id,
                    PartnerTransaction.type == 'withdrawal',
                    PartnerTransaction.date >= month_start,
                    PartnerTransaction.date < month_end).scalar()
        my_withdrawals = abs(my_withdrawals) if my_withdrawals else 0.0

        # الرصيد الافتتاحي (ديون أو مستحقات سابقة تعامل كإيراد شخصي)
        opening_balance = db.session.query(func.sum(PartnerTransaction.amount))\
            .filter(PartnerTransaction.partner_id == u.id,
                    PartnerTransaction.type == 'opening_balance').scalar() or 0.0

        # نصيب المستعرض الحالي (الأرباح فقط)
        my_share = (global_net_profit / 2.0) if is_partner else global_net_profit

        # --- حسابات أصحاب الشركة (الشركاء) بناءً على صافي الربح الفعلي منذ البداية (Lifetime) ---
        if is_partner:
            # 1. إجمالي ربح المبيعات للشركة كلها (سعر البيع - سعر التكلفة) للقطع المباعة (تراكمي)
            lifetime_global_gross = db.session.query(
                func.sum(SaleItem.quantity * (SaleItem.unit_price - ProductVariant.cost_price))
            ).join(SaleOrder)\
             .join(ProductVariant, SaleItem.variant_id == ProductVariant.id)\
             .filter(SaleOrder.is_proforma == False).scalar() or 0.0

            # 2. المصاريف العامة على مستوى الشركة ككل (تراكمي)
            def get_lifetime_transaction_sum(type_name):
                query = db.session.query(func.sum(PartnerTransaction.amount)).filter(
                    PartnerTransaction.type == type_name
                )
                if is_partner:
                    query = query.filter(PartnerTransaction.partner_id.in_([1, 3]))
                
                val = query.scalar()
                return abs(val) if val else 0.0

            lifetime_global_girls_comm = get_lifetime_transaction_sum('sub_commission')
            lifetime_global_discounts = get_lifetime_transaction_sum('discount_deduction')
            lifetime_global_returns = get_lifetime_transaction_sum('return_penalty')
            lifetime_global_expenses = get_lifetime_transaction_sum('expense_share')
            lifetime_global_staff_costs = get_lifetime_transaction_sum('staff_expense')
            lifetime_global_salary_expenses = get_lifetime_transaction_sum('salary_expense')  # المرتبات تُخصم من أرباح الشركة
            lifetime_global_shipping_extra = get_lifetime_transaction_sum('shipping_extra_commission')
            
            lt_bonus_query = db.session.query(func.sum(HRTransaction.amount)).filter(
                HRTransaction.type == 'bonus'
            ).join(User, HRTransaction.user_id == User.id).filter(
                User.role != 'manager'  # مكافآت المديرين محسوبة ضمن staff_expense
            )
            if is_partner:
                lt_bonus_query = lt_bonus_query.filter(User.manager_id.in_([1, 3]))
            
            lifetime_global_bonuses = lt_bonus_query.scalar() or 0.0

            # عمولات المديرين التراكمية (بند منفصل)
            lifetime_global_manager_commissions = db.session.query(func.sum(PartnerTransaction.amount)).filter(
                PartnerTransaction.type == 'commission_gross'
            ).scalar() or 0.0

            lifetime_global_net_profit = lifetime_global_gross - (
                lifetime_global_girls_comm + lifetime_global_discounts + 
                lifetime_global_returns + lifetime_global_expenses + 
                lifetime_global_staff_costs + lifetime_global_salary_expenses + 
                lifetime_global_bonuses + lifetime_global_manager_commissions +
                lifetime_global_shipping_extra
            )
            # نصيب كل شريك من الأرباح (المدى الطويل)
            lifetime_partner_share = round_half(lifetime_global_net_profit / 2.0)
            
            # Helper للحصول على أرقام شريك معين (على مستوىLifetime أيضاً)
            def get_partner_lifetime_val(partner_id, type_name):
                # إذا كنا نبحث عن المصروفات الشخصية (التي لا تؤثر في ربح الشراكة)
                val = db.session.query(func.sum(PartnerTransaction.amount))\
                    .filter(PartnerTransaction.partner_id == partner_id,
                            PartnerTransaction.type == type_name).scalar()
                return val or 0.0
                
            def get_partner_hr_withdrawals(user_id):
                val = db.session.query(func.sum(HRTransaction.amount))\
                    .filter(HRTransaction.user_id == user_id,
                            HRTransaction.type.in_(['advance', 'deduction'])).scalar()
                return abs(val) if val else 0.0

            # --- أرقام أبو إياد ---
            eyad_user = User.query.filter_by(username='Abo_Eyad').first()
            eyad_id = eyad_user.id if eyad_user else 1
            eyad_opening = get_partner_lifetime_val(eyad_id, 'opening_balance')
            eyad_withdrawals = abs(get_partner_lifetime_val(eyad_id, 'withdrawal')) + abs(get_partner_lifetime_val(eyad_id, 'personal_expense_share')) + abs(get_partner_lifetime_val(eyad_id, 'personal_salary_expense')) + get_partner_hr_withdrawals(eyad_id)
            
            # الرصيد الشخصي = حصة الشراكة + الرصيد الافتتاحي - السحوبات والمصروفات الشخصية
            eyad_final_net = lifetime_partner_share + eyad_opening - eyad_withdrawals

            # --- أرقام أبو مالك ---
            malek_user = User.query.filter_by(username='Abo_malek').first()
            malek_id = malek_user.id if malek_user else 3
            malek_opening = get_partner_lifetime_val(malek_id, 'opening_balance')
            malek_withdrawals = abs(get_partner_lifetime_val(malek_id, 'withdrawal')) + abs(get_partner_lifetime_val(malek_id, 'personal_expense_share')) + abs(get_partner_lifetime_val(malek_id, 'personal_salary_expense')) + get_partner_hr_withdrawals(malek_id)
            # الرصيد الشخصي لأبو مالك
            malek_final_net = lifetime_partner_share + malek_opening - malek_withdrawals

            
            # --- تصفية حساب الشراكة (مقارنة أداء الفريق الموحد) ---
            # كل المبيعات التي تتم من هذا الفريق تُنسب للشراكة، والخصومات تتقسم 50/50
            
            malek_user_shared = User.query.filter_by(username='Abo_malek').first()
            malek_id_shared = malek_user_shared.id if malek_user_shared else 3
            shared_team_users = User.query.filter(
                db.or_(User.id == malek_id_shared, User.manager_id == malek_id_shared)
            ).all()
            shared_team_ids = [tu.id for tu in shared_team_users]
            
            shared_team_items = db.session.query(func.sum(SaleItem.quantity))\
                .join(SaleOrder)\
                .filter(SaleOrder.is_proforma == False,
                        SaleOrder.date >= month_start,
                        SaleOrder.date < month_end,
                        SaleOrder.user_id.in_(shared_team_ids)).scalar() or 0
                        
            # طالما الفريق واحد، إذن قسمة الخصومات والمصاريف ستكون 50% لكل منهما بالتساوي
            malek_percent = 50.0
            eyad_percent = 50.0
            
            total_period_deductions = global_discounts + global_returns + global_expenses + global_staff_costs
            
            malek_deduction_share = total_period_deductions * (malek_percent / 100.0)
            eyad_deduction_share = total_period_deductions * (eyad_percent / 100.0)
            
            # Placeholder for my_final_net which is no longer needed in the UI for partners but expected by the dictionary
            my_final_net = 0.0
        else:
            # مدير عادي: حساب صافي الأرباح والمسحوبات مدى الحياة (Lifetime) لتطابق تقرير الشركاء 100%
            
            # 1. كل حركات الشراكة التراكمية للمدير
            all_pt = db.session.query(PartnerTransaction).filter(PartnerTransaction.partner_id == u.id).all()
            
            # 2. مكافآت وسلف الموارد البشرية التراكمية
            hr_withdrawals = db.session.query(func.sum(HRTransaction.amount))\
                .filter(HRTransaction.user_id == u.id,
                        HRTransaction.type.in_(['advance', 'deduction'])).scalar() or 0.0
            
            hr_personal_bonuses = db.session.query(func.sum(HRTransaction.amount))\
                .filter(HRTransaction.user_id == u.id, HRTransaction.type == 'bonus').scalar() or 0.0

            # 3. إجمالي الأرباح (كل ما ليس سحب أو افتتاحية) وتضاف لها مكافآت HR
            my_share = sum(t.amount for t in all_pt if t.type not in ['withdrawal', 'personal_expense_share', 'personal_salary_expense', 'partner_bonus', 'partner_deduction', 'opening_balance', 'commission_correction']) + hr_personal_bonuses
            
            # 4. إجمالي المسحوبات (في التقرير نعرضها موجبة)
            partner_withdrawals_sum = sum(t.amount for t in all_pt if t.type in ['withdrawal', 'personal_expense_share', 'personal_salary_expense', 'partner_bonus', 'partner_deduction', 'commission_correction'])
            # المسحوبات عادة تكون سالبة في PartnerTransaction فنطرح منها مسحوبات HR لزيادة سالبيتها ثم أخذ القيمة المطلقة للعرض
            my_withdrawals = abs(partner_withdrawals_sum - hr_withdrawals)

            # الصافي المستحق النهائي: الرصيد الحقيقي التطابقي (المجموع الجبري التام)
            # وهذا يتطابق رياضياً مع: opening_balance + my_share - my_withdrawals
            my_final_net = sum(t.amount for t in all_pt) + hr_personal_bonuses - hr_withdrawals


        # تجميع إجمالي المصاريف للشريك (مصاريف الشراكة + عمولات المديرين)
        global_expenses_total = global_girls_comm + global_discounts + global_returns + global_expenses + global_staff_costs + global_salary_expenses + global_bonuses + global_manager_commissions + global_shipping_extra

        mgr_data = {
            'is_partner': is_partner,
            'global_items': global_team_items,
            'global_gross': round_half(global_gross),
            'my_bonuses': round_half(my_bonuses_val),
            'global_girls_comm': round_half(global_girls_comm),
            'global_discounts': round_half(global_discounts),
            'global_returns': round_half(global_returns),
            'global_expenses': round_half(global_expenses),
            'global_staff_costs': round_half(global_staff_costs),
            'global_bonuses': round_half(global_bonuses),
            'global_salary_expenses': round_half(global_salary_expenses),
            'global_manager_commissions': round_half(global_manager_commissions),
            'global_shipping_extra': round_half(global_shipping_extra),
            'global_expenses_total': round_half(global_expenses_total),
            'global_net_profit': round_half(global_net_profit),
            'opening_balance': round_half(opening_balance),
            'my_share': round_half(my_share),
            'my_withdrawals': round_half(my_withdrawals),
            'my_final_net': round_half(my_final_net),

            # بيانات الشركاء مفصلة (الجديد المقالي)
            'eyad_id': eyad_id if is_partner else 0,
            'eyad_opening': round_half(eyad_opening) if is_partner else 0,
            'eyad_withdrawals': round_half(eyad_withdrawals) if is_partner else 0,
            'eyad_share': round_half(lifetime_partner_share) if is_partner else 0,
            'lifetime_global_net_profit': round_half(lifetime_global_net_profit) if is_partner else 0,
            'lifetime_global_gross': round_half(lifetime_global_gross) if is_partner else 0,
            'eyad_final_net': round_half(eyad_final_net) if is_partner else 0,

            'malek_id': malek_id if is_partner else 0,
            'malek_opening': round_half(malek_opening) if is_partner else 0,
            'malek_withdrawals': round_half(malek_withdrawals) if is_partner else 0,
            'malek_share': round_half(lifetime_partner_share) if is_partner else 0,
            'malek_final_net': round_half(malek_final_net) if is_partner else 0,

            # بيانات تصفية الشراكة القديمة (للاحتياط)
            'shared_team_items': shared_team_items if is_partner else 0,
            'malek_percent': malek_percent if is_partner else 0,
            'eyad_percent': eyad_percent if is_partner else 0,
            'malek_deduction_share': malek_deduction_share if is_partner else 0,
            'eyad_deduction_share': eyad_deduction_share if is_partner else 0
        }

    # === ب) الموظف (Sales / Worker) - هنا كان اللغز ===
    else:
        # 1. إجمالي البيع من الفواتير (نطاق التاريخ الدقيق)
        # هام: نتأكد أن الفاتورة ليست proforma
        gross_items_sold = db.session.query(func.sum(SaleItem.quantity))\
            .join(SaleOrder)\
            .filter(SaleOrder.user_id == u.id,
                    SaleOrder.is_proforma == False,
                    SaleOrder.date >= month_start, # أكبر من أو يساوي 1 في الشهر
                    SaleOrder.date < month_end).scalar() or 0 # أصغر من 1 في الشهر الجاي

        # 2. قراءة المرتجعات من ملاحظات الـ HR (نطاق التاريخ الدقيق)
        hr_trans = HRTransaction.query.filter(
            HRTransaction.user_id == u.id,
            HRTransaction.date >= month_start,
            HRTransaction.date < month_end
        ).all()

        bonuses = 0
        real_deductions = 0
        advances = 0
        returned_items_from_hr = 0
        deductions_list = [] # قائمة لتخزين تفاصيل الخصومات

        for t in hr_trans:
            if t.type == 'bonus':
                bonuses += t.amount
            elif t.type == 'advance':
                advances += t.amount
            elif t.type == 'deduction':
                # استخراج عدد القطع المرتجعة
                if t.note and ('مرتجع' in t.note or 'قطعة' in t.note):
                    match = re.search(r'\((\d+)\s*قطعة\)', t.note)
                    if match:
                        returned_items_from_hr += int(match.group(1))
                else:
                    real_deductions += t.amount
                    deductions_list.append({
                        'date': t.date.strftime('%Y-%m-%d') if t.date else '-',
                        'amount': t.amount,
                        'reason': t.note or 'خصم إداري'
                    })
            elif t.type == 'penalty':
                 real_deductions += t.amount
                 deductions_list.append({
                    'date': t.date.strftime('%Y-%m-%d') if t.date else '-',
                    'amount': t.amount,
                    'reason': t.note or 'جزاء مالي'
                 })

        # 3. صافي القطع
        net_items = gross_items_sold - returned_items_from_hr
        if net_items < 0: net_items = 0

        # 4. حساب العمولة
        commission = calculate_user_commission(u, net_items, net_items)

        # 5. جزاءات الحضور (دايماً الشهر الحالي زي المرتبات)
        att_settings = AttendanceSettings.query.first()
        if not att_settings:
            att_settings = AttendanceSettings()
        daily_rate = (u.base_salary or 0) / 30
        month_str_for_att = now.strftime('%Y-%m')
        attendance_deduction, attendance_details, overtime_bonus = calculate_attendance_deduction(u, month_str_for_att, att_settings, daily_rate)

        # إضافة مكافأة الساعات الإضافية للمكافآت
        bonuses += overtime_bonus

        # 6. الراتب النهائي
        net_salary = (u.base_salary or 0) + commission + bonuses - real_deductions - advances - attendance_deduction

        emp_data = {
            'total_items': int(net_items),
            'commission': round_half(commission),
            'bonuses': round_half(bonuses),
            'deductions': round_half(real_deductions),
            'advances': round_half(advances),
            'attendance_deduction': round_half(attendance_deduction),
            'attendance_details': attendance_details,
            'net_salary': round_half(net_salary),
            # إضافة لمعرفة هل المشكلة في التاريخ أم في الربط
            'debug_gross': int(gross_items_sold),
            'debug_returns': int(returned_items_from_hr),
            'deductions_list': deductions_list # تمرير اللستة للقالب
        }

    return render_template('profile.html', user=u, mgr=mgr_data, emp=emp_data,
                           start_date=start_date_str, end_date=end_date_str,
                           view_user_id=view_user_id)

@app.route('/api/financial-details', methods=['GET'])
@login_required
def financial_details():
    if current_user.role not in ['general_manager', 'manager']:
        return jsonify({'error': 'غير مصرح لك بعرض هذه التفاصيل'}), 403
        
    detail_type = request.args.get('type')
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    partner_id_str = request.args.get('partner_id')
    
    start_date, end_date = None, None
    if start_date_str and end_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            # لضمان شمول اليوم الأخير كاملاً
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date() + timedelta(days=1)
        except ValueError:
            pass
            
    is_partner = current_user.role == 'general_manager' and \
                 current_user.username in ['Abo_Eyad', 'Abo_malek']
                 
    results = []
    
    if detail_type == 'company_expenses':
        # مكافآت HR (تصرف للموظفين العاديين فقط - مكافآت المديرين محسوبة ضمن staff_expense)
        hr_query = HRTransaction.query.join(User, HRTransaction.user_id == User.id).filter(
            HRTransaction.type == 'bonus',
            User.role != 'manager'  # استبعاد مكافآت المديرين (محسوبة ضمن staff_expense)
        )
        if start_date and end_date:
            hr_query = hr_query.filter(HRTransaction.date >= start_date, HRTransaction.date < end_date)
            
        if not is_partner:
            hr_query = hr_query.filter(User.manager_id == current_user.id)

        for t in hr_query.all():
            u_name = User.query.get(t.user_id).fullname if t.user_id else 'غير معروف'
            results.append({
                'date': t.date.strftime('%Y-%m-%d') if t.date else '',
                'category': f"مكافأة ({u_name})",
                'amount': float(t.amount),
                'note': getattr(t, 'note', getattr(t, 'description', ''))
            })

        # حركات PartnerTransaction (مصاريف الشراكة)
        # للشركاء: salary_expense = 0 في الكارت، فنستبعدها هنا أيضاً للتطابق
        expense_types = ['discount_deduction', 'return_penalty', 'expense_share', 'staff_expense', 'shipping_extra_commission']
        if is_partner:
            expense_types.append('sub_commission')
        if not is_partner:
            expense_types.append('salary_expense')
        
        pt_query = PartnerTransaction.query.filter(
            PartnerTransaction.type.in_(expense_types)
        )
        if start_date and end_date:
            pt_query = pt_query.filter(PartnerTransaction.date >= start_date, PartnerTransaction.date < end_date)
            
        if not is_partner:
            pt_query = pt_query.filter(PartnerTransaction.partner_id == current_user.id)
        else:
            pt_query = pt_query.filter(PartnerTransaction.partner_id.in_([1, 3]))
            
        type_labels = {
            'sub_commission': 'عمولة فريق البنات بمكتبه',
            'discount_deduction': 'خصم من الشراكة / المبيعات',
            'return_penalty': 'غرامة وحصة مرتجعات',
            'expense_share': 'مصروف عام (شراكة)',
            'staff_expense': 'تكاليف ومستحقات موظفين',
            'salary_expense': 'رواتب وسلف ومكافآت',
            'shipping_extra_commission': 'عمولة شركة شحن إضافية'
        }
        for t in pt_query.all():
            amt = float(t.amount) * -1
            results.append({
                'date': t.date.strftime('%Y-%m-%d %H:%M') if t.date else '',
                'category': type_labels.get(t.type, t.type),
                'amount': amt,
                'note': getattr(t, 'note', getattr(t, 'description', ''))
            })

        # عمولات المديرين (14 جنيه) - بند منفصل (للشركاء فقط)
        # نعرض كل الحركات (موجبة وسالبة) عشان المجموع يتطابق مع الكارت
        if is_partner:
            comm_query = PartnerTransaction.query.filter(
                PartnerTransaction.type == 'commission_gross'
            )
            if start_date and end_date:
                comm_query = comm_query.filter(PartnerTransaction.date >= start_date, PartnerTransaction.date < end_date)
            for t in comm_query.all():
                partner_user = User.query.get(t.partner_id)
                mgr_name = partner_user.fullname if partner_user else 'مدير'
                results.append({
                    'date': t.date.strftime('%Y-%m-%d') if t.date else '',
                    'category': f"عمولة مدير ({mgr_name})",
                    'amount': float(t.amount),
                    'note': getattr(t, 'description', '')
                })

        # حساب الإجمالي الرسمي (نفس طريقة الكارت بالضبط)
        def _type_sum(pt_type, pid=None):
            q = db.session.query(func.sum(PartnerTransaction.amount))\
                .filter(PartnerTransaction.type == pt_type)
            if start_date and end_date:
                q = q.filter(PartnerTransaction.date >= start_date, PartnerTransaction.date < end_date)
            if pid:
                q = q.filter(PartnerTransaction.partner_id == pid)
            elif is_partner:
                q = q.filter(PartnerTransaction.partner_id.in_([1, 3]))
            val = q.scalar()
            return abs(val) if val else 0.0

        if not is_partner:
            computed_total = (
                _type_sum('discount_deduction', current_user.id) +
                _type_sum('return_penalty', current_user.id) +
                _type_sum('expense_share', current_user.id) +
                _type_sum('staff_expense', current_user.id) +
                _type_sum('salary_expense', current_user.id) +
                _type_sum('shipping_extra_commission', current_user.id)
            )
            # مكافآت HR (غير المديرين) تحت إدارة هذا المدير
            bonus_val = db.session.query(func.sum(HRTransaction.amount)).filter(
                HRTransaction.type == 'bonus'
            ).join(User, HRTransaction.user_id == User.id).filter(
                User.role != 'manager',
                User.manager_id == current_user.id
            )
            if start_date and end_date:
                bonus_val = bonus_val.filter(HRTransaction.date >= start_date, HRTransaction.date < end_date)
            bonus_val = bonus_val.scalar() or 0.0
            computed_total += abs(bonus_val)
        else:
            computed_total = (
                _type_sum('sub_commission') +
                _type_sum('discount_deduction') +
                _type_sum('return_penalty') +
                _type_sum('expense_share') +
                _type_sum('staff_expense')
            )
            # عمولات شركات الشحن الإضافية
            computed_total += _type_sum('shipping_extra_commission')
            # مكافآت HR
            bonus_val = db.session.query(func.sum(HRTransaction.amount)).filter(
                HRTransaction.type == 'bonus'
            ).join(User, HRTransaction.user_id == User.id).filter(
                User.role != 'manager',
                User.manager_id.in_([1, 3])
            )
            if start_date and end_date:
                bonus_val = bonus_val.filter(HRTransaction.date >= start_date, HRTransaction.date < end_date)
            bonus_val = bonus_val.scalar() or 0.0
            computed_total += abs(bonus_val)
            # عمولات المديرين
            comm_val = db.session.query(func.sum(PartnerTransaction.amount)).filter(
                PartnerTransaction.type == 'commission_gross'
            )
            if start_date and end_date:
                comm_val = comm_val.filter(PartnerTransaction.date >= start_date, PartnerTransaction.date < end_date)
            comm_val = comm_val.scalar() or 0.0
            computed_total += abs(comm_val)
            
    elif detail_type == 'sub_commission_details':
        user_id = int(partner_id_str) if partner_id_str else current_user.id
        pt_query = PartnerTransaction.query.filter(
            PartnerTransaction.type == 'sub_commission'
        )
        if start_date and end_date:
            pt_query = pt_query.filter(PartnerTransaction.date >= start_date, PartnerTransaction.date < end_date)
            
        if partner_id_str or not is_partner:
            pt_query = pt_query.filter(PartnerTransaction.partner_id == user_id)
        else:
            pt_query = pt_query.filter(PartnerTransaction.partner_id.in_([1, 3]))
            
        algebraic_sum = 0.0
        for t in pt_query.all():
            amt = float(t.amount) * -1 # العمولات مصاريف (سالبة) فنعكسها عشان تظهر موجبة، ولو مرتجع (موجب) يظهر سالب
            algebraic_sum += amt
            results.append({
                'date': t.date.strftime('%Y-%m-%d %H:%M') if t.date else '',
                'category': 'عمولة فريق البنات بمكتبه',
                'amount': amt,
                'note': getattr(t, 'note', getattr(t, 'description', ''))
            })
        computed_total = algebraic_sum
            
    elif detail_type == 'partner_withdrawals' and partner_id_str:
        user_id = int(partner_id_str)
        
        # 1. سحوبات الأرباح والمصروفات الشخصية (المرتبات المخصومة شخصيا)
        p_trans = PartnerTransaction.query.filter(
            PartnerTransaction.partner_id == user_id,
            PartnerTransaction.type.in_(['withdrawal', 'personal_expense_share', 'personal_salary_expense', 'partner_bonus', 'partner_deduction', 'commission_correction'])
        ).order_by(PartnerTransaction.date.desc()).all()
        
        type_labels_pt = {
            'withdrawal': 'سحوبات أرباح (شريك)',
            'personal_expense_share': 'سحوبات أرباح (مصروفات)',
            'personal_salary_expense': 'سحوبات أرباح (رواتب)',
            'partner_bonus': 'مكافآت وتوريدات',
            'partner_deduction': 'خصومات وجزاءات',
            'commission_correction': 'تسوية/تعويض عمولات'
        }
        
        for t in p_trans:
            amt = float(t.amount) * -1
            results.append({
                'date': t.date.strftime('%Y-%m-%d %H:%M') if t.date else '',
                'category': type_labels_pt.get(t.type, t.type),
                'amount': amt,
                'note': getattr(t, 'note', getattr(t, 'description', ''))
            })
            
        # 2. سلفيات وخصومات الـ HR
        hr_trans = HRTransaction.query.filter(
            HRTransaction.user_id == user_id,
            HRTransaction.type.in_(['advance', 'deduction'])
        ).order_by(HRTransaction.date.desc()).all()
        
        for t in hr_trans:
            # مسحوبات الـ HR (السلف والخصومات) مسجلة كقيم موجبة في الداتا بيز
            # فلازم تفضل موجبة عشان تتجمع على إجمالي السحوبات في المودال وتطابق الرقم الخارجي
            amt = float(t.amount)
            results.append({
                'date': t.date.strftime('%Y-%m-%d %H:%M') if t.date else '',
                'category': f"خصم سلفة/مسحوبات",
                'amount': amt,
                'note': getattr(t, 'note', getattr(t, 'description', ''))
            })
            
    elif detail_type == 'sales_profit':
        # جلب صافي أرباح الفواتير ككل
        orders_query = SaleOrder.query.filter(SaleOrder.is_proforma == False)
        if start_date and end_date:
            orders_query = orders_query.filter(SaleOrder.date >= start_date, SaleOrder.date < end_date)
            
        if not is_partner:
            if current_user.role == 'manager':
                team_ids = [u.id for u in User.query.filter(db.or_(User.id == current_user.id, User.manager_id == current_user.id)).all()]
                orders_query = orders_query.filter(SaleOrder.user_id.in_(team_ids))
            else:
                orders_query = orders_query.filter(SaleOrder.user_id == current_user.id)
            
        orders = orders_query.order_by(SaleOrder.date.desc()).all()
        
        for o in orders:
            order_profit = sum(i.quantity * (i.unit_price - (i.variant.cost_price or 0)) for i in o.items if i.variant)
            if order_profit != 0:
                results.append({
                    'date': o.date.strftime('%Y-%m-%d %H:%M') if o.date else getattr(o, 'created_at', '').strftime('%Y-%m-%d'),
                    'category': f"ربح فاتورة مبيعات #{o.id}",
                    'amount': float(order_profit),
                    'note': f"العميل: {o.customer.name if o.customer else 'بدون عميل'}" + (f" - ملاحظات: {o.notes}" if hasattr(o, 'notes') and o.notes else "")
                })
                
    elif detail_type == 'net_profit':
        user_id = int(partner_id_str) if partner_id_str else current_user.id
        
        # 1. Partner Transactions excluding withdrawals and opening balances
        exclude_types = ['withdrawal', 'personal_expense_share', 'personal_salary_expense', 'partner_bonus', 'partner_deduction', 'opening_balance', 'commission_correction']
        pt_query = PartnerTransaction.query.filter(
            PartnerTransaction.partner_id == user_id,
            PartnerTransaction.type.notin_(exclude_types)
        )
        if start_date and end_date:
            pt_query = pt_query.filter(PartnerTransaction.date >= start_date, PartnerTransaction.date < end_date)
            
        for t in pt_query.order_by(PartnerTransaction.date.desc()).all():
            amt = float(t.amount)
            type_labels = {
                'commission_gross': 'عمولة مبيعات',
                'sub_commission': 'عمولة فريق البنات',
                'discount_deduction': 'خصم من الشراكة',
                'return_penalty': 'غرامة وحصة مرتجعات',
                'expense_share': 'مصروف عام (شراكة)',
                'staff_expense': 'تكاليف ومستحقات موظفين',
                'salary_expense': 'رواتب وسلف ومكافآت',
                'shipping_extra_commission': 'عمولة شركة شحن إضافية'
            }
            cat = type_labels.get(t.type, t.type)
            if t.order_id:
                cat += f" (فاتورة #{t.order_id})"
            
            results.append({
                'date': t.date.strftime('%Y-%m-%d %H:%M') if t.date else '',
                'category': cat,
                'amount': amt,
                'note': getattr(t, 'description', getattr(t, 'note', ''))
            })
            
        # 2. HR Bonuses
        hr_query = HRTransaction.query.filter(
            HRTransaction.user_id == user_id,
            HRTransaction.type == 'bonus'
        )
        if start_date and end_date:
            hr_query = hr_query.filter(HRTransaction.date >= start_date, HRTransaction.date < end_date)
            
        for t in hr_query.order_by(HRTransaction.date.desc()).all():
            results.append({
                'date': t.date.strftime('%Y-%m-%d %H:%M') if t.date else '',
                'category': 'مكافأة موارد بشرية (HR)',
                'amount': float(t.amount),
                'note': getattr(t, 'description', getattr(t, 'note', ''))
            })

    elif detail_type == 'commission_gross':
        # جلب عمولات المدير أو الشريك المباشرة من فواتيره
        user_id = int(partner_id_str) if partner_id_str else current_user.id
        
        pt_query = PartnerTransaction.query.filter(
            PartnerTransaction.partner_id == user_id,
            PartnerTransaction.type == 'commission_gross'
        )
        if start_date and end_date:
            pt_query = pt_query.filter(PartnerTransaction.date >= start_date, PartnerTransaction.date < end_date)
            
        transactions = pt_query.order_by(PartnerTransaction.date.desc()).all()
        for t in transactions:
            results.append({
                'date': t.date.strftime('%Y-%m-%d %H:%M') if t.date else '',
                'category': f"عمولة مبيعات (فاتورة #{t.order_id})" if t.order_id else "عمولة مبيعات",
                'amount': float(t.amount),
                'note': getattr(t, 'description', getattr(t, 'note', ''))
            })
                
    elif detail_type == 'sold_items' and start_date and end_date:
        # تحديد المدير المستهدف (لو المدير العام بيشوف ملف مدير تاني)
        target_user_id = int(partner_id_str) if partner_id_str else current_user.id
        target_user = User.query.get(target_user_id)
        target_is_partner = target_user.username in ['Abo_Eyad', 'Abo_malek'] if target_user else is_partner

        if not target_is_partner:
            # --- المديرين العاديين: نستخدم الفواتير مباشرة (نفس مصدر الكارت الجديد) ---
            mgr_detail_ids = [target_user_id] + [t.id for t in User.query.filter(User.manager_id == target_user_id).all()]
            orders_query = SaleOrder.query.filter(
                SaleOrder.date >= start_date, SaleOrder.date < end_date,
                SaleOrder.is_proforma == False,
                SaleOrder.user_id.in_(mgr_detail_ids)
            )
            orders = orders_query.order_by(SaleOrder.date.desc()).all()
            for o in orders:
                order_items_count = sum(i.quantity for i in o.items)
                if order_items_count > 0:
                    results.append({
                        'date': o.date.strftime('%Y-%m-%d %H:%M') if o.date else '',
                        'category': f"قطع فاتورة #{o.id}",
                        'amount': float(order_items_count),
                        'note': f"العميل: {o.customer.name if o.customer else 'بدون عميل'}" + (f" - بواسطة: {o.sales_rep.fullname}" if getattr(o, 'sales_rep', None) else "")
                    })
        else:
            # --- الشركاء: نستخدم SaleOrder مباشرة (نفس مصدر الكارت للشركاء) ---
            orders_query = SaleOrder.query.filter(
                SaleOrder.date >= start_date, SaleOrder.date < end_date,
                SaleOrder.is_proforma == False
            )
            orders = orders_query.order_by(SaleOrder.date.desc()).all()
            for o in orders:
                order_items_count = sum(i.quantity for i in o.items)
                if order_items_count > 0:
                    results.append({
                        'date': o.date.strftime('%Y-%m-%d %H:%M') if o.date else getattr(o, 'created_at', '').strftime('%Y-%m-%d'),
                        'category': f"قطع فاتورة #{o.id}",
                        'amount': float(order_items_count),
                        'note': f"العميل: {o.customer.name if o.customer else 'بدون عميل'}" + (f" - بواسطة: {o.sales_rep.fullname}" if getattr(o, 'sales_rep', None) else "")
                    })

    elif detail_type == 'shipping_extra_commission':
        # عمولات شركات الشحن الإضافية (الفارق بين المبلغ المستحق والمحصل)
        sec_query = PartnerTransaction.query.filter(
            PartnerTransaction.type == 'shipping_extra_commission'
        )
        if start_date and end_date:
            sec_query = sec_query.filter(PartnerTransaction.date >= start_date, PartnerTransaction.date < end_date)
        
        if not is_partner:
            sec_query = sec_query.filter(PartnerTransaction.partner_id == current_user.id)
        else:
            sec_query = sec_query.filter(PartnerTransaction.partner_id.in_([1, 3]))
        
        # تجميع الحركات حسب order_id لتجنب التكرار (حركة لكل شريك)
        seen_orders = set()
        for t in sec_query.order_by(PartnerTransaction.date.desc()).all():
            order_key = t.order_id or t.id
            if order_key in seen_orders:
                continue
            seen_orders.add(order_key)
            # المبلغ الإجمالي للفارق (ضعف نصيب الشريك الواحد)
            full_amount = abs(t.amount) * 2
            results.append({
                'date': t.date.strftime('%Y-%m-%d') if t.date else '',
                'category': f"عمولة شركة شحن (فاتورة #{t.order_id})" if t.order_id else "عمولة شركة شحن",
                'amount': float(full_amount),
                'note': t.description or ''
            })

    # ترتيب من الأحدث للأقدم
    try:
        results.sort(key=lambda x: x['date'], reverse=True)
    except Exception:
        pass

    # لو company_expenses نرجع الإجمالي الرسمي مع البيانات
    if detail_type == 'company_expenses':
        return jsonify({'items': results, 'computed_total': round_half(computed_total)})
    return jsonify(results)
@app.route('/api/attendance', methods=['POST'])
@login_required
def attendance():
    data = request.get_json()
    lat = data.get('lat')
    lng = data.get('lng')
    action = data.get('action')
    if not lat or not lng: return jsonify({'error': 'لم يتم تحديد الموقع'}), 400
    distance = calculate_distance(lat, lng, FACTORY_LAT, FACTORY_LNG)
    if distance > ALLOWED_RADIUS: return jsonify({'error': f'أنت بعيد عن المصنع ({int(distance)}م). المسموح {ALLOWED_RADIUS}م.'}), 403
    today = date.today()
    record = Attendance.query.filter_by(user_id=current_user.id, date=today).first()
    if action == 'check_in':
        if record: return jsonify({'error': 'تم تسجيل الحضور مسبقاً'}), 400
        status = 'present'
        if current_user.shift_start:
            try:
                shift_time = datetime.strptime(current_user.shift_start, '%H:%M').time()
                grace_limit = datetime.combine(today, shift_time) + timedelta(minutes=15)
                if cairo_now() > grace_limit: status = 'late'
            except: pass
        db.session.add(Attendance(user_id=current_user.id, check_in=cairo_now(), status=status))
        db.session.commit()
        return jsonify({'success': f"تم تسجيل الحضور ({'متأخر ⚠️' if status=='late' else '✅'})"})
    elif action == 'check_out':
        if not record: return jsonify({'error': 'لم تسجل حضور اليوم!'}), 400
        record.check_out = cairo_now(); db.session.commit()
        return jsonify({'success': 'تم تسجيل الانصراف بنجاح 👋'})
    return jsonify({'error': 'Invalid Action'}), 400

@app.route('/api/attendance/edit', methods=['POST'])
@login_required
def edit_attendance():
    if current_user.role != 'general_manager':
        return jsonify({'error': 'غير مسموح'}), 403
    data = request.get_json()
    rec_id = data.get('id')
    record = Attendance.query.get(rec_id)
    if not record:
        return jsonify({'error': 'سجل غير موجود'}), 404

    new_check_in = data.get('check_in')
    new_check_out = data.get('check_out')
    new_status = data.get('status')

    if new_check_in:
        try:
            record.check_in = datetime.strptime(new_check_in, '%Y-%m-%dT%H:%M')
        except:
            pass
    if new_check_out:
        try:
            record.check_out = datetime.strptime(new_check_out, '%Y-%m-%dT%H:%M')
        except:
            pass
    elif new_check_out == '':
        record.check_out = None

    if new_status:
        record.status = new_status

    db.session.commit()
    return jsonify({'success': 'تم تعديل سجل الحضور بنجاح ✅'})

@app.route('/api/attendance/delete', methods=['POST'])
@login_required
def delete_attendance():
    if current_user.role not in ['manager', 'general_manager']:
        return jsonify({'error': 'غير مسموح - هذه الصلاحية للمديرين فقط'}), 403
    data = request.get_json()
    rec_id = data.get('id')
    date_str = data.get('date')
    user_id = data.get('user_id')

    # لو rec_id = 0 يعني يوم غياب بدون سجل حضور → نعمل إذن يوم كامل عشان يلغي الجزاء
    if not rec_id or rec_id == 0:
        if date_str and user_id:
            from datetime import date as date_type
            excuse_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            # تأكد مفيش إذن يوم كامل مسجل قبل كده لنفس اليوم
            existing = EmployeeExcuse.query.filter_by(user_id=int(user_id), date=excuse_date).first()
            if existing:
                # لو فيه إذن بس مش يوم كامل (مثلاً إذن ساعات) → نحوّله ليوم كامل
                if existing.type != 'day':
                    existing.type = 'day'
                    existing.note = 'إلغاء جزاء غياب (بواسطة المدير)'
                    db.session.commit()
            else:
                db.session.add(EmployeeExcuse(
                    user_id=int(user_id),
                    date=excuse_date,
                    type='day',
                    note='إلغاء جزاء غياب (بواسطة المدير)'
                ))
                db.session.commit()
            return jsonify({'success': 'تم إلغاء جزاء الغياب وتسجيل إذن يوم كامل ✅'})
        return jsonify({'error': 'بيانات ناقصة لإلغاء جزاء الغياب'}), 400

    record = Attendance.query.get(rec_id)
    if not record:
        return jsonify({'error': 'سجل غير موجود'}), 404
    db.session.delete(record)
    db.session.commit()
    return jsonify({'success': 'تم إلغاء الجزاء وحذف سجل الحضور بنجاح ✅'})

@app.route('/fix_shifts')
@login_required
def fix_shifts():
    if current_user.role != 'general_manager':
        return 'غير مسموح', 403
    count = 0
    users = User.query.all()
    for u in users:
        changed = False
        if u.shift_start == '01:00':
            u.shift_start = '13:00'
            changed = True
        if u.shift_end == '05:00':
            u.shift_end = '17:00'
            changed = True
        if not u.shift_start or u.shift_start == '09:00':
            u.shift_start = '13:00'
            changed = True
        if changed:
            count += 1
    db.session.commit()
    return f'تم تعديل مواعيد الوردية لـ {count} موظف ✅ (13:00 - 17:00)'

@app.route('/hr/attendance_settings', methods=['GET', 'POST'])
@login_required
def attendance_settings():
    if current_user.role != 'general_manager':
        flash('غير مسموح', 'danger')
        return redirect('/')
    settings = AttendanceSettings.query.first()
    if not settings:
        settings = AttendanceSettings()
        db.session.add(settings)
        db.session.commit()

    if request.method == 'POST':
        settings.grace_period = int(request.form.get('grace_period', 15))
        settings.tier1_max_mins = int(request.form.get('tier1_max_mins', 30))
        settings.tier1_penalty = float(request.form.get('tier1_penalty', 0.25))
        settings.tier2_max_mins = int(request.form.get('tier2_max_mins', 60))
        settings.tier2_penalty = float(request.form.get('tier2_penalty', 0.5))
        settings.tier3_max_mins = int(request.form.get('tier3_max_mins', 120))
        settings.tier3_penalty = float(request.form.get('tier3_penalty', 1.0))
        settings.tier4_penalty = float(request.form.get('tier4_penalty', 2.0))
        settings.absent_no_excuse = float(request.form.get('absent_no_excuse', 1.0))
        settings.absent_excused = float(request.form.get('absent_excused', 0.5))
        settings.absent_full_day_excuse = float(request.form.get('absent_full_day_excuse', 0.0))
        settings.no_checkout_penalty = float(request.form.get('no_checkout_penalty', 2.0))
        settings.skip_friday = 'skip_friday' in request.form
        settings.skip_saturday = 'skip_saturday' in request.form
        db.session.commit()
        flash('تم حفظ إعدادات الجزاءات بنجاح ✅', 'success')
        return redirect('/hr/attendance_settings')

    return render_template('attendance_settings.html', s=settings)

@app.route('/fix_commissions')
@general_manager_required
def fix_commissions_manual():
    # بنجيب كل الموظفين السيلز
    sales_reps = User.query.filter_by(role='sales').all()
    count = 0
    today = cairo_now()

    for rep in sales_reps:
        # تحديث عمولاتهم للشهر الحالي
        update_monthly_commissions(rep.id, today)
        count += 1

    # تحديث عمولات المديرين برضه (لو باعوا بنفسهم)
    managers = User.query.filter_by(role='manager').all()
    for mgr in managers:
        update_monthly_commissions(mgr.id, today)
        count += 1

    return f"تم تحديث العمولات لـ {count} موظف ومدير بنجاح! راجع تقرير الشركاء الآن."
def add_split_partner_transaction(partner_id, type_val, amount, description, order_id=None):
    """
    مساعد لإضافة حركة شراكة بالمبلغ الكامل (بدون تقسيم 50/50).
    التقارير بتجمع كل حركات الشراكة ب partner_id IN (1, 3) فالإجمالي مظبوط.
    """
    db.session.add(PartnerTransaction(
        partner_id=partner_id,
        order_id=order_id,
        type=type_val,
        amount=amount,
        description=description
    ))

def update_monthly_commissions(sales_rep_id, ref_date):
    """
    دالة تعيد حساب عمولات الشهر بالكامل للموظف ومديره
    كل شهر مستقل بذاته - بدون تراكم أو تسويات بأثر رجعي
    """
    try:
        # 1. تحديد الموظف والشريك (المدير)
        sales_rep = User.query.get(sales_rep_id)
        if not sales_rep: return

        partner = None
        if sales_rep.role == 'manager':
            partner = sales_rep
        elif sales_rep.manager_id:
            partner = User.query.get(sales_rep.manager_id)

        if not partner or partner.role != 'manager': return

        # 2. تحديد حدود الشهر
        target_month_str = ref_date.strftime('%Y-%m')
        target_month_start = ref_date.replace(day=1, hour=0, minute=0, second=0)
        next_month = (target_month_start.replace(day=28) + timedelta(days=4)).replace(day=1)

        # 3. حساب إجمالي مبيعات الشهر فقط (لتحديد الشريحة)
        monthly_sales = db.session.query(func.sum(SaleItem.quantity))\
            .join(SaleOrder)\
            .filter(SaleOrder.user_id == sales_rep.id,
                    SaleOrder.is_proforma == False,
                    SaleOrder.is_reviewed == True,
                    SaleOrder.date >= target_month_start,
                    SaleOrder.date < next_month)\
            .scalar() or 0

        # خصم المرتجعات لنفس الشهر
        monthly_returns = db.session.query(func.sum(ReturnInvoice.total_qty))\
            .join(SaleOrder)\
            .filter(SaleOrder.user_id == sales_rep.id,
                    SaleOrder.date >= target_month_start,
                    SaleOrder.date < next_month)\
            .scalar() or 0

        total_monthly_items = max(0, monthly_sales - monthly_returns)

        # 4. تحديد سعر عمولة الموظفة (بناءً على صافي مبيعات الشهر)
        rate_per_item = 0.0
        if sales_rep.job_type == 'tiered_sales' and sales_rep.commission_rules:
            try:
                tiers = json.loads(sales_rep.commission_rules)
                for tier in tiers:
                    t_min = float(tier.get('min', 0))
                    t_max = float(tier.get('max', 999999))
                    t_val = float(tier.get('val', 0))
                    if t_min <= total_monthly_items <= t_max:
                        rate_per_item = t_val
                        break
            except: pass
        elif sales_rep.commission_value:
            rate_per_item = float(sales_rep.commission_value)

        # LOGGING
        with open('debug_comm_log.txt', 'a', encoding='utf-8') as f:
            f.write(f"\n--- DEBUG [{target_month_str}]: {sales_rep.fullname} ---\n")
            f.write(f"Monthly Sales: {monthly_sales}, Monthly Returns: {monthly_returns}, Net: {total_monthly_items}\n")
            f.write(f"Rate: {rate_per_item}\n")

        # 5. حذف التسويات القديمة (اللي ملهاش order_id) الخاصة بالشهر ده
        PartnerTransaction.query.filter(
            PartnerTransaction.partner_id == partner.id,
            PartnerTransaction.type == 'sub_commission',
            PartnerTransaction.order_id == None,
            PartnerTransaction.description.like(f"%{sales_rep.fullname}%"),
            PartnerTransaction.date >= target_month_start,
            PartnerTransaction.date < next_month
        ).delete(synchronize_session=False)

        # 6. تحديث فواتير الشهر
        monthly_orders = SaleOrder.query.filter(
            SaleOrder.user_id == sales_rep.id,
            SaleOrder.is_proforma == False,
            SaleOrder.is_reviewed == True,
            func.to_char(SaleOrder.date, 'YYYY-MM') == target_month_str
        ).all()

        total_month_comm = 0.0

        for order in monthly_orders:
            # أ) تنظيف القديم
            PartnerTransaction.query.filter(
                PartnerTransaction.order_id == order.id,
                PartnerTransaction.type.in_(['commission_gross', 'sub_commission'])
            ).delete(synchronize_session=False)

            # ب) حساب صافي الفاتورة
            gross_qty = sum(item.quantity for item in order.items)
            returned_qty = sum(ret.total_qty for ret in order.return_invoices) if order.return_invoices else 0
            net_qty = max(0, gross_qty - returned_qty)
            
            if net_qty <= 0: continue

            # ج) عمولة الشريك (Gross) - 14 جنيه ثابتة
            if partner.username not in ['Abo_Eyad', 'Abo_malek']:
                db.session.add(PartnerTransaction(
                    partner_id=partner.id,
                    order_id=order.id,
                    type='commission_gross',
                    amount=net_qty * 14.0,
                    date=order.date,
                    description=f"عمولة ({net_qty} قطعة) - فاتورة مبيعات ({sales_rep.fullname})"
                ))

            # د) عمولة الموظفة (تتخصم من الشريك)
            if sales_rep.id != partner.id and rate_per_item > 0:
                girl_comm = net_qty * rate_per_item
                total_month_comm += girl_comm
                
                add_split_partner_transaction(
                    partner_id=partner.id,
                    order_id=order.id,
                    type_val='sub_commission',
                    amount=-girl_comm,
                    description=f"عمولة ({sales_rep.fullname}) - فاتورة #{order.id} ({net_qty} قطعة × {rate_per_item})"
                )

        with open('debug_comm_log.txt', 'a', encoding='utf-8') as f:
            f.write(f"Total Month Commission: {total_month_comm}\n")

        db.session.commit()
        print(f"✅ Updated monthly commissions for Partner {partner.fullname} from Sales {sales_rep.fullname}")

    except Exception as e:
        db.session.rollback()
        print(f"❌ Error: {e}")

@app.route('/suppliers')
@permission_required('manage_inventory')
def suppliers():
    all_suppliers = Supplier.query.all()

    # حساب إجمالي المديونية (أي رصيد موجب يعتبر فلوس للمورد)
    total_debt = sum(s.balance for s in all_suppliers if s.balance > 0)

    return render_template('suppliers.html', suppliers=all_suppliers, total_debt=total_debt)
@app.route('/suppliers/add', methods=['POST'])
@permission_required('manage_inventory')
def add_supplier():
    name = request.form.get('name')
    phone = request.form.get('phone')
    if name:
        db.session.add(Supplier(name=name, phone=phone))
        db.session.commit()
        flash('تم إضافة المورد بنجاح ✅', 'success')
    else: flash('الاسم مطلوب', 'warning')
    return redirect(url_for('suppliers'))

@app.route('/supplier/edit/<int:id>', methods=['POST'])
@permission_required('manage_inventory')
def edit_supplier(id):
    supp = Supplier.query.get_or_404(id)
    supp.name = request.form.get('name')
    supp.phone = request.form.get('phone')
    db.session.commit()
    flash('تم التحديث', 'success')
    return redirect(url_for('suppliers'))

@app.route('/suppliers/<int:id>')
@permission_required('manage_inventory')
def supplier_profile(id):
    supp = Supplier.query.get_or_404(id)
    accounts = MoneyAccount.query.all()

    # === الإضافة الجديدة: حساب إجمالي عدد القطع ===
    # نقوم بجمع كميات الأصناف من كل فواتير الشراء الخاصة بهذا المورد
    total_items = db.session.query(func.sum(PurchaseItem.quantity))\
        .join(PurchaseOrder)\
        .filter(PurchaseOrder.supplier_id == id)\
        .scalar() or 0

    # === جلب مرتجعات الشراء الخاصة بهذا المورد ===
    purchase_returns = StockMovement.query.filter(
        StockMovement.reason.like(f'مرتجع شراء للمورد: {supp.name}%')
    ).order_by(StockMovement.timestamp.desc()).all()

    return render_template('supplier_profile.html',
                           supplier=supp,
                           orders=supp.orders,
                           payments=supp.payments,
                           accounts=accounts,
                           purchase_returns=purchase_returns,
                           total_items=int(total_items))
@app.route('/suppliers/return/delete/<int:move_id>', methods=['POST'])
@permission_required('manage_inventory')
def delete_purchase_return(move_id):
    move = StockMovement.query.get_or_404(move_id)
    # التأكد إن دي حركة مرتجع شراء
    if not move.reason or 'مرتجع شراء للمورد' not in move.reason:
        flash('هذه الحركة ليست مرتجع شراء!', 'danger')
        return redirect(url_for('suppliers'))

    # استخراج اسم المورد من السبب
    supplier_name = move.reason.replace('مرتجع شراء للمورد: ', '')
    supplier = Supplier.query.filter_by(name=supplier_name).first()

    # 1. إرجاع الكمية للمخزن
    if move.variant:
        move.variant.stock += abs(move.quantity_change)

    # 2. إرجاع القيمة لحساب المورد (زيادة المديونية)
    if supplier and move.variant:
        return_value = abs(move.quantity_change) * move.variant.cost_price
        supplier.balance += return_value

    # 3. حذف الحركة
    db.session.delete(move)
    db.session.commit()

    flash('تم حذف المرتجع وإرجاع الكمية للمخزن ✅', 'success')
    if supplier:
        return redirect(url_for('supplier_profile', id=supplier.id))
    return redirect(url_for('suppliers'))

@app.route('/suppliers/pay', methods=['POST'])
@permission_required('manage_inventory')
def add_supplier_payment():
    sid = request.form.get('supplier_id')
    try:
        amount = float(request.form.get('amount') or 0)
    except:
        amount = 0

    acc_id = request.form.get('account_id') # استقبال رقم الخزينة

    if amount <= 0:
        flash('يجب إدخال مبلغ صحيح', 'warning')
        return redirect(url_for('supplier_profile', id=sid))

    # التحقق من الخزينة
    account = MoneyAccount.query.get(acc_id)
    if not account:
        flash('يجب اختيار خزينة للسداد منها', 'danger')
        return redirect(url_for('supplier_profile', id=sid))

    # معالجة الصورة
    fname = None
    if 'receipt_image' in request.files and request.files['receipt_image'].filename:
        fname = secure_filename(request.files['receipt_image'].filename)
        save_uploaded_file(request.files['receipt_image'], fname)

    # 1. تسجيل عملية السداد للمورد
    payment = SupplierPayment(
        supplier_id=sid,
        amount=amount,
        receipt_image=fname,
        notes=request.form.get('notes'),
        account_id=account.id # ربطها بالخزنة
    )
    db.session.add(payment)

    # 2. تقليل مديونية المورد
    supplier = Supplier.query.get(sid)
    supplier.balance -= amount

    # 3. خصم المبلغ من الخزينة المختارة وتسجيل حركة مالية
    account.balance = round_half(account.balance - amount)

    db.session.add(FinancialTransaction(
        type='expense', # مصروف
        category='سداد موردين',
        amount=-amount, # بالسالب
        description=f"سداد دفعة للمورد ({supplier.name})",
        date=cairo_now(),
        created_by_id=current_user.id,
        account_id=account.id
    ))

    db.session.commit()
    flash(f'تم تسجيل السداد وخصم {amount} من {account.name} ✅', 'success')
    return redirect(url_for('supplier_profile', id=sid))
# === تقرير تفاصيل المصروفات الشامل ===
@app.route('/expenses/details')
@general_manager_required
def expenses_details():
    # 1. استقبال فلاتر التاريخ (الافتراضي: الشهر الحالي)
    today = date.today()
    default_start = today.replace(day=1).strftime('%Y-%m-%d')
    default_end = today.strftime('%Y-%m-%d')

    start_date = request.args.get('start_date', default_start)
    end_date = request.args.get('end_date', default_end)
    category_filter = request.args.get('category_id', 'all')

    # 2. الاستعلام الأساسي (فلترة بالتاريخ)
    query = Expense.query.filter(
        cast(Expense.date, Date) >= start_date,
        cast(Expense.date, Date) <= end_date
    ).order_by(Expense.date.desc())

    # 3. تطبيق فلتر التصنيف
    if category_filter != 'all':
        query = query.filter(Expense.category_id == category_filter)

    expenses = query.all()

    # 4. حساب الإجماليات
    total_amount = sum(e.amount for e in expenses)

    # 5. البيانات المساعدة للقوائم
    categories = ExpenseCategory.query.all()

    return render_template('expenses_details.html',
                           expenses=expenses,
                           total_amount=total_amount,
                           categories=categories,
                           start_date=start_date,
                           end_date=end_date,
                           selected_cat=category_filter)
# 1. نعدل دالة العرض عشان نبعت الخزائن للصفحة
@app.route('/shipping/orders')
@login_required
def shipping_dashboard():
    # التحقق من صلاحية الرؤية
    if not current_user.has_perm('view_shipping') and current_user.emp_code != 'EMP201':
        flash('غير مصرح لك', 'danger')
        return redirect(url_for('dashboard'))

    # شيماء (SHIMAA01) أو EMP201 يشوفوا كل فواتير الشحن بدون فلتر
    if current_user.username in ['SHIMAA01', 'Abo_malek'] or current_user.emp_code == 'EMP201' or current_user.role == 'general_manager':
        orders = SaleOrder.query.filter(
            SaleOrder.is_shipping == True,
            SaleOrder.shipping_status.in_(['none', 'pending', 'shipped', 'delivered', 'returned'])
        ).order_by(SaleOrder.date.desc()).all()
    else:
        # باقي المستخدمين يشوفوا بتاعهم بس (أو فريقهم لو مدير فريق)
        accessible_ids = get_accessible_users()
        orders = SaleOrder.query.filter(
            SaleOrder.is_shipping == True,
            SaleOrder.user_id.in_(accessible_ids),
            SaleOrder.shipping_status.in_(['none', 'pending', 'shipped', 'delivered', 'returned'])
        ).order_by(SaleOrder.date.desc()).all()

    total_pending = sum(o.amount_due for o in orders if o.shipping_status in ['none', 'pending', 'shipped', 'delivered', 'returned'])

    return render_template('shipping_dashboard.html',
                         orders=orders,
                         total_pending=total_pending,
                         companies=ShippingCompany.query.all(),
                         accounts=MoneyAccount.query.all())

# 2. نعدل دالة التحديث عشان تسجل الفلوس
@app.route('/shipping/update/<int:id>', methods=['POST'])
@login_required
def update_shipping(id):
    # السماح بالدخول لو يملك الصلاحية أو لو كان كوده EMP201
    if not current_user.has_perm('manage_shipping') and current_user.emp_code != 'EMP201':
        flash('غير مصرح لك بإدارة الشحن', 'warning')
        return redirect(request.referrer)

    order = SaleOrder.query.get_or_404(id)
    action = request.form.get('action')

    # ... (باقي الحالات: save_note, set_waybill, edit_waybill, mark_delivered زي ما هي بدون تغيير) ...
    if action == 'save_note':
        order.shipping_notes = request.form.get('note')
        flash('تم حفظ الملاحظة بنجاح 📝', 'success')

    elif action == 'set_waybill':
        order.waybill_no = request.form.get('waybill_no')
        order.shipping_status = 'shipped'
        flash('تم تسجيل خروج الشحنة ✅', 'success')

    elif action == 'edit_waybill':
        new_waybill = request.form.get('waybill_no')
        if new_waybill:
            order.waybill_no = new_waybill
            flash('تم تصحيح رقم البوليصة بنجاح ✏️', 'success')

    elif action == 'mark_delivered':
        if order.shipping_status != 'delivered' and order.shipping_status != 'settled':
            order.shipping_status = 'delivered'
            
            # --- Update Customer Balance ---
            if order.amount_due > 0 and order.customer_id:
                customer = Customer.query.get(order.customer_id)
                if customer:
                    customer.balance = round_half((customer.balance or 0) - order.amount_due)
                    waybill_str = order.waybill_no or "بدون بوليصة"
                    payment_note = f'سداد استلام شحنة بوليصة {waybill_str} (الدفع عند الاستلام)'
                    customer_payment = CustomerPayment(
                        customer_id=customer.id,
                        amount=order.amount_due,
                        account_id=None,
                        notes=payment_note
                    )
                    db.session.add(customer_payment)

            flash('تم توصيل الشحنة للعميل وتسوية مديونيته 🚚', 'success')
        
    elif action == 'undo_delivered':
        if order.shipping_status == 'delivered':
            order.shipping_status = 'shipped'
            
            # --- Revert Customer Balance ---
            if order.amount_due > 0 and order.customer_id:
                customer = Customer.query.get(order.customer_id)
                if customer:
                    customer.balance = round_half((customer.balance or 0) + order.amount_due)
                    waybill_str = order.waybill_no or "بدون بوليصة"
                    note_match = f'%سداد استلام شحنة بوليصة {waybill_str} (الدفع عند الاستلام)%'
                    payment = CustomerPayment.query.filter(CustomerPayment.customer_id == customer.id, CustomerPayment.notes.like(note_match)).first()
                    if payment:
                        db.session.delete(payment)
            
            flash('تم التراجع: الشحنة الآن مسجلة كـ قيد التوصيل وتم إعادة مديونية العميل 🚚', 'warning')

    # === التعديل الجذري هنا (التحصيل) ===
    elif action == 'settle':
        was_delivered = (order.shipping_status == 'delivered')
        if order.shipping_status == 'settled':
            flash('تم التحصيل مسبقاً!', 'warning')
            return redirect(request.referrer)

        account_id = request.form.get('account_id')
        account = MoneyAccount.query.get(account_id) if account_id else None

        # 1. جلب المبلغ المحصل من الفورم (أو إجمالي الفاتورة لو مش موجود)
        raw_collected = request.form.get('amount_collected')
        
        # التعديل: لو الفاتورة مرتجعة، المديونية بتكون نزلت لصفر، بس المفروض نحصل الإجمالي الأصلي (اللي شركة الشحن أخدته)
        if order.shipping_status == 'returned':
            original_due = order.final_total - order.paid_upfront
        else:
            original_due = order.amount_due

        amount_collected = float(raw_collected) if raw_collected else original_due
        
        # لو المبلغ صفر أو سالب — تسوية مباشرة بدون خزينة
        if amount_collected <= 0:
            order.amount_due = 0
            order.shipping_status = 'settled'
            db.session.commit()
            flash('تم تسوية الشحنة (العميل دافع بالكامل) ✅', 'success')
            return redirect(request.referrer)

        if not account:
            flash('يجب اختيار خزينة لإيداع المبلغ!', 'danger')
            return redirect(request.referrer)
        
        if amount_collected < 0:
            flash('لا يمكن تحصيل مبلغ بالسالب', 'danger')
            return redirect(request.referrer)
            
        # Add small margin for float comparison
        if amount_collected > original_due + 0.1:
            flash(f'لا يمكن تحصيل مبلغ أكبر من المتبقي ({original_due})', 'danger')
            return redirect(request.referrer)
            
        # حساب العمولة الإضافية لشركة الشحن (الخصم الذي تحملته الشركة لإعفاء العميل)
        extra_commission = original_due - amount_collected if original_due > amount_collected else 0.0

        company = ShippingCompany.query.get(order.shipping_company_id)
        calculated_fee = 0.0

        if company and amount_collected > 0:
            calculated_fee += company.fee_first_1k
            if amount_collected > 1000:
                extra_amount = amount_collected - 1000
                thousands_count = math.ceil(extra_amount / 1000)
                calculated_fee += thousands_count * company.fee_extra_1k

        net_income = amount_collected - calculated_fee

        # 2. الفاتورة تعتبر خالصة بالكامل للعميل
        order.amount_due = 0
        order.shipping_fee = calculated_fee + extra_commission # الفارق يضاف كمصروف شحن على الشركة
        order.shipping_status = 'settled'

        # 3. تحديث حساب العميل وتسجيل الدفعة (لو لم يتم التوصيل مسبقاً فقط)
        # ولا نقوم بتسجيل دفعة إذا كانت الفاتورة مرتجعة (لأن الدورة المالية الخاصة بالمرتجع تولت ذلك)
        if not was_delivered and order.shipping_status != 'returned' and original_due > 0 and order.customer_id:
            customer = Customer.query.get(order.customer_id)
            if customer:
                # تقليل مديونية العميل بكامل الفاتورة وليس المحصل فقط
                customer.balance = round_half((customer.balance or 0) - original_due)
                
                # تسجيل حركة "دفعة عميل" عشان تظهر في بروفايله
                payment_note = f'سداد استلام شحنة بوليصة {order.waybill_no} (سداد كلي)'
                    
                customer_payment = CustomerPayment(
                    customer_id=customer.id,
                    amount=original_due,
                    account_id=account.id,
                    notes=payment_note
                )
                db.session.add(customer_payment)

        # 4. إيداع الصافي في الخزينة
        if net_income > 0:
            account.balance = round_half(account.balance + net_income)
            
            trans_desc = f"تحصيل شحنة بوليصة {order.waybill_no} (العميل: {order.customer.name})"
                
            db.session.add(FinancialTransaction(
                account_id=account.id,
                type='income',
                category='تحصيل شحن',
                amount=net_income,
                description=trans_desc,
                created_by_id=current_user.id,
                date=cairo_now()
            ))
            flash(f'تم التحصيل وإيداع الصافي ({net_income} ج.م) في {account.name} ✅', 'success')
        elif net_income < 0:
            # لو مصاريف الشحن أكبر من المبلغ المحصل
            account.balance = round_half(account.balance + net_income) # هنا هنطرح من الخزنة
            db.session.add(FinancialTransaction(
                account_id=account.id,
                type='expense',
                category='مصاريف شحن',
                amount=abs(net_income),
                description=f"مصاريف إضافية لشحنة بوليصة {order.waybill_no} (التحصيل أقل من تكلفة الشحن)",
                created_by_id=current_user.id,
                date=cairo_now()
            ))
            flash(f'تم التسوية. مصاريف الشحن تجاوزت المحصل. تم خصم ({abs(net_income)} ج.م) من {account.name} ⚠️', 'warning')
        else:
            flash('تم تسوية الشحنة (المحصل يغطي مصاريف الشحن فقط)', 'warning')

        # 5. تسجيل عمولة شركة الشحن الإضافية كمصروف على الشركاء (50/50)
        if extra_commission > 0:
            waybill_str = order.waybill_no or "بدون بوليصة"
            customer_name = order.customer.name if order.customer else "عميل"
            share_per_partner = round_half(extra_commission / 2.0)
            for partner_id in [1, 3]:
                db.session.add(PartnerTransaction(
                    partner_id=partner_id,
                    order_id=order.id,
                    type='shipping_extra_commission',
                    amount=-share_per_partner,
                    description=f'عمولة شركة شحن إضافية - بوليصة {waybill_str} ({customer_name}) - الفارق {extra_commission} ج.م',
                    date=cairo_now()
                ))

    db.session.commit()
    return redirect(request.referrer)
@app.route('/shipping/companies', methods=['GET', 'POST'])
@permission_required('manage_shipping')
def shipping_companies():
    if request.method == 'POST':
        name = request.form.get('name')
        phone = request.form.get('phone')
        try:
            fee_first = float(request.form.get('fee_first') or 0)
            fee_extra = float(request.form.get('fee_extra') or 0)
        except ValueError:
            fee_first = 0.0
            fee_extra = 0.0
        if name:
            db.session.add(ShippingCompany(name=name, phone=phone, cs_number="-", fee_first_1k=fee_first, fee_extra_1k=fee_extra))
            db.session.commit()
            flash('تم حفظ شركة الشحن ونظام التحصيل ✅', 'success')
        else: flash('اسم الشركة مطلوب', 'warning')
        return redirect(url_for('shipping_companies'))
    return render_template('shipping_companies.html', companies=ShippingCompany.query.all())

@app.route('/shipping/company/edit/<int:id>', methods=['POST'])
@permission_required('manage_shipping')
def edit_shipping_company(id):
    comp = ShippingCompany.query.get_or_404(id)
    comp.name = request.form.get('name')
    comp.phone = request.form.get('phone')
    try:
        comp.fee_first_1k = float(request.form.get('fee_first') or 0)
        comp.fee_extra_1k = float(request.form.get('fee_extra') or 0)
    except: pass
    db.session.commit()
    flash('تم تعديل البيانات بنجاح ✅', 'success')
    return redirect(url_for('shipping_companies'))

@app.route('/shipping/company/delete/<int:id>')
@permission_required('manage_shipping')
def delete_shipping_company(id):
    comp = ShippingCompany.query.get_or_404(id)
    if comp.orders: flash('لا يمكن الحذف', 'warning')
    else: db.session.delete(comp); db.session.commit(); flash('تم', 'success')
    return redirect(url_for('shipping_companies'))

@app.route('/shipping/company/<int:id>')
@permission_required('manage_shipping')
def shipping_company_profile(id):
    company = ShippingCompany.query.get_or_404(id)
    orders = SaleOrder.query.filter_by(shipping_company_id=id).order_by(SaleOrder.date.desc()).all()
    pending = sum(o.amount_due for o in orders if o.shipping_status in ['shipped', 'delivered'])
    collected = sum(o.amount_due for o in orders if o.shipping_status == 'settled')
    return render_template('shipping_company_profile.html', company=company, orders=orders, total_orders=len(orders), pending_money=pending, collected_money=collected)



@app.route('/treasury/view')
@general_manager_required
def treasury_report():
    accounts = MoneyAccount.query.all()
    total_balance = sum(acc.balance for acc in accounts)
    recent_transactions = FinancialTransaction.query.order_by(FinancialTransaction.date.desc()).limit(50).all()
    return render_template('treasury.html', accounts=accounts, total_balance=total_balance, transactions=recent_transactions)
@app.route('/api/process_order', methods=['POST'])
@login_required
def process_order():
    data = request.get_json()

    # 1. استلام البيانات الأساسية
    cart = data.get('cart', [])
    payments = data.get('payments', []) # قائمة الدفعات [{'account_id': 1, 'amount': 100}, ...]
    customer_id = data.get('customer_id')
    packer_id = data.get('packer_id') or None
    is_proforma = data.get('is_proforma', False)
    is_shipping = data.get('is_shipping', False)
    shipping_company_id = data.get('shipping_company_id')
    is_office = data.get('is_office_invoice', False) # فاتورة المكتب (تكلفة + 5)
    manual_shipping_fee = float(data.get('shipping_fee') or 0)
    shipping_paid_by = data.get('shipping_paid_by', 'customer')  # 'customer' or 'manager'

    # معالجة التاريخ
    date_str = data.get('date')
    if date_str:
        try: order_date = datetime.strptime(date_str, '%Y-%m-%dT%H:%M')
        except ValueError: order_date = cairo_now()
    else: order_date = cairo_now()

    discount = float(data.get('discount') or 0)

    # === [أ] معالجة تعديل المسودة (حذف القديم) ===
    old_order_id = data.get('old_order_id')
    if old_order_id:
        old_order = SaleOrder.query.get(old_order_id)
        # شرط أمان: نحذف فقط لو كانت مسودة، عشان منمسحش فاتورة حقيقية بالغلط
        if old_order and old_order.is_proforma:
            SaleItem.query.filter_by(order_id=old_order.id).delete()
            db.session.delete(old_order)
            db.session.flush() # تنفيذ الحذف فوراً لتفريغ البضاعة المحجوزة نظرياً

    # === [ب] التحقق من المخزون (لو مش عرض سعر) ===
    if not is_proforma:
        for item in cart:
            qty_needed = int(item['qty'])
            if qty_needed <= 0: continue

            var = ProductVariant.query.get(item['id'])
            if not var:
                return jsonify({'error': f'المنتج كود {item["id"]} غير موجود'}), 400

            if var.stock < qty_needed:
                return jsonify({'error': f'عفواً، الكمية غير كافية للمنتج: {var.model.name} (المتاح: {var.stock})'}), 400

    # === [ج] تحديد البائع الفعلي ===
    actual_seller_id = current_user.id
    # لو المدير بيسجل باسم موظف تاني
    if current_user.role in ['manager', 'general_manager'] and data.get('sales_rep_id'):
        try: actual_seller_id = int(data.get('sales_rep_id'))
        except: pass

    seller_user = User.query.get(actual_seller_id)
    seller_code = seller_user.emp_code if seller_user else ""

    # === [د] حساب إجمالي المدفوع ===
    paid_upfront = sum(float(p.get('amount', 0)) for p in payments)
    
    # تصحيح: عروض السعر لا يجب أن تحتوي على مدفوعات
    if is_proforma:
        paid_upfront = 0
        payments = [] # تفريغ القائمة لمنع المعالجة اللاحقة
        
    # === [هـ] إنشاء الأوردر ===
    # تكلفة الشحن اليدوية
    customer_shipping = manual_shipping_fee if shipping_paid_by == 'customer' else 0.0
    manager_shipping  = manual_shipping_fee if shipping_paid_by == 'manager'  else 0.0

    order = SaleOrder(
        user_id=actual_seller_id,
        customer_id=customer_id,
        packer_id=packer_id,
        date=order_date,
        is_shipping=is_shipping,
        shipping_company_id=shipping_company_id,
        shipping_fee=manual_shipping_fee,
        shipping_paid_by=shipping_paid_by,
        paid_upfront=paid_upfront,
        is_proforma=is_proforma,
        discount=discount,
        sales_rep_code=seller_code
    )
    db.session.add(order)
    db.session.flush() # للحصول على ID الفاتورة

    total_amount = 0

    # === [و] إضافة المنتجات وحساب الأسعار ===
    for item in cart:
        qty = int(item['qty'])
        if qty <= 0: continue

        variant = ProductVariant.query.get(item['id'])

        # منطق التسعير (مكتب vs عادي)
        if is_office and (current_user.role == 'general_manager' or current_user.username == 'Abo_malek'):
            unit_price = (variant.cost_price or 0) + 5
        else:
            unit_price = float(item['price'])

        item_total = unit_price * qty
        total_amount += item_total

        # إضافة البند للفاتورة
        db.session.add(SaleItem(
            order_id=order.id,
            variant_id=item['id'],
            quantity=qty,
            unit_price=unit_price,
            total_price=item_total
        ))

        # خصم المخزون (لو مش عرض سعر)
        if not is_proforma:
            variant.stock -= qty
            db.session.add(StockMovement(
                variant_id=variant.id,
                user_id=current_user.id,
                quantity_change=-qty,
                reason=f"بيع فاتورة #{order.id}"
            ))

    # === [ز] تحديث مجاميع الفاتورة والعميل ===
    order.total_amount = total_amount
    # لو الشحن على العميل، يتضاف للمجموع النهائي
    order.final_total = total_amount - discount + customer_shipping
    raw_amount_due = round_half(order.final_total - paid_upfront)
    order.amount_due = max(0, raw_amount_due)
    overpayment = abs(raw_amount_due) if raw_amount_due < 0 else 0

    # حالة الشحن
    if is_proforma: order.shipping_status = 'proforma'
    elif is_shipping: order.shipping_status = 'none' # عشان تظهر في لوحة الشحن
    else: order.shipping_status = 'settled'

    # تحديث رصيد العميل (إضافة المديونية)
    if not is_proforma and customer_id:
        customer = Customer.query.get(customer_id)
        if customer:
            if order.amount_due > 0:
                customer.balance = (customer.balance or 0) + order.amount_due
            if overpayment > 0:
                customer.balance = (customer.balance or 0) - overpayment

    # === [ح] معالجة الدفعات المالية (Payments Loop) ===
    payment_errors = []
    if not is_proforma and payments:
        for pay in payments:
            try:
                amt = float(pay.get('amount', 0))
                acc_id_raw = pay.get('account_id')
                
                if amt > 0:
                    if acc_id_raw == 'credit':
                        # الدفع من رصيد العميل
                        if customer_id:
                            cust = Customer.query.get(customer_id)
                            if cust:
                                cust.balance = round_half(float(cust.balance or 0) + amt)
                                db.session.add(FinancialTransaction(
                                    type='income', # or 'neutral' if you prefer
                                    category='خصم من الرصيد',
                                    amount=amt,
                                    description=f"سداد جزء من فاتورة #{order.id} عبر خصم من رصيد العميل الدائن",
                                    date=cairo_now(),
                                    created_by_id=current_user.id
                                ))
                        continue # تخطي باقي اللوب الخاصة بالخزينة
                        
                acc_id = int(acc_id_raw) if acc_id_raw else None

                if amt > 0:
                    if not acc_id:
                        default_acc = MoneyAccount.query.first()
                        acc_id = default_acc.id if default_acc else None

                    account = MoneyAccount.query.get(acc_id)
                    if account:
                        account.balance = round_half(account.balance + amt)

                        db.session.add(FinancialTransaction(
                            type='income',
                            category='مبيعات',
                            amount=amt,
                            description=f"تحصيل فاتورة #{order.id} (دفعة) - {order.customer.name if order.customer else 'عميل نقدي'}",
                            date=cairo_now(),
                            created_by_id=current_user.id,
                            account_id=account.id
                        ))
                    else:
                        payment_errors.append(f"خزينة ID={acc_id} غير موجودة")
            except Exception as e:
                payment_errors.append(str(e))

    if payment_errors:
        db.session.rollback()
        return jsonify({'error': f"خطأ في تسجيل الدفعات: {', '.join(payment_errors)}"}), 400

    # === [ح2] تسجيل تكلفة الشحن على المدير كمصروف ===
    if not is_proforma and manager_shipping > 0:
        manager_user = User.query.get(actual_seller_id)
        # لو البائع موظف مبيعات، خصم الشحن من مصاريف المدير التابع له
        target_manager = manager_user.manager if (manager_user and manager_user.manager) else manager_user
        db.session.add(FinancialTransaction(
            type='expense',
            category='مصاريف شحن',
            amount=manager_shipping,
            description=f"تكلفة شحن فاتورة #{order.id} - {order.customer.name if order.customer else ''} (مدير: {target_manager.fullname if target_manager else ''})",
            date=cairo_now(),
            created_by_id=current_user.id
        ))

    # === [ط] تسجيل العمولات والخصومات (على الشركاء) ===
    if not is_proforma:
        # تحديد الشريك المسؤول (المدير المباشر)
        partner = None
        if seller_user.role == 'manager': partner = seller_user
        elif seller_user.manager_id:
            mgr = User.query.get(seller_user.manager_id)
            if mgr and mgr.role == 'manager': partner = mgr

        # 1. تسجيل عمولة الشريك (14ج عن القطعة مثلاً) - حسب منطقك
        # هنا بنحسب عدد القطع الكلي
        total_items_qty = sum(int(item['qty']) for item in cart)
        if partner and partner.username not in ['Abo_Eyad', 'Abo_malek']:
             db.session.add(PartnerTransaction(
                partner_id=partner.id,
                order_id=order.id,
                type='commission_gross',
                amount=total_items_qty * 14.0, # العمولة الثابتة للشريك
                date=order.date,
                description=f"عمولة ({total_items_qty} قطعة) - فاتورة #{order.id}"
            ))

        # 2. خصم التخفيض من الشريك
        if partner and discount > 0:
            add_split_partner_transaction(
                partner_id=partner.id,
                order_id=order.id,
                type_val='discount_deduction',
                amount=-discount,
                description=f"خصم ممنوح للعميل - فاتورة #{order.id}"
            )

        # 3. تحديث عمولة السيلز (تراكمي الشهر)
        # (يتم استدعاء دالة التحديث الخارجية لضمان دقة الشرائح)
        update_monthly_commissions(actual_seller_id, order_date)

    db.session.commit()
    return jsonify({'success': True, 'order_id': order.id})
@app.route('/shipping/daily_report')
@login_required
def shipping_daily_report():
    if not current_user.has_perm('view_shipping') and current_user.emp_code != 'EMP201':
        return "غير مصرح لك", 403

    # 1. تحديد نطاق التاريخ (الافتراضي: من أول الشهر الحالي لحد النهاردة)
    today = date.today()
    default_start = today.replace(day=1).strftime('%Y-%m-%d')
    default_end = today.strftime('%Y-%m-%d')

    start_date = request.args.get('start_date', default_start)
    end_date = request.args.get('end_date', default_end)

    # 2. جلب حركات التحصيل من الخزينة (تحصيل شحن) في الفترة المحددة
    #    هذه هي الحركات الفعلية التي تمت عند الضغط على "تحصيل" في صفحة الشحن
    settle_transactions = FinancialTransaction.query.filter(
        FinancialTransaction.category == 'تحصيل شحن',
        cast(FinancialTransaction.date, Date) >= start_date,
        cast(FinancialTransaction.date, Date) <= end_date
    ).order_by(FinancialTransaction.date.desc()).all()

    # 3. تجهيز البيانات
    report_data = []
    totals = {
        'total_collected': 0.0,
        'total_fees': 0.0,
        'total_net': 0.0,
        'total_extra_commission': 0.0
    }

    # نمر على كل حركة تحصيل ونجيب الفاتورة المرتبطة بها من الوصف
    for tx in settle_transactions:
        # استخراج رقم البوليصة من الوصف
        import re as _re
        waybill_match = _re.search(r'بوليصة\s+(\S+)', tx.description or '')
        waybill_no = waybill_match.group(1) if waybill_match else '---'
        
        # محاولة إيجاد الفاتورة المرتبطة عن طريق رقم البوليصة
        order = SaleOrder.query.filter(
            SaleOrder.is_shipping == True,
            SaleOrder.waybill_no == waybill_no
        ).first() if waybill_no != '---' else None
        
        customer_name = '---'
        original_due = 0.0
        shipping_fee = 0.0
        extra_commission = 0.0
        
        if order:
            customer_name = order.customer.name if order.customer else 'عميل نقدي'
            shipping_fee = order.shipping_fee or 0.0
            # المبلغ الأصلي = الصافي المودع + رسوم الشحن
            original_due = tx.amount + shipping_fee
            
            # حساب عمولة شركة الشحن الإضافية (الفارق)
            extra_comm_tx = PartnerTransaction.query.filter(
                PartnerTransaction.order_id == order.id,
                PartnerTransaction.type == 'shipping_extra_commission'
            ).first()
            if extra_comm_tx:
                extra_commission = abs(extra_comm_tx.amount) * 2  # المبلغ الكامل (مقسوم على شريكين)
        else:
            # لو مش لاقي الفاتورة نستخدم بيانات الحركة المالية
            customer_match = _re.search(r'\(العميل:\s*(.+?)\)', tx.description or '')
            customer_name = customer_match.group(1) if customer_match else '---'
            original_due = tx.amount
        
        net_income = tx.amount  # الصافي المودع في الخزينة

        report_data.append({
            'date': tx.date.strftime('%Y-%m-%d') if tx.date else '---',
            'waybill': waybill_no,
            'customer': customer_name,
            'collected': round_half(original_due),
            'fee': round_half(shipping_fee),
            'extra_commission': round_half(extra_commission),
            'net': round_half(net_income),
            'account': tx.account.name if tx.account else '---'
        })

        totals['total_collected'] += original_due
        totals['total_fees'] += shipping_fee
        totals['total_extra_commission'] += extra_commission
        totals['total_net'] += net_income

    # تقريب الإجماليات
    for k in totals:
        totals[k] = round_half(totals[k])

    return render_template('shipping_daily_report.html',
                           orders=report_data,
                           totals=totals,
                           start_date=start_date,
                           end_date=end_date)
@app.route('/customers/pay', methods=['POST'])
@general_manager_required
def add_customer_payment():
    try:
        cid = request.form.get('customer_id')
        amount = float(request.form.get('amount') or 0)
        acc_id = request.form.get('account_id')
        notes = request.form.get('notes', '')
        order_id = request.form.get('order_id')  # فاتورة محددة (اختياري)

        customer = Customer.query.get_or_404(cid)
        account = MoneyAccount.query.get_or_404(acc_id)

        if amount <= 0:
            flash('يجب إدخال مبلغ أكبر من الصفر', 'warning')
            return redirect(url_for('customer_profile', id=cid))

        # 1. خصم المبلغ من مديونية العميل
        customer.balance = (customer.balance or 0) - amount

        # 2. زيادة رصيد الخزينة المختارة
        account.balance = (account.balance or 0) + amount

        # 3. لو فيه فاتورة محددة - نطرح منها المبلغ
        linked_order = None
        if order_id:
            linked_order = SaleOrder.query.get(int(order_id))
            if linked_order and linked_order.customer_id == int(cid):
                linked_order.amount_due = round_half(max((linked_order.amount_due or 0) - amount, 0))

        # 4. تسجيل دفعة العميل في جدول المدفوعات
        payment = CustomerPayment(
            customer_id=cid,
            amount=amount,
            account_id=acc_id,
            notes=notes
        )
        db.session.add(payment)

        # 4. تسجيل حركة مالية (إيراد) في سجلات الخزينة العامة
        invoice_ref = f' (حساب فاتورة {linked_order.id})' if linked_order else ''
        db.session.add(FinancialTransaction(
            account_id=acc_id,
            type='income',
            category='تحصيل مديونية',
            amount=amount,
            description=f"تحصيل من حساب العميل: {customer.name}{invoice_ref} ({notes})",
            created_by_id=current_user.id,
            date=cairo_now()
        ))

        db.session.commit()
        flash(f'تم تحصيل {amount} ج.م وإضافتها لـ {account.name} بنجاح ✅', 'success')
        return redirect(url_for('customer_profile', id=cid))
    except Exception as e:
        db.session.rollback()
        flash(f'حدث خطأ أثناء العملية: {str(e)}', 'danger')
        return redirect(url_for('customer_profile', id=cid))

@app.route('/customers/refund', methods=['POST'])
@general_manager_required
def customer_refund():
    """رد مبلغ للعميل من الخزينة (لما العميل يكون ليه فلوس عندنا)"""
    try:
        cid = request.form.get('customer_id')
        amount = float(request.form.get('amount') or 0)
        acc_id = request.form.get('account_id')
        notes = request.form.get('notes', '')

        customer = Customer.query.get_or_404(cid)
        account = MoneyAccount.query.get_or_404(acc_id)

        if amount <= 0:
            flash('يجب إدخال مبلغ أكبر من الصفر', 'warning')
            return redirect(url_for('customer_profile', id=cid))

        if amount > account.balance:
            flash(f'رصيد الخزينة غير كافي! المتاح: {account.balance} ج.م', 'danger')
            return redirect(url_for('customer_profile', id=cid))

        # 1. زيادة مديونية العميل (تقليل السالب)
        customer.balance = round_half((customer.balance or 0) + amount)

        # 2. خصم من رصيد الخزينة
        account.balance = round_half((account.balance or 0) - amount)

        # 3. تسجيل حركة مالية (مصروف - رد للعميل)
        db.session.add(FinancialTransaction(
            account_id=acc_id,
            type='expense',
            category='رد مبلغ لعميل',
            amount=-amount,
            description=f"رد مبلغ للعميل: {customer.name} ({notes})",
            created_by_id=current_user.id,
            date=cairo_now()
        ))

        db.session.commit()
        flash(f'تم رد {amount} ج.م للعميل {customer.name} من خزينة {account.name} بنجاح ✅', 'success')
        return redirect(url_for('customer_profile', id=cid))
    except Exception as e:
        db.session.rollback()
        flash(f'حدث خطأ: {str(e)}', 'danger')
        return redirect(url_for('customer_profile', id=cid))

@app.route('/customers/adjust_balance', methods=['POST'])
@general_manager_required
def adjust_customer_balance():
    try:
        cid = request.form.get('customer_id')
        new_balance = float(request.form.get('new_balance'))
        secure_pin = request.form.get('secure_pin')
        
        # الرقم السري المطلوب
        if secure_pin != '1712':
            flash('الرقم السري غير صحيح. لم يتم التعديل.', 'danger')
            return redirect(url_for('customer_profile', id=cid))
            
        customer = Customer.query.get_or_404(cid)
        old_balance = customer.balance or 0
        
        # التعديل الفعلي
        customer.balance = new_balance
        
        # تسجيل الحركة في الخزينة بصفر للتسوية أو مجرد ملاحظة بس من غير أرصدة (Optional)
        # المستخدم طلب "متسمعش في اي خزينة" فمش هنضيف FinancialTransaction ولا نعدل خزنة.
        
        db.session.commit()
        flash(f'تم تعديل المديونية بنجاح من {old_balance} إلى {new_balance} ج.م', 'success')
        return redirect(url_for('customer_profile', id=cid))
        
    except Exception as e:
        db.session.rollback()
        flash(f'خطأ أثناء التعديل اليدوي: {str(e)}', 'danger')
        return redirect(url_for('customer_profile', id=cid))

@app.route('/invoice/print/<int:id>')
@login_required
def print_invoice(id):
    order = SaleOrder.query.get_or_404(id)
    # الحصول على كل الموظفين لاستخدامهم في النافذة المنبثقة لتغيير المُعبئ
    all_employees = User.query.all()
    # الحصول على كل المنتجات للبحث في نافذة إضافة صنف
    all_variants = ProductVariant.query.filter(ProductVariant.stock > 0).all()
    
    # جلب تفاصيل دفع الإيصال (الخزائن اللي استلمت الفلوس) - تشمل الدفعات الأولية والإضافية
    transactions = FinancialTransaction.query.filter(
        db.or_(
            FinancialTransaction.description.like(f"%تحصيل فاتورة #{order.id} (دفعة)%"),
            FinancialTransaction.description.like(f"%دفعة إضافية على فاتورة #{order.id}%"),
            FinancialTransaction.description.like(f"%حساب فاتورة {order.id}%")
        ),
        FinancialTransaction.amount > 0
    ).all()
    
    # الخزائن المتاحة (لنافذة الدفعة الإضافية)
    accounts = MoneyAccount.query.all()
    # شركات الشحن (لنافذة تحويل الفاتورة لشحن)
    couriers = ShippingCompany.query.all()
    
    # جلب تفاصيل المرتجعات (القطع المرتجعة بالتفصيل)
    return_details = []
    if order.return_invoices:
        returned_movements = StockMovement.query.filter(
            db.or_(
                StockMovement.reason == f"مرتجع فاتورة #{order.id}",
                StockMovement.reason.like(f"مرتجع #% فاتورة #{order.id}")
            ),
            StockMovement.quantity_change > 0
        ).all()
        for mv in returned_movements:
            sale_item = next((si for si in order.items if si.variant_id == mv.variant_id), None)
            unit_price = sale_item.unit_price if sale_item else 0
            return_details.append({
                'name': mv.variant.model.name if mv.variant else '---',
                'variant_id': mv.variant_id,
                'qty': mv.quantity_change,
                'unit_price': unit_price,
                'total': mv.quantity_change * unit_price,
                'date': mv.timestamp
            })

    return render_template('invoice.html', order=order, all_employees=all_employees, all_variants=all_variants, transactions=transactions, accounts=accounts, couriers=couriers, return_details=return_details)

@app.route('/invoice/<int:id>/change_packer', methods=['POST'])
@login_required
def change_packer(id):
    order = SaleOrder.query.get_or_404(id)
    if order.is_proforma:
        flash('لا يمكن تعديل هذه الفاتورة من هنا.', 'danger')
        return redirect(url_for('print_invoice', id=id))

    packer_id = request.form.get('packer_id')
    if packer_id:
        order.packer_id = packer_id
        db.session.commit()
        flash('تم تعديل المعبئ بنجاح', 'success')
    return redirect(url_for('print_invoice', id=id))

@app.route('/invoice/<int:id>/add_item', methods=['POST'])
@login_required
def invoice_add_item(id):
    # التحقق من صلاحية تعديل الفاتورة (المدير العام دايماً مسموح)
    if current_user.role != 'general_manager' and not current_user.has_perm('edit_invoice'):
        flash('غير مصرح لك بتعديل أصناف الفاتورة', 'danger')
        return redirect(url_for('print_invoice', order_id=id))

    order = SaleOrder.query.get_or_404(id)
    if order.is_proforma:
        flash('لا يمكن التعديل من هنا، استخدم شاشة الكاشير.', 'danger')
        return redirect(url_for('print_invoice', id=id))

    variant_id = request.form.get('variant_id')
    qty = int(request.form.get('quantity', 1))

    variant = ProductVariant.query.get_or_404(variant_id)

    if qty > variant.stock:
        flash(f'الكمية المطلوبة ({qty}) أكبر من المخزون المتاح ({variant.stock}).', 'danger')
        return redirect(url_for('print_invoice', id=id))

    unit_price = variant.sell_price or variant.cost_price
    item_total = unit_price * qty

    # إضافة الصنف
    new_item = SaleItem(
        order_id=order.id,
        variant_id=variant.id,
        quantity=qty,
        unit_price=unit_price
    )
    db.session.add(new_item)

    # خصم المخزون
    variant.stock -= qty
    db.session.add(StockMovement(
        variant_id=variant.id,
        user_id=current_user.id,
        quantity_change=-qty,
        reason=f"إضافة تفاعلية لفاتورة المبيعات #{order.id}"
    ))

    # زيادة الفاتورة
    order.total_amount = (order.total_amount or 0) + item_total
    order.final_total = (order.final_total or 0) + item_total
    order.amount_due = (order.amount_due or 0) + item_total

    # زيادة مديونية العميل
    if order.customer:
        order.customer.balance = (order.customer.balance or 0) + item_total

    db.session.commit()
    flash(f'تم إضافة الصنف: {variant.model.name} بنجاح.', 'success')
    return redirect(url_for('print_invoice', id=id))

@app.route('/invoice/<int:id>/remove_item/<int:item_id>', methods=['POST'])
@login_required
def invoice_remove_item(id, item_id):
    """حذف صنف من فاتورة تامة مع إرجاع المخزون وتعديل الحسابات"""
    if current_user.role != 'general_manager' and not current_user.has_perm('edit_invoice'):
        flash('غير مصرح لك بحذف أصناف الفاتورة', 'danger')
        return redirect(url_for('print_invoice', order_id=id))

    order = SaleOrder.query.get_or_404(id)
    item = SaleItem.query.get_or_404(item_id)

    if item.order_id != order.id:
        flash('الصنف لا ينتمي لهذه الفاتورة', 'danger')
        return redirect(url_for('print_invoice', id=id))

    # لو الفاتورة فيها صنف واحد بس، مينفعش يتحذف (استخدم حذف الفاتورة)
    if len(order.items) <= 1:
        flash('لا يمكن حذف آخر صنف في الفاتورة. استخدم حذف الفاتورة بدلاً من ذلك.', 'danger')
        return redirect(url_for('print_invoice', id=id))

    item_total = item.unit_price * item.quantity

    # 1. إرجاع المخزون
    if item.variant:
        item.variant.stock += item.quantity
        db.session.add(StockMovement(
            variant_id=item.variant_id,
            user_id=current_user.id,
            quantity_change=item.quantity,
            reason=f"حذف صنف من فاتورة #{order.id}"
        ))

    # 2. تعديل أرقام الفاتورة
    order.total_amount = round_half((order.total_amount or 0) - item_total)
    customer_shipping = order.shipping_fee if order.shipping_paid_by == 'customer' and order.shipping_fee else 0
    order.final_total = round_half(order.total_amount - (order.discount or 0) + customer_shipping)
    old_due = order.amount_due or 0
    order.amount_due = round_half(max(0, order.final_total - (order.paid_upfront or 0)))
    due_diff = old_due - order.amount_due  # الفرق اللي هنرجعه من المديونية

    # 3. تقليل مديونية العميل
    if order.customer and due_diff > 0:
        order.customer.balance = round_half((order.customer.balance or 0) - due_diff)

    # 4. حذف الصنف
    item_name = item.variant.model.name if item.variant else 'صنف محذوف'
    db.session.delete(item)
    db.session.commit()

    # تحديث العمولات
    if order.user_id:
        update_monthly_commissions(order.user_id, order.date)

    flash(f'تم حذف الصنف: {item_name} وإرجاع المخزون بنجاح ✅', 'success')
    return redirect(url_for('print_invoice', id=id))


@app.route('/invoice/<int:id>/update_item/<int:item_id>', methods=['POST'])
@login_required
def invoice_update_item(id, item_id):
    """تعديل كمية أو سعر صنف في فاتورة تامة"""
    if current_user.role != 'general_manager' and not current_user.has_perm('edit_invoice'):
        flash('غير مصرح لك بتعديل أصناف الفاتورة', 'danger')
        return redirect(url_for('print_invoice', order_id=id))

    order = SaleOrder.query.get_or_404(id)
    item = SaleItem.query.get_or_404(item_id)

    if item.order_id != order.id:
        flash('الصنف لا ينتمي لهذه الفاتورة', 'danger')
        return redirect(url_for('print_invoice', id=id))

    new_qty = int(request.form.get('new_qty', item.quantity))
    new_price = float(request.form.get('new_price', item.unit_price))

    if new_qty <= 0:
        flash('الكمية يجب أن تكون أكبر من صفر. استخدم زرار الحذف لإزالة الصنف.', 'danger')
        return redirect(url_for('print_invoice', id=id))

    old_qty = item.quantity
    old_price = item.unit_price
    old_item_total = old_qty * old_price
    new_item_total = new_qty * new_price

    qty_diff = new_qty - old_qty  # + زيادة ، - نقصان

    # 1. تعديل المخزون (لو الكمية تغيرت)
    if qty_diff != 0 and item.variant:
        if qty_diff > 0:
            # زيادة كمية → اخصم من المخزن
            if item.variant.stock < qty_diff:
                flash(f'المخزون المتاح ({item.variant.stock}) أقل من الزيادة المطلوبة ({qty_diff})', 'danger')
                return redirect(url_for('print_invoice', id=id))
            item.variant.stock -= qty_diff
        else:
            # نقصان كمية → رّجع للمخزن
            item.variant.stock += abs(qty_diff)

        db.session.add(StockMovement(
            variant_id=item.variant_id,
            user_id=current_user.id,
            quantity_change=-qty_diff,
            reason=f"تعديل كمية في فاتورة #{order.id}"
        ))

    # 2. تحديث الصنف
    item.quantity = new_qty
    item.unit_price = new_price
    item.total_price = new_item_total

    # 3. تعديل أرقام الفاتورة
    total_diff = new_item_total - old_item_total  # الفرق في الإجمالي
    order.total_amount = round_half((order.total_amount or 0) + total_diff)
    customer_shipping = order.shipping_fee if order.shipping_paid_by == 'customer' and order.shipping_fee else 0
    order.final_total = round_half(order.total_amount - (order.discount or 0) + customer_shipping)
    old_due = order.amount_due or 0
    order.amount_due = round_half(max(0, order.final_total - (order.paid_upfront or 0)))
    due_diff = order.amount_due - old_due  # + زادت المديونية ، - قلت

    # 4. تعديل مديونية العميل
    if order.customer and due_diff != 0:
        order.customer.balance = round_half((order.customer.balance or 0) + due_diff)

    db.session.commit()

    # تحديث العمولات
    if order.user_id:
        update_monthly_commissions(order.user_id, order.date)

    flash(f'تم تعديل الصنف بنجاح ✅', 'success')
    return redirect(url_for('print_invoice', id=id))


@app.route('/invoice/<int:id>/update_discount', methods=['POST'])
@login_required
def invoice_update_discount(id):
    """تعديل الخصم على فاتورة تامة"""
    if current_user.role not in ['manager', 'general_manager']:
        return jsonify({'success': False, 'message': 'غير مصرح'}), 403

    order = SaleOrder.query.get_or_404(id)
    new_discount = float(request.form.get('new_discount', 0))

    if new_discount < 0:
        flash('الخصم لا يمكن أن يكون بالسالب', 'danger')
        return redirect(url_for('print_invoice', id=id))

    if new_discount > (order.total_amount or 0):
        flash('الخصم أكبر من إجمالي الفاتورة!', 'danger')
        return redirect(url_for('print_invoice', id=id))

    old_discount = order.discount or 0
    discount_diff = new_discount - old_discount  # + خصم زاد ، - خصم قل

    order.discount = new_discount
    customer_shipping = order.shipping_fee if order.shipping_paid_by == 'customer' and order.shipping_fee else 0
    order.final_total = round_half((order.total_amount or 0) - new_discount + customer_shipping)
    old_due = order.amount_due or 0
    order.amount_due = round_half(max(0, order.final_total - (order.paid_upfront or 0)))
    due_diff = order.amount_due - old_due

    # تعديل مديونية العميل
    if order.customer and due_diff != 0:
        order.customer.balance = round_half((order.customer.balance or 0) + due_diff)

    db.session.commit()
    flash(f'تم تعديل الخصم إلى {new_discount} ج.م بنجاح ✅', 'success')
    return redirect(url_for('print_invoice', id=id))

# === الكتالوج الرقمي (رابط عام للعملاء) ===
@app.route('/public/catalog')
def public_catalog():
    # استلام رقم مندوب المبيعات من الرابط
    ref_phone = request.args.get('ref', '')

    # جلب كل التصنيفات
    all_cats = Category.query.all()
    catalog_data = []

    for cat in all_cats:
        # جلب المنتجات المتاحة فقط (رصيد > 0) التابعة لهذا التصنيف
        # نستخدم join لأن الـ category_id موجود في ProductModel وليس Variant
        products = ProductVariant.query.join(ProductModel).filter(
            ProductModel.category_id == cat.id,
            ProductVariant.stock > 0
        ).all()

        # إذا كان التصنيف يحتوي على منتجات متاحة، نضيفه للقائمة
        if products:
            catalog_data.append({
                'category': cat,
                'products': products
            })

    return render_template('public_catalog.html',
                           catalog_data=catalog_data,
                           ref_phone=ref_phone,
                           company_name= "مصنع فور برازر")
@app.route('/invoice/convert/<int:id>')
@login_required
def convert_to_invoice(id):
    order = SaleOrder.query.get_or_404(id)

    # التأكد أنها عرض سعر فعلاً
    if not order.is_proforma:
        return redirect(url_for('print_invoice', id=id))

    # 1. التحقق من المخزون أولاً قبل الخصم
    for item in order.items:
        if item.variant and item.variant.stock < item.quantity:
            flash(f'الكمية غير كافية للمنتج: {item.variant.model.name} (المتاح: {item.variant.stock}, المطلوب: {item.quantity})', 'danger')
            return redirect(url_for('print_invoice', id=id))

    # 2. خصم الكميات من المخزن (لأنها أصبحت فاتورة فعلية)
    for item in order.items:
        if item.variant:
            item.variant.stock -= item.quantity
            db.session.add(StockMovement(
                variant_id=item.variant.id,
                user_id=current_user.id,
                quantity_change=-item.quantity,
                reason=f"تحويل عرض سعر #{order.id} لفاتورة"
            ))

    # 2. تحديث حالة الفاتورة
    order.is_proforma = False
    order.date = cairo_now() # تحديث التاريخ لوقت الاعتماد

    # === [التعديل هنا] ضبط حالة الشحن ===
    if order.is_shipping:
        # لو الفاتورة شحن، نخلي حالتها 'none' عشان تظهر في صفحة الشحن كشحنة جديدة
        order.shipping_status = 'none'
    else:
        # لو استلام محل، نعتبرها 'settled' (منتهية لوجيستياً)
        order.shipping_status = 'settled'

    # 3. تحديث مديونية العميل (لأنها أصبحت فاتورة فعلية)
    if order.customer_id and order.amount_due > 0:
        customer = Customer.query.get(order.customer_id)
        if customer:
            customer.balance = (customer.balance or 0) + order.amount_due

    # 4. تحديث العمولات للموظف (لأنها أصبحت بيعة حقيقية)
    if order.user_id:
        update_monthly_commissions(order.user_id, order.date)

    db.session.commit()
    flash('تم اعتماد عرض السعر وتحويله لفاتورة بنجاح، وتم إدراجها في الشحن أو تسويتها ✅', 'success')
    return redirect(url_for('print_invoice', id=id))
@app.route('/invoice/edit_proforma/<int:id>')
@login_required
def edit_proforma(id):
    order = SaleOrder.query.get_or_404(id)

    # التأكد أنها مسودة (عرض سعر)
    if not order.is_proforma:
        flash('لا يمكن تعديل فاتورة تم اعتمادها، فقط عروض الأسعار.', 'warning')
        return redirect(url_for('invoices'))

    # تجهيز البيانات لإرسالها للجافاسكريبت
    order_data = {
        'id': order.id,
        'customer_id': order.customer_id,
        'discount': order.discount,
        'paid_upfront': order.paid_upfront,
        'items': []
    }

    for item in order.items:
        order_data['items'].append({
            'id': item.variant.id,
            'name': item.variant.model.name,
            'price': item.unit_price,
            'qty': item.quantity,
            'stock': item.variant.stock # عشان الـ Validation
        })

    # إرسال نفس البيانات التي تحتاجها صفحة POS العادية + بيانات الفاتورة
    if current_user.username == 'Abo_malek' or current_user.role == 'general_manager' or current_user.emp_code == 'EMP201':
        customers = Customer.query.order_by(Customer.id.desc()).all()
    else:
        accessible_ids = get_accessible_users()
        customers = Customer.query.filter(
            or_(Customer.created_by_id.in_(accessible_ids), Customer.name == "عميل نقدي")
        ).order_by(Customer.id.desc()).all()

    return render_template('pos.html',
                           categories=Category.query.all(),
                           products=ProductVariant.query.all(),
                           customers=customers,
                           shipping_companies=ShippingCompany.query.all(),
                           money_accounts=MoneyAccount.query.all(),
                           # المتغير الجديد المهم جداً 👇
                           edit_order_data=order_data)
@app.route('/fix/transfer_sales')
@general_manager_required
def transfer_sales():
    from_username = request.args.get('from_user') # يوزر المدير (الخاطئ)
    to_username = request.args.get('to_user')     # يوزر الموظفة (الصحيح)

    if not from_username or not to_username:
        return "يجب تحديد from_user و to_user في الرابط"

    u_from = User.query.filter_by(username=from_username).first()
    u_to = User.query.filter_by(username=to_username).first()

    if not u_from or not u_to: return "مستخدم غير موجود"

    # نقل فواتير اليوم فقط (عشان منبوظش القديم)
    today = date.today()
    orders = SaleOrder.query.filter(
        SaleOrder.user_id == u_from.id,
        cast(SaleOrder.date, Date) == today
    ).all()

    count = 0
    for o in orders:
        o.user_id = u_to.id
        o.sales_rep_code = u_to.emp_code
        count += 1

    # إعادة حساب العمولات للموظفة
    update_monthly_commissions(u_to.id, cairo_now())

    db.session.commit()
    return f"تم نقل {count} فاتورة من {u_from.fullname} إلى {u_to.fullname} بنجاح! راجع بروفايلها الآن."
@app.route('/invoice/delete/<int:order_id>', methods=['GET', 'POST'])
@login_required
def delete_invoice(order_id):
    if not current_user.has_perm('manage_orders') and current_user.role != 'general_manager':
        return jsonify({'success': False, 'message': 'غير مصرح لك بحذف الفواتير'}), 403

    try:
        order = SaleOrder.query.get(order_id)
        if not order:
            return jsonify({'success': False, 'message': 'الفاتورة غير موجودة'}), 404

        # =========================================================
        # === 1. إرجاع الأموال للخزينة وتصحيح الرصيد (الجديد) ===
        # =========================================================
        # إحضار كل المعاملات المحتملة للبحث الدقيق لمنع كارثة المسح العشوائي للأرقام المتشابهة
        financial_txs_raw = FinancialTransaction.query.filter(
            FinancialTransaction.description.like(f'%فاتورة #{order_id}%')
        ).all()

        financial_txs = []
        for tx in financial_txs_raw:
            # (?!\\d) للتأكد من إن بعد الرقم مفيش رقم تاني، ففاتورة 1 لن تحذف فاتورة 10
            if tx.description and re.search(rf'فاتورة #{order_id}(?!\d)', tx.description):
                financial_txs.append(tx)

        for tx in financial_txs:
            if tx.type in ('income', 'expense'):
                account = MoneyAccount.query.get(tx.account_id)
                if account:
                    if tx.type == 'income':
                        # لو كانت الفاتورة دخل (بيع)، نطرح المبلغ من الخزنة
                        account.balance = round_half(account.balance - tx.amount)
                    elif tx.type == 'expense':
                        # لو كانت مصروف (نادر في البيع)، نرجعه للخزنة
                        account.balance = round_half(account.balance + tx.amount)
            # ملاحظة: المديونية يتم تصحيحها مباشرة من order.amount_due أدناه

            # حذف سجل المعاملة بعد تعديل الرصيد
            db.session.delete(tx)

        # === تصحيح مديونية العميل مباشرة (الضمان الأساسي) ===
        # نخصم final_total بالكامل لأن ده المبلغ الكلي اللي اتضاف لرصيد العميل
        # (سواء كان amount_due أو دفعات إضافية اللي خصمت من رصيده)
        if order.customer_id and not order.is_proforma:
            customer = Customer.query.get(order.customer_id)
            if customer:
                customer.balance = round_half((customer.balance or 0) - (order.final_total or 0))

        # تنظيف حركات دفع من رصيد العميل (credit payments)
        credit_txs_del = FinancialTransaction.query.filter(
            FinancialTransaction.description.like(f'%رصيد عميل #{order_id}%')
        ).all()
        for ctx in credit_txs_del:
            db.session.delete(ctx)

        # = ::::: بقية الكود كما هو مع التأكد من الحذف الصحيح ::::: =

        # 2. إرجاع المخزون
        should_restore_stock = (not order.is_proforma) and (len(order.return_invoices) == 0)
        if should_restore_stock:
            for item in order.items:
                db.session.execute(text(f"UPDATE product_variant SET stock = stock + :qty WHERE id = :vid"),
                                   {'qty': item.quantity, 'vid': item.variant_id})
                try:
                    db.session.add(StockMovement(
                        variant_id=item.variant_id,
                        user_id=current_user.id,
                        quantity_change=item.quantity,
                        reason=f"حذف فاتورة #{order_id}"
                    ))
                except: pass

        # 3. تنظيف الحسابات الأخرى ببحث آمن بالريجكس لتفادي حذف بيانات فواتير أخرى
        hr_raw = HRTransaction.query.filter(HRTransaction.note.like(f'%فاتورة #{order_id}%')).all()
        for hr in hr_raw:
            if hr.note and re.search(rf'فاتورة #{order_id}(?!\d)', hr.note):
                db.session.delete(hr)
        db.session.execute(text("DELETE FROM partner_transaction WHERE order_id = :oid"), {'oid': order_id})
        db.session.execute(text("DELETE FROM return_invoice WHERE order_id = :oid"), {'oid': order_id})

        # 4. حذف الأصناف والفاتورة
        db.session.execute(text("DELETE FROM sale_item WHERE order_id = :oid"), {'oid': order_id})
        db.session.execute(text("DELETE FROM sale_order WHERE id = :oid"), {'oid': order_id})

        db.session.commit()

        # تحديث العمولات
        if order.user_id:
            update_monthly_commissions(order.user_id, order.date)

        return jsonify({'success': True, 'message': 'تم حذف الفاتورة، تصفير المديونية، وإرجاع الفلوس للخزنة بنجاح! 💰🗑️'})

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'خطأ قاعدة بيانات: {str(e)}'}), 500

@app.route('/invoice/<int:order_id>/revert_to_proforma', methods=['POST'])
@login_required
def revert_to_proforma(order_id):
    """تحويل فاتورة تامة إلى عرض سعر (مسودة) مع عكس كل التأثيرات المالية والمخزنية"""
    if not current_user.has_perm('revert_to_proforma'):
        flash('غير مصرح لك باسترجاع الفواتير لمسودة', 'danger')
        return redirect(url_for('print_invoice', id=order_id))

    try:
        order = SaleOrder.query.get_or_404(order_id)

        if order.is_proforma:
            flash('الفاتورة بالفعل عرض سعر!', 'warning')
            return redirect(url_for('print_invoice', id=order_id))

        if order.return_invoices and len(order.return_invoices) > 0:
            flash('لا يمكن إرجاع فاتورة عليها مرتجعات! يرجى حذف المرتجعات أولاً.', 'danger')
            return redirect(url_for('print_invoice', id=order_id))

        # 1. إرجاع الأموال للخزينة 
        financial_txs = FinancialTransaction.query.filter(
            FinancialTransaction.description.like(f'%فاتورة #{order_id}%')
        ).all()

        for tx in financial_txs:
            if tx.description and re.search(rf'فاتورة #{order_id}(?!\d)', tx.description):
                if tx.type in ('income', 'expense'):
                    account = MoneyAccount.query.get(tx.account_id)
                    if account:
                        if tx.type == 'income':
                            account.balance = round_half(account.balance - tx.amount)
                        elif tx.type == 'expense':
                            account.balance = round_half(account.balance + tx.amount)
                db.session.delete(tx)

        # 2. إرجاع رصيد العميل بالكامل (final_total = المديونية الأصلية + أي دفعات إضافية أو من الرصيد)
        if order.customer_id:
            customer = Customer.query.get(order.customer_id)
            if customer:
                # نخصم final_total لأنها المبلغ الكلي اللي اتضاف لرصيد العميل
                # (سواء amount_due أو دفعات إضافية اللي بتنقص الرصيد)
                customer.balance = round_half((customer.balance or 0) - (order.final_total or 0))

        # 3. إرجاع المخزون
        for item in order.items:
            db.session.execute(text("UPDATE product_variant SET stock = stock + :qty WHERE id = :vid"),
                               {'qty': item.quantity, 'vid': item.variant_id})
            try:
                db.session.add(StockMovement(
                    variant_id=item.variant_id,
                    user_id=current_user.id,
                    quantity_change=item.quantity,
                    reason=f"إرجاع فاتورة #{order_id} لمسودة"
                ))
            except: pass

        # 4. تنظيف الحسابات المتفرعة
        hr_raw = HRTransaction.query.filter(HRTransaction.note.like(f'%فاتورة #{order_id}%')).all()
        for hr in hr_raw:
            if hr.note and re.search(rf'فاتورة #{order_id}(?!\d)', hr.note):
                db.session.delete(hr)
        
        db.session.execute(text("DELETE FROM partner_transaction WHERE order_id = :oid"), {'oid': order_id})

        # تنظيف حركات دفع من رصيد العميل (credit payments)
        credit_txs = FinancialTransaction.query.filter(
            FinancialTransaction.description.like(f'%رصيد عميل #{order_id}%')
        ).all()
        for ctx in credit_txs:
            db.session.delete(ctx)

        # تنظيف سجل مراجعة الدفعات (CustomerPayment) إذا وجد
        if order.customer_id:
            CustomerPayment.query.filter(
                CustomerPayment.customer_id == order.customer_id,
                CustomerPayment.notes.like(f'%فاتورة #{order_id}%')
            ).delete()

        # 5. تصفير قيم الفاتورة للحفظ كمسودة
        order.is_proforma = True
        order.is_reviewed = False
        order.paid_upfront = 0
        order.amount_due = 0
        order.is_shipping = False
        order.shipping_company_id = None
        order.waybill_no = None
        order.shipping_fee = 0
        order.shipping_paid_by = 'customer'
        order.shipping_status = 'proforma'
        order.shipping_notes = None

        db.session.commit()

        # تحديث عمولات البائع بعد الإرجاع
        if order.user_id:
            update_monthly_commissions(order.user_id, order.date)

        flash(f'تم إرجاع الفاتورة #{order_id} لمسودة بنجاح! حساب الخزينة والعملاء عاد لسابقه.', 'success')
        return redirect(url_for('print_invoice', id=order_id))

    except Exception as e:
        db.session.rollback()
        flash(f'حدث خطأ غير متوقع: {str(e)}', 'danger')
        return redirect(url_for('print_invoice', id=order_id))

@app.route('/hr/add_excuse', methods=['POST'])
@login_required
def add_excuse():
    if not current_user.has_perm('manage_hr') and current_user.role != 'general_manager':
        return jsonify({'success': False, 'message': 'غير مصرح'}), 403

    try:
        user_id = request.form.get('user_id')
        excuse_date = datetime.strptime(request.form.get('date'), '%Y-%m-%d').date()
        excuse_type = request.form.get('type')
        hours = float(request.form.get('hours') or 0)
        note = request.form.get('note')

        new_excuse = EmployeeExcuse(
            user_id=user_id,
            date=excuse_date,
            type=excuse_type,
            hours=hours,
            note=note
        )
        db.session.add(new_excuse)

        # تحديث سجل الحضور إذا كان موجوداً ليكون "بإذن"
        att_record = Attendance.query.filter_by(user_id=user_id, date=excuse_date).first()
        if att_record and excuse_type == 'day':
            att_record.status = 'absent_excused' # حالة جديدة للغياب المبرر

        db.session.commit()
        return jsonify({'success': True, 'message': 'تم تسجيل الإذن بنجاح ✅'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
@app.route('/invoice/edit/<int:id>', methods=['GET', 'POST'])
@general_manager_required
def edit_invoice(id):
    order = SaleOrder.query.get_or_404(id)
    if order.date.date() != cairo_now().date(): flash('لا يمكن تعديل فواتير سابقة', 'warning'); return redirect(url_for('invoices'))
    if request.method == 'POST':
        for item in order.items:
            item.variant.stock += item.quantity
            db.session.delete(item)
        p_names = request.form.getlist('product_name[]')
        qtys = request.form.getlist('qty[]')
        total = 0
        for i in range(len(p_names)):
            p_name = p_names[i]
            try: qty = int(qtys[i])
            except: qty = 0
            if p_name and qty > 0:
                model = ProductModel.query.filter_by(name=p_name).first()
                if model:
                    variant = model.variants[0]
                    if variant.stock < qty:
                        flash(f'الكمية غير كافية للمنتج: {model.name} (المتاح: {variant.stock})', 'danger')
                        return redirect(url_for('edit_invoice', id=id))
                    variant.stock -= qty
                    price = variant.sell_price
                    total += price * qty
                    db.session.add(SaleItem(order=order, variant_id=variant.id, quantity=qty, unit_price=price, total_price=price*qty))
        order.discount = float(request.form.get('discount', 0))
        order.total_amount = total
        customer_shipping = order.shipping_fee if order.shipping_paid_by == 'customer' and order.shipping_fee else 0
        order.final_total = total - order.discount + customer_shipping
        

        old_amount_due = order.amount_due
        # التصحيح: إزالة shipping_fee من المعادلة عشان متتحسبش مرتين
        order.amount_due = order.final_total - order.paid_upfront
        
        # === [التعديل هنا] تحديث رصيد العميل بالفرق ===
        if order.customer_id and not order.is_proforma:
            customer = Customer.query.get(order.customer_id)
            if customer:
                difference = order.amount_due - old_amount_due
                customer.balance = (customer.balance or 0) + difference
                
        db.session.commit(); return redirect(url_for('invoices'))
    return render_template('edit_invoice.html', order=order, products=ProductModel.query.all())

@app.route('/invoices')
@login_required
def invoices():
    if not current_user.has_perm('view_invoices'):
        return "غير مصرح لك", 403

    # 1. تحديد نوع الفواتير المطلوبة من الرابط
    # إذا كان الرابط ?type=proforma نعرض المسودات، غير ذلك نعرض الفواتير التامة
    show_proforma = (request.args.get('type') == 'proforma')

    accessible_ids = get_accessible_users()
    
    # جلب قائمة الكائنات للمستخدمين المتاحين (عشان نعرضهم في الفلتر)
    accessible_users_list = User.query.filter(User.id.in_(accessible_ids)).all()

    # 2. الاستعلام الأساسي (مع الفلتر الجديد)
    query = SaleOrder.query.filter(SaleOrder.user_id.in_(accessible_ids))

    # فلتر الموظف (لو تم اختياره)
    selected_user_id = request.args.get('user_id')
    if selected_user_id and selected_user_id.isdigit():
        uid = int(selected_user_id)
        # التأكد إن الموظف المختار ضمن صلاحياتي
        if uid in accessible_ids:
            query = query.filter(SaleOrder.user_id == uid)

    # فلتر التاريخ (من - إلى)
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    if start_date:
        query = query.filter(SaleOrder.date >= f"{start_date} 00:00:00")
    if end_date:
        query = query.filter(SaleOrder.date <= f"{end_date} 23:59:59")

    if show_proforma:
        # عرض عروض الأسعار فقط
        query = query.filter(SaleOrder.is_proforma == True)
    else:
        # عرض الفواتير التامة فقط
        query = query.filter(SaleOrder.is_proforma == False)

    orders = query.order_by(SaleOrder.date.desc()).all()

    # 3. حساب الإجماليات (للمدير العام فقط) - سيتم الحساب بناءً على القائمة المفلترة
    is_gm = (current_user.username == 'gm_ahmed')
    grand_totals = {
        'total_cost': 0, 'total_sell': 0, 'total_profit': 0,
        'total_comm': 0, 'total_company_net': 0, 'total_items': 0
    }

    if is_gm:
        for o in orders:
            # نفس منطق الحساب القديم
            o.real_cost = sum((i.variant.cost_price or 0) * i.quantity for i in o.items if i.variant)

            # عمولة تقديرية
            seller = db.session.get(User, o.user_id) if o.user_id else None
            o.est_comm = 0
            if seller:
                order_qty = sum(i.quantity for i in o.items)
                o.est_comm = calculate_user_commission(seller, order_qty, order_qty)

            revenue = o.final_total - (o.shipping_fee or 0)
            o.gross_profit = revenue - o.real_cost
            o.company_net = o.gross_profit - o.est_comm

            grand_totals['total_cost'] += o.real_cost
            grand_totals['total_sell'] += o.final_total
            grand_totals['total_profit'] += o.gross_profit
            grand_totals['total_comm'] += o.est_comm
            grand_totals['total_company_net'] += o.company_net
            grand_totals['total_items'] += sum(i.quantity for i in o.items)

    return render_template('invoices.html',
                           orders=orders,
                           is_gm=is_gm,
                           grand_totals=grand_totals,
                           is_proforma_view=show_proforma,
                           accessible_users=accessible_users_list, # قائمة الموظفين للفلترة
                           selected_user_id=int(selected_user_id) if selected_user_id and selected_user_id.isdigit() else None,
                           start_date=start_date,
                           end_date=end_date)
@app.route('/team/add_member', methods=['POST'])
@permission_required('manage_hr')
def add_team_member():
    if current_user.role not in ['general_manager', 'manager']:
        return "غير مصرح لك", 403

    fullname = request.form['fullname']
    username = request.form['username']
    password = request.form['password']
    role = request.form.get('role', 'sales')
    job_type = request.form['job_type']
    phone = request.form['phone']

    shift_start = request.form.get('shift_start', '09:00')
    shift_end = request.form.get('shift_end', '17:00')

    raw_s = request.form.get('base_salary', '')
    base_salary = float(raw_s) if raw_s and raw_s.strip() else 0.0

    raw_c = request.form.get('commission_value', '')
    comm_val = float(raw_c) if raw_c and raw_c.strip() else 0.0

    tiers = []
    if job_type == 'tiered_sales':
        for i in range(1, 5):
            s = request.form.get(f'tier_{i}_start')
            e = request.form.get(f'tier_{i}_end')
            a = request.form.get(f'tier_{i}_amount')
            if s and s.strip() and e and e.strip() and a and a.strip():
                tiers.append({'min': float(s), 'max': float(e), 'val': float(a)})

    emp_code = f"EMP{''.join(random.choices(string.digits, k=3))}"

    manager_id = current_user.id if current_user.role in ['manager', 'general_manager'] else None

    # --- التصحيح هنا: تغيير password_hash إلى password ---
    new_user = User(
        fullname=fullname,
        username=username,
        password=generate_password_hash(password), # <--- تم التصحيح هنا
        role=role,
        emp_code=emp_code,
        phone=phone,
        job_type=job_type,
        base_salary=base_salary,
        commission_value=comm_val,
        commission_rules=json.dumps(tiers) if tiers else None,
        manager_id=manager_id,
        shift_start=shift_start,
        shift_end=shift_end,
        work_from_home=(request.form.get('work_from_home') == 'on')
    )

    db.session.add(new_user)
    db.session.commit()

    flash('تم إضافة الموظف بنجاح ✅', 'success')
    return redirect(url_for('dashboard'))
@app.route('/employee/update_data/<int:id>', methods=['POST'])
@login_required # Removed @permission_required('manage_hr') to allow custom logic inside
def update_employee_data(id):
    emp = User.query.get_or_404(id)
    
    # Allow if the user has manage_hr perm, OR is a general_manager editing their own profile
    is_self_gm = (current_user.role == 'general_manager' and current_user.id == emp.id)
    if not current_user.has_perm('manage_hr') and not is_self_gm:
        flash("عفواً، لا تملك صلاحية تعديل بيانات هذا الموظف.", "danger")
        return redirect(url_for('employee_profile', id=id))

    # If the user is only a GM editing themselves (without HR permissions), ONLY update phone.
    if is_self_gm and not current_user.has_perm('manage_hr'):
        emp.phone = request.form.get('phone', emp.phone)
        db.session.commit()
        flash('تم تحديث رقم الهاتف بنجاح ✅', 'success')
        return redirect(url_for('employee_profile', id=emp.id))

    # --- Full Update for authorized HR managers starts here ---

    # 1. استقبال البيانات الجديدة
    new_username = request.form.get('username')

    # 2. التحقق من اسم المستخدم (هام جداً لمنع التكرار)
    if new_username and new_username != emp.username:
        # لو غير الاسم، نتأكد إنه مش محجوز لحد تاني
        existing_user = User.query.filter_by(username=new_username).first()
        if existing_user:
            flash(f'❌ خطأ: اسم المستخدم "{new_username}" مسجل بالفعل لموظف آخر!', 'danger')
            return redirect(url_for('employee_profile', id=id))

        # لو تمام، نحدثه
        emp.username = new_username

    # 3. تحديث باقي البيانات
    emp.fullname = request.form['fullname']
    emp.phone = request.form['phone']
    emp.role = request.form['role']
    emp.emp_code = request.form['emp_code']
    emp.base_salary = float(request.form['base_salary'])
    emp.job_type = request.form['job_type']

    if 'commission_value' in request.form:
        emp.commission_value = float(request.form['commission_value'])

    # تحديث حالة العمل من المنزل
    emp.work_from_home = (request.form.get('work_from_home') == 'on')

    working_hours_val = request.form.get('working_hours')
    if working_hours_val:
        try:
            emp.working_hours = float(working_hours_val)
        except: pass
    emp.salary_method = request.form.get('salary_method', 'direct_manager')

    # تحديث الشرائح (لو موجودة)
    if emp.job_type == 'tiered_sales':
        tiers = []
        for i in range(1, 5):
            s, e, a = request.form.get(f'tier_{i}_start'), request.form.get(f'tier_{i}_end'), request.form.get(f'tier_{i}_amount')
            if s and s.strip():
                tiers.append({'min': float(s), 'max': float(e), 'val': float(a)})
        emp.commission_rules = json.dumps(tiers) if tiers else None
    else:
        emp.commission_rules = None

    db.session.commit()
    flash('تم تحديث بيانات الموظف (بما فيها اسم الدخول) بنجاح ✅', 'success')
    return redirect(url_for('employee_profile', id=emp.id))
@app.route('/employee/delete/<int:id>')
@general_manager_required
def delete_employee(id):
    user = User.query.get_or_404(id)
    if user.id == current_user.id: flash('لا يمكن حذف حسابك', 'danger'); return redirect(request.referrer)
    try:
        Attendance.query.filter_by(user_id=id).delete()
        db.session.delete(user); db.session.commit()
        flash('تم الحذف', 'success')
    except: db.session.rollback(); flash('خطأ أثناء الحذف', 'danger')
    return redirect(url_for('dashboard'))

@app.route('/employee/<int:id>', methods=['GET', 'POST'])
@login_required
def employee_profile(id):
    emp = User.query.get_or_404(id)

    # === معالجة إضافة (مكافأة / خصم / سلفة) ===
    if request.method == 'POST':
        if not current_user.has_perm('manage_hr') and current_user.role != 'general_manager':
            return "غير مصرح", 403

    # === معالجة إضافة (مكافأة / خصم / سلفة) ===
    if request.method == 'POST':
        if not current_user.has_perm('manage_hr') and current_user.role != 'general_manager':
            return "غير مصرح", 403

        try:
            amount = float(request.form['amount'])
            t_type = request.form['type'] # bonus, deduction, advance
            note = request.form.get('note', '')
            account_id = request.form.get('account_id') # استقبال رقم الخزنة

            # === إذا كان منفذ العملية مديراً (مش general_manager) → معلقة للموافقة ===
            if current_user.role == 'manager':
                pending = PendingFinancialAction(
                    created_by_id=current_user.id,
                    target_emp_id=emp.id,
                    action_type=t_type,
                    amount=amount,
                    account_id=account_id if account_id else None,
                    note=note,
                    date=cairo_now(),
                    status='pending'
                )
                db.session.add(pending)
                db.session.commit()
                flash('✅ تم إرسال الطلب للمدير العام للموافقة عليه. لن يُسجَّل في الحسابات إلا بعد الموافقة.', 'info')
                return redirect(url_for('employee_profile', id=id))

            # === إذا كان general_manager → تنفيذ فوري كما كان ===
            # 1. تسجيل الحركة في ملف الموظف
            db.session.add(HRTransaction(
                user_id=emp.id,
                type=t_type,
                amount=amount,
                note=note,
                date=cairo_now()
            ))

            is_company_partner = emp.username in ['Abo_Eyad', 'Abo_malek']

            if t_type == 'advance':
                # أ - الخصم من الخزينة لحركة السلفة
                deducted_from_safe = False
                if account_id:
                    account = MoneyAccount.query.get(account_id)
                    if account:
                        account.balance -= amount
                        db.session.add(FinancialTransaction(
                            account_id=account.id,
                            type='expense',
                            category='سحوبات شخصية' if is_company_partner else 'سلف موظفين',
                            amount=-amount,
                            description=f"صرف سلفة نقدية لـ {emp.fullname}" + (f" - {note}" if note else ""),
                            created_by_id=current_user.id,
                            date=cairo_now()
                        ))
                        deducted_from_safe = True
                
                if not deducted_from_safe:
                    cash_acc = MoneyAccount.query.filter_by(type='cash').first()
                    if cash_acc:
                        cash_acc.balance -= amount
                        db.session.add(FinancialTransaction(
                            account_id=cash_acc.id,
                            type='expense',
                            category='سحوبات شخصية' if is_company_partner else 'سلف موظفين',
                            amount=-amount,
                            description=f"سلفة نقدية لـ {emp.fullname}" + (f" - {note}" if note else ""),
                            created_by_id=current_user.id,
                            date=cairo_now()
                        ))

                # ب - تحميل السلفة حسب الـ salary_method (نفس اللي بيحصل في الراتب)
                if is_company_partner:
                    db.session.add(PartnerTransaction(
                        partner_id=emp.id,
                        type='withdrawal',
                        amount=-amount,
                        description=f"سحب شخصي: {note}"
                    ))
                else:
                    _record_partner_salary_expense(emp, amount, f"سلفة للموظف ({emp.fullname}): {note}", db.session)

            elif t_type == 'bonus':
                if not is_company_partner:
                    if emp.role == 'manager':
                        # مكافأة لمدير → تتحملها الشراكة (50/50)
                        half = amount / 2
                        gm = User.query.filter_by(username='gm').first() or User.query.filter_by(role='general_manager').first()
                        abo_malek = User.query.filter_by(username='Abo_malek').first()
                        if gm:
                            db.session.add(PartnerTransaction(partner_id=gm.id, type='staff_expense', amount=-half, description=f"مكافأة للموظف ({emp.fullname}): {note} [شراكة 50%]"))
                        if abo_malek:
                            db.session.add(PartnerTransaction(partner_id=abo_malek.id, type='staff_expense', amount=-half, description=f"مكافأة للموظف ({emp.fullname}): {note} [شراكة 50%]"))
                    else:
                        _record_partner_salary_expense(emp, amount, f"مكافأة للموظف ({emp.fullname}): {note}", db.session)

            elif t_type == 'deduction':
                if amount > 0 and not is_company_partner:
                    if emp.role == 'manager':
                        # خصم من مدير → يعود للشراكة (50/50)
                        half = amount / 2
                        gm = User.query.filter_by(username='gm').first() or User.query.filter_by(role='general_manager').first()
                        abo_malek = User.query.filter_by(username='Abo_malek').first()
                        if gm:
                            db.session.add(PartnerTransaction(partner_id=gm.id, type='staff_expense', amount=half, description=f"خصم/جزاء يعوض التكلفة ({emp.fullname}): {note} [شراكة 50%]"))
                        if abo_malek:
                            db.session.add(PartnerTransaction(partner_id=abo_malek.id, type='staff_expense', amount=half, description=f"خصم/جزاء يعوض التكلفة ({emp.fullname}): {note} [شراكة 50%]"))
                    else:
                        # الخصم يعتبر تخفيض للتكاليف، لذا نسجله بالموجب
                        _record_partner_salary_expense(emp, -amount, f"خصم/جزاء يعوض التكلفة ({emp.fullname}): {note}", db.session)

            db.session.commit()
            flash('تم تسجيل الحركة المالية بنجاح ✅', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'خطأ: {e}', 'warning')

        return redirect(url_for('employee_profile', id=id))


    # === الحسابات المالية وعرض البيانات ===
    today = date.today()
    month_str = request.args.get('month', today.strftime('%Y-%m'))
    try:
        y, m = map(int, month_str.split('-'))
        month_start = datetime(y, m, 1)
    except ValueError:
        now = cairo_now()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        month_str = month_start.strftime('%Y-%m')
        
    if month_start.month == 12:
        month_end = month_start.replace(year=month_start.year + 1, month=1)
    else:
        month_end = month_start.replace(month=month_start.month + 1)

    monthly_sales = db.session.query(func.sum(SaleOrder.final_total)).filter(SaleOrder.user_id == emp.id, SaleOrder.is_proforma == False, SaleOrder.date >= month_start, SaleOrder.date < month_end).scalar() or 0
    orders_count = SaleOrder.query.filter(SaleOrder.user_id == emp.id, SaleOrder.is_proforma == False, SaleOrder.date >= month_start, SaleOrder.date < month_end).count()
    gross_items = db.session.query(func.sum(SaleItem.quantity)).join(SaleOrder).filter(SaleOrder.user_id == emp.id, SaleOrder.is_proforma == False, SaleOrder.date >= month_start, SaleOrder.date < month_end).scalar() or 0

    returned_items = db.session.query(func.sum(ReturnInvoice.total_qty)).join(SaleOrder).filter(
        SaleOrder.user_id == emp.id,
        cast(ReturnInvoice.date, Date) >= month_start.date(),
        cast(ReturnInvoice.date, Date) < month_end.date()
    ).scalar() or 0
    
    net_items = max(0, gross_items - returned_items)
    commission = round_half(calculate_user_commission(emp, net_items, net_items))

    hr_trans = HRTransaction.query.filter(HRTransaction.user_id == emp.id, HRTransaction.date >= month_start, HRTransaction.date < month_end).all()

    base_bonuses = sum(t.amount for t in hr_trans if t.type == 'bonus')
    base_deductions = sum(t.amount for t in hr_trans if t.type in ['deduction', 'penalty'])
    advances = sum(t.amount for t in hr_trans if t.type == 'advance')

    # حساب خصومات الغياب ومكافآت الإضافي
    att_settings = AttendanceSettings.query.first() or AttendanceSettings()
    daily_rate = (emp.base_salary or 0) / 30
    attendance_deduction, attendance_details, overtime_bonus = calculate_attendance_deduction(emp, month_str, att_settings, daily_rate)
    
    deductions = round_half(base_deductions + attendance_deduction)
    bonuses = round_half(base_bonuses + overtime_bonus)
    advances = round_half(advances)

    net_salary = round_half((emp.base_salary or 0) + commission + bonuses - deductions - advances)

    current_tiers = []
    if emp.commission_rules:
        try: current_tiers = json.loads(emp.commission_rules)
        except: pass
    while len(current_tiers) < 4: current_tiers.append({'min': '', 'max': '', 'val': ''})

    recent_orders = SaleOrder.query.filter(SaleOrder.user_id == emp.id, SaleOrder.date >= month_start, SaleOrder.date < month_end).order_by(SaleOrder.date.desc()).all()
    transactions = HRTransaction.query.filter(HRTransaction.user_id == emp.id, HRTransaction.date >= month_start, HRTransaction.date < month_end).order_by(HRTransaction.date.desc()).all()

    # جلب الحسابات لإرسالها للقالب
    accounts = MoneyAccount.query.all()

    return render_template('employee_profile.html',
                           emp=emp,
                           sales=monthly_sales,
                           orders_count=orders_count,
                           total_items=int(net_items),
                           gross_items=int(gross_items),
                           returned_items=int(returned_items),
                           commission=commission,
                           bonuses=bonuses,
                           deductions=deductions,
                           advances=advances,
                           net_salary=net_salary,
                           transactions=transactions,
                           attendance_details=attendance_details,
                           orders=recent_orders,
                           current_tiers=current_tiers,
                           month_str=month_str,
                           accounts=accounts) # تم إضافة الحسابات هنا
@app.route('/customers')
@login_required
def customers():
    if not current_user.has_perm('view_customers'):
        return "غير مصرح لك", 403

    if current_user.username == 'Abo_malek' or current_user.role == 'general_manager' or current_user.emp_code == 'EMP201':
        all_customers = Customer.query.order_by(Customer.balance.desc(), Customer.id.desc()).all()
    else:
        accessible_ids = get_accessible_users()
        all_customers = Customer.query.filter(Customer.created_by_id.in_(accessible_ids))\
            .order_by(Customer.balance.desc(), Customer.id.desc()).all()

    return render_template('customers.html', customers=all_customers)
@app.route('/customers/add', methods=['POST'])
@login_required
def add_customer():
    name = request.form.get('name')
    phone = request.form.get('phone')
    address = request.form.get('address')

    # التحقق من أن جميع الحقول ممتلئة وليست فارغة
    if not name or not name.strip() or not phone or not phone.strip() or not address or not address.strip():
        flash('❌ خطأ: جميع بيانات العميل (الاسم، الهاتف، والعنوان) مطلوبة.', 'danger')
        return redirect(request.referrer)

    # التحقق من عدم تكرار رقم الهاتف
    if Customer.query.filter_by(phone=phone).first():
        flash('❌ خطأ: رقم الهاتف مسجل لعميل آخر بالفعل.', 'warning')
        return redirect(request.referrer)

    db.session.add(Customer(
        name=name,
        phone=phone,
        address=address,
        created_by_id=current_user.id
    ))
    db.session.commit()

    flash('✅ تم إضافة العميل الجديد بنجاح.', 'success')
    return redirect(request.referrer)
@app.route('/customers/<int:id>')
@login_required
def customer_profile(id):
    customer = Customer.query.get_or_404(id)
    # جلب جميع فواتير العميل
    orders = SaleOrder.query.filter_by(customer_id=id).order_by(SaleOrder.date.desc()).all()
    # جلب جميع الخزائن لعرضها في القائمة المنسدلة
    accounts = MoneyAccount.query.all()
    # جلب سجل المدفوعات التي دفعها العميل (عبر الـ backref المسمى payments_received)
    payments = customer.payments_received if hasattr(customer, 'payments_received') else []

    # جلب جميع المرتجعات الخاصة بفواتير هذا العميل
    customer_returns = []
    for order in orders:
        if order.return_invoices:
            for ret in order.return_invoices:
                # جلب تفاصيل القطع المرتجعة من حركات المخزون
                # البحث بدقة عن حركات هذا المرتجع المحدد (بالـ ID بتاعه)
                # الفورمات الجديد: "مرتجع #RET_ID فاتورة #ORDER_ID"
                # الفورمات القديم: "مرتجع فاتورة #ORDER_ID" (للتوافقية)
                returned_movements = StockMovement.query.filter(
                    db.or_(
                        StockMovement.reason == f"مرتجع #{ret.id} فاتورة #{order.id}",
                        # fallback للبيانات القديمة - لو مرتجع واحد فقط على الفاتورة
                        db.and_(
                            StockMovement.reason == f"مرتجع فاتورة #{order.id}",
                            ~StockMovement.reason.like(f"مرتجع #% فاتورة #{order.id}")
                        )
                    ),
                    StockMovement.quantity_change > 0
                ).all()
                items_detail = []
                total_value = 0
                for mv in returned_movements:
                    sale_item = next((si for si in order.items if si.variant_id == mv.variant_id), None)
                    unit_price = sale_item.unit_price if sale_item else 0
                    item_total = mv.quantity_change * unit_price
                    total_value += item_total
                    items_detail.append({
                        'name': mv.variant.model.name if mv.variant else '---',
                        'qty': mv.quantity_change,
                        'unit_price': unit_price,
                        'total': item_total
                    })
                customer_returns.append({
                    'return_id': ret.id,
                    'order_id': order.id,
                    'date': ret.date,
                    'total_qty': ret.total_qty,
                    'shipping_loss': ret.shipping_loss or 0,
                    'missing_cost': ret.missing_items_cost or 0,
                    'total_deduction': ret.total_deduction or 0,
                    'items_value': total_value,
                    'net_refund': total_value - (ret.total_deduction or 0),
                    'notes': ret.notes,
                    'creator': ret.creator.fullname if ret.creator else '---',
                    'returned_items': items_detail
                })

    return render_template('customer_profile.html',
                           customer=customer,
                           orders=orders,
                           accounts=accounts,
                           payments=payments,
                           customer_returns=customer_returns)# --- إدارة المصروفات الشاملة ---
# استبدل دالة expenses و add_expense بهذا الكود الموحد
# أضف هذا الرابط الجديد للتعامل مع تحديث الصورة السريع
@app.route('/api/update_product_image', methods=['POST'])
@permission_required('manage_inventory')
def update_product_image():
    try:
        product_id = request.form.get('id')
        if 'image' not in request.files:
            return jsonify({'success': False, 'message': 'لم يتم اختيار صورة'}), 400
        
        file = request.files['image']
        if file.filename == '':
            return jsonify({'success': False, 'message': 'اسم الملف فارغ'}), 400

        if file:
            filename = secure_filename(file.filename)
            filename = f"{int(cairo_now().timestamp())}_{filename}"
            save_uploaded_file(file, filename)

            # تحديث المنتج
            variant = ProductVariant.query.get(product_id)
            if variant:
                variant.model.image = filename
                db.session.commit()
                return jsonify({'success': True, 'message': 'تم تحديث الصورة بنجاح', 'image_url': f'/static/uploads/{filename}'})
            else:
                return jsonify({'success': False, 'message': 'المنتج غير موجود'}), 404

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/customers/add', methods=['POST'])
@login_required
def api_add_customer():
    try:
        data = request.get_json()
        name = data.get('name')
        phone = data.get('phone')
        address = data.get('address')

        if not name or not phone:
             return jsonify({'success': False, 'message': 'الاسم والهاتف مطلوبان'}), 400
        
        if Customer.query.filter_by(phone=phone).first():
            return jsonify({'success': False, 'message': 'رقم الهاتف مسجل مسبقاً'}), 400

        new_customer = Customer(
            name=name,
            phone=phone,
            address=address,
            created_by_id=current_user.id
        )
        db.session.add(new_customer)
        db.session.commit()

        return jsonify({
            'success': True, 
            'message': 'تم إضافة العميل بنجاح',
            'customer': {
                'id': new_customer.id,
                'name': new_customer.name,
                'phone': new_customer.phone
            }
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
@app.route('/expenses', methods=['GET', 'POST'])
@general_manager_required
def expenses():
    # 1. إضافة بند مصروف جديد
    if 'add_category' in request.form:
        cat_name = request.form.get('new_category_name')
        if cat_name:
            if not ExpenseCategory.query.filter_by(name=cat_name).first():
                db.session.add(ExpenseCategory(name=cat_name))
                db.session.commit()
                flash('تم إضافة البند', 'success')
        return redirect(url_for('expenses'))

    # 2. إضافة مصروف جديد
    if 'add_expense' in request.form:
        try:
            amount = float(request.form.get('amount'))
            description = request.form.get('description')
            cat_id = request.form.get('category_id')
            expense_type = request.form.get('expense_type')
            account_id = request.form.get('account_id') # الخزينة

            account = MoneyAccount.query.get(account_id)
            if not account:
                flash('يجب اختيار خزينة', 'danger'); return redirect(url_for('expenses'))

            # إنشاء كائن المصروف (مع حفظ رقم الخزينة)
            new_expense = Expense(
                category_id=cat_id,
                amount=amount,
                description=description,
                user_id=current_user.id,
                account_id=account.id # <--- هام جداً
            )

            # تحديد النوع
            if expense_type == 'partnership':
                # 1. الشراكة ( gm 50% - Abo_malek 50% )
                if "شراكة" not in description:
                    new_expense.description = f"{description} (شراكة)".strip()
                new_expense.is_shared = False

                gm = User.query.filter_by(username='gm').first() or User.query.filter_by(role='general_manager').first()
                abo_malek = User.query.filter_by(username='Abo_malek').first()
                
                half_amount = amount / 2
                if gm:
                    db.session.add(PartnerTransaction(
                        partner_id=gm.id, type='expense_share', amount=-half_amount,
                        description=f"مصروف شراكة 50%: {new_expense.description}", date=cairo_now()
                    ))
                if abo_malek:
                    db.session.add(PartnerTransaction(
                        partner_id=abo_malek.id, type='expense_share', amount=-half_amount,
                        description=f"مصروف شراكة 50%: {new_expense.description}", date=cairo_now()
                    ))

            elif expense_type == 'personal':
                # 2. حساب شخصي (لمدير محدد)
                partner_id = request.form.get('partner_id')
                new_expense.is_shared = False
                if partner_id:
                    partner = User.query.get(partner_id)
                    part_name = partner.fullname if partner else "غير معروف"
                    
                    # تنظيف الوصف من أي تاجات قديمة (شخصي، شراكة، مقسم) عشان لو اليوزر نسخ وصف قديم
                    clean_desc = re.sub(r'\(شخصي:.*?\)', '', description)
                    clean_desc = re.sub(r'\(شراكة\)', '', clean_desc)
                    clean_desc = re.sub(r'\(مقسم\)', '', clean_desc).strip()
                    
                    new_expense.description = f"{clean_desc} (شخصي: {part_name})".strip()
                        
                    db.session.add(PartnerTransaction(
                        partner_id=partner_id, type='personal_expense_share', amount=-amount,
                        description=f"مصروف شخصي: {clean_desc}", date=cairo_now()
                    ))

            elif expense_type == 'split_4':
                # 3. مقسم على 5: 20% لكل واحد (Ehab, SMSM, Elsayd, Abo_Eyad, Abo_malek)
                clean_desc = re.sub(r'\(شخصي:.*?\)', '', description)
                clean_desc = re.sub(r'\(شراكة\)', '', clean_desc)
                clean_desc = re.sub(r'\(مقسم\)', '', clean_desc).strip()

                new_expense.description = f"{clean_desc} (مقسم)".strip()
                new_expense.is_shared = False
                
                share_20 = amount / 5
                
                # 20% لكل شخص
                all_split_users = ['Elsayd_Elwekel', 'SMSM_Hamdy', 'Ehab_habls']
                for m_username in all_split_users:
                    mgr = User.query.filter_by(username=m_username).first()
                    if mgr:
                        db.session.add(PartnerTransaction(
                            partner_id=mgr.id, type='expense_share', amount=-share_20,
                            description=f"حصة (20%): {new_expense.description}", date=cairo_now()
                        ))
                
                # 20% أبو إياد + 20% أبو مالك
                gm = User.query.filter_by(username='gm').first() or User.query.filter_by(role='general_manager').first()
                abo_malek = User.query.filter_by(username='Abo_malek').first()
                
                if gm:
                    db.session.add(PartnerTransaction(
                        partner_id=gm.id, type='expense_share', amount=-share_20,
                        description=f"حصة (20%): {new_expense.description}", date=cairo_now()
                    ))
                if abo_malek:
                    db.session.add(PartnerTransaction(
                        partner_id=abo_malek.id, type='expense_share', amount=-share_20,
                        description=f"حصة (20%): {new_expense.description}", date=cairo_now()
                    ))

            # حفظ المصروف
            db.session.add(new_expense)

            # خصم الفلوس من الخزينة
            account.balance -= amount
            db.session.add(FinancialTransaction(
                account_id=account.id, type='expense', category='مصروفات',
                amount=-amount, description=f"صرف: {description}", created_by_id=current_user.id, date=cairo_now()
            ))

            db.session.commit()
            flash('تم تسجيل المصروف ✅', 'success')

        except Exception as e:
            db.session.rollback()
            flash(f'خطأ: {e}', 'danger')

        return redirect(url_for('expenses'))

    # العرض
    categories = ExpenseCategory.query.all()
    all_expenses = Expense.query.order_by(Expense.date.desc()).limit(100).all()
    partners = User.query.filter_by(role='manager').all()
    accounts = MoneyAccount.query.all()

    return render_template('expenses.html', categories=categories, expenses=all_expenses, partners=partners, accounts=accounts)
@app.route('/expenses/delete/<int:id>')
@general_manager_required
def delete_expense(id):
    try:
        exp = Expense.query.get_or_404(id)

        # 1. إرجاع الأموال للخزينة (إذا كانت الخزينة مسجلة)
        if exp.account_id:
            account = MoneyAccount.query.get(exp.account_id)
            if account:
                account.balance = round_half(account.balance + exp.amount) # رد المبلغ

                # تسجيل حركة "استرداد" في سجل الخزينة عشان الحساب يظبط
                db.session.add(FinancialTransaction(
                    account_id=account.id,
                    type='income', # دخل (استرداد)
                    category='استرداد مصروف',
                    amount=exp.amount,
                    description=f"إلغاء مصروف: {exp.description}",
                    created_by_id=current_user.id,
                    date=cairo_now()
                ))

        # 2. حذف التأثير على الشركاء (لو كان سحب أو مشترك)
        # هذا يتطلب بحث معقد قليلاً في PartnerTransaction،
        # للتبسيط الآن: سنقوم بحذف المصروف، وسنحتاج لتسوية حساب الشركاء يدوياً أو
        # (الأفضل) نضيف كود لحذف PartnerTransaction المرتبط، لكن بما أننا لم نربطهم بـ ID مباشر
        # سنكتفي برد الأموال للخزينة وحذف سجل المصروف.

        # ملاحظة: لإلغاء تأثير الشركاء بدقة، يفضل مستقبلاً ربط PartnerTransaction بـ Expense ID
        # حالياً سنقوم بحذف الـ PartnerTransaction الذي يتطابق تماماً مع وصف المصروف والمبلغ
        try:
            clean_desc = re.sub(r'\(شخصي:.*?\)', '', exp.description).strip()
            clean_desc = re.sub(r'\(شراكة\)', '', clean_desc).strip()
            clean_desc = re.sub(r'\(مقسم\)', '', clean_desc).strip()
            
            # The PartnerTransaction description depends on how it was created
            pt_desc1 = f"مصروف شراكة 50%: {exp.description}"
            pt_desc2 = f"مصروف شخصي: {clean_desc}"
            pt_desc3 = f"حصة (20%): {exp.description}"
            
            # Delete transactions that match the exact description and are related to this expense amount
            db.session.query(PartnerTransaction).filter(
                PartnerTransaction.description.in_([pt_desc1, pt_desc2, pt_desc3]),
                PartnerTransaction.amount.in_([-exp.amount, -exp.amount/2, -exp.amount/5])
            ).delete(synchronize_session=False)
        except Exception as e:
            pass

        # 3. حذف المصروف
        db.session.delete(exp)
        db.session.commit()

        flash('تم حذف المصروف ورد المبلغ للخزينة (وإلغاء الخصم من الشركاء إن وجد) ✅', 'success')

    except Exception as e:
        db.session.rollback()
        flash(f'حدث خطأ أثناء الحذف: {e}', 'danger')

    return redirect(url_for('expenses'))
@app.route('/purchases/new', methods=['GET', 'POST'])
@login_required
def new_purchase():
    if request.method == 'POST':
        supplier_id = request.form.get('supplier_id')

        # استقبال البيانات من الفورم كقوائم
        product_ids = request.form.getlist('product_id[]') # الحقل المخفي للـ ID
        names = request.form.getlist('name[]')
        costs = request.form.getlist('cost[]')
        sells = request.form.getlist('sell[]')
        qtys = request.form.getlist('qty[]')
        barcodes = request.form.getlist('barcode[]')
        categories = request.form.getlist('category[]')
        images = request.files.getlist('image[]')

        new_supp_name = request.form.get('new_supplier_name')
        new_supp_phone = request.form.get('new_supplier_phone')

        if not names:
            flash('لم يتم إدخال أصناف!', 'warning')
            return redirect(request.url)

        # 1. معالجة المورد (جديد أو موجود)
        if supplier_id == 'new' and new_supp_name:
            new_supp = Supplier(name=new_supp_name, phone=new_supp_phone)
            db.session.add(new_supp)
            db.session.flush()
            supplier = new_supp
        elif supplier_id and supplier_id != 'new':
            supplier = Supplier.query.get(supplier_id)
        else:
            # معالجة الخطأ إذا تم نسيان إدخال المورد تفادياً للاختفاء
            supplier = Supplier.query.filter_by(name="مورد غير محدد").first()
            if not supplier:
                supplier = Supplier(name="مورد غير محدد", phone="")
                db.session.add(supplier)
                db.session.flush()

        # 2. إنشاء رأس الفاتورة
        purchase_order = PurchaseOrder(created_by=current_user.id, total_cost=0.0, status='received')
        if supplier:
            purchase_order.supplier_id = supplier.id
        db.session.add(purchase_order)
        db.session.flush()

        total_invoice_cost = 0.0

        # 3. اللفة على المنتجات (Product Loop)
        for i in range(len(names)):
            p_name = names[i].strip()
            if not p_name: continue

            # معالجة الأرقام لتجنب أخطاء الإدخال
            try: cost = float(costs[i]) if costs[i].strip() else 0.0
            except: cost = 0.0
            try: sell = float(sells[i]) if sells[i].strip() else 0.0
            except: sell = 0.0
            try: qty = int(qtys[i]) if qtys[i].strip() else 0
            except: qty = 0

            p_id = product_ids[i] if i < len(product_ids) else ""
            p_barcode = barcodes[i].strip() if i < len(barcodes) else None
            if p_barcode == "": p_barcode = None

            p_category = categories[i].strip() if i < len(categories) else "عام"
            if not p_category: p_category = "عام"

            # معالجة الصورة المرفوعة
            image_filename = 'default_product.png'
            if i < len(images):
                file = images[i]
                if file and file.filename != '':
                    filename = secure_filename(file.filename)
                    # إضافة طابع زمني لاسم الصورة لمنع التداخل
                    filename = f"{int(cairo_now().timestamp())}_{filename}"
                    save_uploaded_file(file, filename)
                    image_filename = filename

            # أ) تحديد الكاتيجوري أولاً
            cat = Category.query.filter_by(name=p_category).first()
            if not cat:
                cat = Category(name=p_category)
                db.session.add(cat)
                db.session.flush()

            variant = None

            # ب) المنطق المطور للبحث (الاسم + الفئة)
            # 1. إذا كان هناك ID مرسل من الفورم (المستخدم اختار منتج موجود ولم يغير فئته)
            if p_id and p_id != "":
                variant = ProductVariant.query.get(p_id)

            # 2. إذا لم نجد بـ ID، نبحث بالباركود (لأنه فريد)
            if not variant and p_barcode:
                variant = ProductVariant.query.filter_by(barcode=p_barcode).first()

            # 3. إذا لم نجد، نبحث بالاسم داخل هذا التصنيف تحديداً
            if not variant:
                model = ProductModel.query.filter_by(name=p_name, category_id=cat.id).first()
                if model:
                    if model.variants:
                        variant = model.variants[0]
                    # تحديث الصورة لو تم رفع صورة جديدة لمنتج موجود
                    if image_filename != 'default_product.png':
                        model.image = image_filename
                else:
                    # ج) إنشاء منتج جديد تماماً (موديل + فارينت)
                    model = ProductModel(name=p_name, category_id=cat.id, image=image_filename)
                    db.session.add(model)
                    db.session.flush()

                    variant = ProductVariant(model_id=model.id, barcode=p_barcode, cost_price=cost, sell_price=sell, stock=0)
                    db.session.add(variant)
                    db.session.flush()

            # د) تحديث بيانات المخزون والأسعار
            if cost > 0: variant.cost_price = cost
            if sell > 0: variant.sell_price = sell
            variant.stock += qty

            # تسجيل حركة المخزون
            db.session.add(StockMovement(
                variant_id=variant.id,
                user_id=current_user.id,
                quantity_change=qty,
                reason=f"شراء فاتورة #{purchase_order.id}"
            ))

            # حساب إجمالي الفاتورة
            item_total = cost * qty
            total_invoice_cost += item_total

            db.session.add(PurchaseItem(
                purchase_id=purchase_order.id,
                variant_id=variant.id,
                quantity=qty,
                unit_cost=cost,
                total_cost=item_total
            ))

        # 4. تحديث إجماليات الفاتورة وحساب المورد
        purchase_order.total_cost = total_invoice_cost
        if supplier:
            supplier.balance += total_invoice_cost

        db.session.commit()

        flash(f'تم حفظ الفاتورة بنجاح ✅ (إجمالي: {total_invoice_cost} ج.م)', 'success')
        return redirect(url_for('inventory'))

    # عرض الصفحة (GET)
    return render_template('new_purchase.html',
                           suppliers=Supplier.query.all(),
                           categories=Category.query.all(),
                           product_suggestions=ProductVariant.query.all())
    # =========================================================
@app.route('/purchases/edit/<int:id>', methods=['GET', 'POST'])
@permission_required('manage_inventory')
def edit_purchase(id):
    order = PurchaseOrder.query.get_or_404(id)

    if request.method == 'POST':
        try:
            # 1. عكس التأثير القديم (إرجاع المخزون + إلغاء دين المورد)
            old_total_cost = order.total_cost
            if order.supplier:
                order.supplier.balance -= old_total_cost  # إلغاء الدين القديم

            for item in order.items:
                if item.variant:
                    item.variant.stock -= item.quantity  # سحب الكمية التي أضيفت سابقاً
                    # تسجيل حركة مخزون عكسية
                    db.session.add(StockMovement(
                        variant_id=item.variant.id,
                        user_id=current_user.id,
                        quantity_change=-item.quantity,
                        reason=f"تعديل فاتورة شراء #{order.id} (تصحيح)"
                    ))

            # حذف الأصناف القديمة
            PurchaseItem.query.filter_by(purchase_id=order.id).delete()

            # 2. إضافة الأصناف الجديدة (نفس منطق الشراء الجديد)
            names = request.form.getlist('name[]')
            costs = request.form.getlist('cost[]')
            qtys = request.form.getlist('qty[]')

            # تحديث المورد لو تغير
            new_supplier_id = request.form.get('supplier_id')
            if new_supplier_id:
                order.supplier_id = new_supplier_id

            new_total_cost = 0.0

            for i in range(len(names)):
                p_name = names[i].strip()
                if not p_name: continue

                try: cost = float(costs[i]) if costs[i].strip() else 0.0
                except: cost = 0.0
                try: qty = int(qtys[i]) if qtys[i].strip() else 0
                except: qty = 0

                if qty <= 0: continue

                # البحث عن المنتج بالاسم (لأنه موجود بالفعل)
                model = ProductModel.query.filter_by(name=p_name).first()
                if model and model.variants:
                    variant = model.variants[0]

                    # تحديث التكلفة والمخزون
                    variant.cost_price = cost
                    variant.stock += qty

                    # تسجيل حركة المخزون الجديدة
                    db.session.add(StockMovement(
                        variant_id=variant.id,
                        user_id=current_user.id,
                        quantity_change=qty,
                        reason=f"تعديل فاتورة شراء #{order.id} (إضافة)"
                    ))

                    item_total = cost * qty
                    new_total_cost += item_total

                    db.session.add(PurchaseItem(
                        purchase_id=order.id,
                        variant_id=variant.id,
                        quantity=qty,
                        unit_cost=cost,
                        total_cost=item_total
                    ))

            # 3. تحديث إجماليات الفاتورة وحساب المورد
            order.total_cost = new_total_cost
            if order.supplier:
                order.supplier.balance += new_total_cost # إضافة الدين الجديد

            db.session.commit()
            flash(f'تم تعديل فاتورة الشراء بنجاح ✅ (الإجمالي الجديد: {new_total_cost})', 'success')
            return redirect(url_for('purchase_details', id=order.id))

        except Exception as e:
            db.session.rollback()
            flash(f'حدث خطأ: {e}', 'danger')
            return redirect(request.url)

    return render_template('edit_purchase.html', order=order, suppliers=Supplier.query.all())
# ==========================================
# ===   نظام مسير الرواتب (Payroll)    ===
# ==========================================


@app.route('/api/pay_salary', methods=['POST'])
@login_required
def pay_salary():
    # 1. التحقق من الصلاحية (HR أو المدير العام)
    if not current_user.has_perm('manage_hr') and current_user.role != 'general_manager':
        return jsonify({'success': False, 'message': 'غير مصرح'}), 403

    try:
        # 2. استقبال البيانات من الطلب (بما فيها العمولة والشهر)
        user_id = request.form.get('user_id')
        net_payout = float(request.form.get('amount')) # المبلغ الصافي اللي الموظف هياخده في إيده
        commission_val = float(request.form.get('commission_amount', 0)) # قيمة العمولة فقط
        month_context = request.form.get('month', '') # مثال: 2026-01
        account_id = request.form.get('account_id') # رقم الخزينة

        # 3. التحقق من الموظف والخزينة
        employee = User.query.get(user_id)
        if not employee:
            return jsonify({'success': False, 'message': 'الموظف غير موجود'}), 404

        account = MoneyAccount.query.get(account_id)
        if not account:
            return jsonify({'success': False, 'message': 'يجب اختيار خزينة صحيحة'}), 400

        # 4. معالجة الخزينة: خصم المبلغ الصافي وتسجيل الحركة المالية
        account.balance = round_half(account.balance - net_payout)
        db.session.add(FinancialTransaction(
            account_id=account.id,
            type='expense',
            category='رواتب',
            amount=-net_payout,
            description=f"صرف راتب شهر {month_context} للموظف {employee.fullname}",
            created_by_id=current_user.id,
            date=cairo_now()
        ))

        # 5. تسجيل الحركة في ملف الموظف (لإخفاء زر الصرف لاحقاً)
        db.session.add(HRTransaction(
            user_id=user_id,
            type='salary_payment',
            amount=net_payout,
            note=f"صرف راتب شهر {month_context}" if month_context else "صرف راتب شهري",
            date=cairo_now()
        ))

        # 6. توزيع الخصم المالي على حسابات الشركاء حسب salary_method بتاع الموظف
        # العمولة اتحسبت أصلاً كـ sub_commission بعد كل فاتورة
        # فنخصمها من المبلغ المحمل على المدير عشان متتحسبش مرتين
        desc = f"راتب {employee.fullname} — {month_context}"
        if employee.role not in ('manager', 'general_manager') and commission_val > 0:
            salary_for_partner = net_payout - commission_val
            _record_partner_salary_expense(employee, salary_for_partner, desc + f" [بدون عمولة {int(commission_val)}]", db.session)
        else:
            _record_partner_salary_expense(employee, net_payout, desc, db.session)

        # 7. تسجيل المصروف في سجل الشركة العام (Reference Only)
        # ملاحظة: is_shared=False لأن المبلغ خُصم بالفعل من الشركاء في الخطوة السابقة
        sal_cat = ExpenseCategory.query.filter_by(name="رواتب").first()
        if not sal_cat:
            sal_cat = ExpenseCategory(name="رواتب")
            db.session.add(sal_cat)
            db.session.flush()

        smart_description = _generate_expense_description(employee, month_context)

        db.session.add(Expense(
            category_id=sal_cat.id,
            amount=net_payout,
            description=smart_description,
            date=cairo_now(),
            user_id=current_user.id,
            is_shared=False,
            account_id=account.id
        ))

        # 8. حفظ كافة التغييرات
        db.session.commit()
        return jsonify({'success': True, 'message': 'تم صرف الراتب وتوزيعه محاسبياً بدقة ✅'})

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'حدث خطأ غير متوقع: {str(e)}'}), 500
@app.route('/purchases/<int:id>')
@permission_required('manage_inventory')
def purchase_details(id):
    return render_template('purchase_details.html', order=PurchaseOrder.query.get_or_404(id), suppliers=Supplier.query.all())

@app.route('/purchases/change_supplier', methods=['POST'])
@permission_required('manage_inventory')
def change_purchase_supplier():
    try:
        order_id = request.form.get('order_id')
        new_supplier_id = request.form.get('new_supplier_id')

        order = PurchaseOrder.query.get_or_404(order_id)
        new_supplier = Supplier.query.get_or_404(new_supplier_id)

        # خصم الرصيد من المورد القديم
        if order.supplier and order.total_cost:
            order.supplier.balance -= order.total_cost

        # إضافة الرصيد للمورد الجديد
        if order.total_cost:
            new_supplier.balance += order.total_cost

        # تغيير المورد
        order.supplier_id = new_supplier.id
        db.session.commit()

        flash(f'تم نقل فاتورة الشراء #{order.id} للمورد "{new_supplier.name}" بنجاح ✅', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'حدث خطأ: {e}', 'danger')

    return redirect(url_for('purchase_details', id=order_id))

@app.route('/reports')
@login_required
def reports_hub():
    # 1. التحقق من صلاحية رؤية التقارير
    if not current_user.has_perm('view_reports'):
        flash('غير مصرح لك بدخول التقارير', 'danger')
        return redirect(url_for('dashboard'))

    # 2. جلب قائمة المستخدمين المسموح برؤية بياناتهم
    accessible_ids = get_accessible_users()

    report_type = request.args.get('type', 'sales')

    # === إعداد تواريخ الفلتر ===
    today = date.today()
    # الافتراضي: من أول الشهر الحالي إلى اليوم
    default_start = today.replace(day=1).strftime('%Y-%m-%d')
    default_end = today.strftime('%Y-%m-%d')

    start_date_str = request.args.get('start_date', default_start)
    end_date_str = request.args.get('end_date', default_end)

    data = {}
    chart = {'labels': [], 'values': [], 'type': 'bar'}

    # === تقرير المبيعات (Sales) ===
    # === تقرير المبيعات (Sales) ===
    if report_type == 'sales':
        # فلتر أساسي للفترة المحددة
        base_filters = [
            SaleOrder.is_proforma == False,
            SaleOrder.user_id.in_(accessible_ids),
            cast(SaleOrder.date, Date) >= start_date_str,
            cast(SaleOrder.date, Date) <= end_date_str
        ]

        # 1. إجمالي المبيعات
        total_sales = db.session.query(func.sum(SaleOrder.final_total)).filter(*base_filters).scalar() or 0

        # 2. عدد الفواتير
        orders_count = SaleOrder.query.filter(*base_filters).count()

        # 3. إجمالي الخصومات
        total_discounts = db.session.query(func.sum(SaleOrder.discount)).filter(*base_filters).scalar() or 0

        # 4. [الجديد] إجمالي عدد القطع المباعة
        total_items_sold = db.session.query(func.sum(SaleItem.quantity))\
            .join(SaleOrder)\
            .filter(*base_filters)\
            .scalar() or 0

        # المنتجات الأكثر مبيعاً
        top_products = db.session.query(ProductModel.name, func.sum(SaleItem.quantity).label('qty'), func.sum(SaleItem.total_price).label('rev'))\
            .select_from(ProductModel).join(ProductVariant).join(SaleItem).join(SaleOrder)\
            .filter(*base_filters)\
            .group_by(ProductModel.name).order_by(text('qty DESC')).limit(10).all()

        discount_orders = SaleOrder.query.filter(SaleOrder.discount > 0, *base_filters).order_by(SaleOrder.date.desc()).limit(20).all()

        data = {
            'total_sales': total_sales,
            'orders_count': orders_count,
            'total_discount': total_discounts,
            'total_items_sold': int(total_items_sold), # <--- تم الإرسال هنا
            'top_products': top_products,
            'discount_orders': discount_orders
        }

        if top_products:
            chart = {'labels': [p.name for p in top_products[:5]], 'values': [p.qty for p in top_products[:5]], 'type': 'bar'}
    elif report_type == 'inventory':
        # 1. القيمة المالية
        total_cost_value = db.session.query(func.sum(ProductVariant.stock * ProductVariant.cost_price)).filter(ProductVariant.stock > 0).scalar() or 0
        total_sell_value = db.session.query(func.sum(ProductVariant.stock * ProductVariant.sell_price)).filter(ProductVariant.stock > 0).scalar() or 0
        expected_profit = total_sell_value - total_cost_value

        # 2. الإحصائيات
        total_items_count = db.session.query(func.sum(ProductVariant.stock)).filter(ProductVariant.stock > 0).scalar() or 0

        # منتجات نفذت (0 أو سالب)
        out_of_stock_count = ProductVariant.query.filter(ProductVariant.stock <= 4).count()

        # 3. [تصحيح] قائمة التنبيهات (تشمل النواقص + اللي خلص)
        # بنرتب تصاعدي عشان اللي رصيده 0 أو سالب يظهر الأول
        low_stock_items = db.session.query(ProductModel.name, ProductVariant.stock)\
            .join(ProductVariant)\
            .filter(ProductVariant.stock <= 5)\
            .order_by(ProductVariant.stock.asc())\
            .limit(50).all() # نعرض أهم 50 صنف فقط عشان الصفحة متبقاش طويلة

        # 4. الأكثر توفراً
        top_stock = db.session.query(ProductModel.name, ProductVariant.stock)\
            .join(ProductVariant).filter(ProductVariant.stock > 0)\
            .order_by(ProductVariant.stock.desc()).limit(10).all()

        data = {
            'total_cost_value': total_cost_value,
            'total_sell_value': total_sell_value,
            'expected_profit': expected_profit,
            'total_items': total_items_count,
            'low_stock_items': low_stock_items,
            'out_of_stock_count': out_of_stock_count,
            'top_stock': top_stock
        }

        if top_stock:
            chart = {
                'labels': [p[0] for p in top_stock[:10]],
                'values': [p[1] for p in top_stock[:10]],
                'type': 'bar'
            }
    # === التقرير المالي (Finance) ===
    # === تقرير الحضور والانصراف (Attendance) - الإضافة الجديدة ===
    elif report_type == 'attendance':
        # جلب السجلات في الفترة المحددة
        query = Attendance.query.filter(
            cast(Attendance.date, Date) >= start_date_str,
            cast(Attendance.date, Date) <= end_date_str
        )

        # ترتيب النتائج
        records = query.order_by(Attendance.date.desc(), Attendance.check_in.asc()).all()

        # إحصائيات سريعة
        total_present = len(records)
        total_late = sum(1 for r in records if r.status == 'late')

        # تجميع ساعات العمل
        total_seconds = 0
        attendance_list = []

        for r in records:
            work_hours_str = "---"
            if r.check_in and r.check_out:
                diff = r.check_out - r.check_in
                seconds = diff.total_seconds()
                total_seconds += seconds

                h = int(seconds // 3600)
                m = int((seconds % 3600) // 60)
                work_hours_str = f"{h}س {m}د"

            attendance_list.append({
                'id': r.id,
                'user': r.user.fullname,
                'role': r.user.role,
                'date': r.date,
                'check_in': r.check_in,
                'check_out': r.check_out,
                'status': r.status,
                'is_excused': getattr(r, 'is_excused', False),
                'work_hours': work_hours_str,
                'user_shift_start': r.user.shift_start,
                'user_shift_end': r.user.shift_end
            })

        total_hours_sum = int(total_seconds // 3600)

        data = {
            'records': attendance_list,
            'stats': {
                'total_present': total_present,
                'total_late': total_late,
                'total_hours': total_hours_sum
            }
        }
    elif report_type == 'finance':
        # 1. حساب مجمل الربح (Gross Profit) للفترة المحددة
        sales_condition = [
            SaleOrder.is_proforma == False,
            or_(SaleOrder.is_shipping == False, SaleOrder.shipping_status == 'settled'),
            SaleOrder.user_id.in_(accessible_ids),
            cast(SaleOrder.date, Date) >= start_date_str,
            cast(SaleOrder.date, Date) <= end_date_str
        ]

        total_rev = db.session.query(func.sum(SaleOrder.final_total - SaleOrder.shipping_fee)).filter(*sales_condition).scalar() or 0
        total_cogs = db.session.query(func.sum(SaleItem.quantity * ProductVariant.cost_price)).join(SaleOrder).filter(*sales_condition).join(ProductVariant).scalar() or 0
        gross = total_rev - total_cogs

        # 2. تحليل المصروفات
        all_expenses = Expense.query.filter(
            cast(Expense.date, Date) >= start_date_str,
            cast(Expense.date, Date) <= end_date_str
        ).all()

        categories_data = {}

        def get_cat(name, icon='file-invoice-dollar', color='primary'):
            if name not in categories_data:
                categories_data[name] = {'total': 0, 'transactions': [], 'icon': icon, 'color': color}
            return categories_data[name]

        for exp in all_expenses:
            cat_name = exp.category.name if exp.category else "غير مصنف"
            c = get_cat(cat_name, 'tags', 'dark')
            
            c['total'] += exp.amount
            
            # تحديد نوع الخصم من الوصف
            desc = exp.description if exp.description else ""
            deduction_type = "عام"
            if "شراكة" in desc or "50%" in desc: deduction_type = "شراكة 50/50"
            elif "مقسم" in desc: deduction_type = "مقسم على الإدارة"
            elif "شخصي" in desc: deduction_type = "شخصي (مدير معين)"

            c['transactions'].append({
                'date': exp.date.strftime('%Y-%m-%d %H:%M') if exp.date else '---',
                'desc': desc.replace('(شراكة)', '').replace('(مقسم)', '').strip(),
                'amount': exp.amount,
                'type': deduction_type,
                'by': exp.created_by.fullname if exp.created_by else '---',
                'account': getattr(exp.account, 'name', '---') if hasattr(exp, 'account') and exp.account else '---',
            })

        # (تم إزالة دمج مصاريف التشغيل من PartnerTransaction و HRTransaction بناء على طلب المستخدم لتجنب التكرار ولعرض مسحوبات الخزينة الفعلية فقط)

        # تجهيز القائمة النهائية (ترتيب حسب المبلغ)
        expenses_by_type = []
        for name, data in categories_data.items():
            if data['total'] > 0:
                type_groups = {}
                for trx in data['transactions']:
                    t_type = trx['type']
                    if t_type not in type_groups:
                        type_groups[t_type] = {'total': 0, 'transactions': [], 'id': str(hash(name + t_type)).replace('-', '')}
                    type_groups[t_type]['transactions'].append(trx)
                    type_groups[t_type]['total'] += trx['amount']
                
                sorted_type_groups = []
                for tg_name, tg_data in type_groups.items():
                    tg_data['transactions'].sort(key=lambda x: x['date'], reverse=True)
                    sorted_type_groups.append({
                        'name': tg_name,
                        'total': round_half(tg_data['total']),
                        'transactions': tg_data['transactions'],
                        'id': tg_data['id']
                    })
                
                sorted_type_groups.sort(key=lambda x: x['total'], reverse=True)

                expenses_by_type.append({
                    'id': str(hash(name)).replace('-', ''),
                    'name': name,
                    'amount': round_half(data['total']),
                    'color': data['color'],
                    'icon': data['icon'],
                    'transactions': sorted(data['transactions'], key=lambda x: x['date'], reverse=True),
                    'type_groups': sorted_type_groups
                })
        
        expenses_by_type.sort(key=lambda x: x['amount'], reverse=True)

        # تجهيز توزيع مصروفات الخزينة حسب الشخص لكل تصنيف
        treasury_total = 0
        treasury_breakdown = []  # قائمة التصنيفات مع توزيع الأشخاص
        
        import re
        def extract_beneficiary(description):
            """استخراج المستفيد الفعلي (أو جهة الخصم) من وصف المصروف"""
            if not description:
                return "غير محدد"
            desc = description.strip()
            
            # 1. المخصوم على شخص محدد (مدير معين)
            match = re.search(r'\(شخصي[:\s]+([^)]+)\)', desc)
            if match:
                return match.group(1).strip()
            
            # 2. الشراكة (على الخزينة العامة للشركاء)
            if '(شراكة)' in desc or 'شراكة' in desc:
                return "شراكة (مشترك)"
            
            # 3. مقسم على الإدارة
            if '(مقسم)' in desc or 'مقسم' in desc:
                return "مقسم على الإدارة"
            
            # 4. لو لم نجد أي تصنيف مالي، نحاول استخراج اسم الموظف إذا كان راتب (كحل أخير)
            match = re.search(r'صرف راتب[:\s]+([^(]+)', desc)
            if match:
                # لو فيه اسم موظف بس مش متحدد مقسم ولا شراكة، هنرجعه زي ما هو
                return match.group(1).strip()
            
            # افتراضي
            return "عام"
        
        treasury_cat_temp = {}
        for exp in all_expenses:
            cat_name = exp.category.name if exp.category else "غير مصنف"
            person_name = extract_beneficiary(exp.description)
            
            if cat_name not in treasury_cat_temp:
                treasury_cat_temp[cat_name] = {'total': 0, 'persons': {}, 'transactions': []}
            
            tc = treasury_cat_temp[cat_name]
            tc['total'] += exp.amount
            treasury_total += exp.amount
            
            # تجميع حسب المستفيد
            if person_name not in tc['persons']:
                tc['persons'][person_name] = {'total': 0, 'transactions': []}
            tc['persons'][person_name]['total'] += exp.amount
            tc['persons'][person_name]['transactions'].append({
                'date': exp.date.strftime('%Y-%m-%d') if exp.date else '---',
                'desc': exp.description or '---',
                'amount': exp.amount,
                'account': getattr(exp.account, 'name', '---') if hasattr(exp, 'account') and exp.account else '---',
            })

        for cat_name, cat_data in treasury_cat_temp.items():
            if cat_data['total'] > 0:
                persons_list = []
                for p_name, p_data in cat_data['persons'].items():
                    p_data['transactions'].sort(key=lambda x: x['date'], reverse=True)
                    persons_list.append({
                        'name': p_name,
                        'total': round_half(p_data['total']),
                        'percentage': round((p_data['total'] / cat_data['total']) * 100, 1) if cat_data['total'] > 0 else 0,
                        'transactions': p_data['transactions'],
                        'id': str(abs(hash(cat_name + p_name)))
                    })
                persons_list.sort(key=lambda x: x['total'], reverse=True)
                
                treasury_breakdown.append({
                    'id': str(abs(hash(cat_name))),
                    'name': cat_name,
                    'total': round_half(cat_data['total']),
                    'persons': persons_list,
                    'person_labels': [p['name'] for p in persons_list],
                    'person_values': [p['total'] for p in persons_list]
                })
        
        treasury_breakdown.sort(key=lambda x: x['total'], reverse=True)

        # 4. تجميع بيانات الرسم البياني
        chart = {'labels': [], 'values': [], 'type': 'pie'}
        total_exp = sum(x['amount'] for x in expenses_by_type)
        
        for ext in expenses_by_type[:10]: # نظهر أول 10 بس في الشارت عشان الزحمة
            chart['labels'].append(ext['name'])
            chart['values'].append(ext['amount'])

        # 5. الحسابات النهائية للصافي
        net = gross - total_exp

        data = {
            'gross_profit': round_half(gross),
            'total_expenses': round_half(total_exp),
            'net_profit': round_half(net),
            'expenses_by_type': expenses_by_type,
            'treasury_breakdown': treasury_breakdown,
            'treasury_total': round_half(treasury_total),
            'chart': chart
        }


    # === تقرير الموردين (Suppliers) ===
    elif report_type == 'suppliers':
        # الديون تراكمية (لا تتأثر بالتاريخ)
        suppliers_debt = db.session.query(Supplier).filter(Supplier.balance != 0).order_by(Supplier.balance.desc()).all()
        total_debt = sum([s.balance for s in suppliers_debt if s.balance > 0])

        # المشتريات (تتأثر بالتاريخ)
        top_suppliers = db.session.query(Supplier.name, func.count(PurchaseOrder.id).label('orders_count'), func.sum(PurchaseOrder.total_cost).label('total_purchases'))\
            .join(PurchaseOrder)\
            .filter(cast(PurchaseOrder.date, Date) >= start_date_str, cast(PurchaseOrder.date, Date) <= end_date_str)\
            .group_by(Supplier.id).order_by(text('total_purchases DESC')).limit(5).all()

        data = {'suppliers_debt': suppliers_debt, 'total_debt': total_debt, 'top_suppliers': top_suppliers}
        if top_suppliers: chart = {'labels': [s.name for s in top_suppliers], 'values': [s.total_purchases for s in top_suppliers], 'type': 'doughnut'}

    # === تقرير الموارد البشرية (HR) ===
    elif report_type == 'hr':
        sales_reps = User.query.filter(User.id.in_(accessible_ids)).all()
        hr_report = []
        for emp in sales_reps:
            # فلترة المبيعات والطلبات والقطع بالتاريخ
            date_filter = [
                SaleOrder.user_id == emp.id,
                SaleOrder.is_proforma == False,
                cast(SaleOrder.date, Date) >= start_date_str,
                cast(SaleOrder.date, Date) <= end_date_str
            ]

            total_sales = db.session.query(func.sum(SaleOrder.final_total)).filter(*date_filter).scalar() or 0
            orders_count = SaleOrder.query.filter(*date_filter).count()

            # حساب إجمالي القطع المباعة (Gross)
            gross_items = db.session.query(func.sum(SaleItem.quantity))\
                .join(SaleOrder)\
                .filter(*date_filter).scalar() or 0

            # حساب المرتجعات لنفس الموظف خلال نفس الفترة
            returned_items = db.session.query(func.sum(ReturnInvoice.total_qty))\
                .join(SaleOrder)\
                .filter(SaleOrder.user_id == emp.id,
                        cast(ReturnInvoice.date, Date) >= start_date_str,
                        cast(ReturnInvoice.date, Date) <= end_date_str).scalar() or 0
            
            # صافي القطع هو الرقم الصحيح
            total_items = max(0, gross_items - returned_items)

            # حساب العمولة بناءً على الصافي
            commission = calculate_user_commission(emp, total_items, total_items)

            hr_report.append({
                'name': emp.fullname, 'role': emp.role, 'sales': total_sales,
                'orders': orders_count, 'items_count': int(total_items), 'commission': commission
            })
        data = {'hr_report': hr_report}

    # === تقرير العملاء (CRM) ===
    elif report_type == 'crm':
        # العملاء الأكثر شراءً (في الفترة المحددة)
        top_customers = db.session.query(Customer.name, func.count(SaleOrder.id).label('visits'), func.sum(SaleOrder.final_total).label('spent'))\
            .join(SaleOrder)\
            .filter(SaleOrder.is_proforma==False, SaleOrder.user_id.in_(accessible_ids))\
            .filter(cast(SaleOrder.date, Date) >= start_date_str, cast(SaleOrder.date, Date) <= end_date_str)\
            .group_by(Customer.id).order_by(text('spent DESC')).limit(10).all()

        # العملاء الجدد (في الفترة المحددة)
        new_customers = Customer.query.filter(
            cast(Customer.created_at, Date) >= start_date_str,
            cast(Customer.created_at, Date) <= end_date_str,
            Customer.created_by_id.in_(accessible_ids)
        ).count()

        # تحليل السلة (معقد للفلترة بالتاريخ مع SQL مباشر، سنتركه عاماً للتسهيل أو يمكن إضافة شرط التاريخ في جملة SQL)
        sql = text("SELECT p1.name as p1_name, p2.name as p2_name, COUNT(*) as frequency FROM sale_item i1 JOIN sale_item i2 ON i1.order_id = i2.order_id JOIN sale_order o ON i1.order_id = o.id JOIN product_variant v1 ON i1.variant_id = v1.id JOIN product_variant v2 ON i2.variant_id = v2.id JOIN product_model p1 ON v1.model_id = p1.id JOIN product_model p2 ON v2.model_id = p2.id WHERE i1.variant_id < i2.variant_id AND o.is_proforma = 0 GROUP BY p1.name, p2.name ORDER BY frequency DESC LIMIT 5")
        market_basket = db.session.execute(sql).fetchall()

        data = {'top_customers': top_customers, 'market_basket': market_basket, 'new_customers': new_customers}
        if top_customers: chart = {'labels': [c.name for c in top_customers[:5]], 'values': [c.spent for c in top_customers[:5]], 'type': 'pie'}

    # === تقرير المديرين (Managers) ===
    elif report_type == 'managers':
        managers = User.query.filter(User.role.in_(['manager', 'general_manager']),
                                      User.username.notin_(['Abo_Eyad', 'Abo_malek'])).all()
        managers_report = []
        grand_total_items = 0
        grand_total_profit = 0
        grand_total_comm = 0
        grand_total_net = 0

        for mgr in managers:
            # جلب أعضاء الفريق
            team_users = User.query.filter(db.or_(User.id == mgr.id, User.manager_id == mgr.id)).all()
            team_ids = [u.id for u in team_users]

            # عدد القطع المباعة من الفريق في الفترة
            items_sold = db.session.query(func.sum(SaleItem.quantity))\
                .join(SaleOrder)\
                .filter(SaleOrder.is_proforma == False,
                        SaleOrder.user_id.in_(team_ids),
                        cast(SaleOrder.date, Date) >= start_date_str,
                        cast(SaleOrder.date, Date) <= end_date_str).scalar() or 0

            # ربح الشركة من مبيعات الفريق (سعر البيع - سعر التكلفة)
            company_profit = db.session.query(
                func.sum(SaleItem.quantity * (SaleItem.unit_price - ProductVariant.cost_price))
            ).join(SaleOrder)\
             .join(ProductVariant, SaleItem.variant_id == ProductVariant.id)\
             .filter(SaleOrder.is_proforma == False,
                     SaleOrder.user_id.in_(team_ids),
                     cast(SaleOrder.date, Date) >= start_date_str,
                     cast(SaleOrder.date, Date) <= end_date_str).scalar() or 0.0

            # العمولات (14 جنيه × عدد القطع)
            commissions = items_sold * 14

            # صافي ربح الشركة من هذا المدير
            net_profit = company_profit - commissions

            grand_total_items += items_sold
            grand_total_profit += company_profit
            grand_total_comm += commissions
            grand_total_net += net_profit

            managers_report.append({
                'name': mgr.fullname,
                'items_sold': int(items_sold),
                'company_profit': round_half(company_profit),
                'commissions': round_half(commissions),
                'net_profit': round_half(net_profit)
            })

        # ترتيب من الأعلى ربحاً للأقل
        managers_report.sort(key=lambda x: x['net_profit'], reverse=True)

        data = {
            'managers_report': managers_report,
            'grand_total_items': grand_total_items,
            'grand_total_profit': round_half(grand_total_profit),
            'grand_total_comm': round_half(grand_total_comm),
            'grand_total_net': round_half(grand_total_net)
        }
        if managers_report:
            chart = {
                'labels': [m['name'] for m in managers_report],
                'values': [m['net_profit'] for m in managers_report],
                'type': 'bar'
            }

    elif report_type == 'product_tracking':
        # جلب كل المنتجات للبحث
        all_variants = ProductVariant.query.join(ProductModel).order_by(ProductModel.name).all()
        data['all_variants'] = [{
            'id': v.id,
            'name': v.model.name,
            'barcode': v.barcode or '',
            'category': v.model.category.name if v.model.category else '',
            'stock': v.stock,
            'cost': v.cost_price or 0,
            'sell': v.sell_price or 0
        } for v in all_variants]

    # تمرير التواريخ للقالب لعرضها في الفلتر
    return render_template('reports_hub.html', type=report_type, data=data, chart=chart, start_date=start_date_str, end_date=end_date_str)

@app.route('/product/<int:variant_id>/profile')
@login_required
def product_profile(variant_id):
    if not current_user.has_perm('view_reports') and not current_user.has_perm('view_inventory'):
        flash('غير مصرح لك', 'danger')
        return redirect(url_for('dashboard'))

    variant = ProductVariant.query.get_or_404(variant_id)
    model = variant.model

    # 1. المشتريات
    purchases = PurchaseItem.query.filter_by(variant_id=variant.id)\
        .join(PurchaseOrder).order_by(PurchaseOrder.date.desc()).all()
    
    total_purchased = sum(p.quantity for p in purchases)
    total_purchase_cost = sum(p.total_cost or (p.quantity * p.unit_cost) for p in purchases)

    purchase_entries = []
    for p in purchases:
        po = p.purchase_order
        purchase_entries.append({
            'type': 'purchase',
            'date': po.date,
            'date_str': po.date.strftime('%Y-%m-%d %H:%M') if po.date else '---',
            'quantity': p.quantity,
            'unit_price': p.unit_cost,
            'total': p.total_cost or (p.quantity * p.unit_cost),
            'ref': f'طلبية شراء #{po.id}',
            'detail': po.supplier.name if po.supplier else '---',
            'icon': 'box',
            'color': 'primary'
        })

    # 2. المبيعات
    sales = SaleItem.query.filter_by(variant_id=variant.id)\
        .join(SaleOrder).filter(SaleOrder.is_proforma == False)\
        .order_by(SaleOrder.date.desc()).all()
    
    total_sold = sum(s.quantity for s in sales)
    total_revenue = sum(s.total_price or (s.quantity * s.unit_price) for s in sales)
    total_profit = sum(s.quantity * (s.unit_price - (variant.cost_price or 0)) for s in sales)

    sale_entries = []
    for s in sales:
        o = s.order
        sale_entries.append({
            'type': 'sale',
            'date': o.date,
            'date_str': o.date.strftime('%Y-%m-%d %H:%M') if o.date else '---',
            'quantity': s.quantity,
            'unit_price': s.unit_price,
            'total': s.total_price or (s.quantity * s.unit_price),
            'ref': f'فاتورة #{o.id}',
            'detail': f"{o.customer.name if o.customer else 'عميل نقدي'} — بواسطة: {o.sales_rep.fullname if o.sales_rep else '---'}",
            'icon': 'shopping-cart',
            'color': 'success'
        })

    # 3. المرتجعات (عبر ReturnInvoice المرتبطة بالفواتير التي تحتوي على هذا المنتج)
    return_entries = []
    total_returned = 0
    # نجيب كل فواتير المرتجع المرتبطة بفواتير تحتوي على هذا المنتج
    sale_order_ids = list(set(s.order_id for s in sales))
    if sale_order_ids:
        returns = ReturnInvoice.query.filter(ReturnInvoice.order_id.in_(sale_order_ids))\
            .order_by(ReturnInvoice.date.desc()).all()
        for r in returns:
            total_returned += r.total_qty or 0
            return_entries.append({
                'type': 'return',
                'date': r.date,
                'date_str': r.date.strftime('%Y-%m-%d %H:%M') if r.date else '---',
                'quantity': r.total_qty or 0,
                'unit_price': 0,
                'total': r.total_deduction or 0,
                'ref': f'مرتجع فاتورة #{r.order_id}',
                'detail': r.notes or '---',
                'icon': 'undo',
                'color': 'warning'
            })

    # 4. حركات المخزون
    movements = StockMovement.query.filter_by(variant_id=variant.id)\
        .order_by(StockMovement.timestamp.desc()).all()
    
    movement_entries = []
    for m in movements:
        movement_entries.append({
            'type': 'movement',
            'date': m.timestamp,
            'date_str': m.timestamp.strftime('%Y-%m-%d %H:%M') if m.timestamp else '---',
            'quantity': m.quantity_change,
            'unit_price': 0,
            'total': 0,
            'ref': m.reason or 'حركة مخزون',
            'detail': m.user.fullname if m.user else '---',
            'icon': 'exchange-alt',
            'color': 'info'
        })

    # 5. دمج كل الحركات وترتيبها زمنياً
    all_events = purchase_entries + sale_entries + return_entries + movement_entries
    all_events.sort(key=lambda x: x['date'] if x['date'] else datetime.min, reverse=True)

    return render_template('product_profile.html',
        variant=variant,
        model=model,
        stats={
            'total_purchased': total_purchased,
            'total_purchase_cost': round_half(total_purchase_cost),
            'total_sold': total_sold,
            'total_revenue': round_half(total_revenue),
            'total_profit': round_half(total_profit),
            'total_returned': total_returned,
            'current_stock': variant.stock
        },
        events=all_events
    )

@app.route('/inventory')
@permission_required('view_inventory')
def inventory(): return render_template('inventory.html', products=ProductVariant.query.all(), user=current_user, categories=Category.query.all())

@app.route('/product/edit/<int:id>', methods=['POST'])
@permission_required('manage_inventory')
def edit_product(id):
    var = ProductVariant.query.get_or_404(id)
    var.model.name = request.form['name']; var.cost_price = float(request.form['cost']); var.sell_price = float(request.form['sell'])
    new_stock = int(request.form['stock']); diff = new_stock - var.stock
    # تحديث الصورة لو موجودة
    if 'image' in request.files:
        file = request.files['image']
        if file and file.filename != '':
            filename = secure_filename(file.filename)
            save_uploaded_file(file, filename)
            var.model.image = filename
    if diff != 0: var.stock = new_stock; db.session.add(StockMovement(variant_id=var.id, user_id=current_user.id, quantity_change=diff, reason="تعديل يدوي"))
    db.session.commit(); return redirect(url_for('inventory'))
@app.route('/hr/attendance_report')
@login_required
def attendance_report():
    # التحقق من الصلاحية
    if not current_user.has_perm('manage_hr') and current_user.role != 'general_manager':
        flash('غير مصرح لك', 'danger')
        return redirect(url_for('dashboard'))

    # الفلاتر (الشهر والموظف)
    month_str = request.args.get('month', date.today().strftime('%Y-%m'))
    user_id = request.args.get('user_id')

    query = Attendance.query.filter(func.to_char(Attendance.date, 'YYYY-MM') == month_str)

    selected_user = None
    if user_id and user_id != 'all':
        query = query.filter(Attendance.user_id == user_id)
        selected_user = User.query.get(user_id)

    records = query.order_by(Attendance.date.desc(), Attendance.check_in.asc()).all()

    # حساب الإحصائيات للفترة المحددة
    stats = {
        'total_days': len(records),
        'late_days': sum(1 for r in records if r.status == 'late'),
        'total_hours': 0
    }

    # تجهيز البيانات للعرض
    attendance_data = []
    for r in records:
        work_hours = "---"
        if r.check_in and r.check_out:
            diff = r.check_out - r.check_in
            seconds = diff.total_seconds()
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            work_hours = f"{hours}س {minutes}د"
            stats['total_hours'] += hours # جمع تقريبي للساعات

        attendance_data.append({
            'user': r.user.fullname,
            'date': r.date,
            'check_in': r.check_in,
            'check_out': r.check_out,
            'status': r.status,
            'work_hours': work_hours
        })

    users = User.query.all()
    return render_template('attendance_report.html',
                         records=attendance_data,
                         users=users,
                         selected_month=month_str,
                         selected_user=int(user_id) if user_id and user_id != 'all' else None,
                         stats=stats)
@app.route('/product/delete/<int:id>')
@permission_required('manage_inventory')
def delete_product(id):
    try: var = ProductVariant.query.get_or_404(id); db.session.delete(var.model); db.session.delete(var); db.session.commit()
    except: pass
    return redirect(url_for('inventory'))

@app.route('/print_barcode/<int:id>')
@login_required
def print_barcode(id): return render_template('print_barcode.html', product=ProductVariant.query.get_or_404(id))

@app.route('/returns')
@login_required
def returns_list():
    returns = ReturnInvoice.query.order_by(ReturnInvoice.date.desc()).all()
    # Add shipping returns (orders marked as returned by shipping)
    shipping_returns = SaleOrder.query.filter_by(is_shipping=True, shipping_status='returned').order_by(SaleOrder.date.desc()).all()
    return render_template('returns_list.html', returns=returns, shipping_returns=shipping_returns)
def calculate_attendance_deduction(u, month_str, att_settings, daily_rate):
    """حساب قيمة خصم الغياب وتفاصيله لموظف معين في شهر محدد"""
    if getattr(u, 'work_from_home', False):
        return 0, [], 0

    attendance_records = Attendance.query.filter(Attendance.user_id == u.id,
                                                   func.to_char(Attendance.date, 'YYYY-MM') == month_str).all()

    attendance_deduction = 0
    attendance_details = []

    try:
        m_year, m_month = map(int, month_str.split('-'))
        start_date = date(m_year, m_month, 1)
        _, last_day = calendar.monthrange(m_year, m_month)
        end_date = date(m_year, m_month, last_day)
    except Exception:
        start_date = date.today().replace(day=1)
        end_date = date.today()

    today_date = cairo_now().date()
    if start_date.year == today_date.year and start_date.month == today_date.month:
        calc_end_date = min(end_date, today_date - timedelta(days=1))
    else:
        calc_end_date = end_date

    recorded_dates = {rec.date for rec in attendance_records}

    # 1. أولاً: حساب جزاءات الأيام التي لم يسجل فيها حضور أو انصراف نهائياً
    curr_date = start_date
    while curr_date <= calc_end_date:
        is_friday = (curr_date.weekday() == 4)
        is_saturday = (curr_date.weekday() == 5)
        
        skip_day = False
        if att_settings.skip_friday and is_friday: skip_day = True
        if att_settings.skip_saturday and is_saturday: skip_day = True
        
        if not skip_day and curr_date not in recorded_dates:
            excuse = EmployeeExcuse.query.filter_by(user_id=u.id, date=curr_date).first()
            day_deduction = 0
            day_reason = ''
            
            if excuse and excuse.type == 'day':
                if att_settings.absent_full_day_excuse <= 0:
                    # إذن يوم كامل بدون خصم = تخطي اليوم تماماً
                    curr_date += timedelta(days=1)
                    continue
                day_deduction = daily_rate * att_settings.absent_full_day_excuse
                day_reason = f'غياب بإذن يوم كامل (خصم {att_settings.absent_full_day_excuse} يوم)'
            else:
                day_deduction = daily_rate * att_settings.absent_no_excuse
                day_reason = f'غياب بدون إذن (لم يسجل حضور ولا انصراف) - (خصم {att_settings.absent_no_excuse} يوم)'
            
            attendance_deduction += day_deduction
            attendance_details.append({
                'rec_id':    0,
                'date':      curr_date.strftime('%Y-%m-%d'),
                'day_name':  ['الإثنين','الثلاثاء','الأربعاء','الخميس','الجمعة','السبت','الأحد'][curr_date.weekday()],
                'reason':    day_reason,
                'deduction': round_half(day_deduction),
                'check_in':  '---',
                'check_out': '---'
            })
                
        curr_date += timedelta(days=1)

    # متغيرات لتجميع ساعات التأخير والإضافي على مدار الشهر لتعويض بعضها البعض
    total_missed_hours_month = 0
    total_extra_hours_month = 0

    # 2. ثانياً: حساب جزاءات الأيام المسجلة (حضور متأخر، انصراف مبكر، غياب مسجل صراحةً)
    for rec in attendance_records:
        if att_settings.skip_friday and rec.date.weekday() == 4: continue
        if att_settings.skip_saturday and rec.date.weekday() == 5: continue

        excuse = EmployeeExcuse.query.filter_by(user_id=u.id, date=rec.date).first()
        day_deduction = 0
        day_reason = ''

        if rec.status == 'absent':
            if excuse and excuse.type == 'day':
                day_deduction = daily_rate * att_settings.absent_full_day_excuse
                day_reason = f'غياب بإذن يوم كامل (خصم {att_settings.absent_full_day_excuse} يوم)' if att_settings.absent_full_day_excuse > 0 else 'غياب بإذن يوم كامل (بدون خصم)'
            elif rec.is_excused:
                day_deduction = daily_rate * att_settings.absent_excused
                day_reason = f'غياب بإذن (خصم {att_settings.absent_excused} يوم)'
            else:
                day_deduction = daily_rate * att_settings.absent_no_excuse
                day_reason = f'غياب بدون إذن (خصم {att_settings.absent_no_excuse} يوم)'
            attendance_deduction += day_deduction
        else:
            expected_hours = float(u.working_hours) if u.working_hours else 8.0

            if rec.check_in and not rec.check_out:
                day_deduction = daily_rate * att_settings.no_checkout_penalty
                day_reason    = f'لم يسجل انصراف (خصم {att_settings.no_checkout_penalty} يوم)'
                attendance_deduction += day_deduction
            elif expected_hours > 0:
                actual_hours = 0
                if rec.check_in and rec.check_out:
                    actual_hours = max(0, (rec.check_out - rec.check_in).total_seconds() / 3600)

                excuse_hours = 0
                if excuse and excuse.type == 'hours':
                    excuse_hours = excuse.hours or 0

                net_hours = actual_hours + excuse_hours - expected_hours
                
                if net_hours < 0:
                    missed = abs(net_hours)
                    total_missed_hours_month += missed
                    day_reason = f'نقص {missed:.1f} ساعة (عمل {actual_hours:.1f} من {expected_hours:.1f})'
                elif net_hours > 0:
                    extra = net_hours
                    total_extra_hours_month += extra
                    day_reason = f'إضافي {extra:.1f} ساعة (عمل {actual_hours:.1f} من {expected_hours:.1f})'
                else:
                    day_reason = f'اكتمل الدوام بالضبط ({actual_hours:.1f} ساعة)'

        attendance_details.append({
            'rec_id':    rec.id,
            'date':      rec.date.strftime('%Y-%m-%d'),
            'day_name':  ['الإثنين','الثلاثاء','الأربعاء','الخميس','الجمعة','السبت','الأحد'][rec.date.weekday()],
            'reason':    day_reason,
            'deduction': round_half(day_deduction),
            'check_in':  rec.check_in.strftime('%I:%M %p') if rec.check_in else '---',
            'check_out': rec.check_out.strftime('%I:%M %p') if rec.check_out else '---'
        })

    # 3. تصفية ساعات التأخير مع الإضافي على مدار الشهر
    overtime_bonus = 0
    if total_missed_hours_month > 0 or total_extra_hours_month > 0:
        net_missed = max(0, total_missed_hours_month - total_extra_hours_month)
        net_extra = max(0, total_extra_hours_month - total_missed_hours_month)
        std_expected = float(u.working_hours) if u.working_hours else 8.0
        
        hours_money_deduction = 0
        if net_missed > 0 and std_expected > 0:
            hours_money_deduction = (net_missed / std_expected) * daily_rate
        
        if net_extra > 0 and std_expected > 0:
            overtime_bonus = (net_extra / std_expected) * daily_rate
            
        attendance_deduction += hours_money_deduction
        
        if net_extra > 0:
            summary_reason = f'محصلة الشهر: تأخير {total_missed_hours_month:.1f}س | إضافي {total_extra_hours_month:.1f}س | الصافي: إضافي {net_extra:.1f}س (مكافأة {round_half(overtime_bonus)} ج)'
        else:
            summary_reason = f'محصلة الشهر: تأخير {total_missed_hours_month:.1f}س | إضافي {total_extra_hours_month:.1f}س | الصافي: خصم {net_missed:.1f}س'
        
        attendance_details.append({
            'rec_id':    0,
            'date':      'نهاية الشهر',
            'day_name':  'تسوية الساعات',
            'reason':    summary_reason,
            'deduction': round_half(hours_money_deduction),
            'check_in':  '---',
            'check_out': '---'
        })

    return attendance_deduction, attendance_details, overtime_bonus

SEASON_START = datetime(2025, 1, 1)
SEASON_END = datetime(2026, 7, 15)
@app.route('/hr/payroll')
@login_required
def payroll():
    # التحقق من الصلاحيات
    if not current_user.has_perm('manage_hr') and current_user.role != 'general_manager':
        return "غير مصرح", 403

    # استلام الشهر من الرابط أو افتراض الشهر الحالي
    month_str = request.args.get('month', date.today().strftime('%Y-%m'))

    # جلب جميع الخزائن المتاحة للصرف
    accounts = MoneyAccount.query.all()
    employees_data = []

    # جلب الموظفين (سيلز وعمال) فقط
    users = User.query.filter(User.role.in_(['sales', 'worker'])).all()

    # تحميل إعدادات الجزاءات
    att_settings = AttendanceSettings.query.first()
    if not att_settings:
        att_settings = AttendanceSettings()
        db.session.add(att_settings)
        db.session.commit()

    for u in users:
        # حساب أجر اليوم الواحد
        daily_rate = (u.base_salary or 0) / 30

        # 1. حساب "تراكمي الموسم" (من 1 يناير 2025) لتحديد شريحة العمولة
        total_season_items = db.session.query(func.sum(SaleItem.quantity))\
            .join(SaleOrder)\
            .filter(SaleOrder.user_id == u.id,
                    SaleOrder.is_proforma == False,
                    SaleOrder.date >= SEASON_START,
                    SaleOrder.date <= SEASON_END).scalar() or 0

        # 2. حساب قطع "الشهر الحالي" فقط لحساب مبلغ العمولة المستحق الآن
        current_month_items = db.session.query(func.sum(SaleItem.quantity))\
            .join(SaleOrder)\
            .filter(SaleOrder.user_id == u.id,
                    SaleOrder.is_proforma == False,
                    func.to_char(SaleOrder.date, 'YYYY-MM') == month_str).scalar() or 0

        # === [تعديل] خصم المرتجعات من عدد القطع ===
        # أ) مرتجعات الموسم ككل (عشان الشريحة تكون صح)
        returned_items_season = db.session.query(func.sum(ReturnInvoice.total_qty))\
            .join(SaleOrder)\
            .filter(SaleOrder.user_id == u.id,
                    ReturnInvoice.date >= SEASON_START,
                    ReturnInvoice.date <= SEASON_END).scalar() or 0
        
        net_season_items = max(0, total_season_items - returned_items_season)

        # ب) مرتجعات الشهر الحالي (عشان المبلغ المستحق يكون صح)
        returned_items_current_month = db.session.query(func.sum(ReturnInvoice.total_qty))\
            .join(SaleOrder)\
            .filter(SaleOrder.user_id == u.id,
                    func.to_char(ReturnInvoice.date, 'YYYY-MM') == month_str).scalar() or 0

        net_current_month_items = max(0, current_month_items - returned_items_current_month)

        # حساب العمولة بناءً على (صافي) قطع الشهر الحالي فقط
        commission = calculate_user_commission(u, net_current_month_items, net_current_month_items)

        # 3. حساب جزاءات الحضور (بواسطة المساعد)
        attendance_deduction, attendance_details, overtime_bonus = calculate_attendance_deduction(u, month_str, att_settings, daily_rate)


        # 4. جلب كافة الحركات المالية اليدوية (مكافآت، سلف، جزاءات، مرتجعات) لهذا الشهر
        hr_trans = HRTransaction.query.filter(HRTransaction.user_id == u.id,
                                            func.to_char(HRTransaction.date, 'YYYY-MM') == month_str).all()

        bonuses = sum(t.amount for t in hr_trans if t.type == 'bonus') + overtime_bonus
        advances = sum(t.amount for t in hr_trans if t.type == 'advance')
        other_penalties = sum(t.amount for t in hr_trans if t.type in ['penalty', 'deduction'])
        past_returns_deduction = sum(abs(t.amount) for t in hr_trans if t.type == 'return_reversal')

        # 5. المعادلة النهائية الشاملة للاستحقاقات والاستقطاعات
        total_income = (u.base_salary or 0) + commission + bonuses
        total_deductions = past_returns_deduction + attendance_deduction + advances + other_penalties

        net_salary = total_income - total_deductions

        # 6. التحقق هل تم صرف الراتب لهذا الشهر مسبقاً (لمنع تكرار الصرف وظهور الزر)
        is_paid = db.session.query(HRTransaction).filter(
            HRTransaction.user_id == u.id,
            HRTransaction.type == 'salary_payment',
            HRTransaction.note.like(f"%{month_str}%")
        ).first() is not None

        # تجميع البيانات لإرسالها لملف HTML
        employees_data.append({
            'id': u.id,
            'name': u.fullname,
            'base': round_half(u.base_salary or 0),
            'season_total': int(total_season_items),
            'commission': round_half(commission),
            'returns_deduction': round_half(past_returns_deduction),
            'attendance_deduction': round_half(attendance_deduction),
            'attendance_details': attendance_details,
            'other_penalties': round_half(other_penalties),
            'advances': round_half(advances),
            'bonuses': round_half(bonuses),
            'net_salary': round_half(max(0, net_salary)),
            'is_paid': is_paid
        })

    return render_template('payroll.html', employees=employees_data, month=month_str, accounts=accounts)
@app.route('/returns/add', methods=['GET', 'POST'])
@login_required
def add_return():
    # التحقق من الصلاحية (للمديرين فقط)
    if current_user.role not in ['manager', 'general_manager']:
        flash('عفواً، هذه الصلاحية للمديرين فقط 🚫', 'danger')
        return redirect(url_for('returns_list'))

    if request.method == 'POST':
        try:
            order_id = request.form.get('order_id')
            refund_method = request.form.get('refund_method') # 'cash' أو 'debt'
            refund_account_id = request.form.get('refund_account_id')

            try:
                shipping_loss = float(request.form.get('shipping_loss') or 0)
                missing_cost = float(request.form.get('missing_cost') or 0)
            except:
                shipping_loss = 0.0; missing_cost = 0.0

            missing_desc = request.form.get('missing_desc')
            notes = request.form.get('notes')

            order = SaleOrder.query.get(order_id)
            if not order:
                flash('رقم الفاتورة غير صحيح', 'danger'); return redirect(request.url)

            # 1. تم الإلغاء: تم السماح بعمل أكثر من مرتجع للفاتورة

            # 2. معالجة المخزون وحساب قيمة البضاعة المرتجعة
            total_qty_returned = 0
            total_items_value = 0.0
            total_profit_to_deduct = 0.0
            returned_items_for_stock = []

            for item in order.items:
                returned_qty = int(request.form.get(f'qty_returned_{item.id}') or 0)
                
                # حساب الكمية المرتجعة مسبقاً لهذا الصنف (بالاعتماد على حركة المخزون لهذا المرتجع)
                # بما أن السيستم مبيسجلش تفاصيل المرتجع لكل صنف منفصل، المتاح لينا هو `StockMovement` 
                # أو نجيب الكمية من الـ invoice بشكل تقريبي. الصح هو تخزينها أو الاعتماد المتاح.
                # للتسهيل ولأن `StockMovement` مسجل السبب بـ "مرتجع فاتورة #رقم":
                previously_returned = db.session.query(func.sum(StockMovement.quantity_change)).filter(
                    StockMovement.variant_id == item.variant_id,
                    db.or_(
                        StockMovement.reason == f"مرتجع فاتورة #{order.id}",
                        StockMovement.reason.like(f"مرتجع #% فاتورة #{order.id}")
                    )
                ).scalar() or 0
                
                remaining_qty = item.quantity - previously_returned

                if returned_qty > remaining_qty:
                    flash(f'خطأ: الكمية المرتجعة ({returned_qty}) للصنف {item.variant.model.name if item.variant else ""} أكبر من المتبقي المسموح بإرجاعه ({remaining_qty})!', 'danger')
                    return redirect(request.url)

                if returned_qty > 0:
                    total_qty_returned += returned_qty
                    total_items_value += (returned_qty * item.unit_price)
                    
                    if item.variant:
                        total_profit_to_deduct += (returned_qty * (item.unit_price - item.variant.cost_price))
                        item.variant.stock += returned_qty
                        # نجمع بيانات حركات المخزون عشان نضيفها بعد إنشاء المرتجع
                        returned_items_for_stock.append((item.variant.id, returned_qty))

            if total_qty_returned == 0:
                flash('برجاء تحديد الأصناف المرتجعة', 'warning'); return redirect(request.url)

            # 3. حساب القيمة الصافية للمرتجع (بعد خصم الشحن والتوالف)
            total_deduction = shipping_loss + missing_cost
            net_refund_value = total_items_value - total_deduction

            # 4. تسجيل فاتورة المرتجع في السيستم
            ret_inv = ReturnInvoice(
                order_id=order.id, shipping_loss=shipping_loss,
                missing_items_cost=missing_cost, missing_items_desc=missing_desc,
                total_deduction=total_deduction, created_by=current_user.id, notes=notes,
                total_qty=total_qty_returned # تخزين الكمية المرتجعة
            )
            db.session.add(ret_inv)
            db.session.flush()  # للحصول على ID المرتجع
            
            # 4.0.1 تسجيل حركات المخزون بعد الحصول على ID المرتجع
            for variant_id, qty in returned_items_for_stock:
                db.session.add(StockMovement(
                    variant_id=variant_id, user_id=current_user.id,
                    quantity_change=qty, reason=f"مرتجع #{ret_inv.id} فاتورة #{order.id}"
                ))
            
            # 4.1 تحديث وضع الشحن للمرتجع (توضيح: نحتفظ بالفاتورة في متابعة الشحن للتحصيل فقط إذا كانت "تم التوصيل")
            if order.shipping_status == 'delivered':
                order.shipping_status = 'returned'
            elif order.shipping_status in ['none', 'pending', 'shipped']:
                # إذا رُفضت قبل التوصيل، تعتبر منتهية بالنسبة للائحة التحصيل
                order.shipping_status = 'settled'

            # 5. التأثير المالي (الخزينة أو المديونية)
            if net_refund_value > 0:
                if refund_method == 'cash':
                    # رد نقدي من الخزينة (لو الزبون كان دافع)
                    account = MoneyAccount.query.get(refund_account_id)
                    if account:
                        account.balance = round_half(account.balance - net_refund_value)
                        db.session.add(FinancialTransaction(
                            account_id=account.id, type='refund', category='مرتجعات مبيعات',
                            amount=-net_refund_value,
                            description=f"رد نقدي لمرتجع فاتورة #{order.id} (العميل: {order.customer.name if order.customer else 'نقدي'})",
                            created_by_id=current_user.id, date=cairo_now()
                        ))
                    else:
                        flash('يجب اختيار خزينة للرد النقدي!', 'danger'); return redirect(request.url)
                else:
                    # خصم من مديونية العميل (لو الزبون مدفعش أو عليه فلوس)
                    if order.customer:
                        order.customer.balance = (order.customer.balance or 0) - net_refund_value
                        db.session.add(FinancialTransaction(
                            type='debt_adjustment', category='تسوية مديونية', amount=0,
                            description=f"تسوية مديونية (مرتجع #{order.id}): خصم {net_refund_value} من حساب {order.customer.name}",
                            created_by_id=current_user.id, date=cairo_now()
                        ))

            # تحديث مديونية الفاتورة نفسها لتظهر كـ "خالصة" أو مخفضة
            order.amount_due = max(0, order.amount_due - net_refund_value)

            # 6. معالجة حسابات الشركاء (إلغاء الربح والعمولة عن القطع المرتجعة)
            sales_rep = User.query.get(order.user_id)
            partner = None
            if sales_rep.role == 'manager': partner = sales_rep
            elif sales_rep.manager_id: partner = User.query.get(sales_rep.manager_id)

            if partner:
                # أ) إلغاء ربح الشريك عن القطع المرجعة
                if partner.username in ['Abo_Eyad', 'Abo_malek']:
                    # للشركاء الأساسيين: خصم هامش الربح الحقيقي
                    db.session.add(PartnerTransaction(
                        partner_id=partner.id, order_id=order.id, type='commission_gross',
                        amount=-total_profit_to_deduct,
                        description=f"خصم هامش ربح قطع مرتجعة ({total_qty_returned} قطعة) - فاتورة #{order.id}"
                    ))
                else:
                    # للمديرين العاديين: خصم 14 جنيه ثابتة
                    db.session.add(PartnerTransaction(
                        partner_id=partner.id, order_id=order.id, type='commission_gross',
                        amount=-(total_qty_returned * 14.0),
                        description=f"خصم ربح 14ج لقطع مرتجعة ({total_qty_returned} قطعة) - فاتورة #{order.id}"
                    ))
                # ب) خسائر الشحن والتوالف يتحملها العميل فقط (مخصومة من قيمة الرد أعلاه)
                # لا يتم خصمها من الشريك/المدير لتجنب الخصم المزدوج
                # ج) استرداد عمولة السيلز (ترجع لجيب المدير)
                if sales_rep.role == 'sales':
                    comm_to_reverse = calculate_user_commission(sales_rep, total_qty_returned, total_qty_returned)
                    if comm_to_reverse > 0:
                        add_split_partner_transaction(
                            partner_id=partner.id, order_id=order.id, type_val='sub_commission',
                            amount=comm_to_reverse, description=f"استرداد عمولة سيلز ({sales_rep.fullname}) عن مرتجع #{order.id}"
                        )
                    # تسجيل المرتجع في ملف الموظفة لخصمه من التارجت
                    db.session.add(HRTransaction(
                        user_id=sales_rep.id, type='deduction', amount=0,
                        note=f"مرتجع فاتورة #{order.id} ({total_qty_returned} قطعة)", date=cairo_now()
                    ))

            db.session.commit()
            flash(f'تم تسجيل المرتجع بنجاح ✅ (صافي القيمة: {net_refund_value} ج.م)', 'success')
            return redirect(url_for('returns_list'))

        except Exception as e:
            db.session.rollback()
            flash(f"حدث خطأ: {e}", "danger")
            return redirect(request.url)

    # GET: عرض الصفحة
    orders = SaleOrder.query.filter(
        SaleOrder.is_proforma == False
    ).order_by(SaleOrder.id.desc()).all()
    
    # فلترة الفواتير اللي كمياتها المرتجعة أقل من كميتها الأصلية (عشان تظهر في القايمة)
    valid_orders = []
    for o in orders:
        gross = sum(i.quantity for i in o.items)
        ret_qty = sum(r.total_qty for r in o.return_invoices)
        if ret_qty < gross:
            valid_orders.append(o)
            
    orders = valid_orders
    accounts = MoneyAccount.query.all()
    selected_order_id = request.args.get('order_id', type=int)
    return render_template('return_add.html', orders=orders, accounts=accounts, selected_order_id=selected_order_id)
@app.route('/api/get_order_details/<int:id>')
@login_required
def get_order_details(id):
    order = SaleOrder.query.get_or_404(id)
    items = []
    
    for item in order.items:
        # حساب المرتجع مسبقاً لنفس الصنف في نفس الفاتورة
        previously_returned = db.session.query(func.sum(StockMovement.quantity_change)).filter(
            StockMovement.variant_id == item.variant_id,
            StockMovement.reason == f"مرتجع فاتورة #{order.id}"
        ).scalar() or 0
        
        remaining_qty = item.quantity - previously_returned
        
        # نعرض بس اللي لسه مسموح يرجعه، لو 0 مش هنعرضه أصلًا أو نعرضه بالمتلقي 0
        if remaining_qty > 0:
            items.append({
                'id': item.id,
                'name': item.variant.model.name,
                'qty': remaining_qty, # نرسل المتبقي واجهة المستخدم عشان متسمحش بأكتر منه
                'price': item.unit_price
            })

    # حساب إجمالي الخصومات التي تمت بالفعل في المرتجعات السابقة (لتحديث الرصيد والمتبقي في واجهة المرتجع)
    total_refunded_before = 0.0
    for ret in order.return_invoices:
        refund_val = (ret.total_deduction or 0.0) - (ret.shipping_loss or 0.0) - (ret.missing_items_cost or 0.0)
        if refund_val > 0:
            total_refunded_before += refund_val

    return jsonify({
        'items': items,
        'paid_upfront': order.paid_upfront, 
        'amount_due': order.amount_due # المتبقي/الدين الحالي
    })

# تأكد من إعداد مجلد الرفع في إعدادات التطبيق
# app.config['UPLOAD_FOLDER'] = 'static/uploads'

@app.route('/settings', methods=['GET', 'POST'])
@login_required # أو @general_manager_required حسب نظامك
def settings():
    # جلب الإعدادات الحالية أو إنشاء صف جديد إذا لم يوجد
    setting = SystemSetting.query.first()
    if not setting:
        setting = SystemSetting()
        db.session.add(setting)
        db.session.commit()

    if request.method == 'POST':
        try:
            # 1. تحديث اللون
            new_color = request.form.get('theme_color')
            if new_color:
                setting.theme_color = new_color

            # 2. معالجة رفع الشعار (Logo)
            if 'company_logo' in request.files:
                file = request.files['company_logo']
                if file and file.filename != '':
                    filename = secure_filename(file.filename)
                    # حفظ الملف في مجلد uploads
                    save_uploaded_file(file, filename)
                    # تحديث اسم الملف في الداتابيز
                    setting.company_logo = filename

            db.session.commit()
            flash('تم حفظ إعدادات النظام وتحديث المظهر بنجاح ✅', 'success')

        except Exception as e:
            db.session.rollback()
            flash(f'حدث خطأ أثناء الحفظ: {str(e)}', 'danger')

        return redirect(url_for('settings'))

    # في حالة GET نعرض الصفحة بالبيانات الحالية
    return render_template('settings.html',
                         theme_color=setting.theme_color,
                         company_logo=setting.company_logo)
@app.route('/api/quick_update_product', methods=['POST'])
@permission_required('manage_inventory')
def quick_update_product():
    data = request.get_json()
    product_id = data.get('id')
    field = data.get('field') # name, cost_price, sell_price, stock
    value = data.get('value')

    variant = ProductVariant.query.get(product_id)
    if not variant:
        return jsonify({'success': False, 'message': 'المنتج غير موجود'}), 404

    try:
        if field == 'name':
            variant.model.name = value
        elif field == 'category':
            # المدير العام فقط من يستطيع تعديل التصنيف
            if current_user.role != 'general_manager':
                return jsonify({'success': False, 'message': 'غير مصرح لك بتغيير التصنيف'}), 403
            variant.model.category_id = int(value)
        elif field == 'cost':
            variant.cost_price = float(value)
        elif field == 'sell':
            variant.sell_price = float(value)
        elif field == 'stock':
            old_stock = variant.stock
            new_stock = int(value)
            diff = new_stock - old_stock
            if diff != 0:
                variant.stock = new_stock
                # تسجيل حركة مخزون للتعديل اليدوي
                db.session.add(StockMovement(
                    variant_id=variant.id,
                    user_id=current_user.id,
                    quantity_change=diff,
                    reason="تعديل سريع من الجدول"
                ))

        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
@app.route('/fix/cleanup_orphaned_transactions')
@general_manager_required
def cleanup_orphaned_transactions():
    try:
        # 1. نجيب كل حركات الـ HR اللي فيها سيرة فواتير
        hr_transactions = HRTransaction.query.filter(
            HRTransaction.note.like('%فاتورة #%')
        ).all()

        deleted_count = 0

        for trans in hr_transactions:
            # نستخرج رقم الفاتورة من الملاحظة
            # الملاحظة بتكون: "تسجيل مرتجع إداري: فاتورة #105 ..."
            match = re.search(r'فاتورة #(\d+)', trans.note)
            if match:
                order_id = int(match.group(1))

                # نبحث عن الفاتورة في السيستم
                order = SaleOrder.query.get(order_id)

                # لو الفاتورة مش موجودة (اتمسحت) -> يبقى الحركة دي "يتيمة" ولازم تتمسح
                if not order:
                    db.session.delete(trans)
                    deleted_count += 1

        db.session.commit()
        return f"""
        <div style="text-align:center; padding:50px;">
            <h1 style="color:green;">✅ تم تنظيف السجلات بنجاح!</h1>
            <h3>تم حذف {deleted_count} حركة معلقة لفواتير محذوفة.</h3>
            <p>الآن ستعود حسابات الموظفين دقيقة 100%.</p>
            <a href="/dashboard">عودة للرئيسية</a>
        </div>
        """

    except Exception as e:
        return f"حدث خطأ: {e}"
# ==========================================
# === إصلاح هيكل قاعدة البيانات (مرة واحدة) ===
# ==========================================
@app.route('/fix/update_db_schema')
def update_db_schema():
    try:
        from sqlalchemy import text, inspect
        inspector = inspect(db.engine)

        # 1. التأكد من وجود جدول supplier_payment
        if 'supplier_payment' in inspector.get_table_names():
            cols = [c['name'] for c in inspector.get_columns('supplier_payment')]

            # 2. لو عمود account_id مش موجود، نضيفه
            if 'account_id' not in cols:
                with db.engine.connect() as conn:
                    conn.execute(text("ALTER TABLE supplier_payment ADD COLUMN account_id INTEGER REFERENCES money_account(id)"))
                    conn.commit()
            return "❌ جدول supplier_payment غير موجود أصلاً!"
            
        # 3. تحديث جدول المرتجعات بإضافة عمود الكمية
        if 'return_invoice' in inspector.get_table_names():
            cols = [c['name'] for c in inspector.get_columns('return_invoice')]
            if 'total_qty' not in cols:
                with db.engine.connect() as conn:
                    conn.execute(text("ALTER TABLE return_invoice ADD COLUMN total_qty INTEGER DEFAULT 0"))
                    conn.commit()
                return "✅ تم تحديث جدول المرتجعات وإضافة عمود الكمية بنجاح!"

    except Exception as e:
        return f"حدث خطأ: {e}"
# --- إضافة دالة تعديل العميل ---
@app.route('/customer/edit/<int:id>', methods=['POST'])
@login_required
def edit_customer(id):
    # التحقق من الصلاحية
    if not current_user.has_perm('manage_customers') and current_user.role != 'general_manager':
        flash('غير مصرح لك بتعديل البيانات', 'danger')
        return redirect(url_for('customers'))

    cust = Customer.query.get_or_404(id)

    # تحديث البيانات
    cust.name = request.form.get('name')
    cust.phone = request.form.get('phone')
    cust.address = request.form.get('address')

    db.session.commit()
    flash(f'تم تحديث بيانات العميل {cust.name} بنجاح ✅', 'success')
    return redirect(url_for('customers'))
@app.route('/fix/recalculate_treasury')
@login_required
def recalculate_treasury():
    # التأكد من الصلاحية
    if current_user.role != 'general_manager':
        return "غير مصرح لك", 403

    try:
        accounts = MoneyAccount.query.all()
        updated_log = []

        for acc in accounts:
            # 1. تجميع كل الحركات المرتبطة بهذا الحساب بناءً على الـ ID فقط
            # نجمع القيم: الإيداع بيكون موجب، والمصروف بيكون سالب في الداتا بيز
            real_balance = db.session.query(func.sum(FinancialTransaction.amount))\
                .filter(FinancialTransaction.account_id == acc.id).scalar() or 0.0

            old_balance = acc.balance

            # 2. تحديث الرصيد بالقيمة الحقيقية
            acc.balance = real_balance

            updated_log.append(f"✅ {acc.name}: كان ({old_balance}) أصبح ({real_balance})")

        db.session.commit()

        return f"""
        <div style="text-align:center; padding:50px; font-family:tahoma;">
            <h1 style="color:green;">تم ضبط أرصدة الخزائن بنجاح!</h1>
            <p>تم إعادة تجميع الحركات وحساب الرصيد الفعلي بدقة.</p>
            <div style="background:#f9f9f9; padding:20px; border:1px solid #ddd; display:inline-block; text-align:right;">
                {'<br>'.join(updated_log)}
            </div>
            <br><br>
            <a href="/treasury/view" style="background:#0d6efd; color:white; padding:10px 20px; text-decoration:none; border-radius:5px;">عودة للخزينة</a>
        </div>
        """

    except Exception as e:
        return f"حدث خطأ: {e}"
@app.route('/fix/run_restoration')
@login_required
def run_restoration_route():
    if current_user.role != 'general_manager':
        return "غير مصرح لك", 403

    try:
        default_acc = MoneyAccount.query.filter_by(type='cash').first()
        if not default_acc:
            default_acc = MoneyAccount.query.first()

        log_lines = []

        # === الخطوة 1: حذف سجلات الترميم الخاطئة السابقة ===
        old_restore_txs = FinancialTransaction.query.filter(
            or_(
                FinancialTransaction.description.like('%إسترداد دفعات مفقودة%'),
                FinancialTransaction.description.like('%ترميم - فاتورة%')
            )
        ).all()
        old_tx_total = sum(tx.amount for tx in old_restore_txs)
        for tx in old_restore_txs:
            db.session.delete(tx)

        old_restore_cps = CustomerPayment.query.filter(
            CustomerPayment.notes.like('%إسترداد مدفوعات مفقودة%')
        ).all()
        for cp in old_restore_cps:
            db.session.delete(cp)

        db.session.commit()
        log_lines.append(f"🧹 تم تنظيف {len(old_restore_txs)} حركة خاطئة سابقة ({old_tx_total} ج.م) و{len(old_restore_cps)} دفعة عملاء")

        # === الخطوة 2: ترميم ذكي مع تحديد الخزينة الصحيحة ===
        orders = SaleOrder.query.filter(SaleOrder.is_proforma == False).all()
        restored_tx_count = 0
        restored_money = 0.0
        per_account = {}

        for order in orders:
            total_paid_expected = round_half(order.paid_upfront or 0)
            if total_paid_expected <= 0: continue

            existing_txs_raw = FinancialTransaction.query.filter(
                FinancialTransaction.description.like(f'%فاتورة #{order.id}%')
            ).all()

            total_tx_found = 0.0
            for tx in existing_txs_raw:
                if tx.description and re.search(rf'فاتورة #{order.id}(?!\d)', tx.description):
                    if tx.type == 'income': total_tx_found += tx.amount

            missing_money = round_half(total_paid_expected - total_tx_found)
            if missing_money > 0.01:
                # تحديد الخزينة الصحيحة من دفعات العملاء الأصلية
                original_cps = CustomerPayment.query.filter(
                    CustomerPayment.notes.like(f'%فاتورة #{order.id}%'),
                    ~CustomerPayment.notes.like('%إسترداد%'),
                    ~CustomerPayment.notes.like('%ترميم%')
                ).all()
                exact_cps = [cp for cp in original_cps if cp.notes and re.search(rf'فاتورة #{order.id}(?!\d)', cp.notes)]

                if exact_cps and exact_cps[0].account_id:
                    target_acc = MoneyAccount.query.get(exact_cps[0].account_id) or default_acc
                else:
                    target_acc = default_acc

                db.session.add(FinancialTransaction(
                    account_id=target_acc.id, type='income', category='مبيعات',
                    amount=missing_money,
                    description=f"ترميم - فاتورة #{order.id} (العميل: {order.customer.name if order.customer else 'نقدي'})",
                    date=cairo_now(), created_by_id=current_user.id
                ))

                restored_tx_count += 1
                restored_money += missing_money
                acc_name = target_acc.name
                per_account[acc_name] = per_account.get(acc_name, 0) + missing_money
                log_lines.append(f"✅ فاتورة #{order.id}: {missing_money} ج.م → {acc_name}")

        db.session.commit()

        # بناء صفحة النتائج
        details_html = '<br>'.join(log_lines)
        acc_html = ''.join(f"<li><b>{name}</b>: +{amt} ج.م</li>" for name, amt in per_account.items())

        return f"""
        <div style="text-align:center; padding:50px; font-family:tahoma;">
            <h1 style="color:green;">تم الترميم الذكي بنجاح!</h1>
            <h3>تم استرجاع {restored_money} ج.م بإجمالي {restored_tx_count} عملية مفقودة</h3>
            <div style="background:#f0f8ff; padding:20px; border:1px solid #ddd; display:inline-block; text-align:right; max-width:800px; margin:20px auto;">
                <h4>توزيع الترميم على الخزائن:</h4>
                <ul>{acc_html if acc_html else '<li>لا توجد مبالغ مفقودة</li>'}</ul>
                <hr>
                <h4>التفاصيل:</h4>
                <div style="font-size:13px; max-height:300px; overflow-y:auto;">
                    {details_html}
                </div>
            </div>
            <br><br>
            <a href="/fix/recalculate_treasury" style="background:#0d6efd; color:white; padding:10px 20px; text-decoration:none; border-radius:5px;">إضغط هنا لإعادة حساب أرصدة الخزينة الآن</a>
        </div>
        """
    except Exception as e:
        db.session.rollback()
        return f"حدث خطأ: {e}"

@app.route('/fix/manual_restoration_control', methods=['GET', 'POST'])
@login_required
def manual_restoration_control():
    """واجهة للتحكم اليدوي في الخزينة والتاريخ للسجلات المرممة"""
    if current_user.role != 'general_manager':
        return "غير مصرح", 403

    try:
        # نجيب كل سجلات الترميم
        restore_txs = FinancialTransaction.query.filter(
            or_(
                FinancialTransaction.description.like('%إسترداد دفعات مفقودة%'),
                FinancialTransaction.description.like('%ترميم - فاتورة%')
            )
        ).all()

        if request.method == 'POST':
            changes_made = 0
            for tx in restore_txs:
                new_acc_id = request.form.get(f'account_id_{tx.id}')
                new_date = request.form.get(f'date_{tx.id}')
                
                if new_acc_id and int(new_acc_id) != tx.account_id:
                    tx.account_id = int(new_acc_id)
                    changes_made += 1
                
                if new_date:
                    try:
                        # تحويل النص لـ datetime
                        dt = datetime.strptime(new_date, '%Y-%m-%dT%H:%M')
                        if tx.date != dt:
                            tx.date = dt
                            changes_made += 1
                    except Exception as ex:
                        pass
            
            # إعادة حساب الأرصدة
            if changes_made > 0:
                accounts = MoneyAccount.query.all()
                for acc in accounts:
                    calc = db.session.query(func.sum(FinancialTransaction.amount)).filter(
                        FinancialTransaction.account_id == acc.id
                    ).scalar() or 0.0
                    acc.balance = calc
                db.session.commit()
                flash(f'تم حفظ التعديلات بنجاح ({changes_made} تغيير) وتمت إعادة حساب الأرصدة!', 'success')
            
            return redirect('/fix/manual_restoration_control')

        # GET Request: Prepare UI
        accounts = MoneyAccount.query.all()
        html = [
            "<div style='direction:rtl; font-family:tahoma; padding:30px; max-width:1200px; margin:auto;'>",
            "<h1>تصحيح مسار وتاريخ المبالغ المستردة</h1>",
            "<p style='color:#555;'>نظراً لأن السجلات القديمة تم مسحها تماماً، لا يعرف السيستم الخزينة الأصلية التي تم الدفع فيها ولا تاريخ الدفع، فقام بإعادتها للخزينة الرئيسية بتاريخ اليوم. من هنا يمكنك إعادة كل دفعة لخزينتها وتاريخها الأصليين لضبط أرصدة الأيام السابقة.</p>",
            "<form method='POST'>",
            "<table border='1' cellpadding='10' style='border-collapse:collapse; width:100%; text-align:center;'>",
            "<tr style='background:#f2f2f2;'><th>الفاتورة الأصلية (تاريخها)</th><th>العميل</th><th>المبلغ المسترد</th><th>الخزينة المراد تحويله لها</th><th>تاريخ الدفعة (أهم حاجة)</th></tr>"
        ]

        total_restored = 0
        for tx in restore_txs:
            total_restored += tx.amount
            match = re.search(r'فاتورة #(\d+)', tx.description)
            order_info = "غير معروف"
            customer_name = "غير معروف"
            default_date = tx.date.strftime('%Y-%m-%dT%H:%M')
            
            if match:
                order_id = int(match.group(1))
                order = SaleOrder.query.get(order_id)
                if order:
                    order_info = f"فاتورة #{order.id} ({order.date.strftime('%Y-%m-%d')})"
                    customer_name = order.customer.name if order.customer else 'نقدي'
                    # نقترح تاريخ الفاتورة نفسه
                    default_date = order.date.strftime('%Y-%m-%dT%H:%M')
                else:
                    order_info = f"فاتورة #{order_id} (محذوفة)"

            # Dropdown للخزائن
            select_html = f"<select name='account_id_{tx.id}' style='padding:5px; font-size:14px;'>"
            for acc in accounts:
                selected = "selected" if acc.id == tx.account_id else ""
                select_html += f"<option value='{acc.id}' {selected}>{acc.name}</option>"
            select_html += "</select>"

            # Input للتاريخ
            date_html = f"<input type='datetime-local' name='date_{tx.id}' value='{default_date}' style='padding:5px;'>"

            html.append(f"""
            <tr>
                <td>{order_info}</td>
                <td>{customer_name}</td>
                <td style='color:green; font-weight:bold;'>{tx.amount}</td>
                <td>{select_html}</td>
                <td>{date_html}</td>
            </tr>
            """)

        html.append(f"<tr style='background:#ffffe0;'><td colspan='2'><b>الإجمالي المرمم</b></td><td colspan='3' style='color:red; font-weight:bold;'>{total_restored} ج.م</td></tr>")
        html.append("</table>")
        html.append("<br><button class='btn btn-success' type='submit' style='background:green; color:white; padding:15px 30px; border:none; border-radius:5px; font-size:18px; cursor:pointer;'>حفظ التعديلات وضبط الأرصدة</button>")
        html.append("</form>")
        html.append("<br><a href='/fix/check_march30' style='display:inline-block; margin-top:20px;'>العودة لمراجعة رصيد 30 مارس</a>")
        html.append("</div>")

        return "".join(html)

    except Exception as e:
        return str(e)

@app.route('/fix/cleanup_fake_customer_payments', methods=['GET', 'POST'])
@login_required
def cleanup_fake_customer_payments():
    """شاشة لتنظيف الدفعات الوهمية للعملاء التي تم توليدها بالخطأ"""
    if current_user.role != 'general_manager':
        return "غير مصرح", 403

    try:
        # نجيب كل المدفوعات الوهمية
        fake_cps = CustomerPayment.query.filter(
            CustomerPayment.notes.like('%إسترداد مدفوعات مفقودة%')
        ).all()

        customers_affected = {}
        for cp in fake_cps:
            if cp.customer_id not in customers_affected:
                customers_affected[cp.customer_id] = {
                    'customer': Customer.query.get(cp.customer_id),
                    'total_fake_amount': 0.0,
                    'payments': []
                }
            customers_affected[cp.customer_id]['total_fake_amount'] += cp.amount
            customers_affected[cp.customer_id]['payments'].append(cp)

        if request.method == 'POST':
            action = request.form.get('action')
            for cp in fake_cps:
                db.session.delete(cp)

            if action == 'with_balance':
                for cid, data in customers_affected.items():
                    cust = data['customer']
                    if cust:
                        cust.balance = (cust.balance or 0) + data['total_fake_amount']
            
            db.session.commit()
            flash('تم الحذف بنجاح!', 'success')
            return redirect('/fix/cleanup_fake_customer_payments')

        if not customers_affected:
            return "<div style='direction:rtl; font-family:tahoma; padding:30px;'><h1 style='color:green;'>لا توجد مدفوعات وهمية متبقية! كل شيء نظيف.</h1><br><a href='/customers'>العودة للعملاء</a></div>"

        html = [
            "<div style='direction:rtl; font-family:tahoma; padding:30px; max-width:1200px; margin:auto;'>",
            "<h1>تنظيف مدفوعات العملاء الوهمية (العجز والمشاكل)</h1>",
            "<p style='color:red;'>بسبب عملية الترميم السابقة، السيستم قام بإنشاء دفعات تحصيل وهمية لجميع الفواتير المتكيشة (الخالصة) معتقداً أنها مفقودة، مما تسبب في ظهور أرصدة سالبة كبيرة للعديد من العملاء مثل مارتينا وغيرها.</p>",
            "<table border='1' cellpadding='10' style='border-collapse:collapse; width:100%; text-align:center;'>",
            "<tr style='background:#f2f2f2;'><th>العميل</th><th>رصيده الحالي بالسالب (لنا/علينا)</th><th>إجمالي الدفعات الوهمية</th><th>الرصيد بعد الإصلاح</th></tr>"
        ]

        total_fake_sum = 0
        for cid, data in customers_affected.items():
            c = data['customer']
            if not c: continue
            total_fake_sum += data['total_fake_amount']
            current_bal = c.balance or 0
            fixed_bal = current_bal + data['total_fake_amount']
            html.append(f"<tr><td>{c.name}</td><td style='color:red; direction:ltr;'>{current_bal} ج.م</td><td style='color:orange;'>{data['total_fake_amount']} ج.م</td><td style='color:green; font-weight:bold; direction:ltr;'>{fixed_bal} ج.م</td></tr>")

        html.append("</table>")
        html.append(f"<h3 style='margin-top:20px;'>إجمالي الأموال الوهمية للعملاء: {total_fake_sum} ج.م (يجب مسحها)</h3>")
        html.append("<form method='POST' style='margin-top:20px;'>")
        html.append("<button type='submit' name='action' value='with_balance' style='background:green; color:white; padding:15px; border:none; font-size:16px; margin:10px; cursor:pointer;'>مسح المدفوعات الوهمية وتصحيح الرصيد للعملاء (موصى به)</button>")
        html.append("<button type='submit' name='action' value='without_balance' style='background:orange; color:white; padding:15px; border:none; font-size:16px; margin:10px; cursor:pointer;'>مسح المدفوعات الوهمية فقط بدون تعديل الرصيد</button>")
        html.append("</form>")
        html.append("</div>")
        
        return "".join(html)
        
    except Exception as e:
        return str(e)

@app.route('/fix/check_march30')
@login_required
def check_march30():
    if current_user.role != 'general_manager':
        return "غير مصرح", 403
    try:
        html = ["<div style='direction:rtl; font-family:tahoma; padding:30px;'><h1>أرصدة الخزائن بنهاية يوم 30 مارس 2026</h1><table border='1' cellpadding='10' style='border-collapse:collapse; text-align:center;'><tr><th>الخزينة</th><th>الرصيد حتى نهاية 30 مارس</th></tr>"]
        
        target_date = "2026-03-30 23:59:59"
        
        accounts = MoneyAccount.query.all()
        for acc in accounts:
            bal = db.session.query(func.sum(FinancialTransaction.amount)).filter(
                FinancialTransaction.account_id == acc.id,
                FinancialTransaction.date <= target_date
            ).scalar() or 0.0
            
            color = "red" if bal < 0 else "green"
            html.append(f"<tr><td>{acc.name} (ID: {acc.id})</td><td style='color:{color}; font-weight:bold;'>{round_half(bal)} ج.م</td></tr>")
        
        html.append("</table>")
        html.append("<h3>تفاصيل حركات الخزينة الفرعية (ID: 3) يوم 30 و 31 مارس:</h3><table border='1' cellpadding='5' style='border-collapse:collapse; text-align:center;'>")
        html.append("<tr><th>التاريخ</th><th>النوع</th><th>المبلغ</th><th>الوصف</th></tr>")
        
        txs = FinancialTransaction.query.filter(
            FinancialTransaction.account_id == 3,
            FinancialTransaction.date >= "2026-03-30 00:00:00",
            FinancialTransaction.date <= "2026-03-31 23:59:59"
        ).order_by(FinancialTransaction.date.asc()).all()
        
        for tx in txs:
            color = "red" if tx.amount < 0 else "green"
            html.append(f"<tr><td>{tx.date.strftime('%Y-%m-%d %H:%M')}</td><td>{tx.type}</td><td style='color:{color};'>{tx.amount}</td><td>{tx.description[:100]}</td></tr>")
            
        html.append("</table></div>")
        return "".join(html)
    except Exception as e:
        return str(e)

@app.route('/fix/analyze_negative_accounts')
@login_required
def analyze_negative_accounts():
    """تحليل الحسابات ذات الأرصدة السالبة لمعرفة أسباب العجز المشبوهة"""
    if current_user.role != 'general_manager':
        return "غير مصرح لك", 403
    
    try:
        # نجيب الحسابات اللي رصيدها الفعلي سالب
        accounts = MoneyAccount.query.all()
        negative_accounts = []
        
        for acc in accounts:
            calc = db.session.query(func.sum(FinancialTransaction.amount)).filter(
                FinancialTransaction.account_id == acc.id
            ).scalar() or 0.0
            
            if calc < -0.01:
                negative_accounts.append({
                    'id': acc.id,
                    'name': acc.name,
                    'balance': round_half(calc)
                })

        if not negative_accounts:
            return "<h1 style='text-align:center; color:green; padding:50px;'>لا توجد حسابات بأرصدة سالبة (كل الخزائن موجبة أو صفر)</h1>"

        html_lines = [
            "<div style='font-family:tahoma; direction:rtl; padding:30px; max-width:1000px; margin:auto;'>",
            "<h1 style='color:red;'>تحليل أسباب أرصدة الخزائن السالبة</h1>",
            "<p>هذا التقرير يوضح ملخص حركات كل خزينة سالبة لتحديد إذا كان هناك إدخال خاطئ (مثل تكرار سحب، مصروفات ضخمة بالخطأ، حسابات مرتبطة بموردين.. إلخ)</p>"
        ]

        for n_acc in negative_accounts:
            acc_id = n_acc['id']
            bal = n_acc['balance']
            html_lines.append(f"<hr><h2>🏦 الخزينة: {n_acc['name']} | الرصيد: <span style='color:red;'>{bal} ج.م</span></h2>")
            
            # 1. إجمالي الدخل مقابل إجمالي المنصرف
            total_in = db.session.query(func.sum(FinancialTransaction.amount)).filter(
                FinancialTransaction.account_id == acc_id,
                FinancialTransaction.amount > 0
            ).scalar() or 0.0
            
            total_out = db.session.query(func.sum(FinancialTransaction.amount)).filter(
                FinancialTransaction.account_id == acc_id,
                FinancialTransaction.amount < 0
            ).scalar() or 0.0
            
            html_lines.append(f"<b>إجمالي الأموال اللي دخلت:</b> <span style='color:green;'>{round_half(total_in)}</span> ج.م<br>")
            html_lines.append(f"<b>إجمالي الأموال اللي خرجت:</b> <span style='color:red;'>{round_half(abs(total_out))}</span> ج.م<br>")
            
            # 2. تجميع المصروفات حسب الـ type/category
            html_lines.append("<h3>تفصيل المنصرف (حسب النوع):</h3>")
            out_summary = db.session.query(
                FinancialTransaction.type,
                FinancialTransaction.category,
                func.sum(FinancialTransaction.amount).label('total'),
                func.count(FinancialTransaction.id).label('count')
            ).filter(
                FinancialTransaction.account_id == acc_id,
                FinancialTransaction.amount < 0
            ).group_by(FinancialTransaction.type, FinancialTransaction.category).all()
            
            html_lines.append("<table border='1' style='border-collapse:collapse; width:100%; text-align:center;'>")
            html_lines.append("<tr style='background:#f2f2f2;'><th>النوع</th><th>التصنيف</th><th>عدد الحركات</th><th>إجمالي المبلغ المنصرف</th></tr>")
            for row in out_summary:
                html_lines.append(f"<tr><td>{row.type}</td><td>{row.category or '-'}</td><td>{row.count}</td><td style='color:red;'>{round_half(abs(row.total))}</td></tr>")
            html_lines.append("</table>")
            
            # 3. أكبر 10 حركات منصرف (عشان نلقط لو في حركة ضخمة بالغلط)
            top_out = FinancialTransaction.query.filter(
                FinancialTransaction.account_id == acc_id,
                FinancialTransaction.amount < 0
            ).order_by(FinancialTransaction.amount.asc()).limit(10).all()
            
            html_lines.append("<h3>أكبر 10 حركات سداد ومصروفات (من هذه الخزينة):</h3>")
            html_lines.append("<ul>")
            for tx in top_out:
                html_lines.append(f"<li><b>{-tx.amount}</b> ج.م - {tx.category} - {tx.description[:100]} <span style='color:gray; font-size:12px;'>({tx.date.strftime('%Y-%m-%d')} | TX#{tx.id})</span></li>")
            html_lines.append("</ul>")

        html_lines.append("<br><br><a href='/dashboard' style='background:#0d6efd; color:white; padding:10px 20px; text-decoration:none; border-radius:5px;'>عودة للرئيسية</a>")
        html_lines.append("</div>")
        
        return "\n".join(html_lines)
    except Exception as e:
        return f"حدث خطأ: {e}"

@app.route('/fix/diagnose_treasury')
@login_required
def diagnose_treasury():
    """تشخيص حالة الخزائن: عرض كل الفواتير اللي عليها فلوس مفقودة"""
    if current_user.role != 'general_manager':
        return "غير مصرح لك", 403

    try:
        lines = []

        # 1. فحص كل الفواتير الموجودة
        orders = SaleOrder.query.filter(SaleOrder.is_proforma == False).all()
        lines.append(f"<h3>عدد الفواتير المؤكدة (غير بروفورما): {len(orders)}</h3>")

        missing_invoices = []
        for order in orders:
            total_paid_expected = round_half(order.paid_upfront or 0)
            if total_paid_expected <= 0:
                continue

            existing_txs_raw = FinancialTransaction.query.filter(
                FinancialTransaction.description.like(f'%فاتورة #{order.id}%')
            ).all()

            total_tx_found = 0.0
            for tx in existing_txs_raw:
                if tx.description and re.search(rf'فاتورة #{order.id}(?!\d)', tx.description):
                    if tx.type == 'income':
                        total_tx_found += tx.amount

            missing = round_half(total_paid_expected - total_tx_found)
            if missing > 0.01:
                missing_invoices.append({
                    'id': order.id,
                    'expected': total_paid_expected,
                    'found': total_tx_found,
                    'missing': missing,
                    'customer': order.customer.name if order.customer else 'نقدي'
                })

        if missing_invoices:
            lines.append(f"<h3 style='color:red;'>فواتير بها فلوس مفقودة: {len(missing_invoices)}</h3>")
            lines.append("<table border='1' style='border-collapse:collapse; width:100%; text-align:center;'>")
            lines.append("<tr style='background:#f2f2f2;'><th>الفاتورة</th><th>العميل</th><th>المتوقع</th><th>الموجود</th><th>المفقود</th></tr>")
            total_missing = 0
            for inv in missing_invoices:
                lines.append(f"<tr><td>#{inv['id']}</td><td>{inv['customer']}</td><td>{inv['expected']}</td><td>{inv['found']}</td><td style='color:red;font-weight:bold;'>{inv['missing']}</td></tr>")
                total_missing += inv['missing']
            lines.append(f"<tr style='background:#ffe0e0;font-weight:bold;'><td colspan='4'>الإجمالي</td><td>{total_missing}</td></tr>")
            lines.append("</table>")
        else:
            lines.append("<h3 style='color:green;'>لا توجد فواتير بها فلوس مفقودة (من الفواتير الموجودة)</h3>")

        # 2. فحص دفعات العملاء اليتيمة (دفعات لفواتير اتمسحت)
        lines.append("<hr><h3>فحص دفعات العملاء اليتيمة (لفواتير محذوفة):</h3>")
        all_payments = CustomerPayment.query.filter(
            CustomerPayment.notes.like('%فاتورة #%')
        ).all()

        orphan_payments = []
        for cp in all_payments:
            if not cp.notes:
                continue
            match = re.search(r'فاتورة #(\d+)', cp.notes)
            if match:
                order_id = int(match.group(1))
                order = SaleOrder.query.get(order_id)
                if not order:
                    orphan_payments.append({'payment_id': cp.id, 'order_id': order_id, 'amount': cp.amount, 'notes': cp.notes[:60]})

        if orphan_payments:
            lines.append(f"<p style='color:orange;'>وُجدت {len(orphan_payments)} دفعة لفواتير محذوفة</p>")
            for op in orphan_payments[:20]:
                lines.append(f"<p>- دفعة #{op['payment_id']}: فاتورة #{op['order_id']} | {op['amount']} ج.م | {op['notes']}</p>")
        else:
            lines.append("<p style='color:green;'>لا توجد دفعات يتيمة</p>")

        # 3. فحص سجلات الترميم الموجودة
        lines.append("<hr><h3>سجلات ترميم موجودة حالياً:</h3>")
        restore_txs = FinancialTransaction.query.filter(
            or_(
                FinancialTransaction.description.like('%إسترداد دفعات مفقودة%'),
                FinancialTransaction.description.like('%ترميم - فاتورة%'),
                FinancialTransaction.description.like('%ترميم -%')
            )
        ).all()
        if restore_txs:
            restore_total = sum(tx.amount for tx in restore_txs)
            lines.append(f"<p>{len(restore_txs)} سجل ترميم بإجمالي {restore_total} ج.م</p>")
            for tx in restore_txs:
                lines.append(f"<p>- TX#{tx.id}: {tx.amount} ج.م | حساب #{tx.account_id} | {tx.description[:80]}</p>")
        else:
            lines.append("<p style='color:red;font-weight:bold;'>لا توجد سجلات ترميم! إذا كان السكريبت شغّل قبل كده ومسحها الـ web route، الفلوس ضاعت!</p>")

        # 4. أرصدة الخزائن
        lines.append("<hr><h3>أرصدة الخزائن:</h3>")
        lines.append("<table border='1' style='border-collapse:collapse; width:100%; text-align:center;'>")
        lines.append("<tr style='background:#f2f2f2;'><th>الخزينة</th><th>الرصيد المخزن</th><th>الرصيد المحسوب</th><th>الحالة</th></tr>")

        accounts = MoneyAccount.query.all()
        for acc in accounts:
            calc = db.session.query(func.sum(FinancialTransaction.amount)).filter(
                FinancialTransaction.account_id == acc.id
            ).scalar() or 0.0
            diff = round_half(acc.balance - calc)
            color = 'green' if abs(diff) < 0.01 else 'red'
            status = 'متطابق' if abs(diff) < 0.01 else f'فرق: {diff}'
            lines.append(f"<tr><td>{acc.name}</td><td>{acc.balance}</td><td>{round_half(calc)}</td><td style='color:{color};'>{status}</td></tr>")

        lines.append("</table>")

        content = '\n'.join(lines)
        return f"""
        <div style="padding:30px; font-family:tahoma; direction:rtl; max-width:900px; margin:auto;">
            <h1>تقرير تشخيص الخزائن</h1>
            {content}
            <br><br>
            <a href="/fix/recalculate_treasury" style="background:#0d6efd; color:white; padding:10px 20px; text-decoration:none; border-radius:5px; margin:5px;">إعادة حساب الأرصدة</a>
            <a href="/dashboard" style="background:#6c757d; color:white; padding:10px 20px; text-decoration:none; border-radius:5px; margin:5px;">العودة</a>
        </div>
        """

    except Exception as e:
        return f"حدث خطأ: {e}"

@app.route('/fix/redistribute_restoration', methods=['GET', 'POST'])
@login_required
def redistribute_restoration():
    """إعادة توزيع سجلات الترميم على الخزائن الصحيحة"""
    if current_user.role != 'general_manager':
        return "غير مصرح لك", 403

    try:
        default_acc = MoneyAccount.query.filter_by(type='cash').first()
        if not default_acc:
            default_acc = MoneyAccount.query.first()

        # === الخطوة 1: تحليل سجلات الترميم الحالية ===
        old_restore_txs = FinancialTransaction.query.filter(
            or_(
                FinancialTransaction.description.like('%إسترداد دفعات مفقودة%'),
                FinancialTransaction.description.like('%ترميم - فاتورة%'),
                FinancialTransaction.description.like('%ترميم -%')
            )
        ).all()

        if not old_restore_txs:
            return """
            <div style="text-align:center; padding:50px; font-family:tahoma; direction:rtl;">
                <h1 style="color:orange;">لا توجد سجلات ترميم لإعادة توزيعها</h1>
                <a href="/fix/diagnose_treasury">تشخيص الخزائن</a>
            </div>
            """

        # === الخطوة 2: لكل سجل ترميم، نحدد الخزينة الصحيحة ===
        redistribution_plan = []
        for tx in old_restore_txs:
            # استخراج رقم الفاتورة من الوصف
            match = re.search(r'فاتورة #(\d+)', tx.description)
            if not match:
                redistribution_plan.append({
                    'tx_id': tx.id,
                    'order_id': None,
                    'amount': tx.amount,
                    'old_account_id': tx.account_id,
                    'old_account_name': MoneyAccount.query.get(tx.account_id).name if MoneyAccount.query.get(tx.account_id) else '?',
                    'new_account_id': tx.account_id,
                    'new_account_name': 'نفس الحساب (لم يتم تحديد الفاتورة)',
                    'description': tx.description,
                    'changed': False
                })
                continue

            order_id = int(match.group(1))

            # البحث عن الخزينة الصحيحة من دفعات العملاء الأصلية
            original_cps = CustomerPayment.query.filter(
                CustomerPayment.notes.like(f'%فاتورة #{order_id}%'),
                ~CustomerPayment.notes.like('%إسترداد%'),
                ~CustomerPayment.notes.like('%ترميم%')
            ).all()

            # فلترة بالريجكس للمطابقة الدقيقة
            exact_cps = [cp for cp in original_cps if cp.notes and re.search(rf'فاتورة #{order_id}(?!\d)', cp.notes)]

            # تحديد الخزينة الصحيحة
            if exact_cps and exact_cps[0].account_id:
                target_acc = MoneyAccount.query.get(exact_cps[0].account_id)
                if not target_acc:
                    target_acc = default_acc
            else:
                # لو مفيش CustomerPayment، نشوف الحركات المالية الأصلية
                original_txs = FinancialTransaction.query.filter(
                    FinancialTransaction.description.like(f'%فاتورة #{order_id}%'),
                    FinancialTransaction.type == 'income',
                    ~FinancialTransaction.description.like('%إسترداد%'),
                    ~FinancialTransaction.description.like('%ترميم%')
                ).all()
                exact_orig_txs = [t for t in original_txs if t.description and re.search(rf'فاتورة #{order_id}(?!\d)', t.description)]

                if exact_orig_txs:
                    target_acc = MoneyAccount.query.get(exact_orig_txs[0].account_id) or default_acc
                else:
                    target_acc = default_acc

            old_acc = MoneyAccount.query.get(tx.account_id)
            changed = tx.account_id != target_acc.id

            redistribution_plan.append({
                'tx_id': tx.id,
                'order_id': order_id,
                'amount': tx.amount,
                'old_account_id': tx.account_id,
                'old_account_name': old_acc.name if old_acc else '?',
                'new_account_id': target_acc.id,
                'new_account_name': target_acc.name,
                'description': tx.description,
                'changed': changed
            })

        # === GET: عرض الخطة قبل التنفيذ ===
        if request.method == 'GET':
            rows_html = ""
            total_moved = 0
            for item in redistribution_plan:
                color = '#fff3cd' if item['changed'] else '#d4edda'
                arrow = ' ← سيتغير' if item['changed'] else ' (نفسه)'
                rows_html += f"""
                <tr style="background:{color};">
                    <td>#{item['order_id'] or '?'}</td>
                    <td>{item['amount']} ج.م</td>
                    <td>{item['old_account_name']}</td>
                    <td>{item['new_account_name']}{arrow}</td>
                </tr>
                """
                if item['changed']:
                    total_moved += item['amount']

            changes_count = sum(1 for x in redistribution_plan if x['changed'])

            return f"""
            <div style="padding:30px; font-family:tahoma; direction:rtl; max-width:900px; margin:auto;">
                <h1>خطة إعادة توزيع الترميم</h1>
                <h3>إجمالي سجلات الترميم: {len(redistribution_plan)}</h3>
                <h3 style="color:{'orange' if changes_count > 0 else 'green'};">سجلات ستتغير خزنتها: {changes_count} (بإجمالي {total_moved} ج.م)</h3>

                <table border="1" style="border-collapse:collapse; width:100%; text-align:center; margin:20px 0;">
                    <tr style="background:#f2f2f2;">
                        <th>الفاتورة</th><th>المبلغ</th><th>الخزينة الحالية</th><th>الخزينة الصحيحة</th>
                    </tr>
                    {rows_html}
                </table>

                <form method="POST" style="text-align:center; margin-top:20px;">
                    <button type="submit" style="background:#dc3545; color:white; padding:15px 40px; border:none; border-radius:5px; font-size:18px; font-family:tahoma; cursor:pointer;">
                        تنفيذ إعادة التوزيع الآن
                    </button>
                </form>
                <br>
                <a href="/fix/diagnose_treasury" style="margin:10px;">العودة للتشخيص</a>
            </div>
            """

        # === POST: تنفيذ إعادة التوزيع ===
        changes_made = 0
        log_lines = []

        for item in redistribution_plan:
            if item['changed']:
                # جلب سجل الترميم وتعديل الخزينة
                tx = FinancialTransaction.query.get(item['tx_id'])
                if tx:
                    old_name = item['old_account_name']
                    tx.account_id = item['new_account_id']
                    tx.description = f"ترميم - فاتورة #{item['order_id']} (نُقل من {old_name} للخزينة الصحيحة)"
                    changes_made += 1
                    log_lines.append(f"فاتورة #{item['order_id']}: {item['amount']} ج.م | {old_name} → {item['new_account_name']}")

        # إعادة حساب أرصدة كل الخزائن
        accounts = MoneyAccount.query.all()
        balance_log = []
        for acc in accounts:
            real_balance = db.session.query(func.sum(FinancialTransaction.amount)).filter(
                FinancialTransaction.account_id == acc.id
            ).scalar() or 0.0
            old_bal = acc.balance
            acc.balance = real_balance
            if abs(old_bal - real_balance) > 0.01:
                balance_log.append(f"{acc.name}: {old_bal} → {real_balance}")

        db.session.commit()

        details = '<br>'.join(log_lines) if log_lines else 'لا توجد تغييرات'
        balance_details = '<br>'.join(balance_log) if balance_log else 'لم تتغير الأرصدة'

        return f"""
        <div style="text-align:center; padding:50px; font-family:tahoma; direction:rtl; max-width:900px; margin:auto;">
            <h1 style="color:green;">تم إعادة التوزيع بنجاح!</h1>
            <h3>تم نقل {changes_made} سجل للخزائن الصحيحة</h3>

            <div style="background:#f0f8ff; padding:20px; border:1px solid #ddd; display:inline-block; text-align:right; margin:20px;">
                <h4>التفاصيل:</h4>
                <div style="font-size:13px;">{details}</div>
                <hr>
                <h4>تحديث أرصدة الخزائن:</h4>
                <div style="font-size:13px;">{balance_details}</div>
            </div>
            <br><br>
            <a href="/fix/diagnose_treasury" style="background:#0d6efd; color:white; padding:10px 20px; text-decoration:none; border-radius:5px;">فحص الخزائن بعد التعديل</a>
        </div>
        """

    except Exception as e:
        db.session.rollback()
        return f"حدث خطأ: {e}"

@app.route('/fix/force_reset_settings')
def force_reset_settings():
    try:
        # 1. حذف جدول الإعدادات القديم (لضمان نظافة العمل)
        # checkfirst=True تعني: احذفه فقط لو كان موجوداً
        SystemSetting.__table__.drop(db.engine, checkfirst=True)

        # 2. إنشاء الجدول من جديد بالأعمدة الصحيحة
        SystemSetting.__table__.create(db.engine)

        # 3. إضافة البيانات الافتراضية
        default_setting = SystemSetting()
        db.session.add(default_setting)
        db.session.commit()

        return """
        <h2 style='color:green; text-align:center; margin-top:50px;'>
            ✅ تم إعادة بناء جدول الإعدادات بنجاح!
            <br><br>
            <a href='/settings'>اذهب لصفحة الإعدادات الآن</a>
        </h2>
        """
    except Exception as e:
        return f"❌ حدث خطأ: {str(e)}"
@app.route('/fix/adjust_old_dates')
@general_manager_required
def adjust_old_dates():
    try:
        # مقدار الوقت المراد إضافته (مثلاً ساعتين)
        # لو التوقيت صيفي ومحتاج تزود 3 ساعات، خليها hours=3
        offset = timedelta(hours=2)

        count = 0

        # 1. تحديث الفواتير
        for r in SaleOrder.query.all():
            if r.date:
                r.date += offset
                count += 1

        # 2. تحديث الحركات المالية
        for r in FinancialTransaction.query.all():
            if r.date:
                r.date += offset
                count += 1

        # 3. تحديث حركات المخزون
        for r in StockMovement.query.all():
            if r.timestamp:
                r.timestamp += offset
                count += 1

        # 4. تحديث حركات الموظفين والرواتب
        for r in HRTransaction.query.all():
            if r.date:
                r.date += offset
                count += 1

        # 5. تحديث المصروفات
        for r in Expense.query.all():
            if r.date:
                r.date += offset
                count += 1

        # 6. تحديث حركات الشركاء
        for r in PartnerTransaction.query.all():
            if r.date:
                r.date += offset
                count += 1

        # 7. تحديث الحضور والانصراف
        for r in Attendance.query.all():
            if r.check_in:
                r.check_in += offset
            if r.check_out:
                r.check_out += offset
            count += 1

        db.session.commit()

        return f"""
        <div style="text-align:center; padding:50px;">
            <h1 style="color:green;">✅ تم تعديل التواريخ بنجاح!</h1>
            <h3>تم تحديث {count} سجل وإضافة ساعتين للوقت.</h3>
            <a href="/dashboard">عودة للرئيسية</a>
        </div>
        """

    except Exception as e:
        db.session.rollback()
        return f"حدث خطأ: {e}"
# === كود إصلاح الشحنات القديمة (شغله مرة واحدة) ===
@app.route('/partners/settle_all', methods=['POST'])
@general_manager_required
def partner_settlement_all():
    try:
        account_id = request.form.get('account_id')
        notes = request.form.get('notes', 'تصفية مجمعة (مقاصة أرباح وديون)')

        if not account_id:
            flash('يجب اختيار الخزينة', 'danger')
            return redirect(url_for('partners_report'))

        account = MoneyAccount.query.get(account_id)
        partners = User.query.filter_by(role='manager').all()

        net_payout = 0

        for p in partners:
            # حساب الرصيد الحالي (سواء موجب أو سالب)
            current_balance = db.session.query(func.sum(PartnerTransaction.amount)).filter_by(partner_id=p.id).scalar() or 0

            if current_balance != 0:
                # تصفير الحساب: لو له 100 بنسجل -100، لو عليه 100 بنسجل +100
                db.session.add(PartnerTransaction(
                    partner_id=p.id,
                    type='withdrawal',
                    amount=-current_balance,
                    description=f"تصفية مجمعة لتصفير الرصيد: {notes}",
                    date=cairo_now()
                ))
                # جمع جبري للمبالغ (الموجب بيزود والاصلي السالب بينقص من الإجمالي)
                net_payout += current_balance

        # تحديث الخزينة بالصافي النهائي
        if net_payout != 0:
            account.balance -= net_payout

            db.session.add(FinancialTransaction(
                account_id=account.id,
                type='expense' if net_payout > 0 else 'income',
                category='تصفية شركاء',
                amount=-net_payout,
                description=f"صافي صرف تصفية مجمعة للشركاء (مقاصة)",
                created_by_id=current_user.id,
                date=cairo_now()
            ))

            db.session.commit()
            flash(f'✅ تمت المقاصة بنجاح! الصافي المنصرف من الخزنة: {net_payout} ج.م، وتم تصفير حسابات الجميع.', 'success')
        else:
            flash('⚠️ الأرصدة مصفره بالفعل.', 'info')

    except Exception as e:
        db.session.rollback()
        flash(f'❌ حدث خطأ: {str(e)}', 'danger')

    return redirect(url_for('partners_report'))
@app.route('/fix/restore_shipping_orders')
@login_required
def restore_shipping_orders():
    if current_user.role != 'general_manager':
        return "غير مصرح لك"

    # البحث عن كل الشحنات التي تم إنهاؤها (settled)
    # سنعيدها إلى حالة (delivered) لكي تظهر لك مجدداً وتقوم بتحصيلها
    orders = SaleOrder.query.filter_by(is_shipping=True, shipping_status='settled').all()

    count = 0
    for o in orders:
        o.shipping_status = 'delivered'
        count += 1

    db.session.commit()

    return f"""
    <div style="text-align:center; padding:50px; font-family: tahoma;">
        <h1 style="color:green;">✅ تم استرجاع {count} شحنة بنجاح!</h1>
        <h3>تمت إعادة الشحنات المنتهية إلى حالة "تم التوصيل".</h3>
        <p>الآن ستجدها ظهرت في صفحة "متابعة الشحن".</p>
        <p><strong>المطلوب منك:</strong> اضغط على زر "تحصيل وإيداع" لكل واحدة لاختيار الخزينة وإدخال الأموال.</p>
        <br>
        <a href="/shipping/orders" style="background:#0d6efd; color:white; padding:10px 20px; text-decoration:none; border-radius:5px;">الذهاب لصفحة الشحن</a>
    </div>
    """
# === كود طباعة كتالوج المنتجات ===
@app.route('/inventory/print_catalog')
@login_required  # متاح لأي شخص مسجل دخول
def print_inventory_catalog():
    # استقبال الأقسام من الرابط كقائمة
    cat_ids = request.args.getlist('category_id')

    # الاستعلام الأساسي: ترتيب بالكود + (شرط المخزون أكبر من صفر)
    query = ProductVariant.query.filter(ProductVariant.stock > 0).join(ProductModel).order_by(ProductVariant.id)

    title_text = "كل المنتجات المتوفرة"

    # تطبيق فلتر التصنيف لو اختار أكتر من قسم ومفيش "all"
    if cat_ids and 'all' not in cat_ids:
        query = query.filter(ProductModel.category_id.in_(cat_ids))
        
        # تجميع أسماء الأقسام للعنوان
        categories = Category.query.filter(Category.id.in_(cat_ids)).all()
        if categories:
            title_text = " - ".join([c.name for c in categories])

    products = query.all()

    return render_template('print_catalog.html', products=products, catalog_title=title_text)

@app.route('/inventory/print_stock')
@login_required
def print_stock():
    # جلب جميع المنتجات وترتيبها حسب التصنيف ثم الاسم
    products = ProductVariant.query.join(ProductModel).join(Category)\
        .order_by(Category.name, ProductModel.name).all()
    
    # تجميع المنتجات حسب التصنيف
    grouped = {}
    for p in products:
        cat_name = p.model.category.name if p.model.category else "بدون تصنيف"
        if cat_name not in grouped:
            grouped[cat_name] = []
        grouped[cat_name].append(p)
    
    # تنسيق الوقت الحالي
    from datetime import datetime
    now_str = datetime.now().strftime("%Y-%m-%d %I:%M %p")
    
    return render_template('print_stock.html', grouped_products=grouped, now=now_str)

# ==========================================
# أوامر التصنيع الخارجية (قصات)
# ==========================================

@app.route('/api/get_product_by_barcode')
@login_required
def get_product_by_barcode():
    barcode = request.args.get('barcode', '').strip()
    if not barcode:
        return jsonify({'success': False, 'error': 'لم يتم إدخال كلمة بحث'})
        
    model = None
    # 1. Search by barcode in variants
    variant = ProductVariant.query.filter_by(barcode=barcode).first()
    if variant:
        model = variant.model
    else:
        # 2. Search by ID if numeric
        if barcode.isdigit():
            model = ProductModel.query.get(int(barcode))
        
        # 3. Search by Product Name
        if not model:
            model = ProductModel.query.filter(ProductModel.name.ilike(f'%{barcode}%')).first()
            
    if not model:
        return jsonify({'success': False, 'error': 'المنتج غير موجود'})
        
    return jsonify({
        'success': True,
        'model_id': model.id,
        'name': model.name,
        'image': model.image,
        'category': model.category.name if model.category else ''
    })

@app.route('/qassat')
@login_required
def qassat_list():
    if current_user.role != 'general_manager' and not current_user.has_perm('manage_qassat'):
        flash('ليس لديك صلاحية الدخول لهذه الصفحة.', 'danger')
        return redirect(url_for('dashboard'))
    
    # جلب المنتجات عشان الدروب داون في المودال
    products = ProductModel.query.order_by(ProductModel.name).all()
    
    # جلب القصات النشطة فقط
    active_qassat = Qassa.query.filter(Qassa.status != 'تم الاستلام').order_by(Qassa.created_at.desc()).all()
    
    # جلب القصات المستلمة
    received_qassat = Qassa.query.filter_by(status='تم الاستلام').order_by(Qassa.created_at.desc()).limit(150).all()
    
    # تمرير cairo_now لحساب عدد الأيام
    return render_template('qassat.html', active_qassat=active_qassat, received_qassat=received_qassat, products=products, current_time=cairo_now())

@app.route('/qassat/add', methods=['POST'])
@login_required
def qassat_add():
    if current_user.role != 'general_manager' and not current_user.has_perm('manage_qassat'):
        return abort(403)
        
    product_model_id = request.form.get('product_model_id')
    custom_name = request.form.get('custom_name')
    code = request.form.get('code')
    factory = request.form.get('factory')
    quantity = request.form.get('quantity', type=int, default=1)
    
    # رفع صورة لو فيه واسمها بيختلف عشان ميحصلش تعارض
    custom_image = 'default.png'
    file = request.files.get('custom_image')
    if file and file.filename != '':
        filename = secure_filename(f"qassa_{cairo_now().strftime('%Y%m%d%H%M%S')}_{file.filename}")
        save_uploaded_file(file, filename)
        custom_image = filename
        
    if product_model_id and product_model_id != '':
        new_qassa = Qassa(
            product_model_id=int(product_model_id),
            code=code,
            factory=factory,
            quantity=quantity
        )
    else:
        new_qassa = Qassa(
            custom_name=custom_name,
            custom_image=custom_image,
            code=code,
            factory=factory,
            quantity=quantity
        )
        
    db.session.add(new_qassa)
    db.session.commit()
    
    flash('تم إضافة القصة بنجاح.', 'success')
    return redirect(url_for('qassat_list'))

@app.route('/qassat/followup/<int:id>', methods=['POST'])
@login_required
def qassat_followup(id):
    if current_user.role != 'general_manager' and not current_user.has_perm('manage_qassat'):
        return abort(403)
        
    qassa = Qassa.query.get_or_404(id)
    note = request.form.get('note')
    
    if note and note.strip():
        history = QassaHistory(
            qassa_id=qassa.id,
            user_id=current_user.id,
            action_detail=note.strip()
        )
        db.session.add(history)
        db.session.commit()
        flash('تم إضافة المتابعة بنجاح.', 'success')
        
    return redirect(url_for('qassat_list'))

@app.route('/qassat/status/<int:id>', methods=['POST'])
@login_required
def qassat_status(id):
    if current_user.username != 'Abo_Eyad':
        return abort(403)
        
    qassa = Qassa.query.get_or_404(id)
    new_status = request.form.get('status')
    if new_status in ['جار التصنيع', 'تم الاستلام']:
        qassa.status = new_status
        db.session.commit()
        
        if new_status == 'تم الاستلام':
            flash('تم استلام القصة وإخفاؤها من القائمة النشطة.', 'success')
        else:
            flash('تم تحديث حالة القصة.', 'info')
            
    return redirect(url_for('qassat_list'))

@app.route('/qassat/delete/<int:id>', methods=['POST'])
@login_required
def qassat_delete(id):
    if current_user.username != 'Abo_Eyad':
        return abort(403)
        
    qassa = Qassa.query.get_or_404(id)
    db.session.delete(qassa)
    db.session.commit()
    flash('تم حذف القصة بنجاح.', 'success')
    return redirect(url_for('qassat_list'))

@app.route('/qassat/edit_factory/<int:id>', methods=['POST'])
@login_required
def qassat_edit_factory(id):
    if current_user.role != 'general_manager' and not current_user.has_perm('manage_qassat'):
        return abort(403)
        
    qassa = Qassa.query.get_or_404(id)
    new_factory = request.form.get('factory_name')
    if new_factory and new_factory.strip():
        history = QassaHistory(
            qassa_id=qassa.id,
            user_id=current_user.id,
            action_detail=f"تم تعديل اسم المصنع من ({qassa.factory}) إلى ({new_factory.strip()})"
        )
        db.session.add(history)
        
        qassa.factory = new_factory.strip()
        db.session.commit()
        flash('تم تعديل اسم المصنع بنجاح.', 'success')
        
    return redirect(url_for('qassat_list'))

@app.route('/api/search_product')
def search_product():
    q = request.args.get('q', '')
    # بنجيب المنتج مع التصنيف بتاعه عشان نعرضه
    products = ProductModel.query.join(Category).filter(ProductModel.name.ilike(f'%{q}%')).limit(20).all()
    results = []
    for p in products:
        results.append({
            'id': p.id,
            'name': p.name,       # الاسم الصافي
            'category_id': p.category_id,
            'category_name': p.category.name,
            # دا اللي هيظهرلك في القائمة: "اسم المنتج (اسم التصنيف)"
            'label': f"{p.name} - ({p.category.name})"
        })
    return jsonify(results)
@app.route('/purchases/return', methods=['GET', 'POST'])
@login_required
def purchase_return():
    if request.method == 'POST':
        supplier_id = request.form.get('supplier_id')
        names = request.form.getlist('name[]')
        product_ids = request.form.getlist('product_id[]')
        costs = request.form.getlist('cost[]')
        qtys = request.form.getlist('qty[]')

        if not product_ids:
            flash('لم يتم اختيار أصناف للمرتجع!', 'warning')
            return redirect(request.url)

        supplier = Supplier.query.get(supplier_id)
        total_return_value = 0.0

        for i in range(len(product_ids)):
            p_id = product_ids[i]
            if not p_id: continue

            try:
                qty = int(qtys[i])
                cost = float(costs[i])
            except: continue

            variant = ProductVariant.query.get(p_id)
            if variant:
                # 1. التحقق من المخزون قبل الخصم
                if variant.stock < qty:
                    flash(f'الكمية غير كافية للمنتج: {variant.model.name} (المتاح: {variant.stock})', 'danger')
                    return redirect(request.referrer)
                variant.stock -= qty

                # 2. تسجيل حركة المخزن (بالسالب)
                db.session.add(StockMovement(
                    variant_id=variant.id,
                    user_id=current_user.id,
                    quantity_change=-qty,
                    reason=f"مرتجع شراء للمورد: {supplier.name}"
                ))

                total_return_value += (cost * qty)

        # 3. خصم إجمالي المرتجع من حساب المورد (تقليل المديونية)
        if supplier:
            supplier.balance -= total_return_value

        db.session.commit()
        flash(f'تم تسجيل المرتجع بنجاح ✅ وخصم {total_return_value} من حساب المورد', 'success')
        return redirect(url_for('supplier_profile', id=supplier.id))

    # في حالة الـ GET (عرض الصفحة)
    return render_template('new_purchase_return.html',
                           suppliers=Supplier.query.all(),
                           product_suggestions=ProductVariant.query.all())
@app.route('/fix/correct_settled_invoices')
@login_required
def correct_settled_invoices():
    if current_user.role != 'general_manager': return "غير مصرح"

    # البحث عن الفواتير التي حالتها "تم التحصيل" ولكن عليها مديونية
    orders = SaleOrder.query.filter(
        SaleOrder.shipping_status == 'settled',
        SaleOrder.amount_due > 0
    ).all()

    count = 0
    for o in orders:
        o.amount_due = 0 # تصفير المديونية
        count += 1

    db.session.commit()
    return f"تم تصحيح {count} فاتورة محصلة لتظهر كـ 'خالص'."
# === كود كشف العجز (Audit) ===
@app.route('/audit/system_gap')
@general_manager_required
def audit_system_gap():
    try:
        report = []
        total_gap_valuation = 0

        # 1. كشف فروقات تقييم المخزون (أخطر سبب)
        # الفكرة: هنقارن (أعلى سعر اشترينا بيه الصنف) مع (سعر التكلفة الحالي المسجل)
        # لو السعر الحالي أقل من سعر الشراء، ده بيعمل عجز في قيمة المخزن مقارنة بدين المورد

        products = ProductVariant.query.filter(ProductVariant.stock > 0).all()

        report.append("<h3>1. تحليل فروقات أسعار التكلفة (Valuation Gap)</h3>")
        report.append("<table border='1' style='width:100%; border-collapse:collapse; text-align:center;'>")
        report.append("<tr style='background:#f2f2f2;'><th>المنتج</th><th>المخزون الحالي</th><th>سعر التكلفة الحالي</th><th>متوسط سعر الشراء الفعلي</th><th>فرق السعر</th><th>قيمة العجز</th></tr>")

        for p in products:
            # نجيب كل مرات الشراء للمنتج ده
            purchase_items = PurchaseItem.query.filter_by(variant_id=p.id).all()

            if not purchase_items: continue

            # حساب متوسط سعر الشراء الفعلي لهذا المنتج
            total_qty_bought = sum(item.quantity for item in purchase_items)
            total_cost_bought = sum(item.total_cost for item in purchase_items)

            if total_qty_bought > 0:
                avg_purchase_price = total_cost_bought / total_qty_bought
            else:
                avg_purchase_price = 0

            # لو سعر التكلفة الحالي (المسجل في الكارت) أقل من اللي اشترينا بيه
            # ده معناه إن المخزن متقيم بأقل من قيمته الحقيقية (وده سبب العجز)
            if p.cost_price < avg_purchase_price:
                diff = avg_purchase_price - p.cost_price
                gap_value = diff * p.stock # العجز = الفرق × الكمية الموجودة

                # تجاهل الفروقات التافهة (أقل من قرش)
                if gap_value > 1:
                    total_gap_valuation += gap_value
                    report.append(f"""
                    <tr>
                        <td>{p.model.name}</td>
                        <td>{p.stock}</td>
                        <td style='color:red'>{round_half(p.cost_price)}</td>
                        <td style='color:green'>{round_half(avg_purchase_price)}</td>
                        <td>{round_half(diff)}</td>
                        <td style='font-weight:bold;'>{round_half(gap_value)}</td>
                    </tr>
                    """)

        report.append(f"<tr><td colspan='5'><b>إجمالي عجز تقييم المخزون</b></td><td style='background:yellow; font-weight:bold'>{round_half(total_gap_valuation)}</td></tr>")
        report.append("</table>")

        # 2. كشف التلاعب اليدوي في أرصدة الموردين
        report.append("<br><h3>2. تحليل أرصدة الموردين (هل تم تعديل الرصيد يدوياً؟)</h3>")
        report.append("<table border='1' style='width:100%; border-collapse:collapse; text-align:center;'>")
        report.append("<tr style='background:#f2f2f2;'><th>المورد</th><th>الرصيد الحالي (في السيستم)</th><th>الرصيد المفترض (فواتير - سداد)</th><th>الفرق (تعديل يدوي)</th></tr>")

        suppliers = Supplier.query.all()
        total_manual_diff = 0

        for s in suppliers:
            # الرصيد المفترض = (مجموع فواتير الشراء) - (مجموع السدادات)
            total_purchases = sum(o.total_cost for o in s.orders)
            total_payments = sum(p.amount for p in s.payments)
            calculated_balance = total_purchases - total_payments

            diff = s.balance - calculated_balance

            if abs(diff) > 1: # لو الفرق أكبر من جنيه
                total_manual_diff += diff
                report.append(f"""
                <tr>
                    <td>{s.name}</td>
                    <td>{round_half(s.balance)}</td>
                    <td>{round_half(calculated_balance)}</td>
                    <td style='color:red; font-weight:bold'>{round_half(diff)}</td>
                </tr>
                """)

        report.append(f"<tr><td colspan='3'><b>إجمالي الفروقات اليدوية</b></td><td style='background:yellow; font-weight:bold'>{round_half(total_manual_diff)}</td></tr>")
        report.append("</table>")

        # الخلاصة
        total_found = total_gap_valuation + total_manual_diff
        report.append(f"""
        <div style='margin-top:30px; padding:20px; background:#e8f0fe; border:2px solid #0d6efd;'>
            <h2>💡 ملخص التحقيق:</h2>
            <ul>
                <li>قيمة العجز الناتج عن تغيير أسعار التكلفة: <b>{round_half(total_gap_valuation)}</b></li>
                <li>قيمة العجز الناتج عن تعديل أرصدة الموردين يدوياً: <b>{round_half(total_manual_diff)}</b></li>
                <li style='font-size:1.5em; color:green'>إجمالي المبلغ الذي تم العثور عليه: <b>{round_half(total_found)}</b></li>
            </ul>
        </div>
        <br><br>
        <a href='/dashboard' style='padding:10px 20px; background:#333; color:white; text-decoration:none;'>عودة</a>
        """)

        return "".join(report)

    except Exception as e:
        return f"حدث خطأ: {e}"
@app.route('/audit/manual_adjustments')
@general_manager_required
def audit_manual_adjustments():
    try:
        report = []
        report.append("<h3>3. تحليل التسويات اليدوية للمخزون (Manual Stock Adjustments)</h3>")
        report.append("<p>هذا التقرير يجمع كل المرات التي تم فيها إنقاص المخزون يدوياً (ليس بيع ولا مرتجع ولا تحويل فواتير).</p>")
        report.append("<table border='1' style='width:100%; border-collapse:collapse; text-align:center;'>")
        report.append("<tr style='background:#f2f2f2;'><th>المنتج</th><th>الكمية المحذوفة</th><th>سعر التكلفة</th><th>قيمة العجز</th><th>السبب المسجل</th><th>التاريخ</th></tr>")

        movements = StockMovement.query.filter(StockMovement.quantity_change < 0).all()

        total_manual_loss = 0

        for mov in movements:
            # === التعديل هنا: إضافة كلمة 'تحويل' لقائمة الاستثناءات ===
            # تجاهل: بيع، فاتورة، شراء، تحويل (من مسودة لفاتورة)
            is_sales = ('بيع' in mov.reason) or \
                       ('فاتورة' in mov.reason) or \
                       ('شراء' in mov.reason) or \
                       ('تحويل' in mov.reason)

            if not is_sales:
                variant = ProductVariant.query.get(mov.variant_id)
                if variant:
                    qty_lost = abs(mov.quantity_change)
                    cost = variant.cost_price
                    loss_value = qty_lost * cost

                    total_manual_loss += loss_value

                    report.append(f"""
                    <tr>
                        <td>{variant.model.name}</td>
                        <td style='color:red; font-weight:bold'>{mov.quantity_change}</td>
                        <td>{cost}</td>
                        <td style='background:#ffeeba;'>{loss_value}</td>
                        <td>{mov.reason}</td>
                        <td>{mov.timestamp.strftime('%Y-%m-%d')}</td>
                    </tr>
                    """)

        report.append(f"<tr><td colspan='3'><b>إجمالي قيمة البضاعة المحذوفة يدوياً</b></td><td style='background:red; color:white; font-weight:bold; font-size:1.2em;'>{round_half(total_manual_loss)}</td><td colspan='2'></td></tr>")
        report.append("</table>")

        report.append(f"""
        <div style='margin-top:20px; padding:15px; border:2px solid #333;'>
            <h4>💡 الخلاصة:</h4>
            <p>المبلغ <b>{round_half(total_manual_loss)}</b> هو الهالك الفعلي أو التعديل اليدوي الصريح (بعيداً عن المبيعات والتحويلات).</p>
        </div>
        <br>
        <a href='/dashboard' class='btn btn-dark'>عودة</a>
        """)

        return "".join(report)

    except Exception as e:
        return f"حدث خطأ: {e}"
@app.route('/fix/create_excuse_table')
@general_manager_required
def create_excuse_table():
    try:
        inspector = inspect(db.engine)
        if 'employee_excuse' not in inspector.get_table_names():
            EmployeeExcuse.__table__.create(db.engine)
            return "✅ تم إنشاء جدول الأذونات (EmployeeExcuse) بنجاح!"
        else:
            return "⚠️ الجدول موجود بالفعل في قاعدة البيانات."
    except Exception as e:
        return f"❌ حدث خطأ: {str(e)}"
# === أداة إصلاح وتعديل مرتجعات الشراء ===
@app.route('/fix/purchase_returns_list')
@permission_required('manage_inventory')
def fix_purchase_returns_list():
    # جلب آخر 10 حركات مرتجع شراء
    moves = StockMovement.query.filter(
        StockMovement.reason.like('مرتجع شراء%')
    ).order_by(StockMovement.id.desc()).limit(10).all()

    # تصميم بسيط للعرض
    html = """
    <html dir="rtl">
    <head>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    </head>
    <body class="p-5 bg-light">
        <div class="container">
            <h2 class="mb-4 text-danger">🛠️ إصلاح مرتجعات الشراء (حذف المكرر)</h2>
            <div class="card shadow">
                <div class="card-body">
                    <table class="table table-bordered text-center">
                        <thead class="table-dark">
                            <tr>
                                <th>م</th>
                                <th>اسم الصنف</th>
                                <th>الكمية المرجعة</th>
                                <th>السبب (اسم المورد)</th>
                                <th>التاريخ</th>
                                <th>إجراء</th>
                            </tr>
                        </thead>
                        <tbody>
    """

    for m in moves:
        html += f"""
                            <tr>
                                <td>{m.id}</td>
                                <td>{m.variant.model.name if m.variant else 'محذوف'}</td>
                                <td class="fw-bold text-danger">{m.quantity_change}</td>
                                <td>{m.reason}</td>
                                <td>{m.timestamp.strftime('%Y-%m-%d %H:%M')}</td>
                                <td>
                                    <a href="/fix/delete_duplicate_return/{m.id}" class="btn btn-danger btn-sm" onclick="return confirm('هل أنت متأكد؟ سيتم استرجاع الكمية للمخزن وإعادة المديونية للمورد.')">
                                        <i class="fas fa-trash"></i> حذف التكرار
                                    </a>
                                </td>
                            </tr>
        """

    html += """
                        </tbody>
                    </table>
                    <a href="/dashboard" class="btn btn-secondary mt-3">عودة للرئيسية</a>
                </div>
            </div>
        </div>
    </body>
    </html>
    """
    return html

@app.route('/fix/delete_duplicate_return/<int:id>')
@permission_required('manage_inventory')
def delete_duplicate_return(id):
    try:
        move = StockMovement.query.get_or_404(id)

        # 1. استرجاع الكمية للمخزن (عكس الحركة)
        variant = ProductVariant.query.get(move.variant_id)
        qty_to_restore = abs(move.quantity_change) # الكمية بالموجب

        if variant:
            variant.stock += qty_to_restore

        # 2. استرجاع المديونية للمورد (محاولة معرفة المورد من الوصف)
        # الوصف بيكون: "مرتجع شراء للمورد: فلان"
        msg_extra = ""
        try:
            if ":" in move.reason:
                supp_name = move.reason.split(':')[1].strip()
                supplier = Supplier.query.filter_by(name=supp_name).first()
                if supplier:
                    # حساب القيمة التقريبية (الكمية * التكلفة الحالية)
                    # لأننا مش مسجلين السعر وقت المرتجع في جدول الحركة، هناخد السعر الحالي
                    cost_val = qty_to_restore * (variant.cost_price or 0)
                    supplier.balance += cost_val # بنزود حسابه تاني (لأننا لغينا المرتجع)
                    msg_extra = f"وتم إعادة {cost_val} ج.م لحساب المورد {supplier.name}."
        except Exception as e:
            msg_extra = "ولكن لم نتمكن من تعديل رصيد المورد تلقائياً، يرجى مراجعته يدوياً."

        # 3. حذف الحركة الخطأ
        db.session.delete(move)
        db.session.commit()

        return f"""
        <h2 style='color:green; text-align:center; margin-top:50px;'>
            ✅ تم حذف المرتجع المكرر بنجاح!
            <br>
            <small>تمت إعادة {qty_to_restore} قطعة للمخزن. {msg_extra}</small>
            <br><br>
            <a href='/fix/purchase_returns_list'>عودة للقائمة</a>
        </h2>
        """

    except Exception as e:
        return f"حدث خطأ: {e}"


# ============================================================
# === نظام الموافقة على الإجراءات المالية للمديرين       ===
# ============================================================

@app.route('/my_account')
@login_required
def my_account():
    """كشف حساب الموظف - يشوف الموظف كل حركاته المالية"""
    emp = current_user
    now = cairo_now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if month_start.month == 12:
        month_end = month_start.replace(year=month_start.year + 1, month=1)
    else:
        month_end = month_start.replace(month=month_start.month + 1)

    # جميع الحركات المالية (كل الأوقات) مرتبة من الأحدث
    all_transactions = HRTransaction.query.filter_by(user_id=emp.id)\
        .order_by(HRTransaction.date.desc()).all()

    # إجماليات الشهر الحالي فقط
    month_trans = [t for t in all_transactions if month_start <= t.date < month_end]
    bonuses = sum(t.amount for t in month_trans if t.type == 'bonus')
    deductions = sum(t.amount for t in month_trans if t.type == 'deduction')
    advances = sum(t.amount for t in month_trans if t.type == 'advance')

    # عمولات الشهر الحالي
    gross_items = db.session.query(func.sum(SaleItem.quantity)).join(SaleOrder).filter(
        SaleOrder.user_id == emp.id,
        SaleOrder.is_proforma == False,
        SaleOrder.date >= month_start,
        SaleOrder.date < month_end
    ).scalar() or 0
    commission = calculate_user_commission(emp, gross_items, gross_items)

    net_salary = (emp.base_salary or 0) + commission + bonuses - deductions - advances

    return render_template('my_account.html',
                           emp=emp,
                           transactions=all_transactions,
                           bonuses=round_half(bonuses),
                           deductions=round_half(deductions),
                           advances=round_half(advances),
                           commission=round_half(commission),
                           net_salary=round_half(net_salary))


# ================================================================
# === صفحة تنفيذ الرواتب الشهرية — للمدير العام فقط            ===
# ================================================================

PARTNERSHIP_USERS = ['Abo_malek']  # الشريك مع المدير العام في الشراكة
SPLIT_4_USERS = ['Elsayd_Elwekel', 'SMSM_Hamdy', 'Ehab_habls']  # المديرين الـ 3 في طريقة التقسيم على 4


def _get_user_by_username(username):
    """مساعد: جلب مستخدم بالـ username"""
    return User.query.filter_by(username=username).first()


def _record_partner_salary_expense(emp, net_salary, description, session):
    """
    تسجيل تكلفة الراتب على الشريك/الشركاء المناسبين
    حسب salary_method بتاع الموظف
    """
    method = emp.salary_method or 'direct_manager'
    
    if method == 'partnership':
        # 1. الشراكة ( gm 50% - Abo_malek 50% )
        half_amount = net_salary / 2
        gm = User.query.filter_by(username='gm').first() or User.query.filter_by(role='general_manager').first()
        abo_malek = User.query.filter_by(username='Abo_malek').first()
        
        if gm:
            session.add(PartnerTransaction(partner_id=gm.id, type='salary_expense', amount=-half_amount, description=f"{description} [شراكة 50%]"))
        if abo_malek:
            session.add(PartnerTransaction(partner_id=abo_malek.id, type='salary_expense', amount=-half_amount, description=f"{description} [شراكة 50%]"))
            
    elif method == 'split_4':
        # 2. مقسم على 5: 20% لكل واحد (3 مديرين + أبو إياد + أبو مالك)
        share_20 = net_salary / 5
        
        # 20% لكل مدير
        managers_to_split = ['Elsayd_Elwekel', 'SMSM_Hamdy', 'Ehab_habls']
        for m_username in managers_to_split:
            mgr = User.query.filter_by(username=m_username).first()
            if mgr:
                session.add(PartnerTransaction(partner_id=mgr.id, type='salary_expense', amount=-share_20, description=f"{description} [حصة 20%]"))
                
        # 20% أبو إياد + 20% أبو مالك
        gm = User.query.filter_by(username='gm').first() or User.query.filter_by(role='general_manager').first()
        abo_malek = User.query.filter_by(username='Abo_malek').first()
        
        if gm:
            session.add(PartnerTransaction(partner_id=gm.id, type='salary_expense', amount=-share_20, description=f"{description} [حصة 20%]"))
        if abo_malek:
            session.add(PartnerTransaction(partner_id=abo_malek.id, type='salary_expense', amount=-share_20, description=f"{description} [حصة 20%]"))

    else:
        # 3. حساب شخصي (المدير المباشر)
        # استثناء: لو الموظف شغال بعمولة فقط (مرتبه = 0) يبقى بيقبض من الشركة مش من المدير
        # فالسلفة/الراتب يتحمله الشراكة (50/50) مش المدير المباشر
        if (emp.base_salary or 0) == 0 and emp.role == 'sales':
            half_amount = net_salary / 2
            gm = User.query.filter_by(username='gm').first() or User.query.filter_by(role='general_manager').first()
            abo_malek = User.query.filter_by(username='Abo_malek').first()
            if gm:
                session.add(PartnerTransaction(partner_id=gm.id, type='salary_expense', amount=-half_amount, description=f"{description} [شراكة 50% - موظف بعمولة]"))
            if abo_malek:
                session.add(PartnerTransaction(partner_id=abo_malek.id, type='salary_expense', amount=-half_amount, description=f"{description} [شراكة 50% - موظف بعمولة]"))
        else:
            manager = emp.manager if emp.manager_id else User.query.filter_by(role='general_manager').first()
            if manager:
                session.add(PartnerTransaction(partner_id=manager.id, type='personal_salary_expense', amount=-net_salary, description=f"{description} [شخصي/مدير مباشر]"))

def _generate_expense_description(emp, month_context):
    base_desc = f"صرف راتب: {emp.fullname}{f' ({month_context})' if month_context else ''}"
    method = emp.salary_method or 'direct_manager'
    
    if method == 'partnership':
        return f"{base_desc} (شراكة)"
    elif method == 'split_4':
        return f"{base_desc} (مقسم)"
    else:
        manager = emp.manager if emp.manager_id else User.query.filter_by(role='general_manager').first()
        manager_name = manager.fullname if manager else "غير معروف"
        return f"{base_desc} (شخصي: {manager_name})"


@app.route('/hr/payroll_bulk', methods=['GET', 'POST'])
@login_required
def hr_payroll():
    """صفحة تنفيذ الرواتب الشهرية — للمدير العام فقط"""
    if current_user.role != 'general_manager':
        return "غير مصرح لك", 403

    now = cairo_now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if month_start.month == 12:
        month_end = month_start.replace(year=month_start.year + 1, month=1)
    else:
        month_end = month_start.replace(month=month_start.month + 1)

    month_label = month_start.strftime('%Y-%m')
    accounts = MoneyAccount.query.order_by(MoneyAccount.balance.desc()).all()

    # --- بناء قائمة الرواتب ---
    employees = User.query.filter(
        User.role.notin_(['general_manager']),
        User.base_salary > 0
    ).order_by(User.fullname).all()

    payroll_data = []
    for emp in employees:
        # حساب عمولات الشهر (الصافي بعد المرتجعات)
        gross_items = db.session.query(func.sum(SaleItem.quantity)).join(SaleOrder).filter(
            SaleOrder.user_id == emp.id,
            SaleOrder.is_proforma == False,
            SaleOrder.date >= month_start,
            SaleOrder.date < month_end
        ).scalar() or 0

        returned_items = db.session.query(func.sum(ReturnInvoice.total_qty)).join(SaleOrder).filter(
            SaleOrder.user_id == emp.id,
            cast(ReturnInvoice.date, Date) >= month_start.date(),
            cast(ReturnInvoice.date, Date) < month_end.date()
        ).scalar() or 0
        
        net_items = max(0, gross_items - returned_items)
        commission = round_half(calculate_user_commission(emp, net_items, net_items))

        # حساب HR transactions للشهر
        hr = HRTransaction.query.filter(
            HRTransaction.user_id == emp.id,
            HRTransaction.date >= month_start,
            HRTransaction.date < month_end
        ).all()
        base_bonuses = sum(t.amount for t in hr if t.type == 'bonus')
        base_deductions = sum(t.amount for t in hr if t.type in ['deduction', 'penalty'])
        advances = sum(t.amount for t in hr if t.type == 'advance')

        # حساب خصومات الغياب ومكافآت الإضافي
        att_settings = AttendanceSettings.query.first() or AttendanceSettings()
        daily_rate = (emp.base_salary or 0) / 30
        attendance_deduction, _, overtime_bonus = calculate_attendance_deduction(emp, month_label, att_settings, daily_rate)
        
        deductions = round_half(base_deductions + attendance_deduction)
        bonuses = round_half(base_bonuses + overtime_bonus)
        advances = round_half(advances)

        net_salary = round_half((emp.base_salary or 0) + commission + bonuses - deductions - advances)

        # فحص هل تم صرف راتب هذا الشهر
        already_paid = HRTransaction.query.filter(
            HRTransaction.user_id == emp.id,
            HRTransaction.type == 'salary_payment',
            HRTransaction.date >= month_start,
            HRTransaction.date < month_end
        ).first()

        payroll_data.append({
            'emp': emp,
            'commission': commission,
            'bonuses': bonuses,
            'deductions': deductions,
            'advances': advances,
            'net_salary': net_salary,
            'already_paid': already_paid is not None,
            'method_label': {
                'direct_manager': 'المدير المباشر',
                'partnership': 'الشراكة',
                'split_4': 'مقسم على 4'
            }.get(emp.salary_method or 'direct_manager', 'المدير المباشر')
        })

    # === POST: تنفيذ الرواتب ===
    if request.method == 'POST':
        account_id = request.form.get('account_id')
        selected_ids = request.form.getlist('emp_ids')
        account = MoneyAccount.query.get(account_id) if account_id else None

        if not account:
            flash('⚠️ اختر خزينة لصرف الرواتب منها', 'warning')
            return redirect(url_for('hr_payroll'))

        paid_count = 0
        total_paid = 0

        for row in payroll_data:
            if str(row['emp'].id) not in selected_ids:
                continue
            if row['already_paid']:
                continue
            if row['net_salary'] <= 0:
                continue

            emp = row['emp']
            net = row['net_salary']
            desc = f"راتب {emp.fullname} — {month_label}"

            # 1. خصم من الخزينة
            account.balance -= net
            db.session.add(FinancialTransaction(
                account_id=account.id,
                type='expense',
                category='رواتب',
                amount=-net,
                description=desc,
                created_by_id=current_user.id,
                date=now
            ))

            # 2. تسجيل في ملف الموظف
            db.session.add(HRTransaction(
                user_id=emp.id,
                type='salary_payment',
                amount=net,
                note=f'صرف راتب {month_label} — من خزينة: {account.name}',
                date=now
            ))

            # 3. تسجيل التكلفة على الشريك/الشركاء
            # المكافآت والخصومات للمديرين تم تسجيلها بالفعل على الشراكة وقت إضافتها
            # لذا نستبعدها من المبلغ المحمّل على salary_method لتجنب الحساب المزدوج
            if emp.role == 'manager':
                manager_net = net - row['bonuses'] + row['deductions']
                _record_partner_salary_expense(emp, manager_net, desc, db.session)
            else:
                # العمولة اتحسبت أصلاً كـ sub_commission بعد كل فاتورة
                # فنخصمها من المبلغ المحمل على المدير عشان متتحسبش مرتين
                salary_without_comm = net - row['commission']
                _record_partner_salary_expense(emp, salary_without_comm, desc + f" [بدون عمولة {row['commission']}]", db.session)

            paid_count += 1
            total_paid += net

        try:
            db.session.commit()
            flash(f'✅ تم صرف رواتب {paid_count} موظف بإجمالي {round_half(total_paid)} ج.م من خزينة "{account.name}"', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'❌ خطأ أثناء صرف الرواتب: {e}', 'danger')

        return redirect(url_for('hr_payroll'))

    total_net = sum(r['net_salary'] for r in payroll_data if not r['already_paid'])
    return render_template('hr_payroll.html',
                           payroll_data=payroll_data,
                           accounts=accounts,
                           month_label=month_label,
                           total_net=round_half(total_net))

@app.route('/pending_financial_actions')
@login_required
def pending_financial_actions():
    """صفحة الموافقة على الإجراءات المالية المعلقة - للمدير العام فقط"""
    if current_user.role != 'general_manager':
        return "غير مصرح", 403
    pending = PendingFinancialAction.query.filter_by(status='pending').order_by(PendingFinancialAction.date.desc()).all()
    accounts = MoneyAccount.query.all()
    return render_template('pending_financial_actions.html', pending=pending, accounts=accounts)


@app.route('/pending_financial_actions/<int:action_id>/approve', methods=['POST'])
@login_required
def approve_financial_action(action_id):
    """الموافقة على إجراء مالي معلق - يُسجَّل في رصيد الموظف فقط، الخصم من الخزينة عند تحضير الراتب"""
    if current_user.role != 'general_manager':
        return "غير مصرح", 403

    action = PendingFinancialAction.query.get_or_404(action_id)
    if action.status != 'pending':
        flash('هذا الطلب تمت معالجته مسبقاً.', 'warning')
        return redirect(url_for('pending_financial_actions'))

    emp = User.query.get(action.target_emp_id)
    amount = action.amount
    t_type = action.action_type
    note = action.note or ''

    try:
        # تسجيل الحركة في ملف الموظف فقط (بدون خصم من الخزينة الآن)
        db.session.add(HRTransaction(
            user_id=emp.id,
            type=t_type,
            amount=amount,
            note=f"[موافقة المدير العام] {note}",
            date=cairo_now()
        ))
        
        # تسجيل المكافآت والخصومات كمصاريف شراكة أو حسب salary_method
        is_company_partner = emp.username in ['Abo_Eyad', 'Abo_malek']
        if not is_company_partner:
            if emp.role == 'manager':
                # مكافأة/خصم لمدير → تتحملها الشراكة (50/50)
                gm = User.query.filter_by(username='gm').first() or User.query.filter_by(role='general_manager').first()
                abo_malek = User.query.filter_by(username='Abo_malek').first()
                if t_type == 'bonus':
                    half = amount / 2
                    if gm:
                        db.session.add(PartnerTransaction(partner_id=gm.id, type='staff_expense', amount=-half, description=f"مكافأة للموظف [موافقة المدير العام] ({emp.fullname}): {note} [شراكة 50%]"))
                    if abo_malek:
                        db.session.add(PartnerTransaction(partner_id=abo_malek.id, type='staff_expense', amount=-half, description=f"مكافأة للموظف [موافقة المدير العام] ({emp.fullname}): {note} [شراكة 50%]"))
                elif t_type == 'deduction' and amount > 0:
                    half = amount / 2
                    if gm:
                        db.session.add(PartnerTransaction(partner_id=gm.id, type='staff_expense', amount=half, description=f"خصم/جزاء يعوض التكلفة [موافقة المدير العام] ({emp.fullname}): {note} [شراكة 50%]"))
                    if abo_malek:
                        db.session.add(PartnerTransaction(partner_id=abo_malek.id, type='staff_expense', amount=half, description=f"خصم/جزاء يعوض التكلفة [موافقة المدير العام] ({emp.fullname}): {note} [شراكة 50%]"))
            else:
                # موظف عادي → حسب salary_method
                if t_type == 'bonus':
                    _record_partner_salary_expense(emp, amount, f"مكافأة للموظف [موافقة المدير العام] ({emp.fullname}): {note}", db.session)
                elif t_type == 'deduction' and amount > 0:
                    _record_partner_salary_expense(emp, -amount, f"خصم/جزاء يعوض التكلفة [موافقة المدير العام] ({emp.fullname}): {note}", db.session)
        else:
            # الشريك نفسه
            if t_type == 'bonus':
                db.session.add(PartnerTransaction(
                    partner_id=emp.id, 
                    type='partner_bonus', 
                    amount=amount, 
                    description=f"مكافأة شريك [موافقة المدير العام] ({emp.fullname}): {note}"
                ))
            elif t_type == 'deduction' and amount > 0:
                db.session.add(PartnerTransaction(
                    partner_id=emp.id, 
                    type='partner_deduction', 
                    amount=-amount, 
                    description=f"جزاء شريك [موافقة المدير العام] ({emp.fullname}): {note}"
                ))

        # تحديث حالة الطلب
        action.status = 'approved'
        action.reviewed_by_id = current_user.id
        action.reviewed_at = cairo_now()
        db.session.commit()

        type_label = {'advance': 'سلفة', 'bonus': 'مكافأة', 'deduction': 'خصم'}.get(t_type, t_type)
        flash(f'✅ تمت الموافقة وتسجيل {type_label} ({amount} ج.م) في رصيد {emp.fullname}. سيُحسَب في راتبه الشهري.', 'success')

    except Exception as e:
        db.session.rollback()
        flash(f'خطأ أثناء التنفيذ: {e}', 'danger')

    return redirect(url_for('pending_financial_actions'))


@app.route('/pending_financial_actions/<int:action_id>/reject', methods=['POST'])
@login_required
def reject_financial_action(action_id):
    """رفض إجراء مالي معلق"""
    if current_user.role != 'general_manager':
        return "غير مصرح", 403

    action = PendingFinancialAction.query.get_or_404(action_id)
    if action.status != 'pending':
        flash('هذا الطلب تمت معالجته مسبقاً.', 'warning')
        return redirect(url_for('pending_financial_actions'))

    action.status = 'rejected'
    action.reviewed_by_id = current_user.id
    action.reviewed_at = cairo_now()
    action.reject_reason = request.form.get('reason', '')
    db.session.commit()
    flash('❌ تم رفض الطلب.', 'warning')
    return redirect(url_for('pending_financial_actions'))


@app.route('/api/pending_count')
@login_required
def pending_count_api():
    """API لعدد الطلبات المعلقة - للإشعارات في الـ navbar"""
    if current_user.role != 'general_manager':
        return jsonify({'count': 0})
    count = PendingFinancialAction.query.filter_by(status='pending').count()
    return jsonify({'count': count})

@app.route('/api/add_income', methods=['POST'])
@login_required
def add_income_api():
    """تسجيل وارد يدوي من المدير العام"""
    if current_user.role != 'general_manager':
        return jsonify({'error': 'غير مصرح'}), 403

    data = request.get_json()
    amount = float(data.get('amount') or 0)
    description = data.get('description', '').strip()
    account_id = data.get('account_id')
    category = data.get('category', 'وارد يدوي')

    if amount <= 0:
        return jsonify({'error': 'المبلغ يجب أن يكون أكبر من صفر'}), 400
    if not description:
        return jsonify({'error': 'يرجى إدخال وصف للوارد'}), 400

    try:
        account = MoneyAccount.query.get(account_id) if account_id else None

        tx = FinancialTransaction(
            type='income',
            category=category,
            amount=amount,
            description=description,
            date=cairo_now(),
            created_by_id=current_user.id,
            account_id=account.id if account else None
        )
        db.session.add(tx)

        if account:
            account.balance = round_half(account.balance + amount)

        db.session.commit()
        return jsonify({'success': True, 'message': f'تم تسجيل وارد {amount} ج.م ✅'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


with app.app_context():
    db.create_all()


@app.route('/fix/sync_expense_names')
@login_required
def fix_sync_expense_names():
    """أداة إصلاح رجعي: تصحيح أسماء الشركاء في وصف المصروفات القديمة بناءً على PartnerTransaction"""
    if current_user.role != 'general_manager':
        return "غير مصرح", 403

    import re
    from datetime import timedelta

    expenses = Expense.query.filter(Expense.description.like('%شخصي:%')).all()
    count = 0
    
    for exp in expenses:
        # البحث عن PartnerTransaction المطابق للمصروف ده
        # amount المفروض يكون -exp.amount وتاريخه مقارب جداً (في حدود نفس أجزاء الثانية لكن هنسمح بـ 5 ثواني فرق)
        start_time = exp.date - timedelta(seconds=5)
        end_time = exp.date + timedelta(seconds=5)
        
        ptrans = PartnerTransaction.query.filter(
            PartnerTransaction.amount == -exp.amount,
            PartnerTransaction.type == 'personal_expense_share',
            PartnerTransaction.date >= start_time,
            PartnerTransaction.date <= end_time
        ).first()

        if ptrans:
            real_partner = User.query.get(ptrans.partner_id)
            if real_partner:
                real_name = real_partner.fullname
                # تنظيف الوصف القديم من أي تاج شخصي
                clean_desc = re.sub(r'\(شخصي:.*?\)', '', exp.description).strip()
                new_desc = f"{clean_desc} (شخصي: {real_name})".strip()
                
                if new_desc != exp.description:
                    exp.description = new_desc
                    count += 1
                    
    db.session.commit()
    flash(f'تم تحديث {count} مصروف شخصي للأسماء الصحيحة ✅', 'success')
    return redirect(url_for('expenses'))

@app.route('/fix/sync_customer_balances')
@login_required
def fix_sync_customer_balances():
    """أداة إصلاح رجعي: مراجعة وإعادة حساب مديونيات جميع العملاء بناءً على الفواتير والمدفوعات والمرتجعات"""
    if current_user.role != 'general_manager':
        return "غير مصرح لك", 403

    fixed_count = 0
    customers = Customer.query.all()
    for customer in customers:
        # 1. إجمالي ما طلبه العميل (إجمالي قيمة الفواتير)
        total_invoices_value = 0.0
        orders = SaleOrder.query.filter_by(customer_id=customer.id, is_proforma=False).all()
        for order in orders:
            if order.final_total:
                total_invoices_value += order.final_total

        # 2. إجمالي المدفوعات من جدول دفعات العملاء
        # (بعض الدفعات ممكن تتسجل في FinancialTransaction كدخل بدون CustomerPayment
        # بناءً على الكود الحالي، الاعتماد على CustomerPayment هو الأقرب)
        total_payments = 0.0
        payments = CustomerPayment.query.filter_by(customer_id=customer.id).all()
        for payment in payments:
            if payment.amount:
                total_payments += payment.amount

        # 3. دفعات مقدمة أثناء إنشاء الفاتورة لم تسجل كاستلام منفصل
        # لحسابها بأمان: إذا كانت الفاتورة مدفوعة مقدما ومافيش CustomerPayment يغطيها..
        # بس عشان نتجنب الدبلرة المعقدة، لو المديونيات باظت للدرجة دي أحسن يدويا.
        # لكن المعادلة الأساسية السليمة: إجمالي الفواتير - إجمالي المدفوعات المسجلة للعميل.

        # 4. إجمالي المرتجعات (المبالغ التي تم خصمها من المديونية بسبب الإرجاع)
        total_refunds = 0.0
        for order in orders:
            for ret in order.return_invoices:
                refund_val = (ret.total_deduction or 0.0) - (ret.shipping_loss or 0.0) - (ret.missing_items_cost or 0.0)
                if refund_val > 0:
                     total_refunds += refund_val

        # الرصيد الحقيقي رياضياً
        true_balance = round_half(total_invoices_value - total_payments - total_refunds)
        current_safe_balance = round_half(customer.balance or 0.0)

        if current_safe_balance != true_balance:
            customer.balance = true_balance
            fixed_count += 1

    db.session.commit()
    flash(f"تم تصحيح مديونية {fixed_count} عميل ومطابقتها بالفواتير الفعلية بنجاح ✅", "success")
    return redirect(url_for('customers'))


@app.route('/invoice/<int:order_id>/add_payment', methods=['POST'])
@login_required
def add_payment_to_invoice(order_id):
    """تسجيل دفعة إضافية على فاتورة موجودة"""
    if current_user.role not in ['manager', 'general_manager']:
        return jsonify({'success': False, 'message': 'غير مصرح'}), 403

    try:
        order = SaleOrder.query.get_or_404(order_id)
        amount = float(request.form.get('payment_amount', 0))
        account_id = request.form.get('payment_account_id')

        if amount <= 0:
            flash('المبلغ يجب أن يكون أكبر من صفر', 'danger')
            return redirect(url_for('print_invoice', order_id=order_id))

        if amount > (order.amount_due or 0):
            flash(f'المبلغ ({amount}) أكبر من المتبقي على العميل ({order.amount_due})!', 'danger')
            return redirect(url_for('print_invoice', order_id=order_id))

        account = MoneyAccount.query.get(account_id)
        if not account:
            flash('يجب اختيار خزينة صحيحة', 'danger')
            return redirect(url_for('print_invoice', order_id=order_id))

        # 1. تحديث الفاتورة
        order.paid_upfront = round_half((order.paid_upfront or 0) + amount)
        order.amount_due = round_half((order.amount_due or 0) - amount)

        # 2. إدخال الفلوس في الخزينة
        account.balance = round_half(account.balance + amount)

        # 3. تسجيل حركة مالية (إيراد)
        db.session.add(FinancialTransaction(
            type='income', category='مبيعات',
            amount=amount,
            description=f"دفعة إضافية على فاتورة #{order.id} (العميل: {order.customer.name if order.customer else 'نقدي'})",
            created_by_id=current_user.id, date=cairo_now(),
            account_id=account.id
        ))

        # 4. تقليل مديونية العميل
        if order.customer:
            order.customer.balance = round_half((order.customer.balance or 0) - amount)

        # 5. تسجيل دفعة في جدول دفعات العملاء (لو العميل موجود)
        if order.customer:
            db.session.add(CustomerPayment(
                customer_id=order.customer.id,
                amount=amount,
                account_id=account.id,
                notes=f"دفعة إضافية - فاتورة #{order.id}"
            ))

        db.session.commit()
        flash(f'تم تسجيل دفعة {amount} ج.م بنجاح ✅ المتبقي: {order.amount_due} ج.م', 'success')

    except Exception as e:
        db.session.rollback()
        flash(f'خطأ: {str(e)}', 'danger')

    return redirect(url_for('print_invoice', order_id=order_id))


@app.route('/invoice/<int:order_id>/convert_to_shipping', methods=['POST'])
@login_required
def convert_to_shipping(order_id):
    """تحويل فاتورة تامة إلى فاتورة شحن"""
    if current_user.role not in ['manager', 'general_manager']:
        return jsonify({'success': False, 'message': 'غير مصرح'}), 403

    try:
        order = SaleOrder.query.get_or_404(order_id)

        if order.is_proforma:
            flash('لا يمكن تحويل مسودة للشحن، يجب اعتمادها أولاً', 'danger')
            return redirect(url_for('print_invoice', order_id=order_id))

        courier_id = request.form.get('courier_id')
        waybill_no = request.form.get('waybill_no', '').strip()
        shipping_fee = float(request.form.get('shipping_fee', 0) or 0)
        shipping_paid_by = request.form.get('shipping_paid_by', 'customer')
        shipping_notes = request.form.get('shipping_notes', '').strip()

        if not courier_id:
            flash('يجب اختيار شركة شحن', 'danger')
            return redirect(url_for('print_invoice', order_id=order_id))

        # تحديث الفاتورة لتصبح شحن
        order.is_shipping = True
        order.shipping_company_id = int(courier_id)
        order.waybill_no = waybill_no if waybill_no else None
        order.shipping_fee = shipping_fee
        order.shipping_paid_by = shipping_paid_by
        order.shipping_status = 'pending'
        order.shipping_notes = shipping_notes if shipping_notes else None

        # لو الشحن على العميل، نضيفه على إجمالي الفاتورة والمديونية
        if shipping_paid_by == 'customer' and shipping_fee > 0:
            order.final_total = round_half((order.final_total or 0) + shipping_fee)
            order.amount_due = round_half((order.amount_due or 0) + shipping_fee)
            # زيادة مديونية العميل
            if order.customer:
                order.customer.balance = round_half((order.customer.balance or 0) + shipping_fee)

        db.session.commit()
        flash(f'تم تحويل الفاتورة #{order.id} لشحن عبر شركة الشحن بنجاح ✅', 'success')

    except Exception as e:
        db.session.rollback()
        flash(f'خطأ: {str(e)}', 'danger')

    return redirect(url_for('print_invoice', order_id=order_id))


@app.route('/fix/diagnose_discounts')
@login_required
def diagnose_discounts():
    if current_user.role != 'general_manager': return "غير مصرح", 403
    
    orders = SaleOrder.query.filter(SaleOrder.discount > 0, SaleOrder.is_proforma == False).all()
    results = []
    
    for order in orders:
        pt = PartnerTransaction.query.filter_by(order_id=order.id, type='discount_deduction').first()
        if not pt:
            # التحقق هل الفاتورة دي المفروض أصلاً تتخصم من مين؟ وهل ليها شريك/مدير في السيستم؟
            seller_user = order.sales_rep
            target_partner = None
            if seller_user:
                if seller_user.role == 'manager': 
                    target_partner = seller_user
                elif seller_user.manager_id:
                    mgr = User.query.get(seller_user.manager_id)
                    if mgr and mgr.role == 'manager': 
                        target_partner = mgr
                        
            # لو ليها مدير، وهي مش مخصومة منه.. تبقى مشكلة وتظهر في القائمة
            if target_partner:
                results.append(order)
            
    html = ["<h2>فواتير بها خصم ولم يتم خصمها من الشركاء/المديرين</h2><hr>"]
    
    # إضافة زر "إصلاح جماعي"
    if results:
        html.append(f"<div style='margin-bottom: 20px;'><a href='/fix/auto_fix_missed_discounts' class='btn' style='background:#dc3545; color:white; padding:10px 20px; text-decoration:none; border-radius:5px; font-weight:bold;'>🚀 إصلاح كل الفواتير المذكورة تلقائياً بضغطة زر (بدون الحاجة للإرجاع لمسودة)</a></div>")
    
    html.append("<table border='1' cellpadding='8' style='text-align:right; width:80%; max-width:800px; border-collapse:collapse;' dir='rtl'>")
    html.append("<tr style='background-color:#f2f2f2;'><th>رقم الفاتورة</th><th>التاريخ</th><th>البائع / المدير</th><th>قيمة الخصم</th><th>الإجراء الموصى به</th></tr>")
    
    for o in results:
        html.append(f"<tr><td>#{o.id}</td><td>{o.date.strftime('%Y-%m-%d')}</td><td>{o.sales_rep.fullname if o.sales_rep else '---'}</td><td style='color:red; font-weight:bold;'>{o.discount} ج.م</td><td><a href='/invoice/{o.id}' target='_blank'>فتح لعمل (إرجاع لمسودة)</a></td></tr>")
        
    html.append("</table>")
    if not results:
        html.append("<h3 style='color:green;'>لا توجد أي أخطاء! جميع الخصومات مسمعة في حسابات المديرين بشكل صحيح.</h3>")
        
    return "<div style='font-family: Cairo, sans-serif; padding: 20px; direction:rtl;'>" + "".join(html) + "</div>"


@app.route('/fix/auto_fix_missed_discounts')
@login_required
def auto_fix_missed_discounts():
    if current_user.role != 'general_manager': return "غير مصرح", 403
    
    orders = SaleOrder.query.filter(SaleOrder.discount > 0, SaleOrder.is_proforma == False).all()
    fixed_count = 0
    fixed_amount = 0
    
    for order in orders:
        pt = PartnerTransaction.query.filter_by(order_id=order.id, type='discount_deduction').first()
        if not pt:
            # 1. تحديد المدير المسؤول
            seller_user = order.sales_rep
            if not seller_user: continue
            
            partner = None
            if seller_user.role == 'manager': 
                partner = seller_user
            elif seller_user.manager_id:
                mgr = User.query.get(seller_user.manager_id)
                if mgr and mgr.role == 'manager': 
                    partner = mgr
                    
            if partner:
                # 2. إنشاء المعاملة المفقودة
                add_split_partner_transaction(
                    partner_id=partner.id,
                    order_id=order.id,
                    type_val='discount_deduction',
                    amount=-order.discount,
                    description=f"خصم ممنوح للعميل - فاتورة #{order.id} (رصيد تم ترقيعه برمجياً)"
                )
                fixed_count += 1
                fixed_amount += order.discount
                
                # 3. تحديث عمولات هذا الموظف (والمدير تبعا لذلك) لضمان التسميع بالتقارير
                update_monthly_commissions(order.user_id, order.date)
                
    db.session.commit()
    
    return f"<div style='font-family: Cairo; direction: rtl; padding: 40px;'><h2 style='color: green;'>✅ تمت العملية بنجاح!</h2><hr><h3>تم إصلاح ( {fixed_count} ) فاتورة، وتم خصم إجمالي {fixed_amount} ج.م من حسابات المديرين المتأخرة المستحقة.</h3><br><br><a href='/fix/diagnose_discounts' style='padding: 10px 20px; background: #000; color: #fff; text-decoration: none;'>رجوع للفحص</a></div>"

@app.route('/recycle_bin')
@general_manager_required
def recycle_bin():
    logs = DeletedItemLog.query.order_by(DeletedItemLog.deleted_at.desc()).limit(250).all()
    # pass raw json to format in template
    return render_template('recycle_bin.html', logs=logs)

@app.route('/review_invoices')
@general_manager_required
def review_invoices():
    # Fetch all pending reviews sorted by date
    pending_orders = SaleOrder.query.filter_by(is_proforma=False, is_reviewed=False).order_by(SaleOrder.date.desc()).all()
    # Also fetch all accessible users for filtering
    users = User.query.all()
    return render_template('review_invoices.html', orders=pending_orders, users=users)

@app.route('/review_invoices/confirm/<int:id>', methods=['POST'])
@general_manager_required
def confirm_invoice_review(id):
    order = SaleOrder.query.get_or_404(id)
    if order.is_proforma:
        flash('هذه الفاتورة مسودة أصلاً.', 'warning')
        return redirect(url_for('review_invoices'))
        
    order.is_reviewed = True
    db.session.commit()
    # تحديث العمولات للموظف بعد الاعتماد
    if order.user_id:
        update_monthly_commissions(order.user_id, order.date)
    flash(f'تم تأكيد الفاتورة #{order.id} بنجاح وتمت إضافة العمولات.', 'success')
    return redirect(url_for('review_invoices'))


@app.route('/fix/migrate_reviews')
@login_required
def fix_migrate_reviews():
    if current_user.role != 'general_manager': return "Unauthorized"
    try:
        count = SaleOrder.query.filter_by(is_proforma=False, is_reviewed=False).update({'is_reviewed': True})
        db.session.commit()
        return f"تم تنظيف {count} فاتورة قديمة واعتبارها متراجعة بنجاح! <a href='/dashboard'>العودة</a>"
    except Exception as e:
        return f"حدث خطأ: تأكد إنك ضفت العمود في الداتابيز الأول!<br>{str(e)}"

@app.route('/fix/undo_migrate')
@login_required
def fix_undo_migrate():
    if current_user.role != 'general_manager': return "Unauthorized"
    try:
        count = SaleOrder.query.filter_by(is_proforma=False, is_reviewed=True).update({'is_reviewed': False})
        db.session.commit()
        return f"تم إرجاع {count} فاتورة لصفحة المراجعة بنجاح! صاحب الشركة يقدر يراجعهم دلوقتي براحته. <a href='/review_invoices'>الذهاب لصفحة المراجعة</a>"
    except Exception as e:
        return f"حدث خطأ: <br>{str(e)}"

@app.route('/fix/delete_return_41')
@login_required
def fix_delete_return_41():
    if current_user.role != 'general_manager': return "Unauthorized"
    try:
        ret_inv = ReturnInvoice.query.get(41)
        if not ret_inv: return "المرتجع 41 مش موجود أو اتحذف قبل كدة!"
        
        order = SaleOrder.query.get(ret_inv.order_id)
        if not order: return "الفاتورة الأصلية مش موجودة!"

        # 1. Reverse balance and amount_due (595 EGP based on screenshot)
        if order.customer:
            order.customer.balance = (order.customer.balance or 0) + 595.0
        order.amount_due = (order.amount_due or 0) + 595.0
        
        # 2. Reverse Stock (3 items returned)
        movements = StockMovement.query.filter_by(reason=f"مرتجع فاتورة #{order.id}").order_by(StockMovement.id.desc()).limit(3).all()
        for m in movements:
            variant = ProductVariant.query.get(m.variant_id)
            if variant:
                variant.stock -= m.quantity_change
            db.session.delete(m)
            
        # 3. Reverse PartnerTransaction
        ptrans = PartnerTransaction.query.filter(PartnerTransaction.description.like(f"%فاتورة #{order.id}%"), PartnerTransaction.type == 'return_deduction').order_by(PartnerTransaction.id.desc()).limit(2).all()
        for p in ptrans:
            db.session.delete(p)
                
        # 4. Reverse HRTransaction
        hrtrans = HRTransaction.query.filter(HRTransaction.note.like(f"%مرتجع فاتورة #{order.id}%")).order_by(HRTransaction.id.desc()).limit(1).all()
        for h in hrtrans:
            db.session.delete(h)
            
        # 5. Delete FinancialTransactions
        ftrans = FinancialTransaction.query.filter(FinancialTransaction.description.like(f"%فاتورة #{order.id}%"), FinancialTransaction.amount == 0).order_by(FinancialTransaction.id.desc()).limit(1).all()
        for f in ftrans:
            db.session.delete(f)
            
        # 6. Delete ReturnInvoice 41
        db.session.delete(ret_inv)
        
        db.session.commit()
        return "تم حذف المرتجع المكرر رقم 41 وإرجاع 595 جنيه لمديونية العميل وتقليل المخزون بالمنتجات الزيادة بنجاح! <a href='/customers'>رجوع للعملاء</a>"
    except Exception as e:
        db.session.rollback()
@app.route('/fix/restore_return_39')
@login_required
def fix_restore_return_39():
    if current_user.role != 'general_manager': return "Unauthorized"
    try:
        order = SaleOrder.query.get(467)
        if not order: return "فاتورة 467 مش موجودة!"
        
        # 1. Reverse the incorrect balance adjustment (+595) that was made by the previous script
        if order.customer:
            order.customer.balance = (order.customer.balance or 0) - 595.0
        
        order.amount_due = (order.amount_due or 0) - 595.0
        
        stock_added = 0
        prices_to_match = [175.0, 235.0, 185.0]
        
        # 2. Recreate the 3 deleted stock movements
        for item in order.items:
            # We match the prices slightly loosely to ensure float match
            matched = False
            for p in prices_to_match:
                if abs(item.unit_price - p) < 0.1:
                    matched = True
                    price_matched = p
                    break
                    
            if matched:
                if item.variant:
                    item.variant.stock += 1
                sm = StockMovement(
                    variant_id=item.variant_id,
                    user_id=current_user.id,
                    quantity_change=1,
                    reason=f"مرتجع فاتورة #{order.id}"
                )
                db.session.add(sm)
                prices_to_match.remove(price_matched)
                stock_added += 1

        db.session.commit()
        return f"تم استرجاع القطع المحذوفة للمرتجع 39 وتصحيح المديونية بنجاح! الأصناف المسترجعة: {stock_added} <br><a href='/dashboard'>العودة للرئيسية</a>"
    except Exception as e:
        db.session.rollback()
        return f"حدث خطأ: {str(e)}"

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')
