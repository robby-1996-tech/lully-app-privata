import os
import sqlite3
from datetime import datetime
from flask import Flask, request, redirect, url_for, session, render_template_string, abort

app = Flask(__name__)

APP_NAME = "Lullyland"

app.secret_key = os.getenv("SECRET_KEY", "dev-secret-key-change-me")
APP_PIN = os.getenv("APP_PIN", "1234")

DB_PATH = os.getenv("DB_PATH", "lullyland.db")


# -------------------------
# DB helpers
# -------------------------
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT,

            nome_festeggiato TEXT,
            eta_festeggiato INTEGER,
            data_compleanno TEXT,
            data_evento TEXT,

            madre_nome_cognome TEXT,
            madre_telefono TEXT,
            padre_nome_cognome TEXT,
            padre_telefono TEXT,

            indirizzo_residenza TEXT,
            email TEXT,

            invitati_bambini INTEGER,
            invitati_adulti INTEGER,

            pacchetto TEXT,
            dettagli_personalizzato TEXT,
            tema_evento TEXT,
            note TEXT,

            acconto REAL,

            data_firma TEXT,
            firma_png_base64 TEXT,

            consenso_privacy INTEGER,
            consenso_foto INTEGER
        )
        """
    )
    conn.commit()
    conn.close()


init_db()


# -------------------------
# Auth
# -------------------------
def is_logged_in():
    return session.get("ok") is True


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("pin") == APP_PIN:
            session["ok"] = True
            return redirect(url_for("home"))
        return render_template_string(LOGIN_HTML, error="PIN errato.", app_name=APP_NAME)
    return render_template_string(LOGIN_HTML, error=None, app_name=APP_NAME)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# -------------------------
# Pages
# -------------------------
@app.route("/")
def home():
    if not is_logged_in():
        return redirect(url_for("login"))
    return render_template_string(HOME_HTML, app_name=APP_NAME)


@app.route("/prenota", methods=["GET", "POST"])
def prenota():
    if not is_logged_in():
        return redirect(url_for("login"))

    if request.method == "POST":
        consenso_privacy = 1 if request.form.get("consenso_privacy") else 0
        consenso_foto = 1 if request.form.get("consenso_foto") else 0

        if consenso_privacy != 1:
            return render_template_string(BOOKING_HTML, error="Devi accettare la privacy.", today=datetime.now().strftime("%Y-%m-%d"), form=request.form, app_name=APP_NAME)

        firma = request.form.get("firma_png_base64", "")
        if not firma.startswith("data:image/png;base64"):
            return render_template_string(BOOKING_HTML, error="Firma obbligatoria.", today=datetime.now().strftime("%Y-%m-%d"), form=request.form, app_name=APP_NAME)

        pacchetto = request.form.get("pacchetto")
        dettagli_personalizzato = request.form.get("dettagli_personalizzato", "").strip()

        if pacchetto == "Personalizzato" and not dettagli_personalizzato:
            return render_template_string(
                BOOKING_HTML,
                error="Inserisci i dettagli del pacchetto personalizzato.",
                today=datetime.now().strftime("%Y-%m-%d"),
                form=request.form,
                app_name=APP_NAME,
            )

        conn = get_db()
        conn.execute(
            """
            INSERT INTO bookings (
                created_at, nome_festeggiato, eta_festeggiato, data_compleanno, data_evento,
                madre_nome_cognome, madre_telefono, padre_nome_cognome, padre_telefono,
                indirizzo_residenza, email, invitati_bambini, invitati_adulti,
                pacchetto, dettagli_personalizzato, tema_evento, note, acconto,
                data_firma, firma_png_base64, consenso_privacy, consenso_foto
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                datetime.now().isoformat(timespec="seconds"),
                request.form.get("nome_festeggiato"),
                request.form.get("eta_festeggiato"),
                request.form.get("data_compleanno"),
                request.form.get("data_evento"),
                request.form.get("madre_nome_cognome"),
                request.form.get("madre_telefono"),
                request.form.get("padre_nome_cognome"),
                request.form.get("padre_telefono"),
                request.form.get("indirizzo_residenza"),
                request.form.get("email"),
                request.form.get("invitati_bambini"),
                request.form.get("invitati_adulti"),
                pacchetto,
                dettagli_personalizzato,
                request.form.get("tema_evento"),
                request.form.get("note"),
                request.form.get("acconto"),
                request.form.get("data_firma"),
                firma,
                consenso_privacy,
                consenso_foto,
            ),
        )
        conn.commit()
        conn.close()

        return redirect(url_for("prenotazioni"))

    return render_template_string(BOOKING_HTML, error=None, today=datetime.now().strftime("%Y-%m-%d"), form={}, app_name=APP_NAME)


@app.route("/prenotazioni")
def prenotazioni():
    if not is_logged_in():
        return redirect(url_for("login"))

    conn = get_db()
    rows = conn.execute("SELECT id, nome_festeggiato, data_evento, pacchetto FROM bookings ORDER BY id DESC").fetchall()
    conn.close()
    return render_template_string(LIST_HTML, rows=rows, app_name=APP_NAME)


@app.route("/prenotazioni/<int:booking_id>")
def prenotazione_dettaglio(booking_id):
    if not is_logged_in():
        return redirect(url_for("login"))

    conn = get_db()
    row = conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
    conn.close()

    if not row:
        abort(404)

    return render_template_string(DETAIL_HTML, b=row, app_name=APP_NAME)


# -------------------------
# HTML (BOOKING: solo piccole aggiunte)
# -------------------------

# ⚠️ NOTA:
# Nel BOOKING_HTML aggiungi:
# - option "Personalizzato"
# - textarea dettagli
# - campo acconto
# - JS toggle
# (tutto il resto è IDENTICO)

# 👉 Se vuoi, nel prossimo messaggio ti mando SOLO
# il BOOKING_HTML isolato evidenziando le righe nuove
