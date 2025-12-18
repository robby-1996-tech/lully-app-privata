import os
import sqlite3
from datetime import date, datetime, timedelta
from calendar import monthcalendar, month_name

from flask import Flask, request, redirect, url_for, session, abort, g

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
        event_date TEXT NOT NULL,        -- YYYY-MM-DD
        slot_code TEXT NOT NULL,         -- MORNING / AFTERNOON
        start_time TEXT NOT NULL,
        end_time TEXT NOT NULL,
        area INTEGER NOT NULL,           -- 1/2/3...
        child_name TEXT DEFAULT '',
        phone TEXT DEFAULT '',
        deposit_cents INTEGER DEFAULT 0,
        created_at TEXT NOT NULL
    )
    """)
    db.execute("""
    CREATE INDEX IF NOT EXISTS idx_bookings_date_slot
    ON bookings(event_date, slot_code)
    """)
    db.commit()


# -------------------------
# Auth
# -------------------------
@app.before_request
def before():
    init_db()
    if request.endpoint not in ("login", "static") and not session.get("auth"):
        return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    msg = ""
    if request.method == "POST":
        if (request.form.get("pin") or "").strip() == APP_PIN:
            session["auth"] = True
            return redirect(url_for("calendar_month"))
        msg = "<div class='msg'>PIN errato</div>"

    return f"""<!doctype html>
<html><head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{APP_NAME} – Login</title>
<style>
  body{{font-family:system-ui,-apple-system,Segoe UI,Roboto;margin:20px;background:#f6f7fb;}}
  .card{{max-width:420px;margin:60px auto;background:#fff;border:1px solid #e5e5e5;border-radius:14px;padding:16px;}}
  input{{width:100%;padding:12px;border-radius:12px;border:1px solid #ddd;font-size:16px;}}
  button{{width:100%;padding:12px;border-radius:12px;border:0;background:#111;color:#fff;font-weight:800;font-size:16px;margin-top:10px;}}
  .msg{{margin-top:10px;color:#b00020;font-weight:700;}}
</style>
</head><body>
  <div class="card">
    <h2 style="margin:0 0 6px 0;">{APP_NAME}</h2>
    <div style="opacity:.7;margin-bottom:10px;">Inserisci PIN</div>
    <form method="post">
      <input name="pin" type="password" inputmode="numeric" placeholder="PIN" autofocus />
      <button type="submit">Entra</button>
    </form>
    {msg}
  </div>
</body></html>
"""

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# -------------------------
# Slot rules
# -------------------------
def slots_for_date(d: date):
    slots = [{
        "code": "AFTERNOON",
        "label": "POMERIDIANO/SERALE",
        "start": "17:00",
        "end": "20:00",
    }]
    if d.weekday() in (5, 6):  # Sat/Sun
        slots.insert(0, {
            "code": "MORNING",
            "label": "MATTINA",
            "start": "09:30",
            "end": "12:30",
        })
    return slots


# -------------------------
# Counts
# -------------------------
def day_total_events(date_iso: str) -> int:
    db = get_db()
    r = db.execute("SELECT COUNT(*) AS c FROM bookings WHERE event_date=?", (date_iso,)).fetchone()
    return int(r["c"])

def slot_count(date_iso: str, slot_code: str) -> int:
    db = get_db()
    r = db.execute(
        "SELECT COUNT(*) AS c FROM bookings WHERE event_date=? AND slot_code=?",
        (date_iso, slot_code)
    ).fetchone()
    return int(r["c"])


# -------------------------
# UI helpers
# -------------------------
def topbar(active: str = "month"):
    # pulsante calendario sempre visibile
    return f"""
    <div class="topbar">
      <div class="left">
        <a class="btn {'primary' if active=='month' else ''}" href="{url_for('calendar_month')}">📆 Calendario</a>
        <a class="btn {'primary' if active=='year' else ''}" href="{url_for('calendar_year')}">🗓️ Anno</a>
      </div>
      <div class="right">
        <a class="btn" href="{url_for('logout')}">Esci</a>
      </div>
    </div>
    """

BASE_CSS = """
<style>
  body{font-family:system-ui,-apple-system,Segoe UI,Roboto; margin:16px; background:#f6f7fb;}
  a{color:inherit}
  .topbar{display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:14px;flex-wrap:wrap;}
  .left,.right{display:flex;gap:8px;align-items:center;flex-wrap:wrap;}
  .btn{display:inline-block;padding:10px 12px;border:1px solid #ddd;background:#fff;border-radius:12px;text-decoration:none;font-weight:750;}
  .btn.primary{background:#111;color:#fff;border-color:#111;}
  .card{background:#fff;border:1px solid #e5e5e5;border-radius:14px;padding:12px;}
  .head{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;}
  .muted{opacity:.7}
  .grid{display:grid;grid-template-columns:repeat(7,1fr);gap:8px;margin-top:10px;}
  .cell{background:#fff;border:1px solid #e5e5e5;border-radius:12px;padding:10px;min-height:86px;}
  .cell.empty{background:transparent;border:0;}
  .daynum{font-weight:900;}
  .bar{margin-top:8px;padding:6px;border-radius:10px;font-size:12px;font-weight:800;border:1px solid #eee;}
  .bar.green{background:#eaffea;border-color:#b7e6b7;}
  .bar.yellow{background:#fff8d8;border-color:#f1df86;}
  .bar.red{background:#ffe1e1;border-color:#f2a0a0;}
  .open{display:inline-block;margin-top:8px;font-weight:800;text-decoration:none;}
  select{padding:10px;border-radius:12px;border:1px solid #ddd;background:#fff;font-weight:700;}
  .row{display:flex;gap:8px;align-items:center;flex-wrap:wrap;}
  .slot{border:1px solid #ddd;border-radius:14px;background:#fff;padding:12px;margin-top:10px;}
  .slothead{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;}
  .pill{font-size:12px;font-weight:900;padding:4px 8px;border-radius:999px;background:#111;color:#fff;}
</style>
"""


# -------------------------
# Calendar Month (iPhone-like navigation)
# -------------------------
@app.route("/")
def calendar_month():
    today = date.today()
    y = int(request.args.get("y", today.year))
    m = int(request.args.get("m", today.month))

    # prev/next month
    prev_y, prev_m = (y - 1, 12) if m == 1 else (y, m - 1)
    next_y, next_m = (y + 1, 1) if m == 12 else (y, m + 1)

    # month grid
    weeks = monthcalendar(y, m)

    # month/year selectors
    month_options = "".join(
        [f"<option value='{i}' {'selected' if i==m else ''}>{month_name[i]}</option>" for i in range(1, 13)]
    )
    year_options = "".join(
        [f"<option value='{yy}' {'selected' if yy==y else ''}>{yy}</option>" for yy in range(today.year - 3, today.year + 6)]
    )

    cells_html = ""
    for w in weeks:
        for dnum in w:
            if dnum == 0:
                cells_html += "<div class='cell empty'></div>"
                continue

            d_iso = date(y, m, dnum).isoformat()
            c = day_total_events(d_iso)

            # colore barra (semplice per ora): 0 verde, 1 giallo, 2+ rosso
            col = "green" if c == 0 else "yellow" if c == 1 else "red"

            cells_html += f"""
              <div class="cell">
                <div class="daynum">{dnum}</div>
                <div class="bar {col}">{c} eventi</div>
                <a class="open" href="{url_for('day_view', date_iso=d_iso)}">Apri</a>
              </div>
            """

    return f"""<!doctype html>
<html><head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{APP_NAME}</title>
{BASE_CSS}
</head><body>
  {topbar('month')}

  <div class="card">
    <div class="head">
      <div>
        <h2 style="margin:0;">{month_name[m]} {y}</h2>
        <div class="muted">Come iPhone: mese corrente + scorrimento mesi</div>
      </div>
      <div class="row">
        <a class="btn" href="{url_for('calendar_month', y=prev_y, m=prev_m)}">←</a>
        <a class="btn" href="{url_for('calendar_month', y=next_y, m=next_m)}">→</a>
      </div>
    </div>

    <form class="row" method="get" action="/" style="margin-top:10px;">
      <select name="m">{month_options}</select>
      <select name="y">{year_options}</select>
      <button class="btn" type="submit">Vai</button>
      <a class="btn" href="{url_for('calendar_month', y=today.year, m=today.month)}">Oggi</a>
    </form>

    <div class="grid">
      {cells_html}
    </div>
  </div>
</body></html>
"""


# -------------------------
# Year view (optional, quick)
# -------------------------
@app.route("/year")
def calendar_year():
    today = date.today()
    y = int(request.args.get("y", today.year))

    months = []
    for mm in range(1, 13):
        start = date(y, mm, 1)
        end = date(y + 1, 1, 1) if mm == 12 else date(y, mm + 1, 1)
        db = get_db()
        c = db.execute("""
          SELECT COUNT(*) AS c FROM bookings
          WHERE event_date >= ? AND event_date < ?
        """, (start.isoformat(), end.isoformat())).fetchone()["c"]
        months.append((mm, int(c)))

    cards = ""
    for mm, cnt in months:
        cards += f"""
          <div class="cell" style="min-height:auto;">
            <div style="font-weight:900;">{month_name[mm]}</div>
            <div class="bar {'green' if cnt==0 else 'yellow' if cnt<3 else 'red'}">{cnt} eventi</div>
            <a class="open" href="{url_for('calendar_month', y=y, m=mm)}">Apri</a>
          </div>
        """

    return f"""<!doctype html>
<html><head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{APP_NAME} – Anno</title>
{BASE_CSS}
</head><body>
  {topbar('year')}
  <div class="card">
    <div class="head">
      <h2 style="margin:0;">Anno {y}</h2>
      <div class="row">
        <a class="btn" href="{url_for('calendar_year', y=y-1)}">← {y-1}</a>
        <a class="btn" href="{url_for('calendar_year', y=y+1)}">{y+1} →</a>
      </div>
    </div>
    <div class="grid" style="grid-template-columns:repeat(3,1fr); margin-top:10px;">
      {cards}
    </div>
  </div>
</body></html>
"""


# -------------------------
# Day view + "Aggiungi festa"
# -------------------------
@app.route("/day/<date_iso>")
def day_view(date_iso):
    try:
        d = datetime.strptime(date_iso, "%Y-%m-%d").date()
    except ValueError:
        abort(404)

    slots = slots_for_date(d)

    blocks = ""
    for s in slots:
        c = slot_count(date_iso, s["code"])
        blocks += f"""
        <div class="slot">
          <div class="slothead">
            <div>
              <div style="font-weight:900;">{s['start']}–{s['end']} <span class="muted">({s['label']})</span></div>
              <div class="muted">Prenotazioni nello slot: <b>{c}/2</b></div>
            </div>
            <a class="btn primary" href="{url_for('booking_new')}?date={date_iso}&slot={s['code']}">➕ Aggiungi festa</a>
          </div>
        </div>
        """

    return f"""<!doctype html>
<html><head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{APP_NAME} – Giorno</title>
{BASE_CSS}
</head><body>
  {topbar('month')}
  <div class="card">
    <div class="head">
      <div>
        <h2 style="margin:0;">{d.strftime('%A %d %B %Y')}</h2>
        <div class="muted">Qui scegli lo slot e aggiungi la festa (stile “+” iPhone)</div>
      </div>
      <a class="btn" href="{url_for('calendar_month', y=d.year, m=d.month)}">← Torna al mese</a>
    </div>
    {blocks}
  </div>
</body></html>
"""


# -------------------------
# Booking placeholder (poi ricolleghiamo il software completo)
# -------------------------
@app.route("/booking/new")
def booking_new():
    date_iso = request.args.get("date")
    slot = request.args.get("slot")
    if not date_iso or not slot:
        abort(400)

    return f"""<!doctype html>
<html><head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{APP_NAME} – Nuova festa</title>
{BASE_CSS}
</head><body>
  {topbar('month')}
  <div class="card">
    <h2 style="margin:0;">Nuova festa</h2>
    <div class="muted" style="margin-top:6px;">Data: <b>{date_iso}</b> · Slot: <b>{slot}</b></div>

    <div style="margin-top:12px;">
      <span class="pill">STEP SUCCESSIVO</span>
      <div class="muted" style="margin-top:8px;">
        Qui agganciamo il software di prenotazione completo (nome bimbo, età, tema, pacchetto, telefono, acconto, ecc.)
      </div>
    </div>

    <div style="margin-top:12px;">
      <a class="btn" href="{url_for('day_view', date_iso=date_iso)}">← Annulla</a>
    </div>
  </div>
</body></html>
"""


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
