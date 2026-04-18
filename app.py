import os
import re
import stripe
import secrets
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_talisman import Talisman
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date, timedelta
from database.models import db, User, Client, Invoice
from utils.gst_calculator import (calculate_gst, validate_gstin, get_state_from_gstin,
                                   INDIAN_STATES, COMMON_HSN_SAC, GST_RATES)
from utils.ai_contract_parser import parse_contract_with_ai
from utils.invoice_generator import generate_invoice_pdf
from utils.mailer import mail, send_verification_email, send_password_reset_email, send_password_changed_email
from config import Config

app = Flask(__name__)
app.config.from_object(Config)

db.init_app(app)
mail.init_app(app)

# ── CSRF Protection ───────────────────────────────────────────────
csrf = CSRFProtect(app)

# ── Security Headers (flask-talisman) ────────────────────────────
# CSP allows Bootstrap/BI CDN, inline styles needed for invoice previews
_CSP = {
    'default-src': ["'self'"],
    'script-src': ["'self'", 'cdnjs.cloudflare.com'],
    'style-src': ["'self'", "'unsafe-inline'", 'cdnjs.cloudflare.com', 'fonts.googleapis.com'],
    'font-src':  ["'self'", 'cdnjs.cloudflare.com', 'fonts.gstatic.com'],
    'img-src': ["'self'", 'data:'],
    'connect-src': ["'self'"],
    'frame-ancestors': ["'none'"],
}
Talisman(
    app,
    force_https=False,          # Railway handles TLS termination
    strict_transport_security=True,
    strict_transport_security_max_age=31536000,
    content_security_policy=_CSP,
    content_security_policy_nonce_in=['script-src'],
    x_content_type_options=True,
    x_xss_protection=True,
    referrer_policy='strict-origin-when-cross-origin',
    feature_policy={
        'geolocation': "'none'",
        'camera': "'none'",
        'microphone': "'none'",
    }
)

# ── Rate Limiting ─────────────────────────────────────────────────
# Use Redis on Railway for persistence across workers/deploys.
# Falls back to memory:// for local dev (set REDIS_URL in Railway vars).
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=["200 per hour"],
    storage_uri=os.environ.get('REDIS_URL', 'memory://')
)

login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = "Please login to continue."

stripe.api_key = app.config['STRIPE_SECRET_KEY']

_APP_DIR = os.path.dirname(os.path.abspath(__file__))
os.makedirs(os.path.join(_APP_DIR, 'invoices_pdf'), exist_ok=True)
os.makedirs(os.path.join(_APP_DIR, 'static/logo'), exist_ok=True)

# ── UPI ID validation ─────────────────────────────────────────────
_UPI_RE = re.compile(r'^[\w.\-]{2,256}@[a-zA-Z]{2,64}$')

def validate_upi_id(upi_id: str) -> bool:
    return bool(_UPI_RE.match(upi_id)) if upi_id else True  # empty is allowed

# ── Safe redirect helper ──────────────────────────────────────────
def _is_safe_next(url: str) -> bool:
    """Return True only if url is a relative internal path (no scheme/host)."""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    return not parsed.scheme and not parsed.netloc and url.startswith('/')


def _validate_password(password: str) -> str | None:
    """
    Return an error string if password fails strength requirements, else None.
    Rules: ≥8 chars, at least one digit, at least one uppercase letter.
    These are deliberately minimal — strong enough to block 'aaaaaaaa' style
    passwords without frustrating legitimate users.
    """
    if len(password) < 8:
        return 'Password must be at least 8 characters.'
    if not any(c.isdigit() for c in password):
        return 'Password must contain at least one number (e.g. "MyPass1").'
    if not any(c.isupper() for c in password):
        return 'Password must contain at least one uppercase letter (e.g. "mypass1A").'
    return None


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


def generate_invoice_number(user_id):
    """Random suffix prevents duplicates; no user_id in number to avoid enumeration."""
    year = datetime.now().year
    count = Invoice.query.filter_by(user_id=user_id).count() + 1
    rand = secrets.token_hex(4).upper()
    return f"INV-{year}-{count:04d}-{rand}"


def _sync_user_state(user):
    """Downgrade expired trial -> free, reset daily counter if new day. Commits if changed."""
    changed = user.ensure_plan_downgrade()
    user.get_daily_count()  # resets daily_invoice_count if new day (no commit inside)
    if changed:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()


# ──────────────────────────────────────────────────────────────────
# PUBLIC ROUTES
# ──────────────────────────────────────────────────────────────────

@app.route('/')
def landing():
    return render_template('landing.html')


@app.route('/register', methods=['GET', 'POST'])
@limiter.limit("10 per hour")
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        name = request.form.get('name', '').strip()[:100]
        email = request.form.get('email', '').strip().lower()[:150]
        password = request.form.get('password', '')
        gstin = request.form.get('gstin', '').strip().upper()[:15]

        if not name or not email or not password:
            flash('All fields are required.', 'danger')
            return render_template('auth.html', mode='register')

        if len(password) < 8:
            flash('Password must be at least 8 characters.', 'danger')
            return render_template('auth.html', mode='register')

        _pw_err = _validate_password(password)
        if _pw_err:
            flash(_pw_err, 'danger')
            return render_template('auth.html', mode='register')

        if User.query.filter_by(email=email).first():
            flash('Email already registered. Please login.', 'warning')
            return render_template('auth.html', mode='register')

        if gstin and not validate_gstin(gstin):
            flash('Invalid GSTIN format. Please check.', 'danger')
            return render_template('auth.html', mode='register')

        trial_end = datetime.utcnow() + timedelta(days=30)
        verify_token = secrets.token_urlsafe(32)
        user = User(
            name=name, email=email,
            password=generate_password_hash(password),
            gstin=gstin,
            plan_type='trial',
            trial_started_at=datetime.utcnow(),
            trial_ends_at=trial_end,
            daily_invoice_count=0,
            daily_reset_date=date.today(),
            email_verified=False,
            email_verify_token=verify_token,
            email_verify_token_expires=datetime.utcnow() + timedelta(hours=24),
        )
        db.session.add(user)
        db.session.commit()
        login_user(user)
        # Send verification email (non-blocking — failure doesn't break signup)
        send_verification_email(app, user, app.config['BASE_URL'])
        flash(f'Welcome to GSTLink, {name}! Check your inbox to verify your email.', 'success')
        return redirect(url_for('dashboard'))

    return render_template('auth.html', mode='register')


@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("20 per hour")
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        user = User.query.filter_by(email=email).first()

        # Per-account lockout check — always check before password to avoid timing oracle
        if user and user.locked_until and datetime.utcnow() < user.locked_until:
            mins_left = max(1, int((user.locked_until - datetime.utcnow()).seconds / 60))
            flash(f'Account temporarily locked. Try again in {mins_left} minute(s).', 'danger')
            return render_template('auth.html', mode='login')

        if user and check_password_hash(user.password, password):
            # Successful login — reset lockout counters
            user.failed_login_count = 0
            user.locked_until = None
            db.session.commit()
            remember = request.form.get('remember') == 'on'
            login_user(user, remember=remember)
            _sync_user_state(user)
            next_page = request.args.get('next', '')
            # Open redirect protection: only allow internal relative paths
            if next_page and _is_safe_next(next_page):
                return redirect(next_page)
            return redirect(url_for('dashboard'))
        else:
            # Failed login — increment counter, lock if threshold reached
            if user:
                user.failed_login_count = (user.failed_login_count or 0) + 1
                if user.failed_login_count >= 10:
                    user.locked_until = datetime.utcnow() + timedelta(minutes=15)
                    user.failed_login_count = 0  # reset counter after locking
                    db.session.commit()
                    flash('Too many failed attempts. Account locked for 15 minutes.', 'danger')
                    return render_template('auth.html', mode='login')
                db.session.commit()
            flash('Invalid email or password.', 'danger')
    return render_template('auth.html', mode='login')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('landing'))


# ──────────────────────────────────────────────────────────────────
# EMAIL VERIFICATION
# ──────────────────────────────────────────────────────────────────

@app.route('/verify-email/<token>')
def verify_email(token):
    """Confirm email address via link sent at registration. Token expires in 24h."""
    user = User.query.filter_by(email_verify_token=token).first()
    # Check existence AND expiry
    if not user or (
        user.email_verify_token_expires and
        datetime.utcnow() > user.email_verify_token_expires
    ):
        flash('This verification link has expired or is invalid. Please request a new one.', 'danger')
        return redirect(url_for('resend_verification') if current_user.is_authenticated else url_for('landing'))
    user.email_verified = True
    user.email_verify_token = None           # one-time use — invalidate immediately
    user.email_verify_token_expires = None   # clear expiry too
    db.session.commit()
    flash('✅ Email verified! Your account is fully active.', 'success')
    return redirect(url_for('dashboard') if current_user.is_authenticated else url_for('login'))


@app.route('/resend-verification')
@login_required
@limiter.limit("3 per hour")
def resend_verification():
    if current_user.email_verified:
        flash('Your email is already verified.', 'info')
        return redirect(url_for('dashboard'))
    token = secrets.token_urlsafe(32)
    current_user.email_verify_token = token
    current_user.email_verify_token_expires = datetime.utcnow() + timedelta(hours=24)
    db.session.commit()
    send_verification_email(app, current_user, app.config['BASE_URL'])
    flash('Verification email sent! Check your inbox.', 'success')
    return redirect(url_for('dashboard'))


# ──────────────────────────────────────────────────────────────────
# PASSWORD RESET (forgot password flow)
# ──────────────────────────────────────────────────────────────────

@app.route('/forgot-password', methods=['GET', 'POST'])
@limiter.limit("5 per hour")
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()[:150]
        user = User.query.filter_by(email=email).first()
        # Always show same message — prevents user enumeration
        if user:
            token = secrets.token_urlsafe(32)
            user.password_reset_token = token
            user.password_reset_expires = datetime.utcnow() + timedelta(hours=1)
            db.session.commit()
            send_password_reset_email(app, user, app.config['BASE_URL'])
        flash('If that email is registered, you will receive a reset link shortly.', 'info')
        return redirect(url_for('login'))
    return render_template('forgot_password.html')


@app.route('/reset-password/<token>', methods=['GET', 'POST'])
@limiter.limit("10 per hour")
def reset_password(token):
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    user = User.query.filter_by(password_reset_token=token).first()
    # Validate token existence and expiry
    if not user or not user.password_reset_expires or datetime.utcnow() > user.password_reset_expires:
        flash('This reset link has expired or is invalid. Please request a new one.', 'danger')
        return redirect(url_for('forgot_password'))
    if request.method == 'POST':
        new_password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')
        _pw_err = _validate_password(new_password)
        if _pw_err:
            flash(_pw_err, 'danger')
            return render_template('reset_password.html', token=token)
        if new_password != confirm:
            flash('Passwords do not match.', 'danger')
            return render_template('reset_password.html', token=token)
        user.password = generate_password_hash(new_password)
        user.password_reset_token = None       # invalidate immediately
        user.password_reset_expires = None
        db.session.commit()
        send_password_changed_email(app, user)  # security alert notification
        flash('Password reset successfully. Please log in with your new password.', 'success')
        return redirect(url_for('login'))
    return render_template('reset_password.html', token=token)


# ──────────────────────────────────────────────────────────────────
# DASHBOARD
# ──────────────────────────────────────────────────────────────────

@app.route('/dashboard')
@login_required
def dashboard():
    _sync_user_state(current_user)
    invoices = Invoice.query.filter_by(user_id=current_user.id).order_by(Invoice.created_at.desc()).limit(5).all()
    clients = Client.query.filter_by(user_id=current_user.id).all()
    all_inv = Invoice.query.filter_by(user_id=current_user.id).all()
    total_invoiced = sum(i.total for i in all_inv)
    paid = sum(i.total for i in all_inv if i.payment_status == 'paid')
    pending = total_invoiced - paid
    invoice_count = len(all_inv)

    today = date.today()
    next_month = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
    gstr1_due = date(next_month.year, next_month.month, 11) if today.day >= 11 else date(today.year, today.month, 11)
    gstr3b_due = date(next_month.year, next_month.month, 20) if today.day >= 20 else date(today.year, today.month, 20)

    # Compute daily count here, pass to template — avoids calling model methods in Jinja
    daily_count = current_user.get_daily_count()

    return render_template('dashboard.html',
        invoices=invoices, clients=clients,
        total_invoiced=total_invoiced, paid=paid, pending=pending,
        invoice_count=invoice_count,
        free_limit=app.config['FREE_INVOICE_LIMIT'],
        daily_limit=app.config['DAILY_FREE_LIMIT'],
        daily_count=daily_count,
        gstr1_due=gstr1_due, gstr3b_due=gstr3b_due,
        today=today)


@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        current_user.name = request.form.get('name', current_user.name)[:100]
        current_user.business_name = request.form.get('business_name', '')[:150]
        gstin = request.form.get('gstin', '').strip().upper()[:15]
        if gstin and not validate_gstin(gstin):
            flash('Invalid GSTIN format.', 'danger')
            return redirect(url_for('profile'))
        current_user.gstin = gstin
        current_user.address = request.form.get('address', '')[:300]
        current_user.phone = request.form.get('phone', '')[:15]
        current_user.hsn_code = request.form.get('hsn_code', '')[:10]
        try:
            current_user.hourly_rate = float(request.form.get('hourly_rate', 0) or 0)
        except ValueError:
            current_user.hourly_rate = 0
        db.session.commit()
        flash('Profile updated successfully!', 'success')
        return redirect(url_for('profile'))
    return render_template('profile.html', states=INDIAN_STATES, hsn_codes=COMMON_HSN_SAC)


@app.route('/change-password', methods=['GET', 'POST'])
@login_required
@limiter.limit("10 per hour")
def change_password():
    """Authenticated password change — requires current password."""
    if request.method == 'POST':
        current_pw  = request.form.get('current_password', '')
        new_pw      = request.form.get('new_password', '')
        confirm_pw  = request.form.get('confirm_password', '')

        if not check_password_hash(current_user.password, current_pw):
            flash('Current password is incorrect.', 'danger')
            return render_template('change_password.html')
        _pw_err = _validate_password(new_pw)
        if _pw_err:
            flash(_pw_err, 'danger')
            return render_template('change_password.html')
        if new_pw != confirm_pw:
            flash('New passwords do not match.', 'danger')
            return render_template('change_password.html')
        if check_password_hash(current_user.password, new_pw):
            flash('New password must be different from your current password.', 'danger')
            return render_template('change_password.html')

        current_user.password = generate_password_hash(new_pw)
        db.session.commit()
        send_password_changed_email(app, current_user)   # security alert
        flash('✅ Password changed successfully!', 'success')
        return redirect(url_for('profile'))
    return render_template('change_password.html')


@app.route('/delete-account', methods=['GET', 'POST'])
@login_required
@limiter.limit("3 per hour")
def delete_account():
    """
    DPDP Act 2023 / GDPR compliance — users can permanently delete their account
    and all associated data. Requires password confirmation to prevent accidents.
    """
    if request.method == 'POST':
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_delete', '')

        if not check_password_hash(current_user.password, password):
            flash('Incorrect password. Account not deleted.', 'danger')
            return render_template('delete_account.html')

        if confirm != 'DELETE':
            flash('Please type DELETE to confirm account deletion.', 'danger')
            return render_template('delete_account.html')

        user_id = current_user.id

        # Hard-delete all user data in correct FK order
        try:
            # Delete all invoice PDFs from disk first
            for inv in Invoice.query.filter_by(user_id=user_id).all():
                if inv.pdf_path and os.path.exists(inv.pdf_path):
                    try:
                        os.remove(inv.pdf_path)
                    except OSError:
                        pass
            Invoice.query.filter_by(user_id=user_id).delete()
            Client.query.filter_by(user_id=user_id).delete()
            logout_user()
            User.query.filter_by(id=user_id).delete()
            db.session.commit()
            flash('Your account and all data have been permanently deleted.', 'info')
            return redirect(url_for('landing'))
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Account deletion error for user {user_id}: {e}")
            flash('An error occurred. Please contact support@gstlink.in.', 'danger')
            return redirect(url_for('profile'))

    return render_template('delete_account.html')


# ──────────────────────────────────────────────────────────────────
# CLIENTS
# ──────────────────────────────────────────────────────────────────

@app.route('/clients')
@login_required
def clients():
    all_clients = Client.query.filter_by(user_id=current_user.id).order_by(Client.created_at.desc()).all()
    return render_template('clients.html', clients=all_clients)


@app.route('/clients/add', methods=['GET', 'POST'])
@login_required
def add_client():
    if request.method == 'POST':
        gstin = request.form.get('client_gstin', '').strip().upper()[:15]
        state = request.form.get('state', '')
        if not state and gstin:
            state = get_state_from_gstin(gstin)
        state_code = INDIAN_STATES.get(state, '')
        client = Client(
            user_id=current_user.id,
            client_name=request.form.get('client_name', '').strip()[:150],
            client_gstin=gstin,
            email=request.form.get('email', '').strip()[:150],
            phone=request.form.get('phone', '').strip()[:15],
            address=request.form.get('address', '').strip()[:300],
            state=state,
            state_code=state_code
        )
        db.session.add(client)
        db.session.commit()
        flash('Client added successfully!', 'success')
        return redirect(url_for('clients'))
    return render_template('add_client.html', states=INDIAN_STATES)


@app.route('/clients/<int:cid>/delete', methods=['POST'])
@login_required
def delete_client(cid):
    client = Client.query.filter_by(id=cid, user_id=current_user.id).first_or_404()
    db.session.delete(client)
    db.session.commit()
    flash('Client deleted.', 'info')
    return redirect(url_for('clients'))


# ──────────────────────────────────────────────────────────────────
# INVOICES
# ──────────────────────────────────────────────────────────────────

@app.route('/invoice/new', methods=['GET', 'POST'])
@login_required
def new_invoice():
    _sync_user_state(current_user)

    if not current_user.can_create_invoice(daily_limit=app.config['DAILY_FREE_LIMIT']):
        if current_user.plan_type == 'trial':
            flash('Your 30-day free trial has ended. Upgrade to Pro to keep creating invoices.', 'warning')
        else:
            flash(f'You\'ve used all {app.config["DAILY_FREE_LIMIT"]} free invoices for today. Upgrade to Pro for unlimited!', 'warning')
        return redirect(url_for('pricing'))

    clients = Client.query.filter_by(user_id=current_user.id).all()

    if request.method == 'POST':
        try:
            client_id = int(request.form.get('client_id'))
        except (TypeError, ValueError):
            flash('Please select a valid client.', 'danger')
            return render_template('invoice_form.html', clients=clients, hsn_codes=COMMON_HSN_SAC,
                gst_rates=GST_RATES, states=INDIAN_STATES, today=date.today().strftime('%Y-%m-%d'))

        client = Client.query.filter_by(id=client_id, user_id=current_user.id).first_or_404()

        try:
            base_amount = float(request.form.get('amount', 0))
            if base_amount <= 0 or base_amount > 10_000_000:  # max ₹1 crore per invoice
                raise ValueError
        except (TypeError, ValueError):
            flash('Please enter a valid amount between ₹1 and ₹1,00,00,000.', 'danger')
            return render_template('invoice_form.html', clients=clients, hsn_codes=COMMON_HSN_SAC,
                gst_rates=GST_RATES, states=INDIAN_STATES, today=date.today().strftime('%Y-%m-%d'))

        gst_rate = float(request.form.get('gst_rate', 18))
        if gst_rate not in [float(r) for r in GST_RATES]:
            gst_rate = 18.0

        description = request.form.get('description', '')[:500]
        notes = request.form.get('notes', '')[:500]
        upi_id = request.form.get('upi_id', '').strip()[:50]
        if upi_id and not validate_upi_id(upi_id):
            flash('Invalid UPI ID format (e.g. yourname@upi).', 'danger')
            return render_template('invoice_form.html', clients=clients, hsn_codes=COMMON_HSN_SAC,
                gst_rates=GST_RATES, states=INDIAN_STATES, today=date.today().strftime('%Y-%m-%d'))

        try:
            due_days = int(request.form.get('due_days', 30))
            if due_days not in [7, 15, 30, 45, 60]:
                due_days = 30
        except ValueError:
            due_days = 30

        supplier_state = get_state_from_gstin(current_user.gstin) if current_user.gstin else ''
        client_state = client.state
        gst = calculate_gst(base_amount, gst_rate, supplier_state, client_state)

        invoice_no = generate_invoice_number(current_user.id)
        due_date = date.today() + timedelta(days=due_days)

        invoice = Invoice(
            user_id=current_user.id,
            client_id=client_id,
            invoice_number=invoice_no,
            description=description,
            hsn_sac=request.form.get('hsn_sac', '')[:10],
            amount=base_amount,
            gst_type=gst['gst_type'],
            gst_rate=gst_rate,
            cgst=gst['cgst'],
            sgst=gst['sgst'],
            igst=gst['igst'],
            total=gst['total'],
            payment_status='unpaid',
            due_date=due_date,
            upi_id=upi_id,
            notes=notes
        )
        db.session.add(invoice)
        db.session.flush()  # assigns invoice.public_token before PDF generation

        pdf_dir = os.path.join(_APP_DIR, 'invoices_pdf')
        os.makedirs(pdf_dir, exist_ok=True)
        pdf_path = os.path.join(pdf_dir, f"{invoice_no}.pdf")
        invoice_data = {
            'seller': {
                'name': current_user.business_name or current_user.name,
                'gstin': current_user.gstin or '',
                'address': current_user.address or '',
                'state': supplier_state,
                'email': current_user.email,
                'phone': current_user.phone or ''
            },
            'client': {
                'name': client.client_name,
                'gstin': client.client_gstin or '',
                'address': client.address or '',
                'state': client.state or '',
                'email': client.email or '',
                'phone': client.phone or ''
            },
            'invoice': {
                'number': invoice_no,
                'date': date.today().strftime('%d %b %Y'),
                'due_date': due_date.strftime('%d %b %Y'),
                'description': description,
                'hsn_sac': invoice.hsn_sac
            },
            'gst': gst,
            'upi_id': upi_id,
            'base_url': app.config['BASE_URL'],
            'public_token': invoice.public_token,
            'notes': notes
        }
        try:
            generate_invoice_pdf(invoice_data, pdf_path)
            invoice.pdf_path = pdf_path
        except Exception as e:
            app.logger.error(f"PDF generation error: {e}")

        # Track daily count for ALL non-pro users (trial users included — for accurate reporting)
        if not current_user.is_pro:
            current_user.daily_invoice_count = (current_user.daily_invoice_count or 0) + 1

        db.session.commit()
        flash(f'Invoice {invoice_no} created successfully!', 'success')
        return redirect(url_for('view_invoice', invoice_id=invoice.id))

    return render_template('invoice_form.html', clients=clients, hsn_codes=COMMON_HSN_SAC,
        gst_rates=GST_RATES, states=INDIAN_STATES, today=date.today().strftime('%Y-%m-%d'))


@app.route('/invoice/<int:invoice_id>')
@login_required
def view_invoice(invoice_id):
    invoice = Invoice.query.filter_by(id=invoice_id, user_id=current_user.id).first_or_404()
    client = invoice.client
    supplier_state = get_state_from_gstin(current_user.gstin) if current_user.gstin else ''
    return render_template('view_invoice.html', invoice=invoice, client=client,
                           supplier=current_user, supplier_state=supplier_state)


@app.route('/invoice/view/<token>')
def public_invoice_view(token):
    """Public link uses random token — not guessable sequential invoice number.
    Token is valid for 72 hours from first view (set lazily on first access).
    """
    invoice = Invoice.query.filter_by(public_token=token).first_or_404()

    # Set expiry on first view (lazy — avoids storing expiry at creation time)
    if invoice.public_token_expires_at is None:
        invoice.public_token_expires_at = datetime.utcnow() + timedelta(hours=72)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()

    # Reject expired tokens
    if datetime.utcnow() > invoice.public_token_expires_at:
        return render_template('invoice_expired.html', invoice_number=invoice.invoice_number), 410

    from flask import make_response
    resp = make_response(render_template('invoice_public.html', invoice=invoice, client=invoice.client))
    # Prevent search engines and WhatsApp/Slack link-preview bots from caching sensitive data
    resp.headers['X-Robots-Tag'] = 'noindex, nofollow'
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
    return resp


@app.route('/invoice/<int:invoice_id>/download')
@login_required
def download_invoice(invoice_id):
    invoice = Invoice.query.filter_by(id=invoice_id, user_id=current_user.id).first_or_404()
    if invoice.pdf_path and os.path.exists(invoice.pdf_path):
        return send_file(invoice.pdf_path, as_attachment=True,
                         download_name=f"{invoice.invoice_number}.pdf")
    flash('PDF not found. Please regenerate.', 'danger')
    return redirect(url_for('view_invoice', invoice_id=invoice_id))


@app.route('/invoice/<int:invoice_id>/status', methods=['POST'])
@login_required
def update_invoice_status(invoice_id):
    invoice = Invoice.query.filter_by(id=invoice_id, user_id=current_user.id).first_or_404()
    status = request.form.get('status', 'unpaid')
    if status not in ('unpaid', 'paid', 'partial'):
        flash('Invalid status.', 'danger')
        return redirect(url_for('view_invoice', invoice_id=invoice_id))
    invoice.payment_status = status
    db.session.commit()
    flash(f'Invoice marked as {status}.', 'success')
    return redirect(url_for('view_invoice', invoice_id=invoice_id))


@app.route('/invoice/<int:invoice_id>/delete', methods=['POST'])
@login_required
def delete_invoice(invoice_id):
    invoice = Invoice.query.filter_by(id=invoice_id, user_id=current_user.id).first_or_404()
    if invoice.pdf_path and os.path.exists(invoice.pdf_path):
        os.remove(invoice.pdf_path)
    db.session.delete(invoice)
    db.session.commit()
    flash('Invoice deleted.', 'info')
    return redirect(url_for('invoice_history'))


@app.route('/invoices')
@login_required
def invoice_history():
    page = request.args.get('page', 1, type=int)
    status_filter = request.args.get('status', '')
    query = Invoice.query.filter_by(user_id=current_user.id)
    if status_filter in ('unpaid', 'paid', 'partial'):
        query = query.filter_by(payment_status=status_filter)
    invoices = query.order_by(Invoice.created_at.desc()).paginate(page=page, per_page=10)
    return render_template('invoice_history.html', invoices=invoices, status_filter=status_filter)


@app.route('/invoice/<int:invoice_id>/duplicate', methods=['POST'])
@login_required
def duplicate_invoice(invoice_id):
    """One-click duplicate — creates a new draft pre-filled from an existing invoice."""
    _sync_user_state(current_user)
    if not current_user.can_create_invoice(daily_limit=app.config['DAILY_FREE_LIMIT']):
        flash('Daily invoice limit reached. Upgrade to Pro for unlimited invoices.', 'warning')
        return redirect(url_for('pricing'))

    src = Invoice.query.filter_by(id=invoice_id, user_id=current_user.id).first_or_404()
    invoice_no = generate_invoice_number(current_user.id)
    new_inv = Invoice(
        user_id=current_user.id,
        client_id=src.client_id,
        invoice_number=invoice_no,
        description=src.description,
        hsn_sac=src.hsn_sac,
        amount=src.amount,
        gst_type=src.gst_type,
        gst_rate=src.gst_rate,
        cgst=src.cgst,
        sgst=src.sgst,
        igst=src.igst,
        total=src.total,
        payment_status='unpaid',
        due_date=date.today() + timedelta(days=30),
        upi_id=src.upi_id,
        notes=src.notes,
    )
    db.session.add(new_inv)
    db.session.flush()  # get new_inv.id and public_token before PDF generation

    # Generate PDF for the duplicated invoice
    supplier_state = get_state_from_gstin(current_user.gstin) if current_user.gstin else ''
    client = src.client
    pdf_dir = os.path.join(_APP_DIR, 'invoices_pdf')
    os.makedirs(pdf_dir, exist_ok=True)
    pdf_path = os.path.join(pdf_dir, f"{invoice_no}.pdf")
    invoice_data = {
        'seller': {
            'name': current_user.business_name or current_user.name,
            'gstin': current_user.gstin or '',
            'address': current_user.address or '',
            'state': supplier_state,
            'email': current_user.email,
            'phone': current_user.phone or ''
        },
        'client': {
            'name': client.client_name,
            'gstin': client.client_gstin or '',
            'address': client.address or '',
            'state': client.state or '',
            'email': client.email or '',
            'phone': client.phone or ''
        },
        'invoice': {
            'number': invoice_no,
            'date': date.today().strftime('%d %b %Y'),
            'due_date': new_inv.due_date.strftime('%d %b %Y'),
            'description': new_inv.description,
            'hsn_sac': new_inv.hsn_sac
        },
        'gst': {
            'gst_type': new_inv.gst_type,
            'gst_rate': new_inv.gst_rate,
            'base_amount': new_inv.amount,
            'cgst': new_inv.cgst,
            'sgst': new_inv.sgst,
            'igst': new_inv.igst,
            'total': new_inv.total
        },
        'upi_id': new_inv.upi_id or '',
        'base_url': app.config['BASE_URL'],
        'public_token': new_inv.public_token,
        'notes': new_inv.notes or ''
    }
    try:
        generate_invoice_pdf(invoice_data, pdf_path)
        new_inv.pdf_path = pdf_path
    except Exception as e:
        app.logger.error(f"PDF generation error on duplicate: {e}")

    if not current_user.is_pro:
        current_user.daily_invoice_count = (current_user.daily_invoice_count or 0) + 1
    db.session.commit()
    flash(f'Invoice duplicated as {invoice_no}.', 'success')
    return redirect(url_for('view_invoice', invoice_id=new_inv.id))


@app.route('/analytics')
@login_required
def analytics():
    """Revenue analytics — monthly breakdown, top clients, unpaid summary."""
    # joinedload prevents N+1 queries when accessing inv.client.client_name
    all_inv = (Invoice.query
               .filter_by(user_id=current_user.id)
               .options(db.joinedload(Invoice.client))
               .all())

    # Monthly revenue (last 6 months)
    from collections import defaultdict
    monthly = defaultdict(float)
    monthly_count = defaultdict(int)
    for inv in all_inv:
        key = inv.created_at.strftime('%b %Y')
        monthly[key] += inv.total
        monthly_count[key] += 1

    # Top clients by revenue
    client_rev = defaultdict(float)
    for inv in all_inv:
        client_rev[inv.client.client_name] += inv.total
    top_clients = sorted(client_rev.items(), key=lambda x: x[1], reverse=True)[:5]

    # Payment summary
    total = sum(i.total for i in all_inv)
    paid = sum(i.total for i in all_inv if i.payment_status == 'paid')
    unpaid = sum(i.total for i in all_inv if i.payment_status == 'unpaid')
    partial = sum(i.total for i in all_inv if i.payment_status == 'partial')

    # Overdue invoices
    today = date.today()
    overdue = [i for i in all_inv if i.payment_status == 'unpaid' and i.due_date and i.due_date < today]

    return render_template('analytics.html',
        monthly=dict(monthly),
        monthly_count=dict(monthly_count),
        top_clients=top_clients,
        total=total, paid=paid, unpaid=unpaid, partial=partial,
        overdue=overdue,
        invoice_count=len(all_inv),
        today=today
    )


# ──────────────────────────────────────────────────────────────────
# AI CONTRACT PARSER
# ──────────────────────────────────────────────────────────────────

@app.route('/ai/parse-contract', methods=['POST'])
@login_required
@limiter.limit("30 per hour")
def parse_contract():
    # Use silent=True so non-JSON bodies return None instead of raising 400
    data = request.get_json(silent=True) or {}
    contract_text = data.get('text', '')
    if not contract_text or len(contract_text) < 20:
        return jsonify({'error': 'Please paste a longer contract text.'}), 400
    if len(contract_text) > 10000:
        return jsonify({'error': 'Contract text too long (max 10,000 characters).'}), 400
    result = parse_contract_with_ai(contract_text)
    result.pop('error', None)  # never expose internal errors to the client
    return jsonify(result)


# ──────────────────────────────────────────────────────────────────
# GST CALCULATOR API
# ──────────────────────────────────────────────────────────────────

@app.route('/api/calculate-gst', methods=['POST'])
@limiter.limit("60 per minute")
def api_calculate_gst():
    data = request.json or {}
    try:
        amount = float(data.get('amount', 0))
        gst_rate = float(data.get('gst_rate', 18))
        if amount < 0 or gst_rate not in [float(r) for r in GST_RATES]:
            return jsonify({'error': 'Invalid amount or GST rate.'}), 400
        result = calculate_gst(amount, gst_rate,
                               data.get('supplier_state', ''),
                               data.get('client_state', ''))
        return jsonify(result)
    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid input values.'}), 400


# ──────────────────────────────────────────────────────────────────
# PRICING & STRIPE
# ──────────────────────────────────────────────────────────────────

@app.route('/pricing')
def pricing():
    return render_template('pricing.html',
        stripe_key=app.config['STRIPE_PUBLISHABLE_KEY'],
        price_inr=app.config['PRO_PRICE_INR'],
        free_limit=app.config['FREE_INVOICE_LIMIT'],
        daily_limit=app.config['DAILY_FREE_LIMIT'],
        trial_days=app.config['TRIAL_DAYS'])


@app.route('/checkout/create', methods=['POST'])
@login_required
def create_checkout():
    try:
        if not app.config['STRIPE_SECRET_KEY']:
            flash('Payment gateway not configured. Contact support.', 'warning')
            return redirect(url_for('pricing'))
        checkout = stripe.checkout.Session.create(
            customer_email=current_user.email,
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'inr',
                    'product_data': {'name': 'GSTLink Pro - Unlimited Invoices'},
                    'unit_amount': app.config['PRO_PRICE_INR'] * 100,
                    'recurring': {'interval': 'month'}
                },
                'quantity': 1
            }],
            mode='subscription',
            success_url=url_for('checkout_success', _external=True) + '?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=url_for('pricing', _external=True),
            metadata={'user_id': str(current_user.id), 'user_email': current_user.email}
        )
        return redirect(checkout.url)
    except Exception as e:
        app.logger.error(f"Stripe checkout error: {e}")
        flash('Payment error. Please try again or contact support.', 'danger')
        return redirect(url_for('pricing'))


@app.route('/checkout/success')
@login_required
def checkout_success():
    session_id = request.args.get('session_id')
    if session_id and app.config['STRIPE_SECRET_KEY']:
        try:
            checkout_session = stripe.checkout.Session.retrieve(session_id)
            # Security: verify the session belongs to the currently logged-in user
            session_email = (checkout_session.customer_details or {}).get('email', '') \
                            or checkout_session.customer_email or ''
            session_user_id = str((checkout_session.metadata or {}).get('user_id', ''))
            email_match = session_email.lower() == current_user.email.lower()
            id_match = session_user_id == str(current_user.id)
            if not (email_match and id_match):
                app.logger.warning(
                    f"Checkout session mismatch: session user_id={session_user_id} "
                    f"email={session_email} vs current user id={current_user.id} "
                    f"email={current_user.email}"
                )
                flash('Session verification failed. Please contact support.', 'danger')
                return redirect(url_for('pricing'))
            if checkout_session.payment_status == 'paid' or checkout_session.status == 'complete':
                current_user.plan_type = 'pro'
                # Save stripe_customer_id so webhook cancellations can look up this user
                if checkout_session.customer and not current_user.stripe_customer_id:
                    current_user.stripe_customer_id = checkout_session.customer
                db.session.commit()
                flash('Welcome to GSTLink Pro! Unlimited invoices activated.', 'success')
        except Exception as e:
            app.logger.error(f"Stripe verification error: {e}")
            flash('Could not verify payment. Contact support if you were charged.', 'warning')
    return redirect(url_for('dashboard'))


@app.route('/stripe-webhook', methods=['POST'])
@csrf.exempt
def stripe_webhook():
    """
    Reliable subscription lifecycle via Stripe webhooks.
    Set STRIPE_WEBHOOK_SECRET in Railway environment variables.
    Configure this endpoint in your Stripe Dashboard to listen for:
      - checkout.session.completed
      - customer.subscription.deleted
    """
    webhook_secret = app.config.get('STRIPE_WEBHOOK_SECRET', '')
    payload = request.get_data(as_text=True)
    sig_header = request.headers.get('Stripe-Signature', '')

    if not webhook_secret:
        app.logger.warning("STRIPE_WEBHOOK_SECRET not set — skipping webhook.")
        return jsonify({'status': 'ignored'}), 200

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except stripe.error.SignatureVerificationError:
        return jsonify({'error': 'Invalid signature'}), 400

    if event['type'] == 'checkout.session.completed':
        session_obj = event['data']['object']
        user_id = session_obj.get('metadata', {}).get('user_id')
        if user_id:
            user = User.query.get(int(user_id))
            if user:
                user.plan_type = 'pro'
                # Save stripe_customer_id so future subscription webhooks can find this user
                customer_id = session_obj.get('customer')
                if customer_id and not user.stripe_customer_id:
                    user.stripe_customer_id = customer_id
                db.session.commit()

    elif event['type'] in ('customer.subscription.deleted', 'customer.subscription.paused'):
        sub = event['data']['object']
        customer_id = sub.get('customer')
        user = User.query.filter_by(stripe_customer_id=customer_id).first() if customer_id else None
        if user and user.plan_type == 'pro':
            user.plan_type = 'free'
            db.session.commit()

    return jsonify({'status': 'ok'}), 200


# ──────────────────────────────────────────────────────────────────
# COMPLIANCE
# ──────────────────────────────────────────────────────────────────

@app.route('/compliance')
@login_required
def compliance():
    today = date.today()
    invoices = Invoice.query.filter_by(user_id=current_user.id).all()
    total_taxable = sum(i.amount for i in invoices)
    total_cgst = sum(i.cgst for i in invoices)
    total_sgst = sum(i.sgst for i in invoices)
    total_igst = sum(i.igst for i in invoices)
    return render_template('compliance.html',
        today=today, total_taxable=total_taxable,
        total_cgst=total_cgst, total_sgst=total_sgst, total_igst=total_igst,
        invoices=invoices)


# ──────────────────────────────────────────────────────────────────
# LEGAL PAGES
# ──────────────────────────────────────────────────────────────────

@app.route('/privacy')
def privacy():
    return render_template('privacy.html')


@app.route('/terms')
def terms():
    return render_template('terms.html',
        free_limit=app.config['FREE_INVOICE_LIMIT'],
        daily_limit=app.config['DAILY_FREE_LIMIT'])


# ──────────────────────────────────────────────────────────────────
# SEO
# ──────────────────────────────────────────────────────────────────

@app.route('/robots.txt')
def robots_txt():
    from flask import Response
    base = app.config.get('BASE_URL', 'https://gstlink.in')
    content = f"""User-agent: *\nAllow: /\nDisallow: /dashboard\nDisallow: /invoice/\nDisallow: /invoices\nDisallow: /clients\nDisallow: /compliance\nDisallow: /profile\nDisallow: /checkout/\nDisallow: /ai/\nDisallow: /api/\nDisallow: /invoice/view/\n\nSitemap: {base}/sitemap.xml\n"""
    return Response(content, mimetype='text/plain')


@app.route('/sitemap.xml')
def sitemap_xml():
    from flask import Response
    base = app.config.get('BASE_URL', 'https://gstlink.in')
    urls = [('/', '1.0', 'weekly'), ('/pricing', '0.8', 'monthly'), ('/privacy', '0.3', 'yearly'), ('/terms', '0.3', 'yearly')]
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    for loc, priority, changefreq in urls:
        xml += f"  <url>\n    <loc>{base}{loc}</loc>\n    <priority>{priority}</priority>\n    <changefreq>{changefreq}</changefreq>\n  </url>\n"
    xml += '</urlset>'
    return Response(xml, mimetype='application/xml')


# ──────────────────────────────────────────────────────────────────
# ERROR HANDLERS — suppress framework version, keep brand experience
# ──────────────────────────────────────────────────────────────────

@app.errorhandler(404)
def not_found(e):
    return render_template('404.html'), 404


@app.errorhandler(500)
def server_error(e):
    app.logger.error(f"500 error: {e}")
    return render_template('500.html'), 500


@app.errorhandler(403)
def forbidden(e):
    return render_template('404.html'), 403  # don't reveal route existence


# ──────────────────────────────────────────────────────────────────
# INIT
# ──────────────────────────────────────────────────────────────────

with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5000)
