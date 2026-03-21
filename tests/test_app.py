"""
WorkPulse — Pytest Unit Tests
==============================
Tests cover: auth, task CRUD, role enforcement,
status auto-detection, validation, recurring logic.

Run with:
    pytest tests/test_app.py -v
"""

import pytest
import json
from datetime import date, timedelta
from app import app, db, User, Task, ActivityLog, validate_task, validate_user_data
from werkzeug.security import generate_password_hash


# ─────────────────────────────────────────
#  TEST FIXTURES
# ─────────────────────────────────────────
@pytest.fixture
def client():
    """Create a test client with an in-memory SQLite database."""
    app.config['TESTING']                = True
    app.config['WTF_CSRF_ENABLED']       = False
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['SECRET_KEY']             = 'test-secret-key'

    with app.test_client() as client:
        with app.app_context():
            db.create_all()
            _seed_test_data()
        yield client
        with app.app_context():
            db.drop_all()


def _seed_test_data():
    """Seed test database with manager and employee."""
    manager = User(
        id='mgr-001', name='Test Manager',
        email='manager@test.com',
        password=generate_password_hash('manager123'),
        role='manager'
    )
    employee = User(
        id='emp-001', name='Test Employee',
        email='employee@test.com',
        password=generate_password_hash('emp123'),
        role='employee'
    )
    db.session.add_all([manager, employee])
    db.session.flush()

    today = date.today()
    task = Task(
        id='task-001', title='Test Task',
        description='A test task',
        priority='high',
        due_date=today.strftime("%Y-%m-%d"),
        category='Testing',
        recurring='none',
        status='todo',
        assigned_to='emp-001',
        created_by='mgr-001'
    )
    overdue_task = Task(
        id='task-002', title='Overdue Task',
        description='An overdue task',
        priority='medium',
        due_date=(today - timedelta(days=2)).strftime("%Y-%m-%d"),
        category='Testing',
        recurring='none',
        status='todo',
        assigned_to='emp-001',
        created_by='mgr-001'
    )
    db.session.add_all([task, overdue_task])
    db.session.commit()


def login_as(client, email, password):
    """Helper to login a user."""
    return client.post('/api/login',
        data=json.dumps({'email': email, 'password': password}),
        content_type='application/json'
    )


# ─────────────────────────────────────────
#  AUTH TESTS
# ─────────────────────────────────────────
class TestAuth:

    def test_login_valid_manager(self, client):
        """Manager can login with correct credentials."""
        res = login_as(client, 'manager@test.com', 'manager123')
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data['role'] == 'manager'
        assert data['name'] == 'Test Manager'

    def test_login_valid_employee(self, client):
        """Employee can login with correct credentials."""
        res = login_as(client, 'employee@test.com', 'emp123')
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data['role'] == 'employee'

    def test_login_wrong_password(self, client):
        """Login fails with wrong password."""
        res = login_as(client, 'manager@test.com', 'wrongpassword')
        assert res.status_code == 401
        data = json.loads(res.data)
        assert 'error' in data

    def test_login_wrong_email(self, client):
        """Login fails with non-existent email."""
        res = login_as(client, 'nobody@test.com', 'password')
        assert res.status_code == 401

    def test_login_missing_fields(self, client):
        """Login fails with missing fields."""
        res = client.post('/api/login',
            data=json.dumps({'email': 'manager@test.com'}),
            content_type='application/json'
        )
        assert res.status_code == 400

    def test_logout(self, client):
        """User can logout successfully."""
        login_as(client, 'manager@test.com', 'manager123')
        res = client.post('/api/logout', content_type='application/json')
        assert res.status_code == 200


# ─────────────────────────────────────────
#  TASK TESTS
# ─────────────────────────────────────────
class TestTasks:

    def test_employee_can_view_own_tasks(self, client):
        """Employee can view their assigned tasks."""
        login_as(client, 'employee@test.com', 'emp123')
        res = client.get('/api/my/tasks')
        assert res.status_code == 200
        data = json.loads(res.data)
        assert 'tasks' in data
        assert 'stats' in data
        assert len(data['tasks']) == 2

    def test_employee_can_create_task(self, client):
        """Employee can create a personal task."""
        login_as(client, 'employee@test.com', 'emp123')
        res = client.post('/api/my/tasks',
            data=json.dumps({
                'title': 'My New Task',
                'due_date': date.today().strftime("%Y-%m-%d"),
                'priority': 'medium',
                'category': 'Personal'
            }),
            content_type='application/json'
        )
        assert res.status_code == 201
        data = json.loads(res.data)
        assert data['title'] == 'My New Task'

    def test_employee_cannot_create_task_without_title(self, client):
        """Task creation fails without required title."""
        login_as(client, 'employee@test.com', 'emp123')
        res = client.post('/api/my/tasks',
            data=json.dumps({'due_date': date.today().strftime("%Y-%m-%d")}),
            content_type='application/json'
        )
        assert res.status_code == 400

    def test_employee_cannot_create_task_without_due_date(self, client):
        """Task creation fails without required due date."""
        login_as(client, 'employee@test.com', 'emp123')
        res = client.post('/api/my/tasks',
            data=json.dumps({'title': 'No Date Task'}),
            content_type='application/json'
        )
        assert res.status_code == 400

    def test_employee_can_mark_task_done(self, client):
        """Employee can mark their task as done."""
        login_as(client, 'employee@test.com', 'emp123')
        res = client.put('/api/my/tasks/task-001',
            data=json.dumps({'status': 'done'}),
            content_type='application/json'
        )
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data['status'] == 'done'

    def test_employee_can_delete_own_task(self, client):
        """Employee can delete their own task."""
        login_as(client, 'employee@test.com', 'emp123')
        res = client.delete('/api/my/tasks/task-001')
        assert res.status_code == 200

    def test_unauthenticated_cannot_access_tasks(self, client):
        """Unauthenticated user cannot access tasks."""
        res = client.get('/api/my/tasks')
        assert res.status_code in [401, 302]


# ─────────────────────────────────────────
#  ROLE ENFORCEMENT TESTS
# ─────────────────────────────────────────
class TestRoleEnforcement:

    def test_employee_cannot_access_manager_api(self, client):
        """Employee cannot access manager-only endpoints."""
        login_as(client, 'employee@test.com', 'emp123')
        res = client.get('/api/manager/tasks')
        assert res.status_code == 403

    def test_employee_cannot_view_all_tasks(self, client):
        """Employee cannot view team tasks."""
        login_as(client, 'employee@test.com', 'emp123')
        res = client.get('/api/manager/employees')
        assert res.status_code == 403

    def test_manager_can_access_all_tasks(self, client):
        """Manager can view all team tasks."""
        login_as(client, 'manager@test.com', 'manager123')
        res = client.get('/api/manager/tasks')
        assert res.status_code == 200

    def test_manager_can_view_employees(self, client):
        """Manager can view all staff members."""
        login_as(client, 'manager@test.com', 'manager123')
        res = client.get('/api/manager/employees')
        assert res.status_code == 200
        data = json.loads(res.data)
        assert len(data['employees']) == 1

    def test_manager_can_assign_task(self, client):
        """Manager can assign a task to an employee."""
        login_as(client, 'manager@test.com', 'manager123')
        res = client.post('/api/manager/tasks',
            data=json.dumps({
                'title': 'Assigned Task',
                'due_date': (date.today() + timedelta(days=3)).strftime("%Y-%m-%d"),
                'priority': 'high',
                'assigned_to': 'emp-001'
            }),
            content_type='application/json'
        )
        assert res.status_code == 201

    def test_manager_can_add_employee(self, client):
        """Manager can add a new staff member."""
        login_as(client, 'manager@test.com', 'manager123')
        res = client.post('/api/manager/employees',
            data=json.dumps({
                'name': 'New Staff',
                'email': 'newstaff@test.com',
                'password': 'staff123'
            }),
            content_type='application/json'
        )
        assert res.status_code == 201

    def test_duplicate_email_rejected(self, client):
        """Adding employee with existing email fails."""
        login_as(client, 'manager@test.com', 'manager123')
        res = client.post('/api/manager/employees',
            data=json.dumps({
                'name': 'Duplicate',
                'email': 'employee@test.com',
                'password': 'pass123'
            }),
            content_type='application/json'
        )
        assert res.status_code == 400


# ─────────────────────────────────────────
#  STATUS AUTO-DETECTION TESTS
# ─────────────────────────────────────────
class TestStatusDetection:

    def test_overdue_task_detected(self, client):
        """Task with past due date is detected as overdue."""
        login_as(client, 'employee@test.com', 'emp123')
        res = client.get('/api/my/tasks')
        data = json.loads(res.data)
        overdue = [t for t in data['tasks'] if t['id'] == 'task-002']
        assert len(overdue) == 1
        assert overdue[0]['status'] == 'overdue'

    def test_today_task_detected_as_inprogress(self, client):
        """Task due today is detected as in progress."""
        login_as(client, 'employee@test.com', 'emp123')
        res = client.get('/api/my/tasks')
        data = json.loads(res.data)
        today_task = [t for t in data['tasks'] if t['id'] == 'task-001']
        assert len(today_task) == 1
        assert today_task[0]['status'] == 'inprogress'

    def test_done_task_stays_done(self, client):
        """Completed task remains done regardless of date."""
        login_as(client, 'employee@test.com', 'emp123')
        client.put('/api/my/tasks/task-002',
            data=json.dumps({'status': 'done'}),
            content_type='application/json'
        )
        res = client.get('/api/my/tasks')
        data = json.loads(res.data)
        done_task = [t for t in data['tasks'] if t['id'] == 'task-002']
        assert done_task[0]['status'] == 'done'


# ─────────────────────────────────────────
#  VALIDATION UNIT TESTS
# ─────────────────────────────────────────
class TestValidation:

    def test_valid_task_passes(self):
        """Valid task data passes validation."""
        valid, errors = validate_task({
            'title': 'Valid Task',
            'due_date': date.today().strftime("%Y-%m-%d"),
            'priority': 'high',
            'category': 'Testing',
            'recurring': 'none'
        })
        assert valid is True
        assert len(errors) == 0

    def test_missing_title_fails(self):
        """Task without title fails validation."""
        valid, errors = validate_task({'due_date': date.today().strftime("%Y-%m-%d")})
        assert valid is False
        assert any('Title' in e for e in errors)

    def test_invalid_priority_fails(self):
        """Task with invalid priority fails validation."""
        valid, errors = validate_task({
            'title': 'Task', 'due_date': date.today().strftime("%Y-%m-%d"),
            'priority': 'super-urgent'
        })
        assert valid is False
        assert any('Priority' in e for e in errors)

    def test_invalid_date_format_fails(self):
        """Task with wrong date format fails validation."""
        valid, errors = validate_task({'title': 'Task', 'due_date': '21/03/2026'})
        assert valid is False
        assert any('date' in e.lower() for e in errors)

    def test_title_too_long_fails(self):
        """Task with title over 200 chars fails validation."""
        valid, errors = validate_task({
            'title': 'x' * 201,
            'due_date': date.today().strftime("%Y-%m-%d")
        })
        assert valid is False

    def test_valid_user_passes(self):
        """Valid user data passes validation."""
        valid, errors = validate_user_data({
            'name': 'John Doe',
            'email': 'john@bank.com',
            'password': 'secure123'
        })
        assert valid is True

    def test_invalid_email_fails(self):
        """User with invalid email fails validation."""
        valid, errors = validate_user_data({
            'name': 'John', 'email': 'notanemail', 'password': 'pass123'
        })
        assert valid is False
        assert any('email' in e.lower() for e in errors)

    def test_short_password_fails(self):
        """User with too-short password fails validation."""
        valid, errors = validate_user_data({
            'name': 'John', 'email': 'john@bank.com', 'password': 'ab'
        })
        assert valid is False
