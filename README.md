# TaskFlow — Python Flask Task Tracker

A fully automated task tracker built with Python (Flask) that runs in your browser.

## 🚀 Setup & Run

### 1. Install dependencies
```bash
pip install flask
```

### 2. Run the app
```bash
cd task_tracker
python app.py
```

### 3. Open in browser
Visit: http://localhost:5000

---

## ✨ Features

- **Kanban Board** — 4 columns: To Do, In Progress, Done, Overdue
- **Auto Status Detection** — Tasks auto-move to "In Progress" if due today, "Overdue" if past due
- **Drag & Drop** — Move tasks between columns manually
- **Priority System** — High / Medium / Low with color-coded badges
- **Recurring Tasks** — Daily / Weekly / Monthly auto-regeneration
- **Smart Notifications** — Banner shows overdue and today's tasks
- **Dashboard Stats** — Total, Completed, Overdue, Due Today, Upcoming
- **Edit & Delete** — Full CRUD operations
- **Auto-Refresh** — Board refreshes every 60 seconds

## 📁 Project Structure
```
task_tracker/
├── app.py              # Flask backend (Python)
├── requirements.txt    # Dependencies
└── templates/
    └── index.html      # Frontend (HTML/CSS/JS)
```
