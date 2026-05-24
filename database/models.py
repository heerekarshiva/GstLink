from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime, date
import secrets

db = SQLAlchemy()

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    gstin = db.Column(db.String(15))
    business_name = db.Column(db.String(150))
    address = db.Column(db.Text)
    phone = db.Column(db.String(15))
    hsn_code = db.Column(db.String(10))
    hourly_rate = db.Column(db.Float, default=0)

    # Plan: 'free' | 'trial' | 'pro'
    plan_type = db.Column(db.String(20), default='trial')

    # Trial tracking
    trial_started_at = db.Column(db.DateTime, default=datetime.utcnow)
    trial_ends_at = db.Column(db.DateTime, nullable=True)   # set on register

    # Daily free limit tracking
    daily_invoice_count = db.Column(db.Integer, default=0)
    daily_reset_date = db.Column(db.Date, default=date.today)

    stripe_customer_id = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Email verification
    email_verified = db.Column(db.Boolean, default=False)
    email_verify_token = db.Column(db.String(64), nullable=True)
    email_verify_token_expires = db.Column(db.DateTime, nullable=True)  # 24h expiry

    # Password reset (token + expiry)
    password_reset_token = db.Column(db.String(64), nullable=True)
    password_reset_expires = db.Column(db.DateTime, nullable=True)

    # Account lockout after repeated failed logins (10 attempts → 15 min lockout)
    failed_login_count = db.Column(db.Integer, default=0)
    locked_until = db.Column(db.DateTime, nullable=True)

    clients = db.relationship('Client', backref='owner', lazy=True)
    invoices = db.relationship('Invoice', backref='creator', lazy=True)

    @property
    def is_trial_active(self):
        if self.plan_type == 'trial' and self.trial_ends_at:
            return datetime.utcnow() <= self.trial_ends_at
        return False

    @property
    def is_pro(self):
        return True  # Everyone gets Pro features for free

    @property
    def trial_days_left(self):
        if self.plan_type == 'trial' and self.trial_ends_at:
            delta = self.trial_ends_at - datetime.utcnow()
            return max(0, delta.days)
        return 0

    def get_daily_count(self):
        """Reset counter if it's a new day, return today's count.
        NOTE: caller must call db.session.commit() after this if the date changed."""
        today = date.today()
        if self.daily_reset_date != today:
            self.daily_invoice_count = 0
            self.daily_reset_date = today
            # Do NOT commit here — commit is the caller's responsibility
        return self.daily_invoice_count

    def ensure_plan_downgrade(self):
        """Transition expired trial users to 'free' plan. Call on login/dashboard."""
        if self.plan_type == 'trial' and not self.is_trial_active:
            self.plan_type = 'free'
            return True  # caller should db.session.commit()
        return False

    def can_create_invoice(self, daily_limit=5):
        """True if user is allowed to create another invoice."""
        return True  # All users get unlimited invoices for free


class Client(db.Model):
    __tablename__ = 'clients'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    client_name = db.Column(db.String(150), nullable=False)
    client_gstin = db.Column(db.String(15))
    email = db.Column(db.String(150))
    phone = db.Column(db.String(15))
    address = db.Column(db.Text)
    state = db.Column(db.String(50))
    state_code = db.Column(db.String(5))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    invoices = db.relationship('Invoice', backref='client', lazy=True)


class Invoice(db.Model):
    __tablename__ = 'invoices'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    client_id = db.Column(db.Integer, db.ForeignKey('clients.id'), nullable=False)
    invoice_number = db.Column(db.String(30), unique=True, nullable=False)
    description = db.Column(db.Text)
    hsn_sac = db.Column(db.String(10))
    amount = db.Column(db.Float, nullable=False)
    gst_type = db.Column(db.String(10))  # CGST_SGST | IGST
    gst_rate = db.Column(db.Float, default=18.0)
    cgst = db.Column(db.Float, default=0)
    sgst = db.Column(db.Float, default=0)
    igst = db.Column(db.Float, default=0)
    total = db.Column(db.Float, nullable=False)
    pdf_path = db.Column(db.String(300))
    payment_status = db.Column(db.String(20), default='unpaid')  # unpaid | paid | partial
    due_date = db.Column(db.Date)
    upi_id = db.Column(db.String(50))
    notes = db.Column(db.Text)
    public_token = db.Column(db.String(32), unique=True, nullable=False,
                             default=lambda: secrets.token_urlsafe(24))
    public_token_expires_at = db.Column(db.DateTime, nullable=True)  # None = no expiry set yet
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
