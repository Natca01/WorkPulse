from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from datetime import datetime, date, timedelta
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import uuid

app = Flask(__name__)
app.secret_key = "taskflow-secret-key-2025"

# ─────────────────────────────────────────
#  IN-MEMORY DATA STORE
# ─────────────────────────────────────────
users = {}       # user_id -> user dict
tasks = {}       # task_id -> task dict
activity_log = []

def log(action, title, task_id=None, user_id=None):
    activity_log.insert(0, {
        "id": str(uuid.uuid4()),
        "action": action,
        "task_title": title,
        "task_id": task_id,
        "user_id": user_id,
        "timestamp": datetime.now().isoformat(),
        "time_label": datetime.now().strftime("%b %d, %H:%M")
    })
    if len(activity_log) > 100:
        activity_log.pop()

# ─────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────
def get_status(due_str, current):
    if current == "done":
        return "done"
    today = date.today()
    try:
        due = datetime.strptime(due_str, "%Y-%m-%d").date()
        if due < today:   return "overdue"
        if due == today:  return "inprogress"
        return current if current in ("todo","inprogress") else "todo"
    except:
        return current

def due_label(due_str):
    try:
        diff = (datetime.strptime(due_str, "%Y-%m-%d").date() - date.today()).days
        if diff < 0:   return f"Overdue by {abs(diff)}d"
        if diff == 0:  return "Due Today"
        if diff == 1:  return "Due Tomorrow"
        return f"Due in {diff}d"
    except:
        return ""

def task_dict(t):
    d = dict(t)
    if d["status"] != "done":
        d["status"] = get_status(d["due_date"], d["status"])
    d["due_label"] = due_label(d["due_date"])
    u = users.get(d.get("assigned_to",""))
    d["assigned_name"] = u["name"] if u else "Unassigned"
    return d

def stats_for(task_list):
    total = len(task_list)
    done  = sum(1 for t in task_list if t["status"] == "done")
    over  = sum(1 for t in task_list if t["status"] == "overdue")
    inp   = sum(1 for t in task_list if t["status"] == "inprogress")
    todo  = sum(1 for t in task_list if t["status"] == "todo")
    pct   = round(done/total*100) if total else 0
    return {"total":total,"done":done,"overdue":over,"inprogress":inp,"todo":todo,"completion_pct":pct}

def require_login(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)
    return decorated

def require_manager(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"error":"Unauthorized"}), 401
        if users.get(session["user_id"],{}).get("role") != "manager":
            return jsonify({"error":"Forbidden"}), 403
        return f(*args, **kwargs)
    return decorated

def current_user():
    return users.get(session.get("user_id"))

# ─────────────────────────────────────────
#  SEED DATA
# ─────────────────────────────────────────
def seed():
    today = date.today()

    # Manager
    mid = str(uuid.uuid4())
    users[mid] = {"id":mid,"name":"Alex Manager","email":"manager@taskflow.com",
                  "password":generate_password_hash("manager123"),
                  "role":"manager","created_at":datetime.now().isoformat()}

    # Employees
    emp_data = [
        ("Sara Khan",    "sara@taskflow.com",    "emp123"),
        ("Ravi Sharma",  "ravi@taskflow.com",    "emp123"),
        ("Priya Singh",  "priya@taskflow.com",   "emp123"),
        ("Omar Farooq",  "omar@taskflow.com",    "emp123"),
    ]
    emp_ids = []
    for name, email, pwd in emp_data:
        eid = str(uuid.uuid4())
        users[eid] = {"id":eid,"name":name,"email":email,
                      "password":generate_password_hash(pwd),
                      "role":"employee","created_at":datetime.now().isoformat()}
        emp_ids.append(eid)

    # Tasks per employee
    sample_tasks = [
        # Sara
        {"title":"Design login UI","desc":"Create Figma mockups for the new login flow","priority":"high","due":(today-timedelta(days=1)).strftime("%Y-%m-%d"),"cat":"Design","rec":"none","status":"todo","emp":0},
        {"title":"Implement dark mode","desc":"Add dark/light toggle to settings page","priority":"medium","due":today.strftime("%Y-%m-%d"),"cat":"Frontend","rec":"none","status":"done","emp":0},
        {"title":"Weekly design review","desc":"Present new designs to the team","priority":"low","due":(today+timedelta(days=3)).strftime("%Y-%m-%d"),"cat":"Meetings","rec":"weekly","status":"todo","emp":0},
        # Ravi
        {"title":"Fix API rate limiter","desc":"Patch the rate limiter bug in production","priority":"high","due":(today-timedelta(days=2)).strftime("%Y-%m-%d"),"cat":"Backend","rec":"none","status":"todo","emp":1},
        {"title":"Write migration scripts","desc":"DB migration for v2.1 schema changes","priority":"medium","due":today.strftime("%Y-%m-%d"),"cat":"Database","rec":"none","status":"inprogress","emp":1},
        {"title":"Code review PRs","desc":"Review open pull requests from teammates","priority":"low","due":today.strftime("%Y-%m-%d"),"cat":"Dev","rec":"daily","status":"todo","emp":1},
        # Priya
        {"title":"Unit test auth module","desc":"Achieve 90% coverage on auth service","priority":"high","due":(today+timedelta(days=1)).strftime("%Y-%m-%d"),"cat":"Testing","rec":"none","status":"todo","emp":2},
        {"title":"Update Swagger docs","desc":"Document all new v2 API endpoints","priority":"medium","due":(today+timedelta(days=4)).strftime("%Y-%m-%d"),"cat":"Docs","rec":"none","status":"done","emp":2},
        # Omar
        {"title":"Setup CI/CD pipeline","desc":"Configure GitHub Actions for auto-deploy","priority":"high","due":(today-timedelta(days=1)).strftime("%Y-%m-%d"),"cat":"DevOps","rec":"none","status":"done","emp":3},
        {"title":"Monitor server metrics","desc":"Check CPU/memory dashboards daily","priority":"medium","due":today.strftime("%Y-%m-%d"),"cat":"DevOps","rec":"daily","status":"todo","emp":3},
        {"title":"Update SSL certificates","desc":"Renew certs before they expire","priority":"high","due":(today+timedelta(days=5)).strftime("%Y-%m-%d"),"cat":"Security","rec":"none","status":"todo","emp":3},
    ]

    for s in sample_tasks:
        tid = str(uuid.uuid4())
        assigned = emp_ids[s["emp"]]
        status = get_status(s["due"], s["status"])
        tasks[tid] = {"id":tid,"title":s["title"],"description":s["desc"],
                      "priority":s["priority"],"due_date":s["due"],
                      "category":s["cat"],"recurring":s["rec"],
                      "status":status,"assigned_to":assigned,
                      "created_by":mid,"created_at":datetime.now().isoformat()}
        log("created", s["title"], tid, mid)

seed()

# ─────────────────────────────────────────
#  AUTH ROUTES
# ─────────────────────────────────────────
@app.route("/")
def root():
    if "user_id" in session:
        u = current_user()
        if u:
            return redirect(url_for("manager_page") if u["role"]=="manager" else url_for("employee_page"))
    return redirect(url_for("login_page"))

@app.route("/login", methods=["GET"])
def login_page():
    return render_template("login.html")

@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.json
    email = data.get("email","").strip().lower()
    pwd   = data.get("password","")
    user  = next((u for u in users.values() if u["email"].lower()==email), None)
    if not user or not check_password_hash(user["password"], pwd):
        return jsonify({"error":"Invalid email or password"}), 401
    session["user_id"] = user["id"]
    return jsonify({"role": user["role"], "name": user["name"]})

@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"ok": True})

@app.route("/manager")
@require_login
def manager_page():
    u = current_user()
    if u["role"] != "manager":
        return redirect(url_for("employee_page"))
    return render_template("manager.html", user=u)

@app.route("/employee")
@require_login
def employee_page():
    u = current_user()
    if u["role"] == "manager":
        return redirect(url_for("manager_page"))
    return render_template("employee.html", user=u)

# ─────────────────────────────────────────
#  EMPLOYEE API
# ─────────────────────────────────────────
@app.route("/api/my/tasks", methods=["GET"])
@require_login
def my_tasks():
    uid = session["user_id"]
    my = [task_dict(t) for t in tasks.values() if t["assigned_to"] == uid]
    priority_order = {"high":0,"medium":1,"low":2}
    my.sort(key=lambda x: priority_order.get(x["priority"],3))
    return jsonify({"tasks": my, "stats": stats_for(my)})

@app.route("/api/my/tasks", methods=["POST"])
@require_login
def create_my_task():
    uid = session["user_id"]
    if users[uid]["role"] == "manager":
        return jsonify({"error":"Managers assign tasks, not create them here"}), 403
    data = request.json
    tid = str(uuid.uuid4())
    status = get_status(data["due_date"], "todo")
    tasks[tid] = {"id":tid,"title":data["title"],"description":data.get("description",""),
                  "priority":data.get("priority","medium"),"due_date":data["due_date"],
                  "category":data.get("category","General"),"recurring":data.get("recurring","none"),
                  "status":status,"assigned_to":uid,"created_by":uid,
                  "created_at":datetime.now().isoformat()}
    log("created", data["title"], tid, uid)
    return jsonify(task_dict(tasks[tid])), 201

@app.route("/api/my/tasks/<tid>", methods=["PUT"])
@require_login
def update_my_task(tid):
    uid = session["user_id"]
    t = tasks.get(tid)
    if not t:
        return jsonify({"error":"Not found"}), 404
    # Employee can only update their own tasks
    if users[uid]["role"] == "employee" and t["assigned_to"] != uid:
        return jsonify({"error":"Forbidden"}), 403
    data = request.json
    for k in ("title","description","priority","due_date","category","recurring"):
        if k in data:
            t[k] = data[k]
    if "status" in data:
        t["status"] = data["status"]
        if data["status"] == "done":
            log("completed", t["title"], tid, uid)
            if t["recurring"] != "none":
                old = datetime.strptime(t["due_date"],"%Y-%m-%d").date()
                delta = {"daily":timedelta(days=1),"weekly":timedelta(weeks=1)}.get(t["recurring"])
                if t["recurring"] == "monthly":
                    m = old.month%12+1; y = old.year+(1 if old.month==12 else 0)
                    new_due = old.replace(year=y,month=m)
                else:
                    new_due = old + delta
                new_id = str(uuid.uuid4())
                tasks[new_id] = {**t,"id":new_id,"status":"todo","due_date":new_due.strftime("%Y-%m-%d"),"created_at":datetime.now().isoformat()}
                log("auto-created (recurring)", t["title"], new_id, uid)
        else:
            log(f"moved to {data['status']}", t["title"], tid, uid)
    else:
        t["status"] = get_status(t["due_date"], t["status"])
        log("updated", t["title"], tid, uid)
    return jsonify(task_dict(t))

@app.route("/api/my/tasks/<tid>", methods=["DELETE"])
@require_login
def delete_my_task(tid):
    uid = session["user_id"]
    t = tasks.get(tid)
    if not t:
        return jsonify({"error":"Not found"}), 404
    if users[uid]["role"] == "employee" and t["assigned_to"] != uid:
        return jsonify({"error":"Forbidden"}), 403
    log("deleted", t["title"], tid, uid)
    del tasks[tid]
    return jsonify({"ok": True})

@app.route("/api/my/dashboard", methods=["GET"])
@require_login
def my_dashboard():
    uid = session["user_id"]
    my = [task_dict(t) for t in tasks.values() if t["assigned_to"] == uid]
    s = stats_for(my)
    pb = {"high":0,"medium":0,"low":0}
    for t in my: pb[t["priority"]] = pb.get(t["priority"],0)+1
    cat_map = {}
    for t in my:
        c = t["category"] or "General"
        if c not in cat_map: cat_map[c] = {"total":0,"done":0,"overdue":0,"inprogress":0,"todo":0}
        cat_map[c]["total"] += 1
        cat_map[c][t["status"]] = cat_map[c].get(t["status"],0)+1
    today = date.today()
    upcoming = []
    for i in range(7):
        d = today+timedelta(days=i)
        cnt = sum(1 for t in my if t["due_date"]==d.strftime("%Y-%m-%d") and t["status"]!="done")
        upcoming.append({"label":d.strftime("%a"),"count":cnt})
    score = 0
    if s["total"] > 0:
        score += (s["done"]/s["total"])*50
        score -= (s["overdue"]/s["total"])*30
        score += min(s["done"]*5, 40)
        score = max(0, min(100, round(score)))
    my_log = [a for a in activity_log if a.get("user_id")==uid][:15]
    return jsonify({"overview":{**s,"productivity_score":score},"priority_breakdown":pb,
                    "categories":[{"name":k,**v} for k,v in cat_map.items()],
                    "upcoming_days":upcoming,"activity_log":my_log})

# ─────────────────────────────────────────
#  MANAGER API
# ─────────────────────────────────────────
@app.route("/api/manager/employees", methods=["GET"])
@require_manager
def get_employees():
    emps = [{"id":u["id"],"name":u["name"],"email":u["email"],"created_at":u["created_at"]}
            for u in users.values() if u["role"]=="employee"]
    return jsonify({"employees": emps})

@app.route("/api/manager/employees", methods=["POST"])
@require_manager
def add_employee():
    data = request.json
    email = data.get("email","").strip().lower()
    if any(u["email"].lower()==email for u in users.values()):
        return jsonify({"error":"Email already exists"}), 400
    eid = str(uuid.uuid4())
    users[eid] = {"id":eid,"name":data["name"],"email":email,
                  "password":generate_password_hash(data.get("password","emp123")),
                  "role":"employee","created_at":datetime.now().isoformat()}
    log("employee added", data["name"], None, session["user_id"])
    return jsonify({"id":eid,"name":data["name"],"email":email}), 201

@app.route("/api/manager/employees/<eid>", methods=["DELETE"])
@require_manager
def remove_employee(eid):
    if eid not in users or users[eid]["role"]=="manager":
        return jsonify({"error":"Not found"}), 404
    name = users[eid]["name"]
    del users[eid]
    # Remove their tasks too
    to_del = [tid for tid,t in tasks.items() if t["assigned_to"]==eid]
    for tid in to_del: del tasks[tid]
    log("employee removed", name, None, session["user_id"])
    return jsonify({"ok": True})

@app.route("/api/manager/tasks", methods=["GET"])
@require_manager
def all_tasks():
    emp_id = request.args.get("emp_id")
    tlist = [task_dict(t) for t in tasks.values()
             if (not emp_id or t["assigned_to"]==emp_id)]
    priority_order = {"high":0,"medium":1,"low":2}
    tlist.sort(key=lambda x: priority_order.get(x["priority"],3))
    return jsonify({"tasks": tlist, "stats": stats_for(tlist)})

@app.route("/api/manager/tasks", methods=["POST"])
@require_manager
def assign_task():
    data = request.json
    uid = session["user_id"]
    assigned_to = data.get("assigned_to","")
    if assigned_to not in users:
        return jsonify({"error":"Employee not found"}), 404
    tid = str(uuid.uuid4())
    status = get_status(data["due_date"], "todo")
    tasks[tid] = {"id":tid,"title":data["title"],"description":data.get("description",""),
                  "priority":data.get("priority","medium"),"due_date":data["due_date"],
                  "category":data.get("category","General"),"recurring":data.get("recurring","none"),
                  "status":status,"assigned_to":assigned_to,"created_by":uid,
                  "created_at":datetime.now().isoformat()}
    log(f"assigned to {users[assigned_to]['name']}", data["title"], tid, uid)
    return jsonify(task_dict(tasks[tid])), 201

@app.route("/api/manager/tasks/<tid>", methods=["PUT"])
@require_manager
def update_any_task(tid):
    t = tasks.get(tid)
    if not t: return jsonify({"error":"Not found"}), 404
    data = request.json
    for k in ("title","description","priority","due_date","category","recurring","assigned_to"):
        if k in data: t[k] = data[k]
    if "status" in data:
        t["status"] = data["status"]
        log(f"status → {data['status']}", t["title"], tid, session["user_id"])
    else:
        t["status"] = get_status(t["due_date"], t["status"])
        log("updated", t["title"], tid, session["user_id"])
    return jsonify(task_dict(t))

@app.route("/api/manager/tasks/<tid>", methods=["DELETE"])
@require_manager
def delete_any_task(tid):
    t = tasks.get(tid)
    if not t: return jsonify({"error":"Not found"}), 404
    log("deleted", t["title"], tid, session["user_id"])
    del tasks[tid]
    return jsonify({"ok": True})

@app.route("/api/manager/dashboard", methods=["GET"])
@require_manager
def manager_dashboard():
    all_t = [task_dict(t) for t in tasks.values()]
    s = stats_for(all_t)
    # Per-employee stats
    emp_stats = []
    for u in users.values():
        if u["role"] != "employee": continue
        et = [task_dict(t) for t in tasks.values() if t["assigned_to"]==u["id"]]
        es = stats_for(et)
        score = 0
        if es["total"] > 0:
            score += (es["done"]/es["total"])*50
            score -= (es["overdue"]/es["total"])*30
            score += min(es["done"]*5, 40)
            score = max(0, min(100, round(score)))
        emp_stats.append({"id":u["id"],"name":u["name"],"email":u["email"],**es,"score":score})
    emp_stats.sort(key=lambda x: -x["score"])
    pb = {"high":0,"medium":0,"low":0}
    for t in all_t: pb[t["priority"]] = pb.get(t["priority"],0)+1
    today = date.today()
    upcoming = []
    for i in range(7):
        d = today+timedelta(days=i)
        cnt = sum(1 for t in all_t if t["due_date"]==d.strftime("%Y-%m-%d") and t["status"]!="done")
        upcoming.append({"label":d.strftime("%a"),"count":cnt})
    return jsonify({"overview":s,"employee_stats":emp_stats,"priority_breakdown":pb,
                    "upcoming_days":upcoming,"activity_log":activity_log[:20]})

if __name__ == "__main__":
    app.run(debug=True, port=5000)
