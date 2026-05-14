"""
api/routes.py
FastAPI routes for Teacher and Student web dashboards.
Serves HTML pages and JSON data endpoints.
"""

from datetime import datetime
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

from db.session import db_session
from db.models import User, Assignment, Submission, Feedback, ProgressUpdate, TeacherStudent

app = FastAPI(title="Classroom Companion API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def format_dt(dt: datetime | None) -> str:
    if not dt:
        return "—"
    return dt.strftime("%d %b %Y, %H:%M")


def time_ago(dt: datetime | None) -> str:
    if not dt:
        return "—"
    diff = datetime.utcnow() - dt
    if diff.days > 0:
        return f"{diff.days}d ago"
    hours = diff.seconds // 3600
    if hours > 0:
        return f"{hours}h ago"
    mins = diff.seconds // 60
    return f"{mins}m ago"


# ---------------------------------------------------------------------------
# JSON API endpoints
# ---------------------------------------------------------------------------

@app.get("/api/teacher/{telegram_id}")
def get_teacher_data(telegram_id: int):
    with db_session() as db:
        teacher = db.query(User).filter_by(telegram_id=telegram_id, role="teacher").first()
        if not teacher:
            raise HTTPException(status_code=404, detail="Teacher not found")

        links = db.query(TeacherStudent).filter_by(teacher_id=teacher.id).all()
        students_data = []

        for link in links:
            student = link.student
            assignments = db.query(Assignment).filter_by(
                teacher_id=teacher.id,
                student_id=student.id
            ).order_by(Assignment.created_at.desc()).all()

            assignments_data = []
            for a in assignments:
                last_update = (
                    db.query(ProgressUpdate)
                    .filter_by(assignment_id=a.id)
                    .order_by(ProgressUpdate.created_at.desc())
                    .first()
                )
                submission = (
                    db.query(Submission)
                    .filter_by(assignment_id=a.id)
                    .first()
                )
                feedback = None
                if submission:
                    feedback = db.query(Feedback).filter_by(
                        submission_id=submission.id
                    ).first()

                assignments_data.append({
                    "id": a.id,
                    "title": a.title or "Assignment",
                    "description": a.description,
                    "status": a.status,
                    "due_date": format_dt(a.due_date),
                    "created_at": format_dt(a.created_at),
                    "is_overdue": a.is_overdue,
                    "last_update": last_update.notes if last_update else None,
                    "last_update_time": time_ago(last_update.created_at) if last_update else None,
                    "has_submission": submission is not None,
                    "has_feedback": feedback is not None,
                })

            students_data.append({
                "id": student.id,
                "name": student.full_name or student.telegram_handle or "Unknown",
                "handle": f"@{student.telegram_handle}" if student.telegram_handle else "—",
                "assignments": assignments_data,
                "total": len(assignments_data),
                "pending": sum(1 for a in assignments_data if a["status"] == "pending"),
                "in_progress": sum(1 for a in assignments_data if a["status"] == "in_progress"),
                "submitted": sum(1 for a in assignments_data if a["status"] == "submitted"),
                "reviewed": sum(1 for a in assignments_data if a["status"] == "reviewed"),
            })

        return {
            "teacher": {
                "name": teacher.full_name or teacher.telegram_handle or "Teacher",
                "handle": f"@{teacher.telegram_handle}" if teacher.telegram_handle else "—",
            },
            "students": students_data,
            "total_students": len(students_data),
            "total_assignments": sum(s["total"] for s in students_data),
        }


@app.get("/api/student/{telegram_id}")
def get_student_data(telegram_id: int):
    with db_session() as db:
        student = db.query(User).filter_by(telegram_id=telegram_id, role="student").first()
        if not student:
            raise HTTPException(status_code=404, detail="Student not found")

        assignments = db.query(Assignment).filter_by(
            student_id=student.id
        ).order_by(Assignment.due_date.asc()).all()

        assignments_data = []
        for a in assignments:
            updates = (
                db.query(ProgressUpdate)
                .filter_by(assignment_id=a.id)
                .order_by(ProgressUpdate.created_at.desc())
                .limit(5)
                .all()
            )
            submission = db.query(Submission).filter_by(assignment_id=a.id).first()
            feedback = None
            if submission:
                feedback = db.query(Feedback).filter_by(submission_id=submission.id).first()

            assignments_data.append({
                "id": a.id,
                "title": a.title or "Assignment",
                "description": a.description,
                "status": a.status,
                "due_date": format_dt(a.due_date),
                "is_overdue": a.is_overdue,
                "updates": [
                    {
                        "status": u.interpreted_status,
                        "notes": u.notes,
                        "time": time_ago(u.created_at),
                    }
                    for u in updates
                ],
                "submission": {
                    "type": submission.submission_type,
                    "submitted_at": format_dt(submission.submitted_at),
                } if submission else None,
                "feedback": feedback.formatted_feedback if feedback else None,
            })

        link = db.query(TeacherStudent).filter_by(student_id=student.id).first()
        teacher_name = None
        if link:
            teacher_name = link.teacher.full_name or link.teacher.telegram_handle

        return {
            "student": {
                "name": student.full_name or student.telegram_handle or "Student",
                "handle": f"@{student.telegram_handle}" if student.telegram_handle else "—",
                "teacher": teacher_name or "—",
            },
            "assignments": assignments_data,
            "total": len(assignments_data),
            "pending": sum(1 for a in assignments_data if a["status"] == "pending"),
            "in_progress": sum(1 for a in assignments_data if a["status"] == "in_progress"),
            "submitted": sum(1 for a in assignments_data if a["status"] == "submitted"),
            "reviewed": sum(1 for a in assignments_data if a["status"] == "reviewed"),
        }


# ---------------------------------------------------------------------------
# Teacher Dashboard HTML
# ---------------------------------------------------------------------------

@app.get("/teacher/{telegram_id}", response_class=HTMLResponse)
def teacher_dashboard(telegram_id: int):
    return HTMLResponse(content=TEACHER_HTML.replace("{{TELEGRAM_ID}}", str(telegram_id)))


# ---------------------------------------------------------------------------
# Student Dashboard HTML
# ---------------------------------------------------------------------------

@app.get("/student/{telegram_id}", response_class=HTMLResponse)
def student_dashboard(telegram_id: int):
    return HTMLResponse(content=STUDENT_HTML.replace("{{TELEGRAM_ID}}", str(telegram_id)))


# ---------------------------------------------------------------------------
# Root — instructions page
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def root():
    return HTMLResponse(content="""
    <html><body style="font-family:monospace;padding:2rem;background:#0f0f0f;color:#e0e0e0">
    <h2>Classroom Companion API</h2>
    <p>Teacher Dashboard: <a href="/teacher/YOUR_TELEGRAM_ID" style="color:#4ade80">/teacher/{telegram_id}</a></p>
    <p>Student Dashboard: <a href="/student/YOUR_TELEGRAM_ID" style="color:#60a5fa">/student/{telegram_id}</a></p>
    <p>API Docs: <a href="/docs" style="color:#f472b6">/docs</a></p>
    </body></html>
    """)


# ---------------------------------------------------------------------------
# Teacher HTML Template
# ---------------------------------------------------------------------------

TEACHER_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Classroom Companion — Teacher</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Mono:wght@400;500&family=DM+Sans:wght@300;400;500&display=swap" rel="stylesheet">
<style>
  :root {
    --bg: #0a0a0f;
    --surface: #13131a;
    --surface2: #1c1c26;
    --border: #2a2a38;
    --accent: #7c6af7;
    --accent2: #a78bfa;
    --green: #34d399;
    --amber: #fbbf24;
    --red: #f87171;
    --blue: #60a5fa;
    --text: #e8e8f0;
    --muted: #6b6b80;
    --subtle: #3a3a4a;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: 'DM Sans', sans-serif;
    min-height: 100vh;
    font-size: 14px;
  }
  .noise {
    position: fixed; inset: 0; pointer-events: none; z-index: 0;
    background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)' opacity='0.03'/%3E%3C/svg%3E");
  }
  .glow {
    position: fixed; top: -200px; left: 50%; transform: translateX(-50%);
    width: 600px; height: 400px;
    background: radial-gradient(ellipse, rgba(124,106,247,0.12) 0%, transparent 70%);
    pointer-events: none; z-index: 0;
  }
  .container { max-width: 1100px; margin: 0 auto; padding: 2rem; position: relative; z-index: 1; }

  header {
    display: flex; align-items: flex-end; justify-content: space-between;
    padding-bottom: 2rem; border-bottom: 1px solid var(--border);
    margin-bottom: 2.5rem;
    animation: fadeDown 0.6s ease both;
  }
  .logo { display: flex; flex-direction: column; gap: 4px; }
  .logo-tag {
    font-family: 'DM Mono', monospace; font-size: 10px;
    color: var(--accent2); letter-spacing: 3px; text-transform: uppercase;
  }
  .logo-title {
    font-family: 'DM Serif Display', serif; font-size: 28px;
    color: var(--text); line-height: 1;
  }
  .teacher-badge {
    background: linear-gradient(135deg, var(--accent), var(--accent2));
    padding: 6px 14px; border-radius: 20px;
    font-size: 12px; font-weight: 500; color: white;
    font-family: 'DM Mono', monospace; letter-spacing: 1px;
  }

  .stats-row {
    display: grid; grid-template-columns: repeat(4, 1fr); gap: 1rem;
    margin-bottom: 2.5rem;
    animation: fadeUp 0.6s ease 0.1s both;
  }
  .stat-card {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 12px; padding: 1.25rem;
    display: flex; flex-direction: column; gap: 6px;
    transition: border-color 0.2s, transform 0.2s;
  }
  .stat-card:hover { border-color: var(--accent); transform: translateY(-2px); }
  .stat-label { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 1.5px; font-family: 'DM Mono', monospace; }
  .stat-value { font-family: 'DM Serif Display', serif; font-size: 32px; color: var(--text); }
  .stat-value.green { color: var(--green); }
  .stat-value.amber { color: var(--amber); }
  .stat-value.blue { color: var(--blue); }

  .section-title {
    font-family: 'DM Serif Display', serif; font-size: 20px;
    color: var(--text); margin-bottom: 1.25rem;
    display: flex; align-items: center; gap: 10px;
  }
  .section-title::after {
    content: ''; flex: 1; height: 1px; background: var(--border);
  }

  .student-card {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 14px; margin-bottom: 1.5rem; overflow: hidden;
    animation: fadeUp 0.5s ease both;
    transition: border-color 0.2s;
  }
  .student-card:hover { border-color: var(--subtle); }

  .student-header {
    padding: 1.25rem 1.5rem;
    display: flex; align-items: center; justify-content: space-between;
    cursor: pointer; user-select: none;
    background: var(--surface2);
  }
  .student-info { display: flex; align-items: center; gap: 12px; }
  .avatar {
    width: 40px; height: 40px; border-radius: 50%;
    background: linear-gradient(135deg, var(--accent), var(--accent2));
    display: flex; align-items: center; justify-content: center;
    font-family: 'DM Serif Display', serif; font-size: 16px; color: white;
    flex-shrink: 0;
  }
  .student-name { font-weight: 500; font-size: 15px; }
  .student-handle { font-family: 'DM Mono', monospace; font-size: 11px; color: var(--muted); }
  .student-meta { display: flex; gap: 8px; align-items: center; }

  .pill {
    padding: 3px 10px; border-radius: 20px; font-size: 11px;
    font-family: 'DM Mono', monospace; font-weight: 500;
  }
  .pill-purple { background: rgba(124,106,247,0.15); color: var(--accent2); border: 1px solid rgba(124,106,247,0.3); }
  .pill-green { background: rgba(52,211,153,0.12); color: var(--green); border: 1px solid rgba(52,211,153,0.25); }
  .pill-amber { background: rgba(251,191,36,0.12); color: var(--amber); border: 1px solid rgba(251,191,36,0.25); }
  .pill-red { background: rgba(248,113,113,0.12); color: var(--red); border: 1px solid rgba(248,113,113,0.25); }
  .pill-blue { background: rgba(96,165,250,0.12); color: var(--blue); border: 1px solid rgba(96,165,250,0.25); }
  .pill-gray { background: rgba(107,107,128,0.15); color: var(--muted); border: 1px solid rgba(107,107,128,0.2); }

  .chevron { color: var(--muted); transition: transform 0.3s; font-size: 18px; }
  .chevron.open { transform: rotate(180deg); }

  .assignments-list { padding: 0 1.5rem 1.25rem; display: none; }
  .assignments-list.open { display: block; }

  .assignment-row {
    padding: 1rem 0; border-top: 1px solid var(--border);
    display: grid; grid-template-columns: 1fr auto; gap: 1rem; align-items: start;
  }
  .assignment-title { font-weight: 500; margin-bottom: 4px; font-size: 14px; }
  .assignment-desc { color: var(--muted); font-size: 12px; line-height: 1.5; margin-bottom: 8px; }
  .assignment-meta { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
  .meta-item { font-family: 'DM Mono', monospace; font-size: 11px; color: var(--muted); }

  .update-bubble {
    background: var(--surface2); border: 1px solid var(--border);
    border-radius: 8px; padding: 8px 12px; margin-top: 8px;
    font-size: 12px; color: var(--muted); max-width: 500px;
    font-style: italic; line-height: 1.4;
  }

  .no-students {
    text-align: center; padding: 4rem 2rem;
    color: var(--muted); font-family: 'DM Serif Display', serif;
    font-size: 18px; font-style: italic;
  }

  .loading {
    display: flex; align-items: center; justify-content: center;
    height: 300px; flex-direction: column; gap: 16px;
  }
  .spinner {
    width: 40px; height: 40px; border: 2px solid var(--border);
    border-top-color: var(--accent); border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }
  .loading-text { color: var(--muted); font-family: 'DM Mono', monospace; font-size: 12px; }

  .error-box {
    background: rgba(248,113,113,0.08); border: 1px solid rgba(248,113,113,0.2);
    border-radius: 12px; padding: 1.5rem; color: var(--red);
    font-family: 'DM Mono', monospace; font-size: 12px; text-align: center;
  }

  .refresh-btn {
    background: var(--surface2); border: 1px solid var(--border);
    color: var(--muted); padding: 6px 14px; border-radius: 8px;
    font-family: 'DM Mono', monospace; font-size: 11px; cursor: pointer;
    transition: all 0.2s; letter-spacing: 1px;
  }
  .refresh-btn:hover { border-color: var(--accent); color: var(--accent2); }

  @keyframes fadeDown { from { opacity:0; transform:translateY(-16px); } to { opacity:1; transform:translateY(0); } }
  @keyframes fadeUp { from { opacity:0; transform:translateY(16px); } to { opacity:1; transform:translateY(0); } }
  @keyframes spin { to { transform: rotate(360deg); } }
</style>
</head>
<body>
<div class="noise"></div>
<div class="glow"></div>
<div class="container">
  <header>
    <div class="logo">
      <span class="logo-tag">Classroom Companion</span>
      <span class="logo-title">Teacher Dashboard</span>
    </div>
    <div style="display:flex;align-items:center;gap:12px">
      <button class="refresh-btn" onclick="loadData()">↻ Refresh</button>
      <span class="teacher-badge" id="teacher-name">Loading...</span>
    </div>
  </header>

  <div id="stats-row" class="stats-row" style="display:none">
    <div class="stat-card">
      <span class="stat-label">Students</span>
      <span class="stat-value" id="stat-students">—</span>
    </div>
    <div class="stat-card">
      <span class="stat-label">Assignments</span>
      <span class="stat-value blue" id="stat-total">—</span>
    </div>
    <div class="stat-card">
      <span class="stat-label">In Progress</span>
      <span class="stat-value amber" id="stat-progress">—</span>
    </div>
    <div class="stat-card">
      <span class="stat-label">Completed</span>
      <span class="stat-value green" id="stat-done">—</span>
    </div>
  </div>

  <div id="main-content">
    <div class="loading">
      <div class="spinner"></div>
      <span class="loading-text">Loading dashboard...</span>
    </div>
  </div>
</div>

<script>
const TELEGRAM_ID = {{TELEGRAM_ID}};

async function loadData() {
  const content = document.getElementById('main-content');
  content.innerHTML = '<div class="loading"><div class="spinner"></div><span class="loading-text">Refreshing...</span></div>';
  try {
    const res = await fetch(`/api/teacher/${TELEGRAM_ID}`);
    if (!res.ok) throw new Error('Teacher not found. Make sure you have registered with the bot first.');
    const data = await res.json();
    render(data);
  } catch(e) {
    content.innerHTML = `<div class="error-box">⚠ ${e.message}</div>`;
  }
}

function statusPill(status, isOverdue) {
  if (isOverdue) return '<span class="pill pill-red">Overdue</span>';
  const map = {
    pending: '<span class="pill pill-gray">Pending</span>',
    in_progress: '<span class="pill pill-amber">In Progress</span>',
    submitted: '<span class="pill pill-blue">Submitted</span>',
    reviewed: '<span class="pill pill-green">Reviewed</span>',
  };
  return map[status] || `<span class="pill pill-gray">${status}</span>`;
}

function render(data) {
  document.getElementById('teacher-name').textContent = data.teacher.name;
  document.getElementById('stats-row').style.display = 'grid';
  document.getElementById('stat-students').textContent = data.total_students;
  document.getElementById('stat-total').textContent = data.total_assignments;

  let inProgress = 0, done = 0;
  data.students.forEach(s => { inProgress += s.in_progress; done += s.reviewed + s.submitted; });
  document.getElementById('stat-progress').textContent = inProgress;
  document.getElementById('stat-done').textContent = done;

  if (data.students.length === 0) {
    document.getElementById('main-content').innerHTML = `
      <div class="no-students">No students linked yet.<br><small style="font-size:14px;font-family:'DM Sans';color:var(--muted)">Use /invite in the bot to add students.</small></div>`;
    return;
  }

  let html = `<div class="section-title">Students & Assignments</div>`;

  data.students.forEach((s, i) => {
    const initials = s.name.split(' ').map(w => w[0]).join('').toUpperCase().slice(0,2);
    const delay = i * 0.08;
    html += `
    <div class="student-card" style="animation-delay:${delay}s">
      <div class="student-header" onclick="toggle(${i})">
        <div class="student-info">
          <div class="avatar">${initials}</div>
          <div>
            <div class="student-name">${s.name}</div>
            <div class="student-handle">${s.handle}</div>
          </div>
        </div>
        <div class="student-meta">
          ${s.pending > 0 ? `<span class="pill pill-gray">${s.pending} pending</span>` : ''}
          ${s.in_progress > 0 ? `<span class="pill pill-amber">${s.in_progress} active</span>` : ''}
          ${s.submitted > 0 ? `<span class="pill pill-blue">${s.submitted} submitted</span>` : ''}
          ${s.reviewed > 0 ? `<span class="pill pill-green">${s.reviewed} reviewed</span>` : ''}
          <span class="chevron" id="chevron-${i}">▾</span>
        </div>
      </div>
      <div class="assignments-list open" id="list-${i}">
        ${s.assignments.length === 0 ? '<div style="padding:1rem 0;color:var(--muted);font-size:13px">No assignments yet.</div>' :
          s.assignments.map(a => `
            <div class="assignment-row">
              <div>
                <div class="assignment-title">${a.title}</div>
                <div class="assignment-desc">${a.description.slice(0,120)}${a.description.length > 120 ? '…' : ''}</div>
                <div class="assignment-meta">
                  ${statusPill(a.status, a.is_overdue)}
                  <span class="meta-item">Due: ${a.due_date}</span>
                  ${a.has_submission ? '<span class="pill pill-blue">📬 Submitted</span>' : ''}
                  ${a.has_feedback ? '<span class="pill pill-green">✓ Feedback given</span>' : ''}
                </div>
                ${a.last_update ? `<div class="update-bubble">"${a.last_update}" <span style="color:var(--subtle)">${a.last_update_time}</span></div>` : ''}
              </div>
            </div>
          `).join('')
        }
      </div>
    </div>`;
  });

  document.getElementById('main-content').innerHTML = html;
}

function toggle(i) {
  const list = document.getElementById(`list-${i}`);
  const chevron = document.getElementById(`chevron-${i}`);
  list.classList.toggle('open');
  chevron.classList.toggle('open');
}

loadData();
setInterval(loadData, 30000);
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Student HTML Template
# ---------------------------------------------------------------------------

STUDENT_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Classroom Companion — Student</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Mono:wght@400;500&family=DM+Sans:wght@300;400;500&display=swap" rel="stylesheet">
<style>
  :root {
    --bg: #0a0f0a;
    --surface: #111811;
    --surface2: #181f18;
    --border: #263026;
    --accent: #34d399;
    --accent2: #6ee7b7;
    --purple: #a78bfa;
    --amber: #fbbf24;
    --red: #f87171;
    --blue: #60a5fa;
    --text: #e8f0e8;
    --muted: #6b806b;
    --subtle: #2a3a2a;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: var(--bg); color: var(--text);
    font-family: 'DM Sans', sans-serif; min-height: 100vh; font-size: 14px;
  }
  .glow {
    position: fixed; top: -200px; left: 50%; transform: translateX(-50%);
    width: 500px; height: 400px;
    background: radial-gradient(ellipse, rgba(52,211,153,0.08) 0%, transparent 70%);
    pointer-events: none; z-index: 0;
  }
  .container { max-width: 900px; margin: 0 auto; padding: 2rem; position: relative; z-index: 1; }

  header {
    display: flex; align-items: flex-end; justify-content: space-between;
    padding-bottom: 2rem; border-bottom: 1px solid var(--border);
    margin-bottom: 2.5rem; animation: fadeDown 0.6s ease both;
  }
  .logo-tag { font-family: 'DM Mono', monospace; font-size: 10px; color: var(--accent2); letter-spacing: 3px; text-transform: uppercase; }
  .logo-title { font-family: 'DM Serif Display', serif; font-size: 28px; color: var(--text); }
  .student-badge {
    background: linear-gradient(135deg, #1a5c3a, #34d399);
    padding: 6px 14px; border-radius: 20px;
    font-size: 12px; font-weight: 500; color: white;
    font-family: 'DM Mono', monospace; letter-spacing: 1px;
  }

  .stats-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 1rem; margin-bottom: 2.5rem; animation: fadeUp 0.6s ease 0.1s both; }
  .stat-card {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 12px; padding: 1.25rem;
    transition: border-color 0.2s, transform 0.2s;
  }
  .stat-card:hover { border-color: var(--accent); transform: translateY(-2px); }
  .stat-label { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 1.5px; font-family: 'DM Mono', monospace; margin-bottom: 6px; }
  .stat-value { font-family: 'DM Serif Display', serif; font-size: 32px; color: var(--text); }
  .stat-value.green { color: var(--accent); }
  .stat-value.amber { color: var(--amber); }
  .stat-value.blue { color: var(--blue); }

  .teacher-info {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 10px; padding: 12px 16px; margin-bottom: 2rem;
    display: flex; align-items: center; gap: 10px;
    font-size: 13px; color: var(--muted);
    animation: fadeUp 0.5s ease 0.15s both;
  }
  .teacher-info span { color: var(--text); font-weight: 500; }

  .assignment-card {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 14px; margin-bottom: 1.25rem; overflow: hidden;
    animation: fadeUp 0.5s ease both;
    transition: border-color 0.2s, transform 0.2s;
  }
  .assignment-card:hover { border-color: var(--subtle); transform: translateY(-1px); }
  .assignment-card.overdue { border-color: rgba(248,113,113,0.3); }
  .assignment-card.reviewed { border-color: rgba(52,211,153,0.2); }

  .card-header {
    padding: 1.25rem 1.5rem 1rem;
    border-bottom: 1px solid var(--border);
    display: flex; justify-content: space-between; align-items: flex-start; gap: 1rem;
  }
  .card-title { font-weight: 500; font-size: 16px; margin-bottom: 4px; }
  .card-desc { color: var(--muted); font-size: 13px; line-height: 1.5; }
  .card-badges { display: flex; gap: 6px; flex-wrap: wrap; flex-shrink: 0; }

  .pill { padding: 3px 10px; border-radius: 20px; font-size: 11px; font-family: 'DM Mono', monospace; font-weight: 500; white-space: nowrap; }
  .pill-green { background: rgba(52,211,153,0.12); color: var(--accent); border: 1px solid rgba(52,211,153,0.25); }
  .pill-amber { background: rgba(251,191,36,0.12); color: var(--amber); border: 1px solid rgba(251,191,36,0.25); }
  .pill-red { background: rgba(248,113,113,0.12); color: var(--red); border: 1px solid rgba(248,113,113,0.25); }
  .pill-blue { background: rgba(96,165,250,0.12); color: var(--blue); border: 1px solid rgba(96,165,250,0.25); }
  .pill-gray { background: rgba(107,107,128,0.15); color: var(--muted); border: 1px solid rgba(107,107,128,0.2); }
  .pill-purple { background: rgba(167,139,250,0.12); color: var(--purple); border: 1px solid rgba(167,139,250,0.25); }

  .card-body { padding: 1rem 1.5rem; }
  .due-line { font-family: 'DM Mono', monospace; font-size: 12px; color: var(--muted); margin-bottom: 12px; }
  .due-line.overdue { color: var(--red); }

  .updates-title { font-size: 11px; text-transform: uppercase; letter-spacing: 1.5px; color: var(--muted); font-family: 'DM Mono', monospace; margin-bottom: 8px; }
  .update-item { display: flex; gap: 10px; align-items: flex-start; padding: 6px 0; border-top: 1px solid var(--border); }
  .update-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--accent); margin-top: 5px; flex-shrink: 0; }
  .update-text { font-size: 12px; color: var(--muted); line-height: 1.5; }
  .update-time { font-family: 'DM Mono', monospace; font-size: 10px; color: var(--subtle); margin-left: auto; flex-shrink: 0; padding-top: 2px; }

  .feedback-box {
    margin-top: 12px; background: rgba(52,211,153,0.05);
    border: 1px solid rgba(52,211,153,0.15); border-radius: 10px;
    padding: 12px 14px;
  }
  .feedback-label { font-size: 11px; text-transform: uppercase; letter-spacing: 1.5px; color: var(--accent); font-family: 'DM Mono', monospace; margin-bottom: 6px; }
  .feedback-text { font-size: 13px; color: var(--text); line-height: 1.6; font-style: italic; }

  .empty { text-align: center; padding: 4rem; color: var(--muted); font-family: 'DM Serif Display', serif; font-size: 18px; font-style: italic; }
  .loading { display: flex; align-items: center; justify-content: center; height: 300px; flex-direction: column; gap: 16px; }
  .spinner { width: 40px; height: 40px; border: 2px solid var(--border); border-top-color: var(--accent); border-radius: 50%; animation: spin 0.8s linear infinite; }
  .loading-text { color: var(--muted); font-family: 'DM Mono', monospace; font-size: 12px; }
  .error-box { background: rgba(248,113,113,0.08); border: 1px solid rgba(248,113,113,0.2); border-radius: 12px; padding: 1.5rem; color: var(--red); font-family: 'DM Mono', monospace; font-size: 12px; text-align: center; }
  .refresh-btn { background: var(--surface2); border: 1px solid var(--border); color: var(--muted); padding: 6px 14px; border-radius: 8px; font-family: 'DM Mono', monospace; font-size: 11px; cursor: pointer; transition: all 0.2s; }
  .refresh-btn:hover { border-color: var(--accent); color: var(--accent2); }
  .section-title { font-family: 'DM Serif Display', serif; font-size: 20px; color: var(--text); margin-bottom: 1.25rem; display: flex; align-items: center; gap: 10px; }
  .section-title::after { content: ''; flex: 1; height: 1px; background: var(--border); }

  @keyframes fadeDown { from { opacity:0; transform:translateY(-16px); } to { opacity:1; transform:translateY(0); } }
  @keyframes fadeUp { from { opacity:0; transform:translateY(16px); } to { opacity:1; transform:translateY(0); } }
  @keyframes spin { to { transform: rotate(360deg); } }
</style>
</head>
<body>
<div class="glow"></div>
<div class="container">
  <header>
    <div>
      <div class="logo-tag">Classroom Companion</div>
      <div class="logo-title">Student Dashboard</div>
    </div>
    <div style="display:flex;align-items:center;gap:12px">
      <button class="refresh-btn" onclick="loadData()">↻ Refresh</button>
      <span class="student-badge" id="student-name">Loading...</span>
    </div>
  </header>

  <div id="stats-row" class="stats-row" style="display:none">
    <div class="stat-card"><div class="stat-label">Total</div><div class="stat-value blue" id="stat-total">—</div></div>
    <div class="stat-card"><div class="stat-label">In Progress</div><div class="stat-value amber" id="stat-progress">—</div></div>
    <div class="stat-card"><div class="stat-label">Submitted</div><div class="stat-value blue" id="stat-submitted">—</div></div>
    <div class="stat-card"><div class="stat-label">Reviewed</div><div class="stat-value green" id="stat-reviewed">—</div></div>
  </div>

  <div id="teacher-info" class="teacher-info" style="display:none">
    🎓 Your teacher: <span id="teacher-name-val">—</span>
  </div>

  <div id="main-content">
    <div class="loading"><div class="spinner"></div><span class="loading-text">Loading your assignments...</span></div>
  </div>
</div>

<script>
const TELEGRAM_ID = {{TELEGRAM_ID}};

async function loadData() {
  const content = document.getElementById('main-content');
  try {
    const res = await fetch(`/api/student/${TELEGRAM_ID}`);
    if (!res.ok) throw new Error('Student not found. Make sure you have joined a class using /join in the bot.');
    const data = await res.json();
    render(data);
  } catch(e) {
    content.innerHTML = `<div class="error-box">⚠ ${e.message}</div>`;
  }
}

function statusPill(status, isOverdue) {
  if (isOverdue) return '<span class="pill pill-red">Overdue</span>';
  const map = {
    pending: '<span class="pill pill-gray">Pending</span>',
    in_progress: '<span class="pill pill-amber">In Progress</span>',
    submitted: '<span class="pill pill-blue">Submitted</span>',
    reviewed: '<span class="pill pill-green">Reviewed ✓</span>',
  };
  return map[status] || `<span class="pill pill-gray">${status}</span>`;
}

function render(data) {
  document.getElementById('student-name').textContent = data.student.name;
  document.getElementById('stats-row').style.display = 'grid';
  document.getElementById('stat-total').textContent = data.total;
  document.getElementById('stat-progress').textContent = data.in_progress;
  document.getElementById('stat-submitted').textContent = data.submitted;
  document.getElementById('stat-reviewed').textContent = data.reviewed;

  if (data.student.teacher) {
    document.getElementById('teacher-info').style.display = 'flex';
    document.getElementById('teacher-name-val').textContent = data.student.teacher;
  }

  if (data.assignments.length === 0) {
    document.getElementById('main-content').innerHTML = '<div class="empty">No assignments yet.<br><small style="font-size:14px;font-family:DM Sans;color:var(--muted)">Your teacher will assign work via the bot.</small></div>';
    return;
  }

  let html = '<div class="section-title">Your Assignments</div>';

  data.assignments.forEach((a, i) => {
    const delay = i * 0.08;
    const cardClass = a.is_overdue ? 'overdue' : a.status === 'reviewed' ? 'reviewed' : '';
    html += `
    <div class="assignment-card ${cardClass}" style="animation-delay:${delay}s">
      <div class="card-header">
        <div>
          <div class="card-title">${a.title}</div>
          <div class="card-desc">${a.description.slice(0,150)}${a.description.length > 150 ? '…' : ''}</div>
        </div>
        <div class="card-badges">
          ${statusPill(a.status, a.is_overdue)}
          ${a.submission ? '<span class="pill pill-blue">📬 Submitted</span>' : ''}
        </div>
      </div>
      <div class="card-body">
        <div class="due-line ${a.is_overdue ? 'overdue' : ''}">
          ${a.is_overdue ? '⚠ OVERDUE — ' : '⏰ Due: '}${a.due_date}
        </div>
        ${a.updates.length > 0 ? `
          <div class="updates-title">Progress Updates</div>
          ${a.updates.map(u => `
            <div class="update-item">
              <div class="update-dot"></div>
              <div class="update-text">${u.notes || u.status}</div>
              <div class="update-time">${u.time}</div>
            </div>
          `).join('')}
        ` : ''}
        ${a.feedback ? `
          <div class="feedback-box">
            <div class="feedback-label">Teacher Feedback</div>
            <div class="feedback-text">${a.feedback}</div>
          </div>
        ` : ''}
      </div>
    </div>`;
  });

  document.getElementById('main-content').innerHTML = html;
}

loadData();
setInterval(loadData, 30000);
</script>
</body>
</html>"""
