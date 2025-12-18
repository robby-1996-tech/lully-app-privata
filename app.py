import os
import sqlite3
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import traceback

from flask import (
    Flask,
    request,
    redirect,
    url_for,
    session,
    render_template_string,
    abort,
)

app = Flask(__name__)

APP_NAME = "Lullyland"

app.secret_key = os.getenv("SECRET_KEY", "dev-secret-key-change-me")
APP_PIN = os.getenv("APP_PIN", "1234")

DB_PATH = os.getenv("DB_PATH", "lullyland.db")

# -------------------------
# Prezzi
# -------------------------
PACKAGE_PRICES_EUR = {
    "Fai da Te": Decimal("15.00"),
    "Lullyland Experience": Decimal("20.00"),
    "Lullyland all-inclusive": Decimal("30.00"),
    "Personalizzato": Decimal("0.00"),
}

PACKAGE_LABELS = {
    "Fai da Te": "Fai da Te €15 a persona",
    "Lullyland Experience": "Lullyland Experience €20 a persona",
    "Lullyland all-inclusive": "Lullyland All-inclusive €30 a persona",
    "Personalizzato": "Personalizzato",
}

# -------------------------
# DATE – PARSER BLINDATO (NO datetime.strptime)
# -------------------------
def parse_manual_date(value: str):
    if not value:
        return None

    v = value.strip()

    # GG/MM/AAAA
    if "/" in v:
        try:
            d, m, y = v.split("/")
            if len(d) == 2 and len(m) == 2 and len(y) == 4:
                return f"{y}-{m}-{d}"
        except Exception:
            return None

    # AAAA-MM-GG
    if "-" in v:
        try:
            y, m, d = v.split("-")
            if len(d) == 2 and len(m) == 2 and len(y) == 4:
                return f"{y}-{m}-{d}"
        except Exception:
            return None

    return None


# -------------------------
# DB
# -------------------------
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT,
            nome_festeggiato TEXT,
            data_compleanno TEXT,
            data_evento TEXT,
            pacchetto TEXT,
            note TEXT
        )
        """
    )
    conn.commit()
    conn.close()


init_db()

# -------------------------
# ERROR HANDLER (STOP AI 500)
# -------------------------
@app.errorhandler(Exception)
def handle_any_exception(e):
    if not session.get("ok"):
        return "Internal Server Error", 500

    tb = traceback.format_exc()
    return f"""
    <h2>ERRORE SERVER (dettaglio)</h2>
    <p><b>{type(e).__name__}:</b> {e}</p>
    <pre>{tb}</pre>
    <a href="/">Home</a>
    """, 500


# -------------------------
# AUTH
# -------------------------
def is_logged_in():
    return session.get("ok") is True


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("pin") == APP_PIN:
            session["ok"] = True
            return redirect("/")
        return "PIN errato"
    return """
    <form method="post">
      <input type="password" name="pin" placeholder="PIN">
      <button>Entra</button>
    </form>
    """


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


# -------------------------
# HOME
# -------------------------
@app.route("/")
def home():
    if not is_logged_in():
        return redirect("/login")
    return """
    <h1>Lullyland</h1>
    <a href="/prenota">+ Nuova prenotazione</a><br>
    <a href="/prenotazioni">Vedi prenotazioni</a><br>
    <a href="/logout">Esci</a>
    """


# -------------------------
# PRENOTA
# -------------------------
@app.route("/prenota", methods=["GET", "POST"])
def prenota():
    if not is_logged_in():
        return redirect("/login")

    if request.method == "POST":
        nome = request.form.get("nome_festeggiato", "").strip()
        data_evento_raw = request.form.get("data_evento", "").strip()
        data_compleanno_raw = request.form.get("data_compleanno", "").strip()
        pacchetto = request.form.get("pacchetto", "").strip()
        note = request.form.get("note", "").strip()

        data_evento = parse_manual_date(data_evento_raw)
        if not data_evento:
            return "Data evento non valida"

        data_compleanno = None
        if data_compleanno_raw:
            data_compleanno = parse_manual_date(data_compleanno_raw)
            if not data_compleanno:
                return "Data compleanno non valida"

        conn = get_db()
        conn.execute(
            """
            INSERT INTO bookings
            (created_at, nome_festeggiato, data_compleanno, data_evento, pacchetto, note)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now().isoformat(timespec="seconds"),
                nome,
                data_compleanno,
                data_evento,
                pacchetto,
                note,
            ),
        )
        conn.commit()
        conn.close()

        return redirect("/prenotazioni")

    return """
    <h2>Nuova prenotazione</h2>
    <form method="post">
      Nome festeggiato<br>
      <input name="nome_festeggiato"><br><br>

      Data compleanno (05052026)<br>
      <input id="data_compleanno" name="data_compleanno"><br><br>

      Data evento (05052026)*<br>
      <input id="data_evento" name="data_evento" required><br><br>

      Pacchetto<br>
      <select name="pacchetto">
        <option>Fai da Te</option>
        <option>Lullyland Experience</option>
        <option>Lullyland all-inclusive</option>
        <option>Personalizzato</option>
      </select><br><br>

      Note<br>
      <textarea name="note"></textarea><br><br>

      <button>Salva</button>
    </form>

    <script>
    function mask(el){
      el.addEventListener('input',function(){
        let v=this.value.replace(/\\D/g,'').slice(0,8);
        if(v.length>=5) this.value=v.slice(0,2)+'/'+v.slice(2,4)+'/'+v.slice(4);
        else if(v.length>=3) this.value=v.slice(0,2)+'/'+v.slice(2);
        else this.value=v;
      });
    }
    mask(document.getElementById('data_evento'));
    mask(document.getElementById('data_compleanno'));
    </script>
    """


# -------------------------
# LISTA
# -------------------------
@app.route("/prenotazioni")
def prenotazioni():
    if not is_logged_in():
        return redirect("/login")

    conn = get_db()
    rows = conn.execute("SELECT * FROM bookings ORDER BY id DESC").fetchall()
    conn.close()

    html = "<h2>Prenotazioni</h2><a href='/'>Home</a><br><br>"
    for r in rows:
        html += f"""
        <div>
        <b>{r['nome_festeggiato']}</b> – {r['data_evento']} – {r['pacchetto']}
        </div>
        """
    return html


# -------------------------
# RUN
# -------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
