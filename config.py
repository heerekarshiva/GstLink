import os
import secrets
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()


class Config:
    # ── SECURITY ────────────────────────────────────────────────────
    # IMPORTANT: Set SECRET_KEY as an environment variable in production.
    # Never use the fallback value in production — it is only for local dev.
    _secret = os.environ.get('SECRET_KEY')
    if not _secret:
        import sys
        if 'gunicorn' in sys.argv[0] or os.environ.get('RAILWAY_ENVIRONMENT'):
            raise RuntimeError(
                "SECRET_KEY environment variable is not set. "
                "Set it in Railway Variables before deploying."
            )
        # Local dev only — generate a random key (sessions won't persist across restarts)
        _secret = secrets.token_hex(32)
    SECRET_KEY = _secret

    # ── DATABASE ─────────────────────────────────────────────────────
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'sqlite:///gstlink.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # ── STRIPE ───────────────────────────────────────────────────────
    STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY', '')
    STRIPE_PUBLISHABLE_KEY = os.environ.get('STRIPE_PUBLISHABLE_KEY', '')
    STRIPE_PRICE_ID = os.environ.get('STRIPE_PRICE_ID', '')
    STRIPE_WEBHOOK_SECRET = os.environ.get('STRIPE_WEBHOOK_SECRET', '')

    # ── AI ───────────────────────────────────────────────────────────
    GROQ_API_KEY = os.environ.get('GROQ_API_KEY', '')

    # ── MAIL (Flask-Mail) ─────────────────────────────────────────────
    # Set all MAIL_* vars in Railway environment variables panel.
    # Use Gmail app passwords or any SMTP provider (Resend, Mailgun, etc.)
    MAIL_SERVER   = os.environ.get('MAIL_SERVER',   'smtp.gmail.com')
    MAIL_PORT     = int(os.environ.get('MAIL_PORT',  '587'))
    MAIL_USE_TLS  = os.environ.get('MAIL_USE_TLS',  'true').lower() == 'true'
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME',  '')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD',  '')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER', 'noreply@gstlink.in')
    MAIL_SUPPRESS_SEND  = not bool(os.environ.get('MAIL_USERNAME', ''))  # suppress in dev

    # ── APP ───────────────────────────────────────────────────────────
    # Set BASE_URL to your deployed domain, e.g. https://gstlink.in
    BASE_URL = os.environ.get('BASE_URL', 'http://localhost:5000')

    FREE_INVOICE_LIMIT = 5       # legacy total limit (kept for reference)
    DAILY_FREE_LIMIT = 5          # free plan: 5 invoices per day
    TRIAL_DAYS = 30               # 30-day full-featured trial for new signups
    PRO_PRICE_INR = 199

    # ── SESSION & COOKIE SECURITY ────────────────────────────────────
    # Prevent JS from accessing session cookies (XSS mitigation)
    SESSION_COOKIE_HTTPONLY = True
    # Only send cookies over HTTPS (Railway serves HTTPS; harmless in local dev)
    SESSION_COOKIE_SECURE   = True
    # Strict same-site policy — extra CSRF layer on top of Flask-WTF tokens
    SESSION_COOKIE_SAMESITE = 'Lax'
    # Remember-me cookie hardening
    REMEMBER_COOKIE_SECURE   = True
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_DURATION = timedelta(days=30)
