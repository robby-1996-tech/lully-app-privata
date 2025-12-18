import os
import sqlite3
from datetime import date, datetime
from calendar import monthcalendar, month_name

from flask import (
    Flask, request, redirect, url_for,
    session, abort, g
)

# -------------------------
# CONFIG
# -------------------------
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "change-me")
APP_PIN = os.getenv("APP_PIN", "1234")
DB_PATH = os.getenv("DB_PATH", "lullyland.db")
APP_NAME = "Lullyland – Calendario"

# -------------------------
# DB
# -------------------------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(_):
    db = g.pop("db", None)
    if db:
        db.close()

def init_db():
    db = get_db()
    db.execute("""
    CREATE TABLE IF NOT EXISTS bookings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_date TEXT,
        slot_code TEXT,
        start_time TEXT,
        end_time TEXT,
        area INTEGER,
        child_name TEXT,
        phone TEXT,
        deposit INTEGER,
        created_at TEXT
    )
    """)
    db.commit()

@app.before_request
def before():
    init_db()
    if request.endpoint not in ("login", "static") and not session.get("auth"):
        return redirect(url_for("login"))

# -------------------------
# AUTH
# -------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("pin") == APP_PIN:
            session["auth"] = True
            return redirect("/")
    return """
    <h2>Lullyland – App privata</h2>
    <form method="post">
      <input name="pin" placeholder="PIN">
      <button>Entra</button>
    </form>
    """

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

# -------------------------
# SLOT RULES
# -------------------------
def slots_for_date(d: date):
    slots = [{
        "code": "AFTERNOON",
        "label": "17:00–20:00",
        "start": "17:00",
        "end": "20:00"
    }]
    if d.weekday() in (5, 6):
        slots.insert(0, {
            "code": "MORNING",
            "label": "09:30–12:30",
            "start": "09:30",
            "end": "12:30"
        })
    return slots

def count_slot(date_iso, slot_code):
    db = get_db()
    r = db.execute(
        "SELECT COUNT(*) c FROM bookings WHERE event_date=? AND slot_code=?",
        (date_iso, slot_code)
    ).fetchone()
    return r["c"]

# -------------------------
# CALENDARIO MENSILE (HOME)
# -------------------------
@app.route("/")
def calendar_month():
    today = date.today()
    y = int(request.args.get("y", today.year))
    m = int(request.args.get("m", today.month))

    weeks = monthcalendar(y, m)

    html_days = ""
    for w in weeks:
        html_days += "<tr>"
        for d in w:
            if d == 0:
                html_days += "<td></td>"
            else:
                d_iso = date(y, m, d).isoformat()
                c = count_slot(d_iso, "AFTERNOON")
                color = "green" if c == 0 else "orange" if c == 1 else "red"
                html_days += f"""
                <td style="padding:10px;border:1px solid #ccc;">
                  <b>{d}</b><br>
                  <div style="background:{color};padding:4px;margin-top:4px;">
                    {c}/2 feste
                  </div>
                  <a href="/day/{d_iso}">Apri</a>
                </td>
                """
        html_days += "</tr>"

    return f"""
    <h1>{APP_NAME}</h1>
    <a href="/logout">Esci</a>
    <h3>{month_name[m]} {y}</h3>

    <table style="border-collapse:collapse;width:100%;">
      {html_days}
    </table>
    """

# -------------------------
# VISTA GIORNO
# -------------------------
@app.route("/day/<date_iso>")
def day_view(date_iso):
    try:
        d = datetime.strptime(date_iso, "%Y-%m-%d").date()
    except ValueError:
        abort(404)

    slot_html = ""
    for s in slots_for_date(d):
        c = count_slot(date_iso, s["code"])
        slot_html += f"""
        <div style="border:1px solid #000;padding:10px;margin:10px 0;">
          <b>{s['label']}</b> – {c}/2
          <br>
          <a href="/booking/new?date={date_iso}&slot={s['code']}">
            ➕ Aggiungi festa
          </a>
        </div>
        """

    return f"""
    <h2>{d.strftime('%A %d %B %Y')}</h2>
    <a href="/">← Torna al calendario</a>
    {slot_html}
    """

# -------------------------
# PRENOTAZIONE (PLACEHOLDER)
# -------------------------
@app.route("/booking/new")
def booking_new():
    date_iso = request.args.get("date")
    slot = request.args.get("slot")

    if not date_iso or not slot:
        abort(400)

    return f"""
    <h2>Nuova festa</h2>
    <p>Data: {date_iso}</p>
    <p>Slot: {slot}</p>

    <p><i>Qui ricolleghiamo il software di prenotazione completo</i></p>

    <a href="/day/{date_iso}">← Annulla</a>
    """

# -------------------------
# RUN
# -------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
