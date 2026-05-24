import os
from flask import Blueprint, render_template_string, request, abort
from database.models import db, User, Invoice, Client
from sqlalchemy import func
from datetime import datetime, timedelta

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

# ── Set ADMIN_SECRET_KEY in your Render environment variables ─────
ADMIN_SECRET_KEY = os.environ.get('ADMIN_SECRET_KEY', 'change_this_secret_123')
# ─────────────────────────────────────────────────────────────────

def check_auth():
    if request.args.get('key') != ADMIN_SECRET_KEY:
        abort(403)


ADMIN_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>GstLink Admin</title>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@300;400;600&display=swap" rel="stylesheet">
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  :root {
    --bg: #0a0c10; --surface: #111318; --border: #1e2330;
    --accent: #00e5a0; --accent2: #0066ff; --warn: #ff6b35;
    --text: #e8eaf0; --muted: #5a6175; --pro: #ffd700;
  }
  body { background: var(--bg); color: var(--text); font-family: 'IBM Plex Sans', sans-serif; font-size: 14px; min-height: 100vh; }
  body::before {
    content: ''; position: fixed; inset: 0;
    background: repeating-linear-gradient(to bottom, transparent 0px, transparent 2px, rgba(0,0,0,0.06) 2px, rgba(0,0,0,0.06) 4px);
    pointer-events: none; z-index: 9999;
  }
  header { border-bottom: 1px solid var(--border); padding: 18px 32px; display: flex; align-items: center; gap: 16px; background: var(--surface); }
  .logo { font-family: 'IBM Plex Mono', monospace; font-size: 18px; font-weight: 600; color: var(--accent); }
  .logo span { color: var(--muted); }
  .badge { background: rgba(0,229,160,0.1); border: 1px solid rgba(0,229,160,0.3); color: var(--accent); font-family: 'IBM Plex Mono', monospace; font-size: 10px; padding: 3px 8px; border-radius: 3px; letter-spacing: 1px; }
  main { padding: 32px; max-width: 1400px; margin: 0 auto; }
  .warn-box { background: rgba(255,107,53,0.08); border: 1px solid rgba(255,107,53,0.3); border-radius: 8px; padding: 14px 20px; color: var(--warn); font-family: 'IBM Plex Mono', monospace; font-size: 12px; margin-bottom: 32px; }
  .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 16px; margin-bottom: 40px; }
  .stat-card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 20px 24px; position: relative; overflow: hidden; }
  .stat-card::after { content: ''; position: absolute; top: 0; left: 0; right: 0; height: 2px; background: var(--accent); }
  .stat-card:nth-child(2)::after { background: var(--accent2); }
  .stat-card:nth-child(3)::after { background: var(--pro); }
  .stat-card:nth-child(4)::after { background: var(--warn); }
  .stat-card:nth-child(5)::after { background: #a855f7; }
  .stat-card:nth-child(6)::after { background: #ec4899; }
  .stat-label { font-family: 'IBM Plex Mono', monospace; font-size: 10px; letter-spacing: 1.5px; color: var(--muted); text-transform: uppercase; margin-bottom: 10px; }
  .stat-value { font-family: 'IBM Plex Mono', monospace; font-size: 36px; font-weight: 600; color: var(--text); line-height: 1; }
  .two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; margin-bottom: 40px; }
  @media (max-width: 900px) { .two-col { grid-template-columns: 1fr; } }
  .card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 24px; }
  .section-title { font-family: 'IBM Plex Mono', monospace; font-size: 11px; letter-spacing: 2px; color: var(--muted); text-transform: uppercase; margin-bottom: 16px; padding-bottom: 8px; border-bottom: 1px solid var(--border); }
  .signup-row { display: flex; align-items: center; gap: 14px; padding: 12px 0; border-bottom: 1px solid var(--border); }
  .signup-row:last-child { border-bottom: none; }
  .avatar { width: 36px; height: 36px; border-radius: 6px; background: linear-gradient(135deg, var(--accent2), var(--accent)); display: flex; align-items: center; justify-content: center; font-family: 'IBM Plex Mono', monospace; font-weight: 600; font-size: 13px; color: #fff; flex-shrink: 0; }
  .signup-info { flex: 1; min-width: 0; }
  .signup-name { font-weight: 600; font-size: 13px; color: var(--text); margin-bottom: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .signup-email { color: var(--muted); font-size: 11px; font-family: 'IBM Plex Mono', monospace; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .signup-time { color: var(--muted); font-size: 11px; font-family: 'IBM Plex Mono', monospace; white-space: nowrap; }
  .inv-count { font-family: 'IBM Plex Mono', monospace; font-size: 13px; color: var(--accent2); }
  .toolbar { display: flex; gap: 12px; margin-bottom: 20px; }
  .search-box { flex: 1; background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 10px 16px; color: var(--text); font-family: 'IBM Plex Mono', monospace; font-size: 13px; outline: none; transition: border-color 0.2s; }
  .search-box:focus { border-color: var(--accent); }
  .search-box::placeholder { color: var(--muted); }
  .table-wrap { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; overflow: hidden; margin-bottom: 40px; overflow-x: auto; }
  .table-header { padding: 16px 24px; border-bottom: 1px solid var(--border); display: flex; align-items: center; justify-content: space-between; }
  .table-title { font-family: 'IBM Plex Mono', monospace; font-size: 11px; letter-spacing: 2px; color: var(--muted); text-transform: uppercase; }
  .count-pill { background: rgba(0,229,160,0.1); color: var(--accent); font-family: 'IBM Plex Mono', monospace; font-size: 11px; padding: 3px 10px; border-radius: 20px; }
  table { width: 100%; border-collapse: collapse; min-width: 900px; }
  thead tr { background: rgba(255,255,255,0.02); }
  th { font-family: 'IBM Plex Mono', monospace; font-size: 10px; letter-spacing: 1px; color: var(--muted); text-transform: uppercase; text-align: left; padding: 12px 20px; border-bottom: 1px solid var(--border); white-space: nowrap; }
  td { padding: 14px 20px; border-bottom: 1px solid rgba(255,255,255,0.03); vertical-align: middle; color: var(--text); }
  tr:last-child td { border-bottom: none; }
  tr:hover td { background: rgba(255,255,255,0.02); }
  .mono { font-family: 'IBM Plex Mono', monospace; font-size: 12px; }
  .plan { display: inline-block; font-family: 'IBM Plex Mono', monospace; font-size: 10px; letter-spacing: 1px; padding: 3px 10px; border-radius: 3px; text-transform: uppercase; font-weight: 600; }
  .plan-pro    { background: rgba(255,215,0,0.12);  color: var(--pro);   border: 1px solid rgba(255,215,0,0.3); }
  .plan-trial  { background: rgba(0,229,160,0.10);  color: var(--accent); border: 1px solid rgba(0,229,160,0.3); }
  .plan-free   { background: rgba(90,97,117,0.15);  color: var(--muted); border: 1px solid rgba(90,97,117,0.3); }
  .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }
  .dot-yes { background: var(--accent); box-shadow: 0 0 6px var(--accent); }
  .dot-no  { background: var(--warn); }
  .date-cell { color: var(--muted); font-family: 'IBM Plex Mono', monospace; font-size: 11px; }
  .empty { text-align: center; padding: 48px; color: var(--muted); font-family: 'IBM Plex Mono', monospace; font-size: 13px; }
  footer { text-align: center; padding: 24px; color: var(--muted); font-family: 'IBM Plex Mono', monospace; font-size: 11px; border-top: 1px solid var(--border); margin-top: 20px; }
</style>
</head>
<body>
<header>
  <div class="logo">GstLink<span>./</span>admin</div>
  <div class="badge">PRIVATE</div>
</header>
<main>

  <div class="warn-box">⚠ &nbsp; Admin panel — protected by secret key. Never share this URL publicly.</div>

  <!-- Stats -->
  <div class="stats">
    <div class="stat-card"><div class="stat-label">Total Users</div><div class="stat-value">{{ stats.total }}</div></div>
    <div class="stat-card"><div class="stat-label">Trial</div><div class="stat-value">{{ stats.trial }}</div></div>
    <div class="stat-card"><div class="stat-label">Pro</div><div class="stat-value">{{ stats.pro }}</div></div>
    <div class="stat-card"><div class="stat-label">Free</div><div class="stat-value">{{ stats.free }}</div></div>
    <div class="stat-card"><div class="stat-label">Verified</div><div class="stat-value">{{ stats.verified }}</div></div>
    <div class="stat-card"><div class="stat-label">Total Invoices</div><div class="stat-value">{{ stats.invoices }}</div></div>
    <div class="stat-card"><div class="stat-label">New (7 days)</div><div class="stat-value">{{ stats.new_7d }}</div></div>
    <div class="stat-card"><div class="stat-label">Total Clients</div><div class="stat-value">{{ stats.clients }}</div></div>
  </div>

  <!-- Recent + Top Creators -->
  <div class="two-col">
    <div class="card">
      <div class="section-title">Recent Signups</div>
      {% for u in recent %}
      <div class="signup-row">
        <div class="avatar">{{ u.name[0].upper() }}</div>
        <div class="signup-info">
          <div class="signup-name">{{ u.name }}</div>
          <div class="signup-email">{{ u.email }}</div>
        </div>
        <div class="signup-time">{{ u.created_at.strftime('%d %b %Y') }}</div>
      </div>
      {% else %}<div class="empty">No users yet</div>{% endfor %}
    </div>

    <div class="card">
      <div class="section-title">Top Invoice Creators</div>
      {% for row in top_creators %}
      <div class="signup-row">
        <div class="avatar">{{ row.name[0].upper() }}</div>
        <div class="signup-info">
          <div class="signup-name">{{ row.name }}</div>
          <div class="signup-email">{{ row.email }}</div>
        </div>
        <div class="inv-count">{{ row.inv_count }} invoices</div>
      </div>
      {% else %}<div class="empty">No invoices yet</div>{% endfor %}
    </div>
  </div>

  <!-- Search + Table -->
  <div class="toolbar">
    <input class="search-box" id="searchBox" type="text" placeholder="Search by name, email, GSTIN, business, phone..." oninput="filterTable()">
  </div>

  <div class="table-wrap">
    <div class="table-header">
      <div class="table-title">All Users</div>
      <div class="count-pill" id="rowCount">{{ users|length }} users</div>
    </div>
    <table id="userTable">
      <thead>
        <tr>
          <th>ID</th><th>Name</th><th>Email</th><th>Phone</th>
          <th>Business</th><th>GSTIN</th><th>Plan</th>
          <th>Verified</th><th>Invoices</th><th>Clients</th><th>Joined</th>
        </tr>
      </thead>
      <tbody id="tableBody">
        {% for u in users %}
        <tr>
          <td class="mono" style="color:var(--muted)">{{ u.id }}</td>
          <td><strong>{{ u.name }}</strong></td>
          <td class="mono" style="font-size:12px">{{ u.email }}</td>
          <td class="mono">{{ u.phone or '—' }}</td>
          <td>{{ u.business_name or '—' }}</td>
          <td class="mono">{{ u.gstin or '—' }}</td>
          <td><span class="plan plan-{{ u.plan_type }}">{{ u.plan_type }}</span></td>
          <td>
            <span class="dot {{ 'dot-yes' if u.email_verified else 'dot-no' }}"></span>
            {{ 'Yes' if u.email_verified else 'No' }}
          </td>
          <td><span class="inv-count">{{ u.invoice_count }}</span></td>
          <td class="mono">{{ u.client_count }}</td>
          <td class="date-cell">{{ u.created_at.strftime('%d %b %Y') }}</td>
        </tr>
        {% else %}
        <tr><td colspan="11" class="empty">No users found</td></tr>
        {% endfor %}
      </tbody>
    </table>
  </div>

</main>
<footer>GstLink Admin &nbsp;·&nbsp; {{ now }} &nbsp;·&nbsp; {{ stats.total }} total users</footer>

<script>
function filterTable() {
  const q = document.getElementById('searchBox').value.toLowerCase();
  const rows = document.querySelectorAll('#tableBody tr');
  let visible = 0;
  rows.forEach(row => {
    const show = row.innerText.toLowerCase().includes(q);
    row.style.display = show ? '' : 'none';
    if (show) visible++;
  });
  document.getElementById('rowCount').textContent = visible + ' users';
}
</script>
</body>
</html>
"""


@admin_bp.route('/')
def dashboard():
    check_auth()

    # ── Stats ──────────────────────────────────────────────────────
    total       = User.query.count()
    trial_count = User.query.filter_by(plan_type='trial').count()
    pro_count   = User.query.filter_by(plan_type='pro').count()
    free_count  = User.query.filter_by(plan_type='free').count()
    verified    = User.query.filter_by(email_verified=True).count()
    inv_total   = Invoice.query.count()
    cli_total   = Client.query.count()
    week_ago    = datetime.utcnow() - timedelta(days=7)
    new_7d      = User.query.filter(User.created_at >= week_ago).count()

    stats = dict(
        total=total, trial=trial_count, pro=pro_count, free=free_count,
        verified=verified, invoices=inv_total, clients=cli_total, new_7d=new_7d
    )

    # ── Recent signups ─────────────────────────────────────────────
    recent = User.query.order_by(User.created_at.desc()).limit(8).all()

    # ── Top invoice creators ───────────────────────────────────────
    top_rows = (
        db.session.query(
            User.name, User.email,
            func.count(Invoice.id).label('inv_count')
        )
        .join(Invoice, Invoice.user_id == User.id)
        .group_by(User.id)
        .order_by(func.count(Invoice.id).desc())
        .limit(8).all()
    )
    top_creators = [
        {'name': r.name, 'email': r.email, 'inv_count': r.inv_count}
        for r in top_rows
    ]

    # ── All users with invoice + client counts ─────────────────────
    all_users_raw = (
        db.session.query(
            User,
            func.count(Invoice.id.distinct()).label('invoice_count'),
            func.count(Client.id.distinct()).label('client_count')
        )
        .outerjoin(Invoice, Invoice.user_id == User.id)
        .outerjoin(Client, Client.user_id == User.id)
        .group_by(User.id)
        .order_by(User.created_at.desc())
        .all()
    )

    users = []
    for u, inv_count, cli_count in all_users_raw:
        u.invoice_count = inv_count
        u.client_count  = cli_count
        users.append(u)

    now = datetime.utcnow().strftime('%d %b %Y %H:%M UTC')

    return render_template_string(
        ADMIN_TEMPLATE,
        stats=stats, recent=recent,
        top_creators=top_creators, users=users, now=now
    )
