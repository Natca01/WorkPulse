from flask import Flask, render_template, request, jsonify, session, redirect, url_for, Response, make_response
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect, CSRFError
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from datetime import datetime, date, timedelta
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import uuid
import os
import csv
import io

app = Flask(__name__)

# ─────────────────────────────────────────
#  CONFIGURATION
# ─────────────────────────────────────────
app.config['SECRET_KEY']                     = os.environ.get('SECRET_KEY', 'dev-fallback-key-change-in-production')
app.config['SQLALCHEMY_DATABASE_URI']        = os.environ.get('DATABASE_URL', 'sqlite:///workpulse.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['WTF_CSRF_ENABLED']               = True
app.config['WTF_CSRF_TIME_LIMIT']            = 3600

db            = SQLAlchemy(app)
csrf          = CSRFProtect(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login_page'

# ─────────────────────────────────────────
#  INPUT VALIDATION
# ─────────────────────────────────────────
VALID_PRIORITIES = {'high', 'medium', 'low'}
VALID_STATUSES   = {'todo', 'inprogress', 'done', 'overdue'}
VALID_RECURRINGS = {'none', 'daily', 'weekly', 'monthly'}

def validate_task(data, require_all=True):
    errors = []
    title = data.get('title', '').strip()
    if require_all and not title:
        errors.append('Title is required.')
    elif title and len(title) > 200:
        errors.append('Title must be under 200 characters.')
    due_date = data.get('due_date', '').strip()
    if require_all and not due_date:
        errors.append('Due date is required.')
    elif due_date:
        try:
            datetime.strptime(due_date, "%Y-%m-%d")
        except ValueError:
            errors.append('Due date must be in YYYY-MM-DD format.')
    priority = data.get('priority', 'medium')
    if priority and priority not in VALID_PRIORITIES:
        errors.append(f'Priority must be one of: {", ".join(VALID_PRIORITIES)}.')
    status = data.get('status')
    if status and status not in VALID_STATUSES:
        errors.append(f'Status must be one of: {", ".join(VALID_STATUSES)}.')
    recurring = data.get('recurring', 'none')
    if recurring and recurring not in VALID_RECURRINGS:
        errors.append(f'Recurring must be one of: {", ".join(VALID_RECURRINGS)}.')
    description = data.get('description', '')
    if description and len(description) > 1000:
        errors.append('Description must be under 1000 characters.')
    category = data.get('category', '')
    if category and len(category) > 50:
        errors.append('Category must be under 50 characters.')
    return (len(errors) == 0), errors

def validate_user_data(data, require_all=True):
    errors = []
    name = data.get('name', '').strip()
    if require_all and not name:
        errors.append('Name is required.')
    elif name and len(name) > 100:
        errors.append('Name must be under 100 characters.')
    email = data.get('email', '').strip().lower()
    if require_all and not email:
        errors.append('Email is required.')
    elif email:
        if '@' not in email or '.' not in email.split('@')[-1]:
            errors.append('Please enter a valid email address.')
        if len(email) > 120:
            errors.append('Email must be under 120 characters.')
    password = data.get('password', '')
    if require_all and not password:
        errors.append('Password is required.')
    elif password and len(password) < 4:
        errors.append('Password must be at least 4 characters.')
    elif password and len(password) > 128:
        errors.append('Password must be under 128 characters.')
    return (len(errors) == 0), errors

# ─────────────────────────────────────────
#  DATABASE MODELS
# ─────────────────────────────────────────
class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id         = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name       = db.Column(db.String(100), nullable=False)
    email      = db.Column(db.String(120), unique=True, nullable=False)
    password   = db.Column(db.String(255), nullable=False)
    role       = db.Column(db.String(20), nullable=False, default='employee')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    tasks      = db.relationship('Task', foreign_keys='Task.assigned_to', backref='assignee', lazy=True)

    def to_dict(self):
        return {
            'id': self.id, 'name': self.name,
            'email': self.email, 'role': self.role,
            'created_at': self.created_at.isoformat()
        }

class Task(db.Model):
    __tablename__ = 'tasks'
    id          = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title       = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default='')
    priority    = db.Column(db.String(10), default='medium')
    due_date    = db.Column(db.String(10), nullable=False)
    category    = db.Column(db.String(50), default='General')
    recurring   = db.Column(db.String(10), default='none')
    status      = db.Column(db.String(20), default='todo')
    assigned_to = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=False)
    created_by  = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=False)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        assignee = User.query.get(self.assigned_to)
        status   = self.get_current_status()
        return {
            'id': self.id, 'title': self.title,
            'description': self.description, 'priority': self.priority,
            'due_date': self.due_date, 'category': self.category,
            'recurring': self.recurring, 'status': status,
            'assigned_to': self.assigned_to,
            'assigned_name': assignee.name if assignee else 'Unassigned',
            'created_by': self.created_by,
            'created_at': self.created_at.isoformat(),
            'due_label': self.get_due_label()
        }

    def get_current_status(self):
        if self.status == 'done':
            return 'done'
        today = date.today()
        try:
            due = datetime.strptime(self.due_date, "%Y-%m-%d").date()
            if due < today:  return 'overdue'
            if due == today: return 'inprogress'
            return self.status if self.status in ('todo', 'inprogress') else 'todo'
        except:
            return self.status

    def get_due_label(self):
        try:
            diff = (datetime.strptime(self.due_date, "%Y-%m-%d").date() - date.today()).days
            if diff < 0:  return f"Overdue by {abs(diff)}d"
            if diff == 0: return "Due Today"
            if diff == 1: return "Due Tomorrow"
            return f"Due in {diff}d"
        except:
            return ""

class ActivityLog(db.Model):
    __tablename__ = 'activity_log'
    id         = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    action     = db.Column(db.String(100), nullable=False)
    task_title = db.Column(db.String(200), nullable=False)
    task_id    = db.Column(db.String(36), nullable=True)
    user_id    = db.Column(db.String(36), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id, 'action': self.action,
            'task_title': self.task_title, 'task_id': self.task_id,
            'user_id': self.user_id,
            'timestamp': self.created_at.isoformat(),
            'time_label': self.created_at.strftime("%b %d, %H:%M")
        }

# ─────────────────────────────────────────
#  FLASK-LOGIN USER LOADER
# ─────────────────────────────────────────
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(user_id)

# ─────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────
def log_activity(action, title, task_id=None, user_id=None):
    entry = ActivityLog(action=action, task_title=title, task_id=task_id, user_id=user_id)
    db.session.add(entry)
    db.session.commit()

def stats_for(task_list):
    total = len(task_list)
    done  = sum(1 for t in task_list if t['status'] == 'done')
    over  = sum(1 for t in task_list if t['status'] == 'overdue')
    inp   = sum(1 for t in task_list if t['status'] == 'inprogress')
    todo  = sum(1 for t in task_list if t['status'] == 'todo')
    pct   = round(done / total * 100) if total else 0
    return {'total': total, 'done': done, 'overdue': over, 'inprogress': inp, 'todo': todo, 'completion_pct': pct}

def require_manager(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            return jsonify({'error': 'Unauthorized'}), 401
        if current_user.role != 'manager':
            return jsonify({'error': 'Forbidden — manager access required'}), 403
        return f(*args, **kwargs)
    return decorated

# ─────────────────────────────────────────
#  ERROR HANDLERS
# ─────────────────────────────────────────
@app.errorhandler(404)
def not_found(e):
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Endpoint not found', 'code': 404}), 404
    return render_template('404.html'), 404

@app.errorhandler(500)
def server_error(e):
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Internal server error', 'code': 500}), 500
    return render_template('500.html'), 500

@app.errorhandler(CSRFError)
def csrf_error(e):
    if request.path.startswith('/api/'):
        return jsonify({'error': 'CSRF token missing or invalid', 'code': 400}), 400
    return render_template('404.html'), 400

@app.errorhandler(403)
def forbidden(e):
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Access forbidden', 'code': 403}), 403
    return render_template('404.html'), 403

# ─────────────────────────────────────────
#  SWAGGER API DOCS
# ─────────────────────────────────────────
@app.route('/api/docs')
def api_docs():
    return render_template('api_docs.html')

@app.route('/api/spec')
def api_spec():
    spec = {
        "openapi": "3.0.0",
        "info": {
            "title": "WorkPulse API",
            "version": "3.0.0",
            "description": "REST API for WorkPulse — Company Secretariat Task Management System"
        },
        "tags": [
            {"name": "Auth",     "description": "Login and logout"},
            {"name": "Employee", "description": "Staff member task operations"},
            {"name": "Manager",  "description": "Manager team operations"},
            {"name": "Exports",  "description": "CSV and PDF report exports"}
        ],
        "paths": {
            "/api/login": {"post": {"tags": ["Auth"], "summary": "Login", "responses": {"200": {"description": "OK"}}}},
            "/api/logout": {"post": {"tags": ["Auth"], "summary": "Logout", "responses": {"200": {"description": "OK"}}}},
            "/api/my/tasks": {
                "get":  {"tags": ["Employee"], "summary": "Get my tasks",   "responses": {"200": {"description": "Tasks list"}}},
                "post": {"tags": ["Employee"], "summary": "Create my task", "responses": {"201": {"description": "Created"}}}
            },
            "/api/my/tasks/{task_id}": {
                "put":    {"tags": ["Employee"], "summary": "Update task", "responses": {"200": {"description": "Updated"}}},
                "delete": {"tags": ["Employee"], "summary": "Delete task", "responses": {"200": {"description": "Deleted"}}}
            },
            "/api/my/dashboard": {"get": {"tags": ["Employee"], "summary": "My dashboard data", "responses": {"200": {"description": "Dashboard"}}}},
            "/api/manager/employees": {
                "get":  {"tags": ["Manager"], "summary": "List staff",    "responses": {"200": {"description": "Staff list"}}},
                "post": {"tags": ["Manager"], "summary": "Add staff",     "responses": {"201": {"description": "Created"}}}
            },
            "/api/manager/employees/{emp_id}": {"delete": {"tags": ["Manager"], "summary": "Remove staff", "responses": {"200": {"description": "Removed"}}}},
            "/api/manager/tasks": {
                "get":  {"tags": ["Manager"], "summary": "All tasks",    "responses": {"200": {"description": "Tasks"}}},
                "post": {"tags": ["Manager"], "summary": "Assign task",  "responses": {"201": {"description": "Assigned"}}}
            },
            "/api/manager/tasks/{task_id}": {
                "put":    {"tags": ["Manager"], "summary": "Update any task", "responses": {"200": {"description": "Updated"}}},
                "delete": {"tags": ["Manager"], "summary": "Delete any task", "responses": {"200": {"description": "Deleted"}}}
            },
            "/api/manager/dashboard": {"get": {"tags": ["Manager"], "summary": "Team dashboard", "responses": {"200": {"description": "Dashboard"}}}},
            "/api/export/csv": {
                "get": {
                    "tags": ["Exports"],
                    "summary": "Export all tasks as CSV",
                    "description": "Downloads a CSV file of all team tasks. Manager only. Optional filter: ?emp_id=xxx&status=xxx",
                    "parameters": [
                        {"name": "emp_id", "in": "query", "required": False, "schema": {"type": "string"}, "description": "Filter by employee ID"},
                        {"name": "status", "in": "query", "required": False, "schema": {"type": "string"}, "description": "Filter by status"}
                    ],
                    "responses": {"200": {"description": "CSV file download"}, "403": {"description": "Manager only"}}
                }
            },
            "/api/export/pdf": {
                "get": {
                    "tags": ["Exports"],
                    "summary": "Export team productivity report as PDF",
                    "description": "Downloads a formatted PDF report with team stats, per-employee breakdown and task list. Manager only.",
                    "responses": {"200": {"description": "PDF file download"}, "403": {"description": "Manager only"}}
                }
            },
            "/api/export/my-csv": {
                "get": {
                    "tags": ["Exports"],
                    "summary": "Export my own tasks as CSV",
                    "description": "Staff member downloads their own tasks as CSV.",
                    "responses": {"200": {"description": "CSV file download"}}
                }
            }
        }
    }
    return jsonify(spec)

# ─────────────────────────────────────────
#  CSV EXPORT HELPER
# ─────────────────────────────────────────
def generate_csv(task_list, filename):
    """Generate a CSV file from a list of task dicts."""
    output = io.StringIO()
    writer = csv.writer(output)

    # Header row
    writer.writerow([
        'Title', 'Description', 'Priority', 'Status',
        'Due Date', 'Category', 'Recurring',
        'Assigned To', 'Created At'
    ])

    # Data rows
    for t in task_list:
        writer.writerow([
            t.get('title', ''),
            t.get('description', ''),
            t.get('priority', '').capitalize(),
            t.get('status', '').capitalize(),
            t.get('due_date', ''),
            t.get('category', ''),
            t.get('recurring', 'none').capitalize(),
            t.get('assigned_name', ''),
            t.get('created_at', '')[:10] if t.get('created_at') else ''
        ])

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )

# ─────────────────────────────────────────
#  PDF REPORT HELPER
# ─────────────────────────────────────────
def generate_pdf_html(task_list, stats, emp_stats=None, title="WorkPulse Report"):
    """Generate an HTML page styled for PDF printing."""
    today = date.today().strftime("%d %B %Y")

    # Build per-employee section
    emp_section = ""
    if emp_stats:
        rows = ""
        for e in emp_stats:
            score_color = "#1a6b35" if e['score'] >= 70 else "#c9a84c" if e['score'] >= 40 else "#c0392b"
            rows += f"""
            <tr>
                <td>{e['name']}</td>
                <td style="text-align:center">{e['total']}</td>
                <td style="text-align:center;color:#1a6b35"><b>{e['done']}</b></td>
                <td style="text-align:center;color:#c0392b"><b>{e['overdue']}</b></td>
                <td style="text-align:center;color:#1a5c8a">{e['inprogress']}</td>
                <td style="text-align:center;color:{score_color}"><b>{e['score']}</b></td>
            </tr>"""
        emp_section = f"""
        <div class="section">
            <div class="section-title">Staff Performance Summary</div>
            <table>
                <thead><tr>
                    <th>Staff Member</th><th>Total</th><th>Done</th>
                    <th>Overdue</th><th>In Progress</th><th>Score</th>
                </tr></thead>
                <tbody>{rows}</tbody>
            </table>
        </div>"""

    # Build task rows
    task_rows = ""
    for t in task_list:
        pri_color = "#c0392b" if t['priority'] == 'high' else "#c9a84c" if t['priority'] == 'medium' else "#1a6b35"
        sta_color = "#c0392b" if t['status'] == 'overdue' else "#1a6b35" if t['status'] == 'done' else "#1a5c8a" if t['status'] == 'inprogress' else "#7a9488"
        task_rows += f"""
        <tr>
            <td>{t['title']}</td>
            <td style="color:{pri_color};font-weight:600">{t['priority'].capitalize()}</td>
            <td style="color:{sta_color};font-weight:600">{t['status'].capitalize()}</td>
            <td>{t['due_date']}</td>
            <td>{t.get('assigned_name', '')}</td>
            <td>{t['category']}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>{title}</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family: 'Georgia', serif; color: #1a2e25; background: #fff; padding: 40px; font-size: 12px; }}
  .header {{ border-bottom: 3px solid #0d3d2e; padding-bottom: 20px; margin-bottom: 30px; display: flex; justify-content: space-between; align-items: flex-end; }}
  .logo {{ font-size: 24px; font-weight: bold; color: #0d3d2e; }}
  .logo span {{ color: #c9a84c; }}
  .report-meta {{ text-align: right; color: #7a9488; font-size: 11px; }}
  .report-title {{ font-size: 18px; font-weight: bold; color: #0d3d2e; margin-bottom: 4px; }}
  .kpi-row {{ display: flex; gap: 16px; margin-bottom: 30px; }}
  .kpi {{ flex: 1; border: 1px solid #ccd9d3; border-radius: 6px; padding: 14px; border-top: 3px solid #155c44; text-align: center; }}
  .kpi.over {{ border-top-color: #c0392b; }}
  .kpi.done {{ border-top-color: #1a6b35; }}
  .kpi.prog {{ border-top-color: #1a5c8a; }}
  .kpi.gold {{ border-top-color: #c9a84c; }}
  .kpi-num {{ font-size: 28px; font-weight: bold; color: #1a2e25; }}
  .kpi-lbl {{ font-size: 10px; text-transform: uppercase; letter-spacing: 0.1em; color: #7a9488; margin-top: 4px; }}
  .section {{ margin-bottom: 28px; }}
  .section-title {{ font-size: 14px; font-weight: bold; color: #0d3d2e; border-bottom: 1px solid #ccd9d3; padding-bottom: 8px; margin-bottom: 14px; text-transform: uppercase; letter-spacing: 0.06em; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 11px; }}
  th {{ background: #0d3d2e; color: #faf7f2; padding: 8px 10px; text-align: left; font-size: 10px; text-transform: uppercase; letter-spacing: 0.08em; }}
  td {{ padding: 7px 10px; border-bottom: 1px solid #e8e0d0; }}
  tr:nth-child(even) td {{ background: #f9f6f0; }}
  .footer {{ margin-top: 40px; border-top: 1px solid #ccd9d3; padding-top: 14px; text-align: center; font-size: 10px; color: #7a9488; }}
  @media print {{
    body {{ padding: 20px; }}
    .no-print {{ display: none; }}
  }}
</style>
</head>
<body>

<div class="header">
  <div>
    <div class="logo">Work<span>Pulse</span></div>
    <div style="font-size:10px;color:#7a9488;margin-top:4px;text-transform:uppercase;letter-spacing:0.15em;">Company Secretariat Division</div>
  </div>
  <div class="report-meta">
    <div class="report-title">{title}</div>
    <div>Generated: {today}</div>
    <div style="color:#c0392b;font-size:10px;margin-top:2px;">CONFIDENTIAL — Internal Use Only</div>
  </div>
</div>

<div class="kpi-row">
  <div class="kpi"><div class="kpi-num">{stats['total']}</div><div class="kpi-lbl">Total Tasks</div></div>
  <div class="kpi done"><div class="kpi-num">{stats['done']}</div><div class="kpi-lbl">Completed</div></div>
  <div class="kpi over"><div class="kpi-num">{stats['overdue']}</div><div class="kpi-lbl">Overdue</div></div>
  <div class="kpi prog"><div class="kpi-num">{stats['inprogress']}</div><div class="kpi-lbl">In Progress</div></div>
  <div class="kpi gold"><div class="kpi-num">{stats['completion_pct']}%</div><div class="kpi-lbl">Completion Rate</div></div>
</div>

{emp_section}

<div class="section">
  <div class="section-title">Task Details</div>
  <table>
    <thead><tr>
      <th>Task Title</th><th>Priority</th><th>Status</th>
      <th>Due Date</th><th>Assigned To</th><th>Category</th>
    </tr></thead>
    <tbody>{task_rows}</tbody>
  </table>
</div>

<div class="footer">
  WorkPulse · Company Secretariat · Confidential Internal Report · {today}
</div>

<div class="no-print" style="margin-top:30px;text-align:center">
  <button onclick="window.print()" style="padding:10px 24px;background:#0d3d2e;color:#faf7f2;border:none;border-radius:6px;font-size:13px;cursor:pointer;">🖨 Print / Save as PDF</button>
  <a href="/manager" style="margin-left:12px;padding:10px 24px;background:#f0ebe0;color:#1a2e25;border:1px solid #ccd9d3;border-radius:6px;font-size:13px;text-decoration:none;">← Back to Dashboard</a>
</div>

</body>
</html>"""
    return html

# ─────────────────────────────────────────
#  EXPORT ROUTES
# ─────────────────────────────────────────

# Manager — Export ALL tasks as CSV
@app.route('/api/export/csv')
@login_required
@require_manager
@csrf.exempt
def export_csv():
    emp_id = request.args.get('emp_id')
    status = request.args.get('status')
    rows   = Task.query.filter_by(assigned_to=emp_id).all() if emp_id else Task.query.all()
    tasks  = [t.to_dict() for t in rows]
    if status:
        tasks = [t for t in tasks if t['status'] == status]
    today    = date.today().strftime("%Y-%m-%d")
    filename = f"WorkPulse_Tasks_{today}.csv"
    return generate_csv(tasks, filename)

# Manager — Export PDF productivity report
@app.route('/api/export/pdf')
@login_required
@require_manager
@csrf.exempt
def export_pdf():
    all_t = [t.to_dict() for t in Task.query.all()]
    s     = stats_for(all_t)

    # Build per-employee stats
    emp_stats = []
    for u in User.query.filter_by(role='employee').all():
        et    = [t.to_dict() for t in Task.query.filter_by(assigned_to=u.id).all()]
        es    = stats_for(et)
        score = 0
        if es['total'] > 0:
            score += (es['done'] / es['total']) * 50
            score -= (es['overdue'] / es['total']) * 30
            score += min(es['done'] * 5, 40)
            score = max(0, min(100, round(score)))
        emp_stats.append({**u.to_dict(), **es, 'score': score})
    emp_stats.sort(key=lambda x: -x['score'])

    today = date.today().strftime("%B %Y")
    html  = generate_pdf_html(all_t, s, emp_stats, f"Team Productivity Report — {today}")
    return Response(html, mimetype='text/html')

# Employee — Export their own tasks as CSV
@app.route('/api/export/my-csv')
@login_required
@csrf.exempt
def export_my_csv():
    rows  = Task.query.filter_by(assigned_to=current_user.id).all()
    tasks = [t.to_dict() for t in rows]
    today = date.today().strftime("%Y-%m-%d")
    name  = current_user.name.replace(' ', '_')
    return generate_csv(tasks, f"WorkPulse_{name}_Tasks_{today}.csv")

# ─────────────────────────────────────────
#  SEED DATA
# ─────────────────────────────────────────
def seed_data():
    if User.query.first():
        return
    today   = date.today()
    manager = User(
        id=str(uuid.uuid4()), name='Alex Manager',
        email='manager@taskflow.com',
        password=generate_password_hash('manager123'),
        role='manager'
    )
    db.session.add(manager)
    db.session.flush()
    emp_data = [
        ('Sara Khan',   'sara@taskflow.com'),
        ('Ravi Sharma', 'ravi@taskflow.com'),
        ('Priya Singh', 'priya@taskflow.com'),
        ('Omar Farooq', 'omar@taskflow.com'),
    ]
    employees = []
    for name, email in emp_data:
        emp = User(
            id=str(uuid.uuid4()), name=name, email=email,
            password=generate_password_hash('emp123'), role='employee'
        )
        db.session.add(emp)
        employees.append(emp)
    db.session.flush()
    sample_tasks = [
        {'title': 'Design database schema',  'desc': 'Plan PostgreSQL schema',            'pri': 'high',   'due': (today - timedelta(days=1)).strftime("%Y-%m-%d"), 'cat': 'Development',   'rec': 'none',  'emp': 0},
        {'title': 'Write unit tests',        'desc': 'Cover API endpoints with pytest',   'pri': 'medium', 'due': today.strftime("%Y-%m-%d"),                      'cat': 'Testing',       'rec': 'none',  'emp': 0},
        {'title': 'Team standup meeting',    'desc': 'Daily sync at 10am',                'pri': 'low',    'due': today.strftime("%Y-%m-%d"),                      'cat': 'Meetings',      'rec': 'daily', 'emp': 0},
        {'title': 'Fix API rate limiter',    'desc': 'Patch rate limiter bug',            'pri': 'high',   'due': (today - timedelta(days=2)).strftime("%Y-%m-%d"), 'cat': 'Backend',       'rec': 'none',  'emp': 1},
        {'title': 'Write migration scripts', 'desc': 'DB migration for v2.1',             'pri': 'medium', 'due': today.strftime("%Y-%m-%d"),                      'cat': 'Database',      'rec': 'none',  'emp': 1},
        {'title': 'Code review PRs',         'desc': 'Review open pull requests',         'pri': 'low',    'due': today.strftime("%Y-%m-%d"),                      'cat': 'Development',   'rec': 'daily', 'emp': 1},
        {'title': 'Unit test auth module',   'desc': 'Achieve 90% coverage on auth',     'pri': 'high',   'due': (today + timedelta(days=1)).strftime("%Y-%m-%d"), 'cat': 'Testing',       'rec': 'none',  'emp': 2},
        {'title': 'Update Swagger docs',     'desc': 'Document all v2 API endpoints',     'pri': 'medium', 'due': (today + timedelta(days=4)).strftime("%Y-%m-%d"), 'cat': 'Documentation', 'rec': 'none',  'emp': 2},
        {'title': 'Setup CI/CD pipeline',    'desc': 'Configure GitHub Actions',          'pri': 'high',   'due': (today - timedelta(days=1)).strftime("%Y-%m-%d"), 'cat': 'DevOps',        'rec': 'none',  'emp': 3},
        {'title': 'Monitor server metrics',  'desc': 'Check CPU/memory dashboards daily', 'pri': 'medium', 'due': today.strftime("%Y-%m-%d"),                      'cat': 'DevOps',        'rec': 'daily', 'emp': 3},
        {'title': 'Update SSL certificates', 'desc': 'Renew certs before expiry',         'pri': 'high',   'due': (today + timedelta(days=5)).strftime("%Y-%m-%d"), 'cat': 'Security',      'rec': 'none',  'emp': 3},
    ]
    for s in sample_tasks:
        emp  = employees[s['emp']]
        task = Task(
            id=str(uuid.uuid4()), title=s['title'], description=s['desc'],
            priority=s['pri'], due_date=s['due'], category=s['cat'],
            recurring=s['rec'], status='todo',
            assigned_to=emp.id, created_by=manager.id
        )
        db.session.add(task)
    db.session.commit()
    print("✓ Database seeded with sample data")

# ─────────────────────────────────────────
#  AUTH ROUTES
# ─────────────────────────────────────────
@app.route('/')
def root():
    if current_user.is_authenticated:
        return redirect(url_for('manager_page') if current_user.role == 'manager' else url_for('employee_page'))
    return redirect(url_for('login_page'))

@app.route('/login', methods=['GET'])
def login_page():
    if current_user.is_authenticated:
        return redirect(url_for('root'))
    return render_template('login.html')

@app.route('/api/login', methods=['POST'])
@csrf.exempt
def api_login():
    data = request.json
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    email = data.get('email', '').strip().lower()
    pwd   = data.get('password', '')
    if not email or not pwd:
        return jsonify({'error': 'Email and password are required'}), 400
    if len(email) > 120 or len(pwd) > 128:
        return jsonify({'error': 'Invalid credentials'}), 400
    user = User.query.filter_by(email=email).first()
    if not user or not check_password_hash(user.password, pwd):
        return jsonify({'error': 'Invalid email or password'}), 401
    login_user(user, remember=True)
    return jsonify({'role': user.role, 'name': user.name})

@app.route('/api/logout', methods=['POST'])
@csrf.exempt
def api_logout():
    logout_user()
    return jsonify({'ok': True})

@app.route('/manager')
@login_required
def manager_page():
    if current_user.role != 'manager':
        return redirect(url_for('employee_page'))
    return render_template('manager.html', user=current_user)

@app.route('/employee')
@login_required
def employee_page():
    if current_user.role == 'manager':
        return redirect(url_for('manager_page'))
    return render_template('employee.html', user=current_user)

# ─────────────────────────────────────────
#  EMPLOYEE API
# ─────────────────────────────────────────
@app.route('/api/my/tasks', methods=['GET'])
@login_required
@csrf.exempt
def my_tasks():
    rows  = Task.query.filter_by(assigned_to=current_user.id).all()
    tasks = sorted([t.to_dict() for t in rows], key=lambda x: {'high': 0, 'medium': 1, 'low': 2}.get(x['priority'], 3))
    return jsonify({'tasks': tasks, 'stats': stats_for(tasks)})

@app.route('/api/my/tasks', methods=['POST'])
@login_required
@csrf.exempt
def create_my_task():
    if current_user.role == 'manager':
        return jsonify({'error': 'Managers assign tasks via manager panel'}), 403
    data = request.json
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    valid, errors = validate_task(data, require_all=True)
    if not valid:
        return jsonify({'error': ' '.join(errors)}), 400
    task = Task(
        title=data['title'].strip(),
        description=data.get('description', '').strip(),
        priority=data.get('priority', 'medium'),
        due_date=data['due_date'],
        category=data.get('category', 'General').strip(),
        recurring=data.get('recurring', 'none'),
        status='todo', assigned_to=current_user.id, created_by=current_user.id
    )
    db.session.add(task)
    db.session.commit()
    log_activity('created', task.title, task.id, current_user.id)
    return jsonify(task.to_dict()), 201

@app.route('/api/my/tasks/<tid>', methods=['PUT'])
@login_required
@csrf.exempt
def update_my_task(tid):
    task = Task.query.get(tid)
    if not task:
        return jsonify({'error': 'Task not found'}), 404
    if current_user.role == 'employee' and task.assigned_to != current_user.id:
        return jsonify({'error': 'Forbidden'}), 403
    data = request.json
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    valid, errors = validate_task(data, require_all=False)
    if not valid:
        return jsonify({'error': ' '.join(errors)}), 400
    for field in ('title', 'description', 'priority', 'due_date', 'category', 'recurring'):
        if field in data:
            setattr(task, field, data[field].strip() if isinstance(data[field], str) else data[field])
    if 'status' in data:
        task.status = data['status']
        if data['status'] == 'done':
            log_activity('completed', task.title, tid, current_user.id)
            if task.recurring != 'none':
                old_due = datetime.strptime(task.due_date, "%Y-%m-%d").date()
                if task.recurring == 'daily':
                    new_due = old_due + timedelta(days=1)
                elif task.recurring == 'weekly':
                    new_due = old_due + timedelta(weeks=1)
                elif task.recurring == 'monthly':
                    m = old_due.month % 12 + 1
                    y = old_due.year + (1 if old_due.month == 12 else 0)
                    new_due = old_due.replace(year=y, month=m)
                new_task = Task(
                    title=task.title, description=task.description,
                    priority=task.priority, due_date=new_due.strftime("%Y-%m-%d"),
                    category=task.category, recurring=task.recurring,
                    status='todo', assigned_to=task.assigned_to, created_by=task.created_by
                )
                db.session.add(new_task)
                log_activity('auto-created (recurring)', task.title, new_task.id, current_user.id)
        else:
            log_activity(f'moved to {data["status"]}', task.title, tid, current_user.id)
    else:
        log_activity('updated', task.title, tid, current_user.id)
    db.session.commit()
    return jsonify(task.to_dict())

@app.route('/api/my/tasks/<tid>', methods=['DELETE'])
@login_required
@csrf.exempt
def delete_my_task(tid):
    task = Task.query.get(tid)
    if not task:
        return jsonify({'error': 'Task not found'}), 404
    if current_user.role == 'employee' and task.assigned_to != current_user.id:
        return jsonify({'error': 'Forbidden'}), 403
    log_activity('deleted', task.title, tid, current_user.id)
    db.session.delete(task)
    db.session.commit()
    return jsonify({'ok': True})

@app.route('/api/my/dashboard', methods=['GET'])
@login_required
@csrf.exempt
def my_dashboard():
    rows  = Task.query.filter_by(assigned_to=current_user.id).all()
    tasks = [t.to_dict() for t in rows]
    s     = stats_for(tasks)
    pb    = {'high': 0, 'medium': 0, 'low': 0}
    for t in tasks:
        pb[t['priority']] = pb.get(t['priority'], 0) + 1
    cat_map = {}
    for t in tasks:
        c = t['category'] or 'General'
        if c not in cat_map:
            cat_map[c] = {'total': 0, 'done': 0, 'overdue': 0, 'inprogress': 0, 'todo': 0}
        cat_map[c]['total'] += 1
        cat_map[c][t['status']] = cat_map[c].get(t['status'], 0) + 1
    today    = date.today()
    upcoming = []
    for i in range(7):
        d   = today + timedelta(days=i)
        cnt = sum(1 for t in tasks if t['due_date'] == d.strftime("%Y-%m-%d") and t['status'] != 'done')
        upcoming.append({'label': d.strftime("%a"), 'count': cnt})
    score = 0
    if s['total'] > 0:
        score += (s['done'] / s['total']) * 50
        score -= (s['overdue'] / s['total']) * 30
        score += min(s['done'] * 5, 40)
        score = max(0, min(100, round(score)))
    logs = ActivityLog.query.filter_by(user_id=current_user.id).order_by(ActivityLog.created_at.desc()).limit(15).all()
    return jsonify({
        'overview':           {**s, 'productivity_score': score},
        'priority_breakdown': pb,
        'categories':         [{'name': k, **v} for k, v in cat_map.items()],
        'upcoming_days':      upcoming,
        'activity_log':       [l.to_dict() for l in logs]
    })

# ─────────────────────────────────────────
#  MANAGER API
# ─────────────────────────────────────────
@app.route('/api/manager/employees', methods=['GET'])
@login_required
@require_manager
@csrf.exempt
def get_employees():
    emps = User.query.filter_by(role='employee').all()
    return jsonify({'employees': [e.to_dict() for e in emps]})

@app.route('/api/manager/employees', methods=['POST'])
@login_required
@require_manager
@csrf.exempt
def add_employee():
    data = request.json
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    valid, errors = validate_user_data(data, require_all=True)
    if not valid:
        return jsonify({'error': ' '.join(errors)}), 400
    email = data['email'].strip().lower()
    if User.query.filter_by(email=email).first():
        return jsonify({'error': 'An account with this email already exists'}), 400
    emp = User(
        name=data['name'].strip(), email=email,
        password=generate_password_hash(data['password']),
        role='employee'
    )
    db.session.add(emp)
    db.session.commit()
    log_activity('employee added', data['name'], None, current_user.id)
    return jsonify(emp.to_dict()), 201

@app.route('/api/manager/employees/<eid>', methods=['DELETE'])
@login_required
@require_manager
@csrf.exempt
def remove_employee(eid):
    emp = User.query.get(eid)
    if not emp or emp.role == 'manager':
        return jsonify({'error': 'Staff member not found'}), 404
    Task.query.filter_by(assigned_to=eid).delete()
    log_activity('employee removed', emp.name, None, current_user.id)
    db.session.delete(emp)
    db.session.commit()
    return jsonify({'ok': True})

@app.route('/api/manager/tasks', methods=['GET'])
@login_required
@require_manager
@csrf.exempt
def all_tasks():
    emp_id = request.args.get('emp_id')
    rows   = Task.query.filter_by(assigned_to=emp_id).all() if emp_id else Task.query.all()
    tasks  = sorted([t.to_dict() for t in rows], key=lambda x: {'high': 0, 'medium': 1, 'low': 2}.get(x['priority'], 3))
    return jsonify({'tasks': tasks, 'stats': stats_for(tasks)})

@app.route('/api/manager/tasks', methods=['POST'])
@login_required
@require_manager
@csrf.exempt
def assign_task():
    data = request.json
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    valid, errors = validate_task(data, require_all=True)
    if not valid:
        return jsonify({'error': ' '.join(errors)}), 400
    assigned_to = data.get('assigned_to', '')
    if not assigned_to or not User.query.get(assigned_to):
        return jsonify({'error': 'Please select a valid staff member'}), 404
    task = Task(
        title=data['title'].strip(),
        description=data.get('description', '').strip(),
        priority=data.get('priority', 'medium'),
        due_date=data['due_date'],
        category=data.get('category', 'General').strip(),
        recurring=data.get('recurring', 'none'),
        status='todo', assigned_to=assigned_to, created_by=current_user.id
    )
    db.session.add(task)
    db.session.commit()
    assignee = User.query.get(assigned_to)
    log_activity(f'assigned to {assignee.name}', task.title, task.id, current_user.id)
    return jsonify(task.to_dict()), 201

@app.route('/api/manager/tasks/<tid>', methods=['PUT'])
@login_required
@require_manager
@csrf.exempt
def update_any_task(tid):
    task = Task.query.get(tid)
    if not task:
        return jsonify({'error': 'Task not found'}), 404
    data = request.json
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    valid, errors = validate_task(data, require_all=False)
    if not valid:
        return jsonify({'error': ' '.join(errors)}), 400
    for field in ('title', 'description', 'priority', 'due_date', 'category', 'recurring', 'assigned_to'):
        if field in data:
            setattr(task, field, data[field].strip() if isinstance(data[field], str) else data[field])
    if 'status' in data:
        task.status = data['status']
        log_activity(f'status → {data["status"]}', task.title, tid, current_user.id)
    else:
        log_activity('updated', task.title, tid, current_user.id)
    db.session.commit()
    return jsonify(task.to_dict())

@app.route('/api/manager/tasks/<tid>', methods=['DELETE'])
@login_required
@require_manager
@csrf.exempt
def delete_any_task(tid):
    task = Task.query.get(tid)
    if not task:
        return jsonify({'error': 'Task not found'}), 404
    log_activity('deleted', task.title, tid, current_user.id)
    db.session.delete(task)
    db.session.commit()
    return jsonify({'ok': True})

@app.route('/api/manager/dashboard', methods=['GET'])
@login_required
@require_manager
@csrf.exempt
def manager_dashboard():
    all_t = [t.to_dict() for t in Task.query.all()]
    s     = stats_for(all_t)
    emp_stats = []
    for u in User.query.filter_by(role='employee').all():
        et    = [t.to_dict() for t in Task.query.filter_by(assigned_to=u.id).all()]
        es    = stats_for(et)
        score = 0
        if es['total'] > 0:
            score += (es['done'] / es['total']) * 50
            score -= (es['overdue'] / es['total']) * 30
            score += min(es['done'] * 5, 40)
            score = max(0, min(100, round(score)))
        emp_stats.append({**u.to_dict(), **es, 'score': score})
    emp_stats.sort(key=lambda x: -x['score'])
    pb = {'high': 0, 'medium': 0, 'low': 0}
    for t in all_t:
        pb[t['priority']] = pb.get(t['priority'], 0) + 1
    today    = date.today()
    upcoming = []
    for i in range(7):
        d   = today + timedelta(days=i)
        cnt = sum(1 for t in all_t if t['due_date'] == d.strftime("%Y-%m-%d") and t['status'] != 'done')
        upcoming.append({'label': d.strftime("%a"), 'count': cnt})
    logs = ActivityLog.query.order_by(ActivityLog.created_at.desc()).limit(20).all()
    return jsonify({
        'overview':           s,
        'employee_stats':     emp_stats,
        'priority_breakdown': pb,
        'upcoming_days':      upcoming,
        'activity_log':       [l.to_dict() for l in logs]
    })

# ─────────────────────────────────────────
#  APP STARTUP
# ─────────────────────────────────────────
with app.app_context():
    db.create_all()
    seed_data()

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5000)
