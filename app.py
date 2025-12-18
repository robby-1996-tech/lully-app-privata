import os
import sqlite3
from datetime import date, datetime, timedelta
from calendar import monthcalendar, month_name

from flask import (
    Flask, request, redirect, url_for, session, render_template_string, abort, g, flash
)

app = Flask(__name__)
APP_NAME = "Lullyland Calendar"
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-key-change-me")
APP_PIN = os.getenv("APP_PIN", "1234")
DB_PATH = os.getenv("DB_PATH", "lullyland.db")


# -------------------------
# DB helpers
# -------------------------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()

def init_db():
    db = get_db()
    db.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_date TEXT NOT NULL,         -- YYYY-MM-DD
            slot_code TEXT NOT NULL,          -- MORNING / AFTERNOON
            start_time TEXT NOT NULL,         -- HH:MM
            end_time TEXT NOT NULL,           -- HH:MM
            area INTEGER NOT NULL,            -- 1 / 2 / 3...
            child_name TEXT NOT NULL,
            child_age INTEGER DEFAULT 0,
            kids_count INTEGER DEFAULT 0,
            adults_count INTEGER DEFAULT 0,
            theme TEXT DEFAULT '',
            package TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            created_at TEXT NOT NULL
        )
    """)
    # indice utile per ricerche veloci
    db.execute("""
        CREATE INDEX IF NOT EXISTS idx_bookings_date_slot
        ON bookings(event_date, slot_code)
    """)
    db.commit()


# -------------------------
# Auth (PIN)
# -------------------------
def require_login():
    if not session.get("authed"):
        return redirect(url_for("login", next=request.path))

@app.before_request
def _before():
    # init db on first request
    if request.endpoint not in ("static",):
        init_db()
    # protect everything except login
    if request.endpoint not in ("login", "static"):
        if not session.get("authed"):
            return redirect(url_for("login", next=request.full_path))

@app.route("/login", methods=["GET", "POST"])
def login():
    next_url = request.args.get("next") or url_for("calendar_week")
    if request.method == "POST":
        pin = request.form.get("pin", "").strip()
        if pin == APP_PIN:
            session["authed"] = True
            return redirect(next_url)
        flash("PIN errato.")
    return render_template_string("""
    <!doctype html><html><head>
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>{{app_name}} - Login</title>
      <style>
        body{font-family:system-ui,-apple-system,Segoe UI,Roboto; margin:20px;}
        .card{max-width:420px;margin:40px auto;padding:18px;border:1px solid #ddd;border-radius:12px;}
        input{width:100%;padding:12px;border-radius:10px;border:1px solid #ccc;font-size:16px;}
        button{width:100%;padding:12px;border-radius:10px;border:0;background:#111;color:#fff;font-weight:700;font-size:16px;margin-top:10px;}
        .msg{color:#b00020;margin-top:10px;}
      </style>
    </head><body>
      <div class="card">
        <h2 style="margin:0 0 10px 0;">{{app_name}}</h2>
        <div style="opacity:.7;margin-bottom:10px;">Inserisci PIN</div>
        <form method="post">
          <input name="pin" type="password" inputmode="numeric" placeholder="PIN" autofocus />
          <button type="submit">Entra</button>
        </form>
        {% with messages = get_flashed_messages() %}
          {% if messages %}<div class="msg">{{messages[0]}}</div>{% endif %}
        {% endwith %}
      </div>
    </body></html>
    """, app_name=APP_NAME)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# -------------------------
# Slot rules
# -------------------------
def weekday_idx(d: date) -> int:
    # Monday=0 ... Sunday=6
    return d.weekday()

def slots_for_date(d: date):
    """
    Returns list of slots for that date:
    Each slot: dict(slot_code, label, start_time, end_time)
    """
    wd = weekday_idx(d)
    slots = []
    # always afternoon slot
    slots.append({
        "slot_code": "AFTERNOON",
        "label": "POMERIDIANO/SERALE",
        "start_time": "17:00",
        "end_time": "20:00",
    })
    # weekend morning slot only Sat(5) Sun(6)
    if wd in (5, 6):
        slots.insert(0, {
            "slot_code": "MORNING",
            "label": "MATTINA",
            "start_time": "09:30",
            "end_time": "12:30",
        })
    return slots

def count_bookings(event_date: str, slot_code: str) -> int:
    db = get_db()
    row = db.execute(
        "SELECT COUNT(*) AS c FROM bookings WHERE event_date=? AND slot_code=?",
        (event_date, slot_code)
    ).fetchone()
    return int(row["c"])

def bookings_for_slot(event_date: str, slot_code: str):
    db = get_db()
    rows = db.execute("""
        SELECT * FROM bookings
        WHERE event_date=? AND slot_code=?
        ORDER BY area ASC, id ASC
    """, (event_date, slot_code)).fetchall()
    return rows

def status_color(n: int) -> str:
    # 0 green, 1 yellow, >=2 red
    if n <= 0:
        return "green"
    if n == 1:
        return "yellow"
    return "red"

def next_area_for_slot(event_date: str, slot_code: str) -> int:
    """
    Assign Area 1 for first, Area 2 for second.
    If already 2+ exist, default to 3 (but require confirmation).
    """
    n = count_bookings(event_date, slot_code)
    if n == 0:
        return 1
    if n == 1:
        return 2
    return 3


# -------------------------
# UI helpers
# -------------------------
BASE_STYLE = """
<style>
  body{font-family:system-ui,-apple-system,Segoe UI,Roboto; margin:18px; background:#fafafa;}
  a{color:inherit}
  .topbar{display:flex;gap:10px;flex-wrap:wrap;align-items:center;justify-content:space-between;margin-bottom:14px;}
  .nav{display:flex;gap:8px;flex-wrap:wrap;align-items:center;}
  .btn{display:inline-block;padding:10px 12px;border:1px solid #ddd;background:#fff;border-radius:12px;text-decoration:none;font-weight:650;}
  .btn:hover{border-color:#bbb}
  .btn.primary{background:#111;color:#fff;border-color:#111}
  .grid{display:grid;gap:10px;}
  .card{background:#fff;border:1px solid #e5e5e5;border-radius:14px;padding:12px;}
  .muted{opacity:.7}
  .slot{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;padding:10px;border-radius:12px;border:1px solid #e5e5e5;margin-top:8px;}
  .slot.green{background:#eaffea;border-color:#b7e6b7;}
  .slot.yellow{background:#fff8d8;border-color:#f1df86;}
  .slot.red{background:#ffe1e1;border-color:#f2a0a0;}
  .pill{font-size:12px;padding:4px 8px;border-radius:999px;background:#111;color:#fff;display:inline-block;}
  .pill.gray{background:#666;}
  .events{margin-top:8px;display:grid;gap:6px;}
  .eventline{padding:8px;border-radius:12px;border:1px solid #eee;background:#fcfcfc;}
  .eventline b{display:block}
  .calmonth{display:grid;grid-template-columns:repeat(7,1fr);gap:8px;}
  .daybox{background:#fff;border:1px solid #e5e5e5;border-radius:12px;padding:10px;min-height:90px;}
  .daynum{font-weight:800}
  .daynum a{text-decoration:none}
  .mini{font-size:12px;margin-top:8px;display:grid;gap:6px}
  .mini .s{padding:6px;border-radius:10px;border:1px solid #eee}
  .mini .s.green{background:#eaffea;border-color:#b7e6b7;}
  .mini .s.yellow{background:#fff8d8;border-color:#f1df86;}
  .mini .s.red{background:#ffe1e1;border-color:#f2a0a0;}
  .table{width:100%;border-collapse:collapse;}
  .table td,.table th{padding:8px;border-bottom:1px solid #eee;text-align:left;vertical-align:top;}
  .flash{padding:10px;border-radius:12px;background:#fff3cd;border:1px solid #ffeeba;margin-bottom:12px;}
  input, textarea, select{width:100%;padding:10px;border:1px solid #ddd;border-radius:12px;font-size:16px;background:#fff;}
  textarea{min-height:90px}
  .row{display:grid;grid-template-columns:1fr 1fr;gap:10px}
  @media (max-width:700px){ .row{grid-template-columns:1fr;} }
</style>
"""

def topbar_html(active: str, today: date):
    return f"""
    <div class="topbar">
      <div class="nav">
        <a class="btn {'primary' if active=='week' else ''}" href="{url_for('calendar_week')}">Settimanale</a>
        <a class="btn {'primary' if active=='month' else ''}" href="{url_for('calendar_month')}">Mensile</a>
        <a class="btn {'primary' if active=='year' else ''}" href="{url_for('calendar_year')}">Annuale</a>
        <a class="btn" href="{url_for('calendar_day', y=today.year, m=today.month, d=today.day)}">Oggi</a>
      </div>
      <div class="nav">
        <span class="muted">Loggato</span>
        <a class="btn" href="{url_for('logout')}">Esci</a>
      </div>
    </div>
    """

# -------------------------
# Calendar views
# -------------------------
@app.route("/")
def home():
    return redirect(url_for("calendar_week"))

@app.route("/calendar/year")
def calendar_year():
    today = date.today()
    y = int(request.args.get("y", today.year))

    # Build months summaries
    months = []
    for m in range(1, 13):
        # count bookings in month
        start = date(y, m, 1)
        if m == 12:
            end = date(y + 1, 1, 1)
        else:
            end = date(y, m + 1, 1)

        db = get_db()
        c = db.execute("""
            SELECT COUNT(*) AS c FROM bookings
            WHERE event_date >= ? AND event_date < ?
        """, (start.isoformat(), end.isoformat())).fetchone()["c"]

        months.append({"m": m, "name": month_name[m], "count": int(c)})

    html = f"""
    <!doctype html><html><head>
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>{APP_NAME} - Annuale</title>
      {BASE_STYLE}
    </head><body>
      {topbar_html('year', today)}
      <div class="card">
        <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;">
          <h2 style="margin:0;">Annuale {y}</h2>
          <div class="nav">
            <a class="btn" href="{url_for('calendar_year', y=y-1)}">← {y-1}</a>
            <a class="btn" href="{url_for('calendar_year', y=y+1)}">{y+1} →</a>
          </div>
        </div>
        <div class="grid" style="grid-template-columns:repeat(3,1fr); margin-top:12px;">
          {''.join([f'''
            <div class="card">
              <div style="display:flex;justify-content:space-between;align-items:center;">
                <b>{mm['name']}</b>
                <span class="pill gray">{mm['count']} pren.</span>
              </div>
              <div style="margin-top:10px;">
                <a class="btn" href="{url_for('calendar_month', y=y, m=mm['m'])}">Apri mese</a>
              </div>
            </div>
          ''' for mm in months])}
        </div>
      </div>
    </body></html>
    """
    return render_template_string(html)

@app.route("/calendar/month")
def calendar_month():
    today = date.today()
    y = int(request.args.get("y", today.year))
    m = int(request.args.get("m", today.month))

    weeks = monthcalendar(y, m)  # list of weeks; 0 means day outside month
    month_label = f"{month_name[m]} {y}"

    # Preload counts for all days/slots in month
    db = get_db()
    rows = db.execute("""
        SELECT event_date, slot_code, COUNT(*) AS c
        FROM bookings
        WHERE event_date >= ? AND event_date < ?
        GROUP BY event_date, slot_code
    """, (date(y, m, 1).isoformat(),
          (date(y+1, 1, 1) if m == 12 else date(y, m+1, 1)).isoformat()
    )).fetchall()
    counts = {(r["event_date"], r["slot_code"]): int(r["c"]) for r in rows}

    # render grid
    day_boxes = []
    for w in weeks:
        for dnum in w:
            if dnum == 0:
                day_boxes.append('<div class="daybox" style="background:transparent;border:0;"></div>')
                continue
            d = date(y, m, dnum)
            d_iso = d.isoformat()
            slot_html = ""
            for s in slots_for_date(d):
                c = counts.get((d_iso, s["slot_code"]), 0)
                col = status_color(c)
                slot_html += f"""
                  <div class="s {col}">
                    <div style="display:flex;justify-content:space-between;gap:6px;">
                      <span><b>{s['start_time']}-{s['end_time']}</b></span>
                      <span class="muted">{'0' if c==0 else c}/2</span>
                    </div>
                    <div class="muted">{s['label']}</div>
                  </div>
                """
            day_boxes.append(f"""
              <div class="daybox">
                <div class="daynum"><a href="{url_for('calendar_day', y=y, m=m, d=dnum)}">{dnum}</a></div>
                <div class="mini">{slot_html}</div>
              </div>
            """)

    html = f"""
    <!doctype html><html><head>
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>{APP_NAME} - Mensile</title>
      {BASE_STYLE}
    </head><body>
      {topbar_html('month', today)}
      <div class="card">
        <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;">
          <h2 style="margin:0;">{month_label}</h2>
          <div class="nav">
            <a class="btn" href="{url_for('calendar_month', y=(y-1 if m==1 else y), m=(12 if m==1 else m-1))}">←</a>
            <a class="btn" href="{url_for('calendar_month', y=(y+1 if m==12 else y), m=(1 if m==12 else m+1))}">→</a>
          </div>
        </div>

        <div class="muted" style="margin-top:6px;">
          🟢 libero · 🟡 una sola area occupata · 🔴 pieno (Area 1+2)
        </div>

        <div class="calmonth" style="margin-top:12px;">
          {''.join(day_boxes)}
        </div>
      </div>
    </body></html>
    """
    return render_template_string(html)

@app.route("/calendar/week")
def calendar_week():
    today = date.today()
    # week starts monday
    ref = request.args.get("d")
    if ref:
        try:
            base = datetime.strptime(ref, "%Y-%m-%d").date()
        except ValueError:
            base = today
    else:
        base = today

    monday = base - timedelta(days=base.weekday())
    days = [monday + timedelta(days=i) for i in range(7)]

    # Preload counts and events for the 7 days
    db = get_db()
    start = days[0].isoformat()
    end = (days[-1] + timedelta(days=1)).isoformat()
    rows = db.execute("""
        SELECT event_date, slot_code, COUNT(*) AS c
        FROM bookings
        WHERE event_date >= ? AND event_date < ?
        GROUP BY event_date, slot_code
    """, (start, end)).fetchall()
    counts = {(r["event_date"], r["slot_code"]): int(r["c"]) for r in rows}

    # also load all bookings for quick listing
    b_rows = db.execute("""
        SELECT * FROM bookings
        WHERE event_date >= ? AND event_date < ?
        ORDER BY event_date ASC, slot_code ASC, area ASC
    """, (start, end)).fetchall()
    by_slot = {}
    for r in b_rows:
        by_slot.setdefault((r["event_date"], r["slot_code"]), []).append(r)

    day_cards = []
    for d in days:
        d_iso = d.isoformat()
        slots_html = ""
        for s in slots_for_date(d):
            c = counts.get((d_iso, s["slot_code"]), 0)
            col = status_color(c)
            events = by_slot.get((d_iso, s["slot_code"]), [])
            events_html = ""
            if events:
                ev_lines = []
                for ev in events:
                    ev_lines.append(f"""
                      <div class="eventline">
                        <b>Area {ev['area']}: <a href="{url_for('booking_detail', booking_id=ev['id'])}">
                          {ev['child_name']}</a> – {ev['child_age']} anni
                        </b>
                        <div class="muted">{ev['kids_count']} bimbi / {ev['adults_count']} adulti · Tema: {ev['theme'] or '-'} · Pacchetto: {ev['package'] or '-'}</div>
                      </div>
                    """)
                events_html = f"<div class='events'>{''.join(ev_lines)}</div>"

            slots_html += f"""
              <div class="slot {col}">
                <div>
                  <div><b>{s['start_time']}–{s['end_time']}</b> <span class="muted">({s['label']})</span></div>
                  <div class="muted" style="margin-top:4px;">{c}/2 prenotazioni</div>
                  {events_html}
                </div>
                <div style="text-align:right;">
                  <a class="btn primary" href="{url_for('booking_new')}?date={d_iso}&slot={s['slot_code']}">Prenota</a>
                  <div style="margin-top:6px;">
                    <a class="btn" href="{url_for('calendar_day', y=d.year, m=d.month, d=d.day)}">Giorno</a>
                  </div>
                </div>
              </div>
            """

        day_cards.append(f"""
          <div class="card">
            <div style="display:flex;justify-content:space-between;align-items:baseline;gap:10px;">
              <h3 style="margin:0;">
                <a style="text-decoration:none" href="{url_for('calendar_day', y=d.year, m=d.month, d=d.day)}">
                  {d.strftime('%a %d/%m')}
                </a>
              </h3>
              <span class="muted">{d_iso}</span>
            </div>
            {slots_html}
          </div>
        """)

    prev_week = (monday - timedelta(days=7)).isoformat()
    next_week = (monday + timedelta(days=7)).isoformat()

    html = f"""
    <!doctype html><html><head>
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>{APP_NAME} - Settimanale</title>
      {BASE_STYLE}
    </head><body>
      {topbar_html('week', today)}
      <div class="card">
        <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;">
          <h2 style="margin:0;">Settimana dal {monday.strftime('%d/%m/%Y')}</h2>
          <div class="nav">
            <a class="btn" href="{url_for('calendar_week')}?d={prev_week}">← Settimana</a>
            <a class="btn" href="{url_for('calendar_week')}?d={next_week}">Settimana →</a>
          </div>
        </div>
        <div class="muted" style="margin-top:6px;">
          🟢 libero · 🟡 una sola area occupata · 🔴 pieno (Area 1+2)
        </div>
      </div>

      <div class="grid" style="margin-top:10px;">
        {''.join(day_cards)}
      </div>
    </body></html>
    """
    return render_template_string(html)

@app.route("/calendar/day/<int:y>/<int:m>/<int:d>")
def calendar_day(y, m, d):
    today = date.today()
    try:
        dd = date(y, m, d)
    except ValueError:
        abort(404)

    d_iso = dd.isoformat()
    slots = slots_for_date(dd)

    slot_blocks = []
    for s in slots:
        c = count_bookings(d_iso, s["slot_code"])
        col = status_color(c)
        events = bookings_for_slot(d_iso, s["slot_code"])
        ev_lines = ""
        if events:
            ev_lines = "<div class='events'>" + "".join([
                f"""
                <div class="eventline">
                  <b>Area {ev['area']}: <a href="{url_for('booking_detail', booking_id=ev['id'])}">{ev['child_name']}</a> – {ev['child_age']} anni</b>
                  <div class="muted">{ev['kids_count']} bimbi / {ev['adults_count']} adulti · Tema: {ev['theme'] or '-'} · Pacchetto: {ev['package'] or '-'}</div>
                </div>
                """ for ev in events
            ]) + "</div>"

        slot_blocks.append(f"""
          <div class="slot {col}">
            <div>
              <div><b>{s['start_time']}–{s['end_time']}</b> <span class="muted">({s['label']})</span></div>
              <div class="muted" style="margin-top:4px;">Stato: {c}/2</div>
              {ev_lines}
            </div>
            <div style="text-align:right;">
              <a class="btn primary" href="{url_for('booking_new')}?date={d_iso}&slot={s['slot_code']}">Prenota</a>
            </div>
          </div>
        """)

    html = f"""
    <!doctype html><html><head>
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>{APP_NAME} - Giorno</title>
      {BASE_STYLE}
    </head><body>
      {topbar_html('', today)}
      <div class="card">
        <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;">
          <h2 style="margin:0;">{dd.strftime('%A %d/%m/%Y')}</h2>
          <div class="nav">
            <a class="btn" href="{url_for('calendar_month', y=y, m=m)}">Mese</a>
            <a class="btn" href="{url_for('calendar_week')}?d={d_iso}">Settimana</a>
          </div>
        </div>
        <div class="muted" style="margin-top:6px;">🟢 libero · 🟡 una sola area occupata · 🔴 pieno (Area 1+2)</div>
      </div>

      <div class="card" style="margin-top:10px;">
        {''.join(slot_blocks)}
      </div>
    </body></html>
    """
    return render_template_string(html)


# -------------------------
# Booking
# -------------------------
@app.route("/booking/new", methods=["GET", "POST"])
def booking_new():
    d_iso = request.args.get("date", "").strip()
    slot_code = request.args.get("slot", "").strip().upper()

    # basic validation
    try:
        d = datetime.strptime(d_iso, "%Y-%m-%d").date()
    except Exception:
        abort(400, "Data non valida.")
    possible = {s["slot_code"] for s in slots_for_date(d)}
    if slot_code not in possible:
        abort(400, "Slot non valido per questa data.")

    # get slot info
    slot = next(s for s in slots_for_date(d) if s["slot_code"] == slot_code)

    # current occupancy
    n = count_bookings(d_iso, slot_code)
    suggested_area = next_area_for_slot(d_iso, slot_code)
    is_overbook = n >= 2  # area 1+2 already used

    if request.method == "POST":
        # read form
        child_name = (request.form.get("child_name") or "").strip()
        child_age = int((request.form.get("child_age") or "0").strip() or 0)
        kids_count = int((request.form.get("kids_count") or "0").strip() or 0)
        adults_count = int((request.form.get("adults_count") or "0").strip() or 0)
        theme = (request.form.get("theme") or "").strip()
        package = (request.form.get("package") or "").strip()
        notes = (request.form.get("notes") or "").strip()

        confirm_area3 = (request.form.get("confirm_area3") == "on")

        if not child_name:
            flash("Inserisci il nome del festeggiato.")
        else:
            # re-check occupancy at save time (important)
            n_now = count_bookings(d_iso, slot_code)
            area = next_area_for_slot(d_iso, slot_code)

            if n_now >= 2 and not confirm_area3:
                flash("Area 1 e 2 sono già impegnate. Se vuoi inserire comunque, conferma Area 3.")
            else:
                db = get_db()
                db.execute("""
                    INSERT INTO bookings(
                      event_date, slot_code, start_time, end_time, area,
                      child_name, child_age, kids_count, adults_count,
                      theme, package, notes, created_at
                    )
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    d_iso, slot_code, slot["start_time"], slot["end_time"], area,
                    child_name, child_age, kids_count, adults_count,
                    theme, package, notes, datetime.now().isoformat(timespec="seconds")
                ))
                db.commit()
                flash(f"Prenotazione salvata in Area {area}.")
                return redirect(url_for("calendar_day", y=d.year, m=d.month, d=d.day))

    html = f"""
    <!doctype html><html><head>
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>{APP_NAME} - Prenota</title>
      {BASE_STYLE}
    </head><body>
      {topbar_html('', date.today())}
      <div class="card">
        <h2 style="margin:0;">Prenota compleanno</h2>
        <div class="muted" style="margin-top:6px;">
          Data: <b>{d.strftime('%d/%m/%Y')}</b> · Slot: <b>{slot['start_time']}-{slot['end_time']}</b> ({slot['label']}) · Occupazione: <b>{n}/2</b>
        </div>
        <div class="muted" style="margin-top:6px;">
          Area suggerita: <b>{suggested_area}</b>
          {"· <span style='color:#b00020;font-weight:700;'>Area 1 e 2 già occupate</span>" if is_overbook else ""}
        </div>

        {% with messages = get_flashed_messages() %}
          {% if messages %}<div class="flash" style="margin-top:12px;">{{messages[0]}}</div>{% endif %}
        {% endwith %}

        <form method="post" style="margin-top:12px;">
          <div class="row">
            <div>
              <label><b>Nome festeggiato</b></label>
              <input name="child_name" placeholder="Es. Marco" required />
            </div>
            <div>
              <label><b>Età</b></label>
              <input name="child_age" type="number" min="0" inputmode="numeric" placeholder="Es. 5" />
            </div>
          </div>

          <div class="row" style="margin-top:10px;">
            <div>
              <label><b>Numero bimbi</b></label>
              <input name="kids_count" type="number" min="0" inputmode="numeric" placeholder="Es. 20" />
            </div>
            <div>
              <label><b>Numero adulti</b></label>
              <input name="adults_count" type="number" min="0" inputmode="numeric" placeholder="Es. 20" />
            </div>
          </div>

          <div class="row" style="margin-top:10px;">
            <div>
              <label><b>Tema</b></label>
              <input name="theme" placeholder="Es. Spiderman" />
            </div>
            <div>
              <label><b>Pacchetto</b></label>
              <input name="package" placeholder="Es. Lullyland Experience" />
            </div>
          </div>

          <div style="margin-top:10px;">
            <label><b>Note</b></label>
            <textarea name="notes" placeholder="Info extra..."></textarea>
          </div>

          {"<div style='margin-top:10px; padding:10px; border:1px solid #f2a0a0; background:#ffe1e1; border-radius:12px;'><b>Allert:</b> Area 1 e 2 sono già impegnate. Se vuoi inserire comunque, spunta qui sotto per confermare Area 3.<div style='margin-top:8px; display:flex; gap:10px; align-items:center;'><input style='width:auto' type='checkbox' name='confirm_area3' id='c3'><label for='c3'><b>Confermo inserimento Area 3</b></label></div></div>" if is_overbook else ""}

          <div class="nav" style="margin-top:12px;">
            <button class="btn primary" type="submit">Salva prenotazione</button>
            <a class="btn" href="{url_for('calendar_day', y=d.year, m=d.month, d=d.day)}">Annulla</a>
          </div>
        </form>
      </div>
    </body></html>
    """
    return render_template_string(html)

@app.route("/booking/<int:booking_id>")
def booking_detail(booking_id: int):
    db = get_db()
    b = db.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
    if not b:
        abort(404)

    d = datetime.strptime(b["event_date"], "%Y-%m-%d").date()
    html = f"""
    <!doctype html><html><head>
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>{APP_NAME} - Dettaglio</title>
      {BASE_STYLE}
    </head><body>
      {topbar_html('', date.today())}
      <div class="card">
        <h2 style="margin:0;">Dettaglio prenotazione</h2>
        <div class="muted" style="margin-top:6px;">
          {b["event_date"]} · {b["start_time"]}-{b["end_time"]} · Slot: {b["slot_code"]} · <b>Area {b["area"]}</b>
        </div>

        <table class="table" style="margin-top:12px;">
          <tr><th>Festeggiato</th><td><b>{b["child_name"]}</b> ({b["child_age"]} anni)</td></tr>
          <tr><th>Partecipanti</th><td>{b["kids_count"]} bimbi / {b["adults_count"]} adulti</td></tr>
          <tr><th>Tema</th><td>{b["theme"] or "-"}</td></tr>
          <tr><th>Pacchetto</th><td>{b["package"] or "-"}</td></tr>
          <tr><th>Note</th><td>{(b["notes"] or "-").replace("<","&lt;").replace(">","&gt;")}</td></tr>
          <tr><th>Creato</th><td class="muted">{b["created_at"]}</td></tr>
        </table>

        <div class="nav" style="margin-top:12px;">
          <a class="btn" href="{url_for('calendar_day', y=d.year, m=d.month, d=d.day)}">Torna al giorno</a>
          <a class="btn" href="{url_for('calendar_week')}?d={b["event_date"]}">Torna alla settimana</a>
          <a class="btn" href="{url_for('calendar_month', y=d.year, m=d.month)}">Torna al mese</a>
        </div>
      </div>
    </body></html>
    """
    return render_template_string(html)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=True)
