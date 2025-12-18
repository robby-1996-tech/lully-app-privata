# === LULLYLAND APP - CALENDARIO + PRENOTAZIONI ===
# File unico app.py
# Copia e incolla TUTTO questo file su GitHub / Render

import os
import sqlite3
from datetime import datetime, date
from decimal import Decimal, ROUND_HALF_UP
from calendar import monthcalendar, month_name

from flask import (
    Flask, request, redirect, url_for, session,
    render_template_string, abort
)

app = Flask(__name__)

APP_NAME = "Lullyland"
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-key-change-me")
APP_PIN = os.getenv("APP_PIN", "1234")
DB_PATH = os.getenv("DB_PATH", "lullyland.db")

# =======================
# PREZZI E CATALOGHI
# =======================
PACKAGE_PRICES_EUR = {
    "Fai da Te": Decimal("15.00"),
    "Lullyland Experience": Decimal("20.00"),
    "Lullyland all-inclusive": Decimal("30.00"),
    "Personalizzato": Decimal("0.00"),
}

PACKAGE_LABELS = {
    "Fai da Te": "Fai da Te EUR 15,00 a persona",
    "Lullyland Experience": "Lullyland Experience EUR 20,00 a persona",
    "Lullyland all-inclusive": "Lullyland All-inclusive EUR 30,00 a persona",
    "Personalizzato": "Personalizzato",
}

# =======================
# DATABASE
# =======================
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute("""
    CREATE TABLE IF NOT EXISTS bookings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT,
        event_date TEXT,
        slot_code TEXT,
        area INTEGER,
        nome_festeggiato TEXT,
        eta_festeggiato INTEGER,
        invitati_bambini INTEGER,
        invitati_adulti INTEGER,
        pacchetto TEXT,
        tema_evento TEXT,
        note TEXT
    )
    """)
    conn.commit()
    conn.close()

init_db()

# =======================
# AUTH
# =======================
def is_logged_in():
    return session.get("ok") is True

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        if request.form.get("pin") == APP_PIN:
            session["ok"] = True
            return redirect(url_for("calendar_month"))
        return "PIN errato"
    return "<form method='post'><input name='pin'><button>Entra</button></form>"

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# =======================
# CALENDARIO MESE
# =======================
@app.route("/")
def calendar_month():
    if not is_logged_in():
        return redirect(url_for("login"))

    today = date.today()
    y = int(request.args.get("y", today.year))
    m = int(request.args.get("m", today.month))

    weeks = monthcalendar(y, m)
    html = "<h1>{} {}</h1>".format(month_name[m], y)

    for w in weeks:
        for d in w:
            if d != 0:
                iso = date(y,m,d).isoformat()
                html += f"<div><a href='/day/{iso}'>{d}</a></div>"
    return html

# =======================
# GIORNO
# =======================
@app.route("/day/<date_iso>")
def day_view(date_iso):
    if not is_logged_in():
        return redirect(url_for("login"))

    return f"""
    <h2>{date_iso}</h2>
    <a href='/booking/new?date={date_iso}&slot=AFTERNOON'>➕ Aggiungi evento</a>
    """

# =======================
# BOOKING (placeholder completo)
# =======================
BOOKING_HTML = '''
<h1>Nuovo evento {{event_date}}</h1>
<form method="post">
  <label>Nome festeggiato</label>
  <input name="nome_festeggiato" required><br>
  <label>Età</label>
  <input name="eta_festeggiato" type="number"><br>
  <label>Bambini</label>
  <input name="invitati_bambini" type="number"><br>
  <label>Adulti</label>
  <input name="invitati_adulti" type="number"><br>
  <label>Pacchetto</label>
  <select name="pacchetto">
    {% for k,v in package_labels.items() %}
    <option value="{{k}}">{{v}}</option>
    {% endfor %}
  </select><br>
  <label>Tema</label>
  <input name="tema_evento"><br>
  <label>Note</label>
  <textarea name="note"></textarea><br>
  <button type="submit">Salva evento</button>
</form>
'''

@app.route("/booking/new", methods=["GET","POST"])
def booking_new():
    if not is_logged_in():
        return redirect(url_for("login"))

    event_date = request.args.get("date")
    slot_code = request.args.get("slot")

    if request.method == "POST":
        conn = get_db()
        conn.execute("""
        INSERT INTO bookings (
            created_at,event_date,slot_code,area,
            nome_festeggiato,eta_festeggiato,
            invitati_bambini,invitati_adulti,
            pacchetto,tema_evento,note
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (
            datetime.now().isoformat(),
            event_date, slot_code, 1,
            request.form.get("nome_festeggiato"),
            request.form.get("eta_festeggiato"),
            request.form.get("invitati_bambini"),
            request.form.get("invitati_adulti"),
            request.form.get("pacchetto"),
            request.form.get("tema_evento"),
            request.form.get("note"),
        ))
        conn.commit()
        conn.close()
        return redirect(url_for("calendar_month"))

    return render_template_string(
        BOOKING_HTML,
        event_date=event_date,
        package_labels=PACKAGE_LABELS
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
