import os
import sqlite3
from datetime import date, datetime, timedelta
from calendar import monthcalendar, month_name

from flask import (
    Flask, request, redirect, url_for,
    session, render_template_string,
    abort, g, flash, get_flashed_messages
)

app = Flask(__name__)
APP_NAME = "Lullyland Calendar"
app.secret_key = os.getenv("SECRET_KEY", "change-me")
APP_PIN = os.getenv("APP_PIN", "1234")
DB_PATH = os.getenv("DB_PATH", "lullyland.db")


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
        child_age INTEGER,
        kids_count INTEGER,
        adults_count INTEGER,
        theme TEXT,
        package TEXT,
        phone TEXT,
        deposit_cents INTEGER,
        notes TEXT,
        created_at TEXT
    )
    """)
    db.commit()


# -------------------------
# AUTH
# -------------------------
@app.before_request
def protect():
    init_db()
    if request.endpoint not in ("login", "static") and not session.get("auth"):
        return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("pin") == APP_PIN:
            session["auth"] = True
            return redirect("/")
        flash("PIN errato")

    messages = get_flashed_messages()
    flash_html = f"<div class='flash'>{messages[0]}</div>" if messages else ""

    return render_template_string(f"""
    <h2>Login {APP_NAME}</h2>
    {flash_html}
    <form method="post">
      <input name="pin" placeholder="PIN">
      <button>Entra</button>
    </form>
    """)


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


# -------------------------
# SLOT
# -------------------------
def slots_for_date(d):
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

def count_bookings(date_iso, slot):
    db = get_db()
    r = db.execute(
        "SELECT COUNT(*) c FROM bookings WHERE event_date=? AND slot_code=?",
        (date_iso, slot)
    ).fetchone()
    return r["c"]

def next_area(date_iso, slot):
    c = count_bookings(date_iso, slot)
    return c + 1


# -------------------------
# CALENDAR
# -------------------------
@app.route("/")
def calendar_week():
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    days = [monday + timedelta(days=i) for i in range(7)]

    db = get_db()
    html_days = ""

    for d in days:
        iso = d.isoformat()
        slot_html = ""

        for s in slots_for_date(d):
            c = count_bookings(iso, s["code"])
            color = "green" if c == 0 else "yellow" if c == 1 else "red"

            slot_html += f"""
            <div style="border:1px solid #ccc;padding:6px;margin:4px;background:{color}">
              {s['label']} – {c}/2
              <a href="/booking/new?date={iso}&slot={s['code']}">Prenota</a>
            </div>
            """

        html_days += f"""
        <div style="border:2px solid #000;padding:10px;margin:10px">
          <h3>{d.strftime('%A %d/%m')}</h3>
          {slot_html}
        </div>
        """

    return f"""
    <h1>{APP_NAME} – Settimana</h1>
    <a href="/logout">Logout</a>
    {html_days}
    """


# -------------------------
# BOOKING
# -------------------------
def eur_to_cents(v):
    if not v:
        return 0
    v = v.replace(",", ".")
    if "." in v:
        a, b = v.split(".")
        return int(a) * 100 + int(b.ljust(2, "0")[:2])
    return int(v) * 100


@app.route("/booking/new", methods=["GET", "POST"])
def booking_new():
    date_iso = request.args.get("date")
    slot = request.args.get("slot")

    if not date_iso or not slot:
        abort(400)

    d = datetime.strptime(date_iso, "%Y-%m-%d").date()
    area = next_area(date_iso, slot)
    over = area > 2

    if request.method == "POST":
        if over and not request.form.get("force"):
            flash("Slot pieno. Conferma Area 3.")
        else:
            db = get_db()
            db.execute("""
            INSERT INTO bookings VALUES (
              NULL,?,?,?,?,?,?,?,?,?,?,?,?,?
            )
            """, (
                date_iso, slot,
                request.form["start"],
                request.form["end"],
                area,
                request.form["child_name"],
                int(request.form.get("child_age", 0)),
                int(request.form.get("kids_count", 0)),
                int(request.form.get("adults_count", 0)),
                request.form.get("theme"),
                request.form.get("package"),
                request.form.get("phone"),
                eur_to_cents(request.form.get("deposit")),
                request.form.get("notes"),
                datetime.now().isoformat()
            ))
            db.commit()
            return redirect("/")

    messages = get_flashed_messages()
    flash_html = f"<div class='flash'>{messages[0]}</div>" if messages else ""

    s = next(x for x in slots_for_date(d) if x["code"] == slot)

    return f"""
    <h2>Prenota – {date_iso} {s['label']}</h2>
    {flash_html}

    <form method="post">
      <input name="child_name" placeholder="Nome bimbo" required>
      <input name="child_age" placeholder="Età">
      <input name="kids_count" placeholder="Bimbi">
      <input name="adults_count" placeholder="Adulti">
      <input name="phone" placeholder="Telefono">
      <input name="deposit" placeholder="Acconto €">
      <input name="theme" placeholder="Tema">
      <input name="package" placeholder="Pacchetto">
      <textarea name="notes"></textarea>

      <input type="hidden" name="start" value="{s['start']}">
      <input type="hidden" name="end" value="{s['end']}">

      {"<label><input type='checkbox' name='force'> Confermo Area 3</label>" if over else ""}

      <button>Salva</button>
    </form>
    """


# -------------------------
# RUN
# -------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
