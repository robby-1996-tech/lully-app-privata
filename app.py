# app_lullyland_completo_v2.py
import os
import sqlite3
import base64
import io
from datetime import datetime, date
from decimal import Decimal, ROUND_HALF_UP
from calendar import monthcalendar, month_name

from flask import Flask, request, redirect, url_for, session, render_template_string, abort, send_file


app = Flask(__name__)

APP_NAME = "Lullyland"
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-key-change-me")
APP_PIN = os.getenv("APP_PIN", "1234")
DB_PATH = os.getenv("DB_PATH", "lullyland.db")

# -------------------------
# Cataloghi e prezzi
# -------------------------
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

CATERING_BABY_OPTIONS = {
    "menu_pizza": "Menu pizza",
    "box_merenda": "Box merenda",
}

TORTA_PRICE_EUR_PER_KG = Decimal("24.00")
TORTA_ESTERNASVC_EUR_PER_PERSON = Decimal("1.00")
KG_PER_PERSON = Decimal("0.10")

TORTA_INTERNA_FLAVORS = {
    "standard": "Pan di spagna analcolico con crema chantilly e gocce di cioccolato",
    "altro": "Altro (scrivi gusto)",
}

DESSERT_OPTIONS = {
    "muffin_nutella": "Muffin alla Nutella",
    "torta_compleanno": "Torta di compleanno",
}

EXTRA_SERVIZI = {
    "zucchero_filato": ("Carretto zucchero filato illimitati", Decimal("50.00")),
    "pop_corn": ("Carretto pop corn illimitati", Decimal("50.00")),
    "torta_scenografica": ("Noleggio torta scenografica", Decimal("45.00")),
    "intrattenitore": ("Intrattenitore", Decimal("100.00")),
    "bolle_sapone": ("Spettacolo bolle di sapone", Decimal("200.00")),
    "mascotte_standard": ("Servizio mascotte standard", Decimal("65.00")),
    "mascotte_deluxe": ("Servizio mascotte deluxe", Decimal("90.00")),
}

EXTRA_SERVIZI_ALL_INCLUSIVE = {
    "bolle_sapone": ("Spettacolo bolle di sapone", Decimal("200.00")),
    "mascotte_standard": ("Servizio mascotte standard", Decimal("65.00")),
    "mascotte_deluxe": ("Servizio mascotte deluxe", Decimal("90.00")),
}

# -------------------------
# DB helpers
# -------------------------
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_column(conn, table: str, col_name: str, col_type: str):
    cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if col_name not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}")


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
            tema_evento TEXT,
            note TEXT,

            data_firma TEXT,
            firma_png_base64 TEXT,

            consenso_privacy INTEGER,
            consenso_foto INTEGER
        )
        """
    )

    ensure_column(conn, "bookings", "acconto_eur", "TEXT")
    ensure_column(conn, "bookings", "pacchetto_personalizzato_dettagli", "TEXT")

    ensure_column(conn, "bookings", "catering_baby_choice", "TEXT")

    ensure_column(conn, "bookings", "torta_choice", "TEXT")
    ensure_column(conn, "bookings", "torta_interna_choice", "TEXT")
    ensure_column(conn, "bookings", "torta_gusto_altro", "TEXT")

    ensure_column(conn, "bookings", "dessert_bimbi_choice", "TEXT")
    ensure_column(conn, "bookings", "dessert_adulti_choice", "TEXT")

    ensure_column(conn, "bookings", "extra_keys_csv", "TEXT")
    ensure_column(conn, "bookings", "totale_stimato_eur", "TEXT")
    ensure_column(conn, "bookings", "dettagli_contratto_text", "TEXT")

    # Calendario
    ensure_column(conn, "bookings", "event_date", "TEXT")
    ensure_column(conn, "bookings", "slot_code", "TEXT")
    ensure_column(conn, "bookings", "start_time", "TEXT")
    ensure_column(conn, "bookings", "end_time", "TEXT")
    ensure_column(conn, "bookings", "area", "INTEGER")

    conn.execute("""
      CREATE INDEX IF NOT EXISTS idx_bookings_calendar
      ON bookings(event_date, slot_code)
    """)

    conn.commit()
    conn.close()


init_db()

# -------------------------
# Utility
# -------------------------
def is_logged_in():
    return session.get("ok") is True


def to_int(val):
    try:
        return int(val) if val not in (None, "",) else None
    except Exception:
        return None



def first_nonempty(values):
    """Return first non-empty string from a list-like; otherwise ''"""
    for v in values or []:
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s
    return ""

def eur(d: Decimal) -> str:
    q = d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    s = f"{q:.2f}"
    return s.replace(".", ",")


def build_contract_text(payload: dict) -> str:
    pacchetto = payload.get("pacchetto", "")
    invitati_b = payload.get("invitati_bambini") or 0
    invitati_a = payload.get("invitati_adulti") or 0
    tot_persone = int(invitati_b) + int(invitati_a)

    lines = []
    if pacchetto in ("Fai da Te", "Lullyland Experience", "Lullyland all-inclusive"):
        price = PACKAGE_PRICES_EUR.get(pacchetto, Decimal("0.00"))
        lines.append(f"PACCHETTO: {pacchetto} - EUR {eur(price)} a persona")
    else:
        lines.append(f"PACCHETTO: {pacchetto}")

    if pacchetto == "Fai da Te":
        lines += [
            "",
            "INCLUDE:",
            "- Accesso al parco giochi di 350mq",
            "- Pulizia e igienizzazione impeccabili prima e dopo la festa",
            "- Area riservata con tavoli e sedie",
            "- Tavolo torta con gonna e tovaglia monocolore, lavagnetta con nome e anni del festeggiato e sfondo a tema",
            "",
            "NON INCLUDE:",
            "- Piatti, bicchieri, tovaglioli, tovaglie",
            "- Servizio",
            "- Sgombero tavoli",
            "",
            "NOTE IMPORTANTI (REGOLE):",
            "- E' obbligatorio fornire certificazione alimentare sia per il buffet che per la torta (fornita dal fornitore da loro scelto)",
            "- E' obbligatorio acquistare le bibite al nostro bar, non e' possibile introdurre bevande dall'esterno",
            "- E' obbligatorio l'utilizzo di calzini antiscivolo per tutti i bambini che usufruiranno del parco",
            "- E' severamente vietato entrare all'interno del parco con scarpe con tacchi (pavimentazione antitrauma in gomma): pena addebito EUR 60,00 per ogni mattonella antitrauma forata",
            "- E' obbligatorio l'utilizzo di copri scarpe all'interno del parco (da noi forniti)",
            "- E' severamente vietato introdurre cibo e bevande all'interno del parco",
        ]

    elif pacchetto == "Lullyland Experience":
        catering_choice = payload.get("catering_baby_choice") or ""
        torta_choice = payload.get("torta_choice") or ""
        torta_interna_choice = payload.get("torta_interna_choice") or ""
        torta_gusto_altro = payload.get("torta_gusto_altro") or ""

        lines += [
            "",
            "INCLUDE:",
            "- Accesso al parco giochi di 350mq",
            "- Pulizia e igienizzazione impeccabili prima e dopo la festa",
            "- Area riservata con tavoli e sedie",
            "- Tavolo torta con gonna e tovaglia monocolore, lavagnetta con nome e anni del festeggiato e sfondo a tema",
            "- Piatti, bicchieri, tovaglioli",
        ]

        if catering_choice == "menu_pizza":
            lines.append("- Catering baby: Menu pizza: Pizza Baby, patatine, bottiglietta dell'acqua")
        elif catering_choice == "box_merenda":
            lines.append("- Catering baby: Box merenda: sandwich con prosciutto cotto, rustico wurstel, mini pizzetta, panzerottino, patatine fritte, bottiglietta dell'acqua")
        else:
            lines.append("- Catering baby: (da definire)")

        lines.append("- Catering adulti: fritti centrali (panzerottini, patatine, bandidos, crocchette), pizze centrali margherita e bibite centrali da 1,5lt (acqua, Coca-Cola, Fanta)")

        lines += ["", "NON INCLUDE:", "- Torta di compleanno", ""]

        if torta_choice == "esterna":
            lines += [
                "TORTA (ESTERNA):",
                f"- Torta esterna: +EUR {eur(TORTA_ESTERNASVC_EUR_PER_PERSON)} a persona (servizio torta)",
            ]
        else:
            lines.append(f"TORTA (SCELTA) (EUR {eur(TORTA_PRICE_EUR_PER_KG)} al chilo):")
            if torta_choice == "interna":
                if torta_interna_choice == "standard":
                    lines.append(f"- Torta interna (da noi): {TORTA_INTERNA_FLAVORS['standard']}")
                elif torta_interna_choice == "altro":
                    lines.append(f"- Torta interna (da noi): Gusto concordato: {torta_gusto_altro or '(da compilare)'}")
                else:
                    lines.append("- Torta interna (da noi): (da definire)")
            else:
                lines.append("- (da definire)")

        extra_keys = payload.get("extra_keys", [])
        if extra_keys:
            lines += ["", "SERVIZI EXTRA (selezionati):"]
            tot_extra = Decimal("0.00")
            for k in extra_keys:
                if k in EXTRA_SERVIZI:
                    name, price = EXTRA_SERVIZI[k]
                    tot_extra += price
                    lines.append(f"- {name} EUR {eur(price)}")
            lines.append(f"Totale extra: EUR {eur(tot_extra)}")

        lines += ["", "NOTE IMPORTANTI (REGOLE):"]
        if torta_choice == "esterna":
            lines.append("- (Torta esterna) E' obbligatorio fornire certificazione alimentare per la torta (fornita dal fornitore da loro scelto)")
        lines += [
            "- E' obbligatorio l'utilizzo di calzini antiscivolo per tutti i bambini che usufruiranno del parco",
            "- E' severamente vietato entrare all'interno del parco con scarpe con tacchi (pavimentazione antitrauma in gomma): pena addebito EUR 60,00 per ogni mattonella antitrauma forata",
            "- E' obbligatorio l'utilizzo di copri scarpe all'interno del parco (da noi forniti)",
            "- E' severamente vietato introdurre cibo e bevande all'interno del parco",
        ]

    elif pacchetto == "Lullyland all-inclusive":
        catering_choice = payload.get("catering_baby_choice") or ""
        dessert_bimbi = payload.get("dessert_bimbi_choice") or ""
        dessert_adulti = payload.get("dessert_adulti_choice") or ""
        torta_interna_choice = payload.get("torta_interna_choice") or ""
        torta_gusto_altro = payload.get("torta_gusto_altro") or ""

        lines += [
            "",
            "INCLUDE:",
            "- Accesso al parco giochi di 350mq",
            "- Pulizia e igienizzazione impeccabili prima e dopo la festa",
            "- Area riservata con tavoli e sedie",
            "- Tavolo torta con gonna e tovaglia monocolore, lavagnetta con nome e anni del festeggiato e sfondo a tema",
            "- Piatti, bicchieri, tovaglioli",
        ]

        if catering_choice == "menu_pizza":
            lines.append("- Catering baby: Menu pizza: Pizza Baby, patatine, bottiglietta dell'acqua")
        elif catering_choice == "box_merenda":
            lines.append("- Catering baby: Box merenda: sandwich con prosciutto cotto, rustico wurstel, mini pizzetta, panzerottino, patatine fritte e bottiglietta dell'acqua")
        else:
            lines.append("- Catering baby: (da definire)")

        lines += [
            "- Catering adulti: tagliere selezione Perina (burratina, ricottina, salumi, ciliegine di mozzarella)",
            "- Catering adulti: fritti centrali (panzerottini, patatine, bandidos, crocchette)",
            "- Catering adulti: pizze in modalita giro pizza farcite (fino ad un massimo di una a testa)",
            "- Bibita a testa tra birra, Coca-Cola, Fanta",
        ]

        # Dessert: solo Muffin o Torta
        lines.append(f"- Dessert per bambini: {DESSERT_OPTIONS.get(dessert_bimbi, '(da definire)')}")
        lines.append(f"- Dessert per adulti: {DESSERT_OPTIONS.get(dessert_adulti, '(da definire)')}")

        need_torta = (dessert_bimbi == "torta_compleanno") or (dessert_adulti == "torta_compleanno")
        if need_torta:
            lines += ["", "TORTA (inclusa nel pacchetto):"]
            if torta_interna_choice == "standard":
                lines.append(f"- Torta interna: {TORTA_INTERNA_FLAVORS['standard']}")
            elif torta_interna_choice == "altro":
                lines.append(f"- Torta interna: Gusto concordato: {torta_gusto_altro or '(da compilare)'}")
            else:
                lines.append("- Torta interna: (da definire)")

        lines += [
            "- Carretto zucchero filato illimitati",
            "- Carretto pop corn illimitati",
            "- Intrattenitore (salvo disponibilita)",
            "- Torta scenografica (noleggio)",
        ]

        extra_keys = payload.get("extra_keys", [])
        if extra_keys:
            lines += ["", "SERVIZI EXTRA (selezionati):"]
            tot_extra = Decimal("0.00")
            for k in extra_keys:
                if k in EXTRA_SERVIZI_ALL_INCLUSIVE:
                    name, price = EXTRA_SERVIZI_ALL_INCLUSIVE[k]
                    tot_extra += price
                    lines.append(f"- {name} EUR {eur(price)}")
            lines.append(f"Totale extra: EUR {eur(tot_extra)}")

        lines += [
            "",
            "NOTE IMPORTANTI (REGOLE):",
            "- E' obbligatorio l'utilizzo di calzini antiscivolo per tutti i bambini che usufruiranno del parco",
            "- E' severamente vietato entrare all'interno del parco con scarpe con tacchi (pavimentazione antitrauma in gomma): pena addebito EUR 60,00 per ogni mattonella antitrauma forata",
            "- E' obbligatorio l'utilizzo di copri scarpe all'interno del parco (da noi forniti)",
            "- E' severamente vietato introdurre cibo e bevande all'interno del parco",
        ]

    elif pacchetto == "Personalizzato":
        det = (payload.get("pacchetto_personalizzato_dettagli") or "").strip()
        lines += ["", "DETTAGLI PERSONALIZZAZIONE:", det if det else "(da compilare)"]

    return "\n".join(lines)


def compute_totals(payload: dict) -> dict:
    pacchetto = payload.get("pacchetto", "")
    invitati_b = int(payload.get("invitati_bambini") or 0)
    invitati_a = int(payload.get("invitati_adulti") or 0)
    tot_persone = invitati_b + invitati_a

    base_price = PACKAGE_PRICES_EUR.get(pacchetto, Decimal("0.00"))
    totale_pacchetto = base_price * Decimal(tot_persone)

    torta_choice = payload.get("torta_choice") or ""
    totale_torta = Decimal("0.00")
    torta_kg = Decimal("0.00")

    if pacchetto == "Lullyland Experience":
        if torta_choice == "esterna":
            totale_torta = TORTA_ESTERNASVC_EUR_PER_PERSON * Decimal(tot_persone)
        elif torta_choice == "interna":
            torta_kg = (Decimal(tot_persone) * KG_PER_PERSON).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            totale_torta = TORTA_PRICE_EUR_PER_KG * torta_kg

    # All-inclusive: torta inclusa -> nessun costo
    extra_keys = payload.get("extra_keys", [])
    totale_extra = Decimal("0.00")
    if pacchetto == "Lullyland all-inclusive":
        for k in extra_keys:
            if k in EXTRA_SERVIZI_ALL_INCLUSIVE:
                totale_extra += EXTRA_SERVIZI_ALL_INCLUSIVE[k][1]
    else:
        for k in extra_keys:
            if k in EXTRA_SERVIZI:
                totale_extra += EXTRA_SERVIZI[k][1]

    totale = (totale_pacchetto + totale_torta + totale_extra).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    return {"totale": totale, "totale_pacchetto": totale_pacchetto, "totale_torta": totale_torta, "totale_extra": totale_extra}

# -------------------------
# PDF: contratto scaricabile
# -------------------------
def _wrap_text(text: str, max_chars: int):
    lines = []
    for raw in (text or "").splitlines():
        s = raw.rstrip()
        if not s:
            lines.append("")
            continue
        while len(s) > max_chars:
            cut = s.rfind(" ", 0, max_chars)
            if cut <= 0:
                cut = max_chars
            lines.append(s[:cut].rstrip())
            s = s[cut:].lstrip()
        lines.append(s)
    return lines

def build_contract_pdf_bytes(row: sqlite3.Row) -> io.BytesIO:
    # Import locali per evitare crash in avvio se reportlab non è installato
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas as pdf_canvas
        from reportlab.lib.units import mm
        from reportlab.lib.utils import ImageReader
    except Exception as e:
        raise RuntimeError("Per generare il PDF serve la libreria 'reportlab'. Installala con: pip install reportlab") from e

    buf = io.BytesIO()
    c = pdf_canvas.Canvas(buf, pagesize=A4)
    w, h = A4

    margin = 18 * mm
    y = h - margin

    def draw_line(text, font="Helvetica", size=11, leading=14):
        nonlocal y
        if y < margin + 40:
            c.showPage()
            y = h - margin
            c.setFont("Helvetica", 11)

        # ReportLab con i font base (Helvetica) non supporta tutto l'UTF-8.
        # Convertiamo a WinAnsi/Latin-1 sostituendo i caratteri non supportati,
        # così evitiamo errori 500 su nomi/temi con emoji o accenti particolari.
        if text is None:
            text = ""
        try:
            safe = str(text).encode("latin-1", "replace").decode("latin-1")
        except Exception:
            safe = str(text)

        c.setFont(font, size)
        c.drawString(margin, y, safe)
        y -= leading

    # Header
    c.setTitle(f"Contratto prenotazione {APP_NAME} #{row['id']}")
    draw_line(f"{APP_NAME} - Contratto prenotazione", font="Helvetica-Bold", size=16, leading=20)
    draw_line(f"Prenotazione #{row['id']}  |  Creato: {row['created_at'] or '-'}", size=10, leading=14)
    draw_line("")

    # Dati evento
    ev_date = (row["event_date"] or row["data_evento"] or "-")
    slot = (row["slot_code"] or "-")
    area = (row["area"] or "-")
    draw_line("Dati evento", font="Helvetica-Bold", size=12, leading=16)
    draw_line(f"Data: {ev_date}   Slot: {slot}   Area: {area}")
    draw_line(f"Festeggiato: {row['nome_festeggiato'] or '-'}  (Eta: {row['eta_festeggiato'] or '-'})")
    draw_line(f"Invitati: {(row['invitati_bambini'] or 0)} bimbi / {(row['invitati_adulti'] or 0)} adulti")
    draw_line(f"Pacchetto: {row['pacchetto'] or '-'}")
    if row["tema_evento"]:
        draw_line(f"Tema evento: {row['tema_evento']}")
    if row["note"]:
        draw_line(f"Note: {row['note']}")
    if row["acconto_eur"]:
        draw_line(f"Acconto: EUR {row['acconto_eur']}")
    if row["totale_stimato_eur"]:
        try:
            tot = Decimal(str(row["totale_stimato_eur"]))
            draw_line(f"Totale stimato: EUR {eur(tot)}")
        except Exception:
            draw_line(f"Totale stimato: EUR {row['totale_stimato_eur']}")
    draw_line("")

    # Genitori/contatti
    draw_line("Dati genitore/i", font="Helvetica-Bold", size=12, leading=16)
    if row["madre_nome_cognome"] or row["madre_telefono"]:
        draw_line(f"Madre: {row['madre_nome_cognome'] or '-'}  |  Tel: {row['madre_telefono'] or '-'}")
    if row["padre_nome_cognome"] or row["padre_telefono"]:
        draw_line(f"Padre: {row['padre_nome_cognome'] or '-'}  |  Tel: {row['padre_telefono'] or '-'}")
    if row["indirizzo_residenza"]:
        draw_line(f"Indirizzo: {row['indirizzo_residenza']}")
    if row["email"]:
        draw_line(f"Email: {row['email']}")
    draw_line("")

    # Corpo contratto
    draw_line("Dettagli pacchetto (contratto)", font="Helvetica-Bold", size=12, leading=16)
    contract_text = row["dettagli_contratto_text"] or ""
    for ln in _wrap_text(contract_text, max_chars=95):
        draw_line(ln, font="Helvetica", size=10, leading=12)

    draw_line("")
    # Firma
    draw_line("Firma", font="Helvetica-Bold", size=12, leading=16)
    draw_line(f"Data firma: {row['data_firma'] or '-'}", size=10, leading=14)

    sig = (row["firma_png_base64"] or "").strip()
    if sig.startswith("data:image/png;base64,"):
        try:
            b64 = sig.split(",", 1)[1]
            img_bytes = base64.b64decode(b64)
            img = ImageReader(io.BytesIO(img_bytes))

            img_w = 90 * mm
            img_h = 35 * mm
            if y - img_h < margin:
                c.showPage()
                y = h - margin
            c.drawImage(img, margin, y - img_h, width=img_w, height=img_h, preserveAspectRatio=True, mask='auto')
            y -= (img_h + 10)
        except Exception:
            draw_line("(Firma non disponibile in PDF)", size=10, leading=14)
    else:
        draw_line("(Firma non disponibile in PDF)", size=10, leading=14)

    c.showPage()
    c.save()
    buf.seek(0)
    return buf

# -------------------------
# Calendario: slot rules
# -------------------------
def slots_for_date(d: date):
    slots = [{"code": "AFTERNOON", "label": "POMERIDIANO/SERALE", "start": "17:00", "end": "20:00"}]
    if d.weekday() in (5, 6):  # Sat/Sun
        slots.insert(0, {"code": "MORNING", "label": "MATTINA", "start": "09:30", "end": "12:30"})
    return slots


def slot_count(conn, event_date: str, slot_code: str) -> int:
    r = conn.execute("SELECT COUNT(*) AS c FROM bookings WHERE event_date=? AND slot_code=?", (event_date, slot_code)).fetchone()
    return int(r["c"])


def next_area(conn, event_date: str, slot_code: str) -> int:
    n = slot_count(conn, event_date, slot_code)
    if n == 0:
        return 1
    if n == 1:
        return 2
    return 3

# -------------------------
# Auth
# -------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        pin = request.form.get("pin", "")
        if pin == APP_PIN:
            session["ok"] = True
            return redirect(url_for("calendar_month"))
        return render_template_string(LOGIN_HTML, error="PIN errato.", app_name=APP_NAME)
    return render_template_string(LOGIN_HTML, error=None, app_name=APP_NAME)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# -------------------------
# Calendario UI
# -------------------------
BASE_CSS = """
<style>
  body{font-family:system-ui,-apple-system,Segoe UI,Roboto;margin:16px;background:#f6f7fb;}
  a{color:inherit}
  .topbar{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:14px;}
  .btn{display:inline-block;padding:10px 12px;border:1px solid #ddd;background:#fff;border-radius:12px;text-decoration:none;font-weight:800;}
  .btn.primary{background:#111;color:#fff;border-color:#111;}
  .card{background:#fff;border:1px solid #e5e5e5;border-radius:14px;padding:12px;}
  .muted{opacity:.7}
  .head{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;}
  .row{display:flex;gap:8px;align-items:center;flex-wrap:wrap;}
  .grid{display:grid;grid-template-columns:repeat(7,1fr);gap:8px;margin-top:10px;}
  .cell{background:#fff;border:1px solid #e5e5e5;border-radius:12px;padding:10px;min-height:86px;}
  .cell.empty{background:transparent;border:0;}
  .daynum{font-weight:900;}
  .bar{margin-top:8px;padding:6px;border-radius:10px;font-size:12px;font-weight:900;border:1px solid #eee;}
  .bar.green{background:#eaffea;border-color:#b7e6b7;}
  .bar.yellow{background:#fff8d8;border-color:#f1df86;}
  .bar.red{background:#ffe1e1;border-color:#f2a0a0;}
  .open{display:inline-block;margin-top:8px;font-weight:900;text-decoration:none;}
  .slot{border:1px solid #ddd;border-radius:14px;background:#fff;padding:12px;margin-top:10px;}
  .slothead{display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;align-items:flex-start;}
  .eventline{padding:10px;border-radius:12px;border:1px solid #eee;background:#fcfcfc;margin-top:8px;}
</style>
"""

def topbar(active="month"):
    return f"""
    <div class="topbar">
      <div class="row">
        <a class="btn {'primary' if active=='month' else ''}" href="{url_for('calendar_month')}">📆 Calendario</a>
        <a class="btn {'primary' if active=='year' else ''}" href="{url_for('calendar_year')}">🗓️ Anno</a>
        <a class="btn" href="{url_for('prenotazioni')}">📋 Prenotazioni</a>
      </div>
      <div class="row">
        <a class="btn" href="{url_for('logout')}">Esci</a>
      </div>
    </div>
    """

@app.route("/")
def calendar_month():
    if not is_logged_in():
        return redirect(url_for("login"))

    today = date.today()
    y = int(request.args.get("y", today.year))
    m = int(request.args.get("m", today.month))

    prev_y, prev_m = (y - 1, 12) if m == 1 else (y, m - 1)
    next_y, next_m = (y + 1, 1) if m == 12 else (y, m + 1)

    weeks = monthcalendar(y, m)

    conn = get_db()
    cells_html = ""
    for w in weeks:
        for dnum in w:
            if dnum == 0:
                cells_html += "<div class='cell empty'></div>"
                continue
            d_iso = date(y, m, dnum).isoformat()
            c = conn.execute("SELECT COUNT(*) AS c FROM bookings WHERE event_date=?", (d_iso,)).fetchone()["c"]
            c = int(c)
            col = "green" if c == 0 else "yellow" if c == 1 else "red"
            cells_html += f"""
              <div class="cell">
                <div class="daynum">{dnum}</div>
                <div class="bar {col}">{c} eventi</div>
                <a class="open" href="{url_for('day_view', date_iso=d_iso)}">Apri</a>
              </div>
            """
    conn.close()

    return f"""<!doctype html><html><head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{APP_NAME} – Calendario</title>
{BASE_CSS}
</head><body>
{topbar('month')}
<div class="card">
  <div class="head">
    <div>
      <h2 style="margin:0;">{month_name[m]} {y}</h2>
      <div class="muted">Scorri mesi come su iPhone</div>
    </div>
    <div class="row">
      <a class="btn" href="{url_for('calendar_month', y=prev_y, m=prev_m)}">←</a>
      <a class="btn" href="{url_for('calendar_month', y=next_y, m=next_m)}">→</a>
      <a class="btn" href="{url_for('calendar_month', y=today.year, m=today.month)}">Oggi</a>
    </div>
  </div>
  <div class="grid">{cells_html}</div>
</div>
</body></html>
"""

@app.route("/year")
def calendar_year():
    if not is_logged_in():
        return redirect(url_for("login"))

    today = date.today()
    y = int(request.args.get("y", today.year))

    conn = get_db()
    cards = ""
    for mm in range(1, 13):
        start = date(y, mm, 1).isoformat()
        end = (date(y + 1, 1, 1) if mm == 12 else date(y, mm + 1, 1)).isoformat()
        c = conn.execute("""
          SELECT COUNT(*) AS c FROM bookings
          WHERE event_date >= ? AND event_date < ?
        """, (start, end)).fetchone()["c"]
        c = int(c)
        col = "green" if c == 0 else "yellow" if c < 3 else "red"
        cards += f"""
          <div class="cell" style="min-height:auto;">
            <div style="font-weight:900;">{month_name[mm]}</div>
            <div class="bar {col}">{c} eventi</div>
            <a class="open" href="{url_for('calendar_month', y=y, m=mm)}">Apri</a>
          </div>
        """
    conn.close()

    return f"""<!doctype html><html><head>
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
  <div class="grid" style="grid-template-columns:repeat(3,1fr);">{cards}</div>
</div>
</body></html>
"""

@app.route("/day/<date_iso>")
def day_view(date_iso):
    if not is_logged_in():
        return redirect(url_for("login"))

    try:
        d = datetime.strptime(date_iso, "%Y-%m-%d").date()
    except ValueError:
        abort(404)

    conn = get_db()
    blocks = ""
    for s in slots_for_date(d):
        c = slot_count(conn, date_iso, s["code"])
        rows = conn.execute("""
          SELECT id, area, nome_festeggiato, eta_festeggiato, invitati_bambini, invitati_adulti,
                 tema_evento, pacchetto
          FROM bookings
          WHERE event_date=? AND slot_code=?
          ORDER BY area ASC, id ASC
        """, (date_iso, s["code"])).fetchall()

        ev_html = ""
        for r in rows:
            ev_html += f"""
              <div class="eventline">
                <b>Area {r['area'] or '-'}: {r['nome_festeggiato'] or '-'}</b>
                <div class="muted">{(r['eta_festeggiato'] or '-')} anni · {(r['invitati_bambini'] or 0)} bimbi / {(r['invitati_adulti'] or 0)} adulti</div>
                <div class="muted">Tema: {(r['tema_evento'] or '-')} · Pacchetto: {(r['pacchetto'] or '-')}</div>
                <div class="row" style="margin-top:8px;">
                  <a class="btn" href="{url_for('prenotazione_dettaglio', booking_id=r['id'])}">Apri</a>
                </div>
              </div>
            """

        blocks += f"""
          <div class="slot">
            <div class="slothead">
              <div>
                <div style="font-weight:900;">{s['start']}–{s['end']} <span class="muted">({s['label']})</span></div>
                <div class="muted">Prenotazioni nello slot: <b>{c}/2</b></div>
                {ev_html}
              </div>
              <a class="btn primary" href="{url_for('booking_new')}?date={date_iso}&slot={s['code']}">➕ Aggiungi evento</a>
            </div>
          </div>
        """

    conn.close()

    return f"""<!doctype html><html><head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{APP_NAME} – Giorno</title>
{BASE_CSS}
</head><body>
{topbar('month')}
<div class="card">
  <div class="head">
    <div>
      <h2 style="margin:0;">{d.strftime('%A %d %B %Y')}</h2>
      <div class="muted">Seleziona lo slot e aggiungi evento</div>
    </div>
    <a class="btn" href="{url_for('calendar_month', y=d.year, m=d.month)}">← Torna al mese</a>
  </div>
  {blocks}
</div>
</body></html>
"""


@app.route("/booking/new", methods=["GET", "POST"])
def booking_new():
    if not is_logged_in():
        return redirect(url_for("login"))

    event_date = (request.args.get("date") or "").strip()
    slot_code = (request.args.get("slot") or "").strip().upper()

    try:
        d = datetime.strptime(event_date, "%Y-%m-%d").date()
    except Exception:
        abort(400, "Data non valida.")

    allowed = {s["code"] for s in slots_for_date(d)}
    if slot_code not in allowed:
        abort(400, "Slot non valido per questa data.")

    slot = next(s for s in slots_for_date(d) if s["code"] == slot_code)

    conn = get_db()
    is_full = slot_count(conn, event_date, slot_code) >= 2

    def render_form(error, form):
        return render_template_string(
            BOOKING_HTML,
            app_name=APP_NAME,
            error=error,
            today=datetime.now().strftime("%Y-%m-%d"),
            form=form,
            package_labels=PACKAGE_LABELS,
            dessert_options=DESSERT_OPTIONS,
            torta_interna_flavors=TORTA_INTERNA_FLAVORS,
            extra_servizi=EXTRA_SERVIZI,
            extra_servizi_ai=EXTRA_SERVIZI_ALL_INCLUSIVE,
            event_date=event_date,
            slot=slot,
            is_full=is_full,
        )

    if request.method == "POST":
        consenso_privacy = 1 if request.form.get("consenso_privacy") else 0
        consenso_foto = 1 if request.form.get("consenso_foto") else 0

        if consenso_privacy != 1:
            conn.close()
            return render_form("Devi accettare l'informativa privacy per continuare.", request.form)

        firma_png_base64 = (request.form.get("firma_png_base64") or "").strip()
        data_firma = (request.form.get("data_firma") or "").strip()

        if not data_firma:
            conn.close()
            return render_form("Inserisci la data firma.", request.form)

        if not firma_png_base64.startswith("data:image/png;base64,"):
            conn.close()
            return render_form("Firma mancante: firma nel riquadro prima di salvare.", request.form)

        pacchetto = (request.form.get("pacchetto") or "").strip()

        confirm_area3 = (request.form.get("confirm_area3") == "on")
        if slot_count(conn, event_date, slot_code) >= 2 and not confirm_area3:
            conn.close()
            return render_form("Area 1 e 2 sono già impegnate. Se vuoi inserire comunque, conferma Area 3.", request.form)

        extra_keys = []
        if pacchetto == "Lullyland all-inclusive":
            for k in EXTRA_SERVIZI_ALL_INCLUSIVE.keys():
                if request.form.get(f"extra_{k}"):
                    extra_keys.append(k)
        else:
            for k in EXTRA_SERVIZI.keys():
                if request.form.get(f"extra_{k}"):
                    extra_keys.append(k)

        payload = {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "nome_festeggiato": (request.form.get("nome_festeggiato") or "").strip(),
            "eta_festeggiato": to_int(request.form.get("eta_festeggiato")),
            "data_compleanno": (request.form.get("data_compleanno") or "").strip(),
            "data_evento": event_date,
            "madre_nome_cognome": (request.form.get("madre_nome_cognome") or "").strip(),
            "madre_telefono": (request.form.get("madre_telefono") or "").strip(),
            "padre_nome_cognome": (request.form.get("padre_nome_cognome") or "").strip(),
            "padre_telefono": (request.form.get("padre_telefono") or "").strip(),
            "indirizzo_residenza": (request.form.get("indirizzo_residenza") or "").strip(),
            "email": (request.form.get("email") or "").strip(),
            "invitati_bambini": to_int(request.form.get("invitati_bambini")),
            "invitati_adulti": to_int(request.form.get("invitati_adulti")),
            "pacchetto": pacchetto,
            "tema_evento": (request.form.get("tema_evento") or "").strip(),
            "note": (request.form.get("note") or "").strip(),
            "data_firma": data_firma,
            "firma_png_base64": firma_png_base64,
            "consenso_privacy": consenso_privacy,
            "consenso_foto": consenso_foto,
            "acconto_eur": (request.form.get("acconto_eur") or "").strip(),
            "pacchetto_personalizzato_dettagli": (request.form.get("pacchetto_personalizzato_dettagli") or "").strip(),
            "catering_baby_choice": (request.form.get("catering_baby_choice") or "").strip(),
            "dessert_bimbi_choice": (request.form.get("dessert_bimbi_choice") or "").strip(),
            "dessert_adulti_choice": (request.form.get("dessert_adulti_choice") or "").strip(),
            "torta_choice": (request.form.get("torta_choice") or "").strip(),
            "torta_interna_choice": first_nonempty(request.form.getlist("torta_interna_choice")),
            "torta_gusto_altro": first_nonempty(request.form.getlist("torta_gusto_altro")),
            "extra_keys": extra_keys,
        }

        if not payload["nome_festeggiato"]:
            conn.close()
            return render_form("Inserisci il nome del festeggiato.", request.form)

        if payload["pacchetto"] not in PACKAGE_LABELS:
            conn.close()
            return render_form("Seleziona un pacchetto valido.", request.form)

        if payload["pacchetto"] == "Personalizzato" and not payload["pacchetto_personalizzato_dettagli"]:
            conn.close()
            return render_form("Hai scelto Personalizzato: inserisci i dettagli.", request.form)

        if payload["pacchetto"] == "Lullyland Experience":
            cb = payload["catering_baby_choice"]
            if cb not in CATERING_BABY_OPTIONS:
                conn.close()
                return render_form("Per Experience scegli Catering baby (Menu pizza o Box merenda).", request.form)

            tc = payload["torta_choice"]
            if tc not in ("esterna", "interna"):
                conn.close()
                return render_form("Per Experience scegli torta: Esterna (+EUR 1 a persona) oppure Interna (EUR 24/kg).", request.form)

            if tc == "interna":
                ti = payload["torta_interna_choice"]
                if ti not in ("standard", "altro"):
                    conn.close()
                    return render_form("Se hai scelto torta interna, seleziona Classica o Altro.", request.form)
                if ti == "altro" and not payload["torta_gusto_altro"]:
                    conn.close()
                    return render_form("Hai scelto Altro: scrivi il gusto della torta.", request.form)

        if payload["pacchetto"] == "Lullyland all-inclusive":
            # NEW: dropdown muffin o torta, poi (se torta) classica o altro (+ campo)
            # Dessert bimbi/adulti NON obbligatori: se compilati, devono essere validi
            if payload["dessert_bimbi_choice"] and payload["dessert_bimbi_choice"] not in ("muffin_nutella", "torta_compleanno"):
                conn.close()
                return render_form("All-inclusive: dessert bimbi non valido.", request.form)
            if payload["dessert_adulti_choice"] and payload["dessert_adulti_choice"] not in ("muffin_nutella", "torta_compleanno"):
                conn.close()
                return render_form("All-inclusive: dessert adulti non valido.", request.form)

            need_torta = (payload["dessert_bimbi_choice"] == "torta_compleanno") or (payload["dessert_adulti_choice"] == "torta_compleanno")
            if need_torta:
                payload["torta_choice"] = "interna"  # sempre interna e inclusa
                # La scelta "Classica/Altro" e l'eventuale gusto NON sono obbligatori.
                # Se non vengono compilati, nel contratto resteranno "(da definire)" / "(da compilare)".
                if payload["torta_interna_choice"] and payload["torta_interna_choice"] not in ("standard", "altro"):
                    conn.close()
                    return render_form("All-inclusive: scelta torta non valida.", request.form)
            else:
                payload["torta_choice"] = ""
                payload["torta_interna_choice"] = ""
                payload["torta_gusto_altro"] = ""

        totals = compute_totals(payload)
        contract_text = build_contract_text(payload)
        area = next_area(conn, event_date, slot_code)

        conn.execute(
            """
            INSERT INTO bookings (
                created_at,
                nome_festeggiato, eta_festeggiato, data_compleanno, data_evento,
                madre_nome_cognome, madre_telefono,
                padre_nome_cognome, padre_telefono,
                indirizzo_residenza, email,
                invitati_bambini, invitati_adulti,
                pacchetto, tema_evento, note,
                data_firma, firma_png_base64,
                consenso_privacy, consenso_foto,
                acconto_eur,
                pacchetto_personalizzato_dettagli,
                catering_baby_choice,
                dessert_bimbi_choice,
                dessert_adulti_choice,
                torta_choice, torta_interna_choice, torta_gusto_altro,
                extra_keys_csv,
                totale_stimato_eur,
                dettagli_contratto_text,
                event_date, slot_code, start_time, end_time, area
            ) VALUES (
                :created_at,
                :nome_festeggiato, :eta_festeggiato, :data_compleanno, :data_evento,
                :madre_nome_cognome, :madre_telefono,
                :padre_nome_cognome, :padre_telefono,
                :indirizzo_residenza, :email,
                :invitati_bambini, :invitati_adulti,
                :pacchetto, :tema_evento, :note,
                :data_firma, :firma_png_base64,
                :consenso_privacy, :consenso_foto,
                :acconto_eur,
                :pacchetto_personalizzato_dettagli,
                :catering_baby_choice,
                :dessert_bimbi_choice,
                :dessert_adulti_choice,
                :torta_choice, :torta_interna_choice, :torta_gusto_altro,
                :extra_keys_csv,
                :totale_stimato_eur,
                :dettagli_contratto_text,
                :event_date, :slot_code, :start_time, :end_time, :area
            )
            """,
            {
                **payload,
                "extra_keys_csv": ",".join(payload["extra_keys"]),
                "totale_stimato_eur": str(totals["totale"]),
                "dettagli_contratto_text": contract_text,
                "event_date": event_date,
                "slot_code": slot_code,
                "start_time": slot["start"],
                "end_time": slot["end"],
                "area": area,
            },
        )
        conn.commit()
        conn.close()
        return redirect(url_for("day_view", date_iso=event_date))

    conn.close()
    return render_template_string(
        BOOKING_HTML,
        app_name=APP_NAME,
        error=None,
        today=datetime.now().strftime("%Y-%m-%d"),
        form={},
        package_labels=PACKAGE_LABELS,
        dessert_options=DESSERT_OPTIONS,
        torta_interna_flavors=TORTA_INTERNA_FLAVORS,
        extra_servizi=EXTRA_SERVIZI,
        extra_servizi_ai=EXTRA_SERVIZI_ALL_INCLUSIVE,
        event_date=event_date,
        slot=slot,
        is_full=is_full,
    )

@app.route("/prenotazioni")
def prenotazioni():
    if not is_logged_in():
        return redirect(url_for("login"))
    conn = get_db()
    rows = conn.execute(
        """
        SELECT id, created_at, nome_festeggiato, data_evento, pacchetto,
               invitati_bambini, invitati_adulti, totale_stimato_eur,
               event_date, slot_code, area
        FROM bookings
        ORDER BY id DESC
        """
    ).fetchall()
    conn.close()
    return render_template_string(LIST_HTML, app_name=APP_NAME, rows=rows)

@app.route("/prenotazioni/<int:booking_id>")
def prenotazione_dettaglio(booking_id: int):
    if not is_logged_in():
        return redirect(url_for("login"))

    conn = get_db()
    row = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
    conn.close()
    if not row:
        abort(404)

    invitati_b = int(row["invitati_bambini"] or 0)
    invitati_a = int(row["invitati_adulti"] or 0)
    tot_persone = invitati_b + invitati_a

    torta_info = "-"
    if row["pacchetto"] == "Lullyland Experience":
        tc = (row["torta_choice"] or "").strip()
        if tc == "interna":
            torta_kg = (Decimal(tot_persone) * KG_PER_PERSON).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            torta_info = f"{tot_persone} persone -> ~ {torta_kg} kg (100g a testa) a EUR {eur(TORTA_PRICE_EUR_PER_KG)}/kg"
        elif tc == "esterna":
            svc_tot = (TORTA_ESTERNASVC_EUR_PER_PERSON * Decimal(tot_persone)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            torta_info = f"{tot_persone} persone -> Servizio torta: EUR {eur(TORTA_ESTERNASVC_EUR_PER_PERSON)} x {tot_persone} = EUR {eur(svc_tot)}"
    elif row["pacchetto"] == "Lullyland all-inclusive":
        need_torta = (row["dessert_bimbi_choice"] == "torta_compleanno") or (row["dessert_adulti_choice"] == "torta_compleanno")
        if need_torta:
            ti = (row["torta_interna_choice"] or "").strip()
            if ti == "standard":
                torta_info = f"Torta interna (inclusa) - {TORTA_INTERNA_FLAVORS['standard']}"
            elif ti == "altro":
                gust = (row["torta_gusto_altro"] or "").strip() or "(da compilare)"
                torta_info = f"Torta interna (inclusa) - Gusto: {gust}"
            else:
                torta_info = "Torta interna (inclusa) - (da definire)"
        else:
            torta_info = "-"

    return render_template_string(DETAIL_HTML, app_name=APP_NAME, b=row, torta_info=torta_info)

@app.route("/prenotazioni/<int:booking_id>/contratto.pdf")
def prenotazione_contratto_pdf(booking_id: int):
    if not is_logged_in():
        return redirect(url_for("login"))

    conn = get_db()
    row = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
    conn.close()
    if not row:
        abort(404)

    pdf_buf = build_contract_pdf_bytes(row)
    filename = f"contratto_prenotazione_{booking_id}.pdf"
    return send_file(pdf_buf, mimetype="application/pdf", as_attachment=True, download_name=filename)

LOGIN_HTML = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>{{app_name}} - Accesso</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body { font-family: Arial, sans-serif; padding: 30px; background:#f6f7fb; }
    .box { max-width: 420px; margin: 60px auto; background:#fff; padding: 18px; border-radius: 12px; border:1px solid #e8e8e8; }
    input { width: 100%; padding: 12px; font-size: 16px; margin: 10px 0; border-radius:10px; border:1px solid #dcdcdc;}
    button { width: 100%; padding: 12px; font-size: 16px; border-radius:10px; border:none; background:#0a84ff; color:#fff; font-weight:700; }
    .err { color: #b00020; }
    h2 { margin: 6px 0 14px; }
  </style>
</head>
<body>
  <div class="box">
    <h2>Accesso {{app_name}}</h2>
    {% if error %}<p class="err">{{ error }}</p>{% endif %}
    <form method="post">
      <input type="password" name="pin" placeholder="Inserisci PIN" required />
      <button type="submit">Entra</button>
    </form>
  </div>
</body>
</html>
"""



BOOKING_HTML = r"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>{{app_name}} - Prenotazione evento</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body { font-family: Arial, sans-serif; padding: 18px; background:#f6f7fb; }
    .card { max-width: 860px; margin: 18px auto; background:#fff; padding: 18px; border-radius: 12px; border:1px solid #e8e8e8; }
    .row { display:flex; gap:12px; flex-wrap:wrap; }
    .col { flex:1; min-width: 240px; }
    label { display:block; margin-top: 10px; font-weight: 700; }
    input, select, textarea {
      width: 100%; padding: 12px; font-size: 16px; margin-top: 6px;
      border-radius:10px; border:1px solid #dcdcdc; background:#fff;
    }
    textarea { min-height: 90px; }
    .actions { display:flex; gap:10px; flex-wrap:wrap; margin-top:16px; }
    button {
      padding: 12px 14px; font-size: 16px; border-radius:10px; border:none;
      background:#0a84ff; color:#fff; font-weight:800; cursor:pointer;
    }
    a.link { display:inline-block; padding: 12px 14px; border-radius:10px; background:#111; color:#fff; text-decoration:none; font-weight:800; }
    .err { color: #b00020; font-weight:700; }
    .hint { color:#666; font-size: 13px; margin-top:6px; }
    .sig-wrap { margin-top: 12px; }
    canvas { width:100%; max-width: 760px; height: 220px; border: 2px dashed #bbb; border-radius: 12px; background:#fff; touch-action: none; }
    .sig-actions { display:flex; gap:10px; margin-top:10px; }
    .btn-secondary { background:#333; }
    .section { margin-top: 14px; padding-top: 10px; border-top: 1px solid #eee; }
    .pill { display:inline-block; padding:6px 10px; border-radius:999px; background:#f0f2f7; font-weight:800; }
    .warn { margin-top:12px; padding:12px; border:1px solid #f2a0a0; border-radius:12px; background:#ffe1e1; }
  </style>
</head>
<body>
  <div class="card">
    <h2>Modulo prenotazione evento - {{app_name}}</h2>
    <p><a href="/day/{{event_date}}"><- Torna al giorno</a></p>

    <div class="pill">Data evento: {{event_date}} · Slot: {{slot.start}}-{{slot.end}} ({{slot.label}})</div>

    {% if is_full %}
      <div class="warn">
        <b>Allert:</b> Area 1 e 2 sono già impegnate. Vuoi inserire comunque Area 3?
        <div style="margin-top:10px;">
          <label style="font-weight:800;">
            <input type="checkbox" name="confirm_area3" form="bookingForm">
            Confermo inserimento Area 3
          </label>
        </div>
      </div>
    {% endif %}

    {% if error %}<p class="err">{{error}}</p>{% endif %}

    <form method="post" id="bookingForm">
      <div class="row">
        <div class="col">
          <label>Nome festeggiato *</label>
          <input name="nome_festeggiato" required value="{{form.get('nome_festeggiato','')}}" />
        </div>
        <div class="col">
          <label>Eta festeggiato</label>
          <input type="number" name="eta_festeggiato" min="0" value="{{form.get('eta_festeggiato','')}}" />
        </div>
      </div>

      <div class="row">
        <div class="col">
          <label>Data del compleanno</label>
          <input type="date" name="data_compleanno" value="{{form.get('data_compleanno','')}}" />
        </div>
        <div class="col">
          <label>Data dell'evento</label>
          <input type="text" value="{{event_date}}" disabled />
          <div class="hint">La data viene dal calendario (non modificabile qui).</div>
        </div>
      </div>

      <div class="row">
        <div class="col">
          <label>Nome e cognome madre</label>
          <input name="madre_nome_cognome" value="{{form.get('madre_nome_cognome','')}}" />
        </div>
        <div class="col">
          <label>Numero di telefono madre</label>
          <input name="madre_telefono" value="{{form.get('madre_telefono','')}}" />
        </div>
      </div>

      <div class="row">
        <div class="col">
          <label>Nome e cognome padre</label>
          <input name="padre_nome_cognome" value="{{form.get('padre_nome_cognome','')}}" />
        </div>
        <div class="col">
          <label>Numero di telefono padre</label>
          <input name="padre_telefono" value="{{form.get('padre_telefono','')}}" />
        </div>
      </div>

      <div class="row">
        <div class="col">
          <label>Indirizzo di residenza</label>
          <input name="indirizzo_residenza" value="{{form.get('indirizzo_residenza','')}}" />
        </div>
        <div class="col">
          <label>Email</label>
          <input type="email" name="email" value="{{form.get('email','')}}" />
        </div>
      </div>

      <div class="row">
        <div class="col">
          <label>Numero invitati bambini</label>
          <input type="number" name="invitati_bambini" min="0" value="{{form.get('invitati_bambini','')}}" />
        </div>
        <div class="col">
          <label>Numero invitati adulti</label>
          <input type="number" name="invitati_adulti" min="0" value="{{form.get('invitati_adulti','')}}" />
        </div>
      </div>

      <div class="row">
        <div class="col">
          <label>Pacchetto scelto *</label>
          {% set p = form.get('pacchetto','') %}
          <select name="pacchetto" id="pacchetto" required>
            <option value="" {% if p=='' %}selected{% endif %}>Seleziona...</option>
            <option value="Fai da Te" {% if p=='Fai da Te' %}selected{% endif %}>{{package_labels['Fai da Te']}}</option>
            <option value="Lullyland Experience" {% if p=='Lullyland Experience' %}selected{% endif %}>{{package_labels['Lullyland Experience']}}</option>
            <option value="Lullyland all-inclusive" {% if p=='Lullyland all-inclusive' %}selected{% endif %}>{{package_labels['Lullyland all-inclusive']}}</option>
            <option value="Personalizzato" {% if p=='Personalizzato' %}selected{% endif %}>{{package_labels['Personalizzato']}}</option>
          </select>
        </div>
        <div class="col">
          <label>Tema evento</label>
          <input name="tema_evento" value="{{form.get('tema_evento','')}}" />
        </div>
      </div>

      <div class="row" id="personalizzatoBox" style="display:none;">
        <div class="col" style="flex-basis:100%;">
          <label>Dettagli personalizzazione (solo se "Personalizzato") *</label>
          <textarea name="pacchetto_personalizzato_dettagli" id="pacchetto_personalizzato_dettagli">{{form.get('pacchetto_personalizzato_dettagli','')}}</textarea>
        </div>
      </div>

      <label>Note</label>
      <textarea name="note">{{form.get('note','')}}</textarea>

      <div class="section" id="experienceBox" style="display:none;">
        <h3>Opzioni pacchetto Experience</h3>

        <div class="row">
          <div class="col">
            <label>Catering baby *</label>
            {% set cb = form.get('catering_baby_choice','') %}
            <select name="catering_baby_choice" id="catering_baby_choice">
              <option value="">Seleziona...</option>
              <option value="menu_pizza" {% if cb=='menu_pizza' %}selected{% endif %}>Menu pizza</option>
              <option value="box_merenda" {% if cb=='box_merenda' %}selected{% endif %}>Box merenda</option>
            </select>
          </div>

          <div class="col">
            <label>Torta (scelta) *</label>
            {% set tc = form.get('torta_choice','') %}
            <select name="torta_choice" id="torta_choice">
              <option value="">Seleziona...</option>
              <option value="esterna" {% if tc=='esterna' %}selected{% endif %}>Torta esterna (+EUR 1,00 a persona)</option>
              <option value="interna" {% if tc=='interna' %}selected{% endif %}>Torta interna (da noi) (EUR 24,00 al chilo)</option>
            </select>
          </div>
        </div>

        <div class="row" id="tortaInternaBox" style="display:none;">
          <div class="col">
            <label>Gusto torta interna *</label>
            {% set ti = form.get('torta_interna_choice','') %}
            <select name="torta_interna_choice" id="torta_interna_choice">
              <option value="">Seleziona...</option>
              <option value="standard" {% if ti=='standard' %}selected{% endif %}>{{torta_interna_flavors['standard']}}</option>
              <option value="altro" {% if ti=='altro' %}selected{% endif %}>Altro (scrivi gusto)</option>
            </select>
          </div>
          <div class="col" id="tortaAltroBox" style="display:none;">
            <label>Gusto concordato (se "Altro") *</label>
            <input name="torta_gusto_altro" id="torta_gusto_altro" value="{{form.get('torta_gusto_altro','')}}" />
          </div>
        </div>

        <div class="section">
          <h3>Servizi extra</h3>
          <div class="row">
            {% for k, v in extra_servizi.items() %}
              <div class="col" style="min-width:260px;">
                <label style="font-weight:700;">
                  <input type="checkbox" name="extra_{{k}}" {% if form.get('extra_' ~ k) %}checked{% endif %}>
                  {{v[0]}} - EUR {{"{:0.2f}".format(v[1]).replace(".", ",")}}
                </label>
              </div>
            {% endfor %}
          </div>
        </div>
      </div>

      <div class="section" id="allInclusiveBox" style="display:none;">
        <h3>Opzioni pacchetto All-inclusive</h3>

        <div class="row">
          <div class="col">
            <label>Catering baby (facoltativo)</label>
            {% set cb2 = form.get('catering_baby_choice','') %}
            <select name="catering_baby_choice" id="catering_baby_choice_ai">
              <option value="">Seleziona...</option>
              <option value="menu_pizza" {% if cb2=='menu_pizza' %}selected{% endif %}>Menu pizza</option>
              <option value="box_merenda" {% if cb2=='box_merenda' %}selected{% endif %}>Box merenda</option>
            </select>
          </div>
        </div>

        <div class="row">
          <div class="col">
            <label>Dessert per bambini</label>
            {% set db = form.get('dessert_bimbi_choice','') %}
            <select name="dessert_bimbi_choice" id="dessert_bimbi_choice">
              <option value="" {% if db=='' %}selected{% endif %}>Seleziona...</option>
              <option value="muffin_nutella" {% if db=='muffin_nutella' %}selected{% endif %}>{{dessert_options['muffin_nutella']}}</option>
              <option value="torta_compleanno" {% if db=='torta_compleanno' %}selected{% endif %}>{{dessert_options['torta_compleanno']}}</option>
            </select>
          </div>

          <div class="col">
            <label>Dessert per adulti</label>
            {% set da = form.get('dessert_adulti_choice','') %}
            <select name="dessert_adulti_choice" id="dessert_adulti_choice">
              <option value="" {% if da=='' %}selected{% endif %}>Seleziona...</option>
              <option value="muffin_nutella" {% if da=='muffin_nutella' %}selected{% endif %}>{{dessert_options['muffin_nutella']}}</option>
              <option value="torta_compleanno" {% if da=='torta_compleanno' %}selected{% endif %}>{{dessert_options['torta_compleanno']}}</option>
            </select>
          </div>
        </div>

        <div class="row" id="aiTortaInternaBox" style="display:none;">
          <div class="col">
            <label>Torta di compleanno (inclusa)</label>
            {% set ti2 = form.get('torta_interna_choice','') %}
            <select name="torta_interna_choice" id="torta_interna_choice_ai">
              <option value="" {% if ti2=='' %}selected{% endif %}>Seleziona...</option>
              <option value="standard" {% if ti2=='standard' %}selected{% endif %}>Classica: {{torta_interna_flavors['standard']}}</option>
              <option value="altro" {% if ti2=='altro' %}selected{% endif %}>Altro (scrivi gusto)</option>
            </select>
            <div class="hint">All-inclusive: niente torta esterna e nessun costo aggiuntivo.</div>
          </div>

          <div class="col" id="aiTortaAltroBox" style="display:none;">
            <label>Gusto scelto (se "Altro")</label>
            <input name="torta_gusto_altro" id="torta_gusto_altro_ai" value="{{form.get('torta_gusto_altro','')}}" />
          </div>
        </div>

        <div class="section">
          <h3>Servizi extra</h3>
          <div class="row">
            {% for k, v in extra_servizi_ai.items() %}
              <div class="col" style="min-width:260px;">
                <label style="font-weight:700;">
                  <input type="checkbox" name="extra_{{k}}" {% if form.get('extra_' ~ k) %}checked{% endif %}>
                  {{v[0]}} - EUR {{"{:0.2f}".format(v[1]).replace(".", ",")}}
                </label>
              </div>
            {% endfor %}
          </div>
        </div>
      </div>

      <div style="margin-top:16px;">
        <label style="font-weight:700;">
          <input type="checkbox" name="consenso_privacy" required {% if form.get('consenso_privacy') %}checked{% endif %}>
          Dichiaro di aver letto e accettato l'informativa privacy di {{app_name}} *
        </label>

        <label style="margin-top:10px; font-weight:700;">
          <input type="checkbox" name="consenso_foto" {% if form.get('consenso_foto') %}checked{% endif %}>
          Autorizzo {{app_name}} a scattare foto/video durante l'evento e a utilizzarli sui canali social
        </label>
      </div>

      <div class="row" style="margin-top:14px;">
        <div class="col">
          <label>Acconto (EUR)</label>
          <input type="text" name="acconto_eur" placeholder="Es: 50,00" value="{{form.get('acconto_eur','')}}" />
        </div>
      </div>

      <div class="row" style="margin-top:14px;">
        <div class="col">
          <label>Data firma genitore *</label>
          <input type="date" name="data_firma" required value="{{form.get('data_firma', today)}}" />
        </div>
      </div>

      <div class="sig-wrap">
        <label>Firma genitore (su tablet) *</label>
        <canvas id="sigCanvas"></canvas>
        <div class="sig-actions">
          <button type="button" class="btn-secondary" onclick="clearSig()">Pulisci firma</button>
        </div>
        <div class="hint">Firma col dito sul riquadro. Obbligatoria.</div>
      </div>

      <input type="hidden" name="firma_png_base64" id="firma_png_base64" />

      <div class="actions">
        <button type="submit">Salva evento</button>
        <a class="link" href="/day/{{event_date}}">Annulla</a>
      </div>
    </form>
  </div>

<script>
(function() {
  const pacchetto = document.getElementById('pacchetto');
  const experienceBox = document.getElementById('experienceBox');
  const allInclusiveBox = document.getElementById('allInclusiveBox');
  const personalizzatoBox = document.getElementById('personalizzatoBox');

  const tortaChoice = document.getElementById('torta_choice');
  const tortaInternaBox = document.getElementById('tortaInternaBox');
  const tortaInternaChoice = document.getElementById('torta_interna_choice');
  const tortaAltroBox = document.getElementById('tortaAltroBox');

  const dessertBimbi = document.getElementById('dessert_bimbi_choice');
  const dessertAdulti = document.getElementById('dessert_adulti_choice');
  const aiTortaInternaBox = document.getElementById('aiTortaInternaBox');
  const tortaInternaChoiceAI = document.getElementById('torta_interna_choice_ai');
  const aiTortaAltroBox = document.getElementById('aiTortaAltroBox');

  function refreshVisibility() {
    const p = pacchetto.value;
    experienceBox.style.display = (p === 'Lullyland Experience') ? 'block' : 'none';
    allInclusiveBox.style.display = (p === 'Lullyland all-inclusive') ? 'block' : 'none';
    personalizzatoBox.style.display = (p === 'Personalizzato') ? 'flex' : 'none';

    const tc = tortaChoice ? tortaChoice.value : '';
    if (tortaInternaBox) tortaInternaBox.style.display = (p === 'Lullyland Experience' && tc === 'interna') ? 'flex' : 'none';

    const ti = tortaInternaChoice ? tortaInternaChoice.value : '';
    if (tortaAltroBox) tortaAltroBox.style.display = (p === 'Lullyland Experience' && tc === 'interna' && ti === 'altro') ? 'block' : 'none';

    const db = dessertBimbi ? dessertBimbi.value : '';
    const da = dessertAdulti ? dessertAdulti.value : '';
    const needTorta = (db === 'torta_compleanno' || da === 'torta_compleanno');

    if (aiTortaInternaBox) aiTortaInternaBox.style.display = (p === 'Lullyland all-inclusive' && needTorta) ? 'flex' : 'none';

    const ti2 = tortaInternaChoiceAI ? tortaInternaChoiceAI.value : '';
    if (aiTortaAltroBox) aiTortaAltroBox.style.display = (p === 'Lullyland all-inclusive' && needTorta && ti2 === 'altro') ? 'block' : 'none';
  }

  pacchetto.addEventListener('change', refreshVisibility);
  if (tortaChoice) tortaChoice.addEventListener('change', refreshVisibility);
  if (tortaInternaChoice) tortaInternaChoice.addEventListener('change', refreshVisibility);
  if (dessertBimbi) dessertBimbi.addEventListener('change', refreshVisibility);
  if (dessertAdulti) dessertAdulti.addEventListener('change', refreshVisibility);
  if (tortaInternaChoiceAI) tortaInternaChoiceAI.addEventListener('change', refreshVisibility);

  refreshVisibility();

  const canvas = document.getElementById('sigCanvas');
  const ctx = canvas.getContext('2d');
  let drawing = false;
  let hasInk = false;

  function resizeCanvas() {
    const rect = canvas.getBoundingClientRect();
    const ratio = window.devicePixelRatio || 1;
    canvas.width = Math.floor(rect.width * ratio);
    canvas.height = Math.floor(rect.height * ratio);
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.lineWidth = 3;
    ctx.lineCap = 'round';
    ctx.strokeStyle = '#111';
    ctx.fillStyle = '#fff';
    ctx.fillRect(0, 0, rect.width, rect.height);
  }

  function getPos(e) {
    const rect = canvas.getBoundingClientRect();
    const touch = e.touches && e.touches[0];
    const clientX = touch ? touch.clientX : e.clientX;
    const clientY = touch ? touch.clientY : e.clientY;
    return { x: clientX - rect.left, y: clientY - rect.top };
  }

  function start(e) {
    e.preventDefault();
    drawing = true;
    const p = getPos(e);
    ctx.beginPath();
    ctx.moveTo(p.x, p.y);
  }

  function move(e) {
    if (!drawing) return;
    e.preventDefault();
    const p = getPos(e);
    ctx.lineTo(p.x, p.y);
    ctx.stroke();
    hasInk = true;
  }

  function end(e) {
    if (!drawing) return;
    e.preventDefault();
    drawing = false;
  }

  window.clearSig = function() { hasInk = false; resizeCanvas(); };

  resizeCanvas();
  window.addEventListener('resize', resizeCanvas);

  canvas.addEventListener('mousedown', start);
  canvas.addEventListener('mousemove', move);
  window.addEventListener('mouseup', end);

  canvas.addEventListener('touchstart', start, { passive:false });
  canvas.addEventListener('touchmove', move, { passive:false });
  window.addEventListener('touchend', end, { passive:false });

  document.getElementById('bookingForm').addEventListener('submit', function(e) {
    if (!hasInk) { e.preventDefault(); alert("Firma mancante: firma nel riquadro prima di salvare."); return; }
    document.getElementById('firma_png_base64').value = canvas.toDataURL('image/png');
  });
})();
</script>
</body>
</html>
"""


LIST_HTML = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>{{app_name}} - Prenotazioni</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body { font-family: Arial, sans-serif; padding: 18px; background:#f6f7fb; }
    .card { max-width: 980px; margin: 18px auto; background:#fff; padding: 18px; border-radius: 12px; border:1px solid #e8e8e8; }
    table { width:100%; border-collapse: collapse; }
    th, td { padding: 10px; border-bottom:1px solid #eee; text-align:left; }
    a.link { color:#0a84ff; font-weight:700; text-decoration:none; }
    .pill { display:inline-block; padding:6px 10px; border-radius:999px; background:#f0f2f7; font-weight:800; }
  </style>
</head>
<body>
  <div class="card">
    <h2>Prenotazioni - {{app_name}}</h2>
    <p><a class="link" href="/">📆 Calendario</a></p>

    {% if rows|length == 0 %}
      <p style="color:#666;">Nessuna prenotazione salvata ancora.</p>
    {% else %}
      <table>
        <thead>
          <tr>
            <th>ID</th>
            <th>Data</th>
            <th>Slot</th>
            <th>Area</th>
            <th>Festeggiato</th>
            <th>Pacchetto</th>
            <th>Invitati</th>
            <th>Totale stimato</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {% for r in rows %}
            <tr>
              <td>{{r['id']}}</td>
              <td>{{r['event_date'] or r['data_evento']}}</td>
              <td>{{r['slot_code'] or '-'}}</td>
              <td>{{r['area'] or '-'}}</td>
              <td>{{r['nome_festeggiato']}}</td>
              <td>{{r['pacchetto']}}</td>
              <td>{{(r['invitati_bambini'] or 0)}} bimbi / {{(r['invitati_adulti'] or 0)}} adulti</td>
              <td>
                {% if r['totale_stimato_eur'] %}
                  <span class="pill">EUR {{"{:0.2f}".format(r['totale_stimato_eur']|float).replace(".", ",")}}</span>
                {% else %}-{% endif %}
              </td>
              <td><a class="link" href="/prenotazioni/{{r['id']}}">Apri</a> &nbsp; <a class="link" title="Scarica PDF" href="/prenotazioni/{{r['id']}}/contratto.pdf">📥 PDF</a></td>
            </tr>
          {% endfor %}
        </tbody>
      </table>
    {% endif %}
  </div>
</body>
</html>
"""

DETAIL_HTML = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>{{app_name}} - Dettaglio prenotazione</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body { font-family: Arial, sans-serif; padding: 18px; background:#f6f7fb; }
    .card { max-width: 980px; margin: 18px auto; background:#fff; padding: 18px; border-radius: 12px; border:1px solid #e8e8e8; }
    .box { border:1px solid #eee; border-radius:12px; padding:12px; margin-top:10px; }
    .k { color:#666; font-size: 12px; margin-bottom:4px; }
    .v { font-weight: 800; margin-bottom:10px; }
    img { max-width: 760px; width:100%; border:1px solid #ddd; border-radius:12px; background:#fff; }
    .contract { white-space: pre-wrap; background:#f6f7fb; padding: 14px; border-radius: 12px; border:1px solid #e8e8e8; }
    a.btnpdf { display:inline-block; margin-top:10px; padding:10px 12px; border-radius:12px; background:#111; color:#fff; text-decoration:none; font-weight:900; }
  </style>
</head>
<body>
  <div class="card">
    <p><a href="/prenotazioni"><- Prenotazioni</a> | <a href="/">Calendario</a></p>
    <h2>Dettaglio prenotazione #{{b['id']}} - {{app_name}}</h2>

    <a class="btnpdf" href="/prenotazioni/{{b['id']}}/contratto.pdf">⬇️ Scarica contratto PDF</a>

    <div class="box">
      <div class="k">Calendario</div>
      <div class="v">{{b['event_date'] or b['data_evento']}} · {{b['slot_code'] or '-'}} · Area {{b['area'] or '-'}}</div>

      <div class="k">Festeggiato</div>
      <div class="v">{{b['nome_festeggiato']}} ({{b['eta_festeggiato'] or '-'}})</div>

      <div class="k">Pacchetto</div>
      <div class="v">{{b['pacchetto']}}</div>

      <div class="k">Invitati</div>
      <div class="v">{{b['invitati_bambini'] or 0}} bimbi - {{b['invitati_adulti'] or 0}} adulti</div>

      <div class="k">Torta / Dessert</div>
      <div class="v">{{torta_info}}</div>
    </div>

    <div class="box">
      <div class="k">Dettagli pacchetto (contratto)</div>
      <div class="contract">{{b['dettagli_contratto_text'] or ''}}</div>
    </div>

    <div class="box">
      <div class="k">Firma</div>
      <img src="{{b['firma_png_base64']}}" alt="Firma genitore" />
    </div>
  </div>
</body>
</html>
"""

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
