"""
GSTLink Mailer — wraps Flask-Mail for password reset & email verification.
Configure these env vars in Railway:
  MAIL_SERVER      e.g. smtp.gmail.com
  MAIL_PORT        e.g. 587
  MAIL_USERNAME    your sending address
  MAIL_PASSWORD    app password (not account password)
  MAIL_DEFAULT_SENDER  e.g. noreply@gstlink.in
"""
from flask_mail import Mail, Message
from markupsafe import escape as html_escape

mail = Mail()


def _send(app, subject: str, recipient: str, html: str) -> bool:
    """Send a single email. Returns True on success, False on failure (never raises)."""
    try:
        with app.app_context():
            msg = Message(
                subject=subject,
                recipients=[recipient],
                html=html,
                sender=app.config.get('MAIL_DEFAULT_SENDER', 'noreply@gstlink.in')
            )
            mail.send(msg)
        return True
    except Exception as e:
        app.logger.error(f"Mail send failed to {recipient}: {e}")
        return False


def send_verification_email(app, user, base_url: str) -> bool:
    token = user.email_verify_token
    verify_url = f"{base_url}/verify-email/{token}"
    # Escape user-controlled data to prevent HTML injection in email clients
    safe_name = html_escape(user.name)
    html = f"""
    <div style="font-family:sans-serif;max-width:520px;margin:auto;">
      <h2 style="color:#00897B;">Verify your GSTLink email</h2>
      <p>Hi {safe_name},</p>
      <p>Click the button below to verify your email address and activate your account:</p>
      <a href="{verify_url}"
         style="display:inline-block;background:#00897B;color:#fff;padding:12px 28px;
                border-radius:8px;text-decoration:none;font-weight:700;margin:12px 0;">
        Verify Email Address
      </a>
      <p style="color:#888;font-size:0.85rem;">
        Link expires in 24 hours. If you didn't sign up for GSTLink, ignore this email.
      </p>
      <hr style="border:none;border-top:1px solid #eee;margin:24px 0;">
      <p style="color:#aaa;font-size:0.8rem;">GSTLink · GST Invoicing for Indian Freelancers</p>
    </div>
    """
    return _send(app, "Verify your GSTLink email", user.email, html)


def send_password_reset_email(app, user, base_url: str) -> bool:
    token = user.password_reset_token
    reset_url = f"{base_url}/reset-password/{token}"
    safe_name = html_escape(user.name)
    html = f"""
    <div style="font-family:sans-serif;max-width:520px;margin:auto;">
      <h2 style="color:#00897B;">Reset your GSTLink password</h2>
      <p>Hi {safe_name},</p>
      <p>We received a request to reset your password. Click below to choose a new one:</p>
      <a href="{reset_url}"
         style="display:inline-block;background:#00897B;color:#fff;padding:12px 28px;
                border-radius:8px;text-decoration:none;font-weight:700;margin:12px 0;">
        Reset Password
      </a>
      <p style="color:#888;font-size:0.85rem;">
        This link expires in <strong>1 hour</strong>. If you didn't request a reset,
        your account is safe — just ignore this email.
      </p>
      <hr style="border:none;border-top:1px solid #eee;margin:24px 0;">
      <p style="color:#aaa;font-size:0.8rem;">GSTLink · GST Invoicing for Indian Freelancers</p>
    </div>
    """
    return _send(app, "Reset your GSTLink password", user.email, html)


def send_password_changed_email(app, user) -> bool:
    """Security notification — alert user that their password was just changed."""
    safe_name = html_escape(user.name)
    html = f"""
    <div style="font-family:sans-serif;max-width:520px;margin:auto;">
      <h2 style="color:#c62828;">Your GSTLink password was changed</h2>
      <p>Hi {safe_name},</p>
      <p>Your GSTLink account password was successfully changed.</p>
      <p style="color:#c62828;"><strong>If you did NOT make this change, contact us immediately at
        <a href="mailto:support@gstlink.in">support@gstlink.in</a>.</strong></p>
      <hr style="border:none;border-top:1px solid #eee;margin:24px 0;">
      <p style="color:#aaa;font-size:0.8rem;">GSTLink · GST Invoicing for Indian Freelancers</p>
    </div>
    """
    return _send(app, "⚠️ Your GSTLink password was changed", user.email, html)
