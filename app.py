import os
import sqlite3
from datetime import datetime, date
from decimal import Decimal, ROUND_HALF_UP
import calendar
import io
import base64

from flask import (
    Flask,
    request,
    redirect,
    url_for,
    session,
    render_template_string,
    abort,
    send_file,
)

# PDF
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader


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
KG_PER_PERSON = Decimal("0.10")  # 100g a testa

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

            event_date TEXT,
            slot_code TEXT,
            area INTEGER,

            nome_festeggiato TEXT,
            eta_festeggiato INTEGER,
            data_compleanno TEXT,

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

    # Migrazioni software avanzato
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
        return int(val) if val not in (None, "") else None
    except Exception:
        return None


def eur(d: Decimal) -> str:
    q = d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    s = f"{q:.2f}"
    return s.replace(".", ",")


def parse_event_date(s: str) -> date:
    # formato atteso: YYYY-MM-DD
    return datetime.strptime(s, "%Y-%m-%d").date()


def slot_label_from_code(code: str) -> str:
    return "09:30–12:30" if code == "MORNING" else "17:00–20:00"


def slots_for_date(d: date):
    # Lun→Dom: 17:00–20:00. Solo Sab+Dom: anche 09:30–12:30.
    slots = [("AFTERNOON", "17:00–20:00")]
    if d.weekday() in (5, 6):  # sab, dom
        slots.insert(0, ("MORNING", "09:30–12:30"))
    return slots


def get_slots_for_date(event_date: str):
    d = parse_event_date(event_date)
    return slots_for_date(d)


def slot_count(conn, event_date: str, slot_code: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM bookings WHERE event_date=? AND slot_code=?",
        (event_date, slot_code),
    ).fetchone()
    return int(row["c"] or 0)


def next_area_for_slot(count: int) -> int:
    # 0 -> Area1, 1 -> Area2, 2 -> Area3
    return 1 if count == 0 else (2 if count == 1 else 3)


# -------------------------
# Contratto + calcoli
# -------------------------
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
            torta_kg = (Decimal(tot_persone) * KG_PER_PERSON).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            totale_torta = TORTA_PRICE_EUR_PER_KG * torta_kg

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

    totale = (totale_pacchetto + totale_torta + totale_extra).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    return {
        "tot_persone": tot_persone,
        "totale_pacchetto": totale_pacchetto,
        "totale_torta": totale_torta,
        "torta_kg": torta_kg,
        "totale_extra": totale_extra,
        "totale": totale,
    }


def build_contract_text(payload: dict) -> str:
    pacchetto = payload.get("pacchetto", "")
    invitati_b = payload.get("invitati_bambini") or 0
    invitati_a = payload.get("invitati_adulti") or 0
    tot_persone = int(invitati_b) + int(invitati_a)

    lines = []
    lines.append(
        f"DATA EVENTO: {payload.get('event_date') or '-'}  |  "
        f"SLOT: {slot_label_from_code(payload.get('slot_code') or '')}  |  "
        f"AREA: {payload.get('area') or '-'}"
    )
    lines.append("")

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
            lines.append("- Catering baby: Box merenda: sandwich con prosciutto cotto, rustico wurstel, mini pizzetta, panzerottino, patatine fritte e bottiglietta dell'acqua")
        else:
            lines.append("- Catering baby: (da definire)")

        lines += [
            "- Catering adulti: tagliere selezione Perina (burratina, ricottina, salumi, ciliegine di mozzarella)",
            "- Catering adulti: fritti centrali (panzerottini, patatine, bandidos, crocchette)",
            "- Catering adulti: pizze in modalita giro pizza farcite (fino ad un massimo di una a testa)",
            "- Bibita a testa tra birra, Coca-Cola, Fanta",
        ]

        if dessert_bimbi == "muffin_nutella":
            lines.append("- Dessert per bambini: Muffin alla Nutella")
        elif dessert_bimbi == "torta_compleanno":
            lines.append("- Dessert per bambini: Torta di compleanno (vedi scelta torta sotto)")
        else:
            lines.append("- Dessert per bambini: (da definire)")

        if dessert_adulti == "muffin_nutella":
            lines.append("- Dessert per adulti: Muffin alla Nutella")
        elif dessert_adulti == "torta_compleanno":
            lines.append("- Dessert per adulti: Torta di compleanno (vedi scelta torta sotto)")
        else:
            lines.append("- Dessert per adulti: (da definire)")

        need_torta = (dessert_bimbi == "torta_compleanno") or (dessert_adulti == "torta_compleanno")
        if need_torta:
            lines += ["", "TORTA (SCELTA) (inclusa nel pacchetto):"]
            if torta_choice == "esterna":
                lines.append("- Torta esterna (con certificazione alimentare del fornitore scelto)")
            elif torta_choice == "interna":
                if torta_interna_choice == "standard":
                    lines.append(f"- Torta interna (da noi): {TORTA_INTERNA_FLAVORS['standard']}")
                elif torta_interna_choice == "altro":
                    lines.append(f"- Torta interna (da noi): Gusto concordato: {torta_gusto_altro or '(da compilare)'}")
                else:
                    lines.append("- Torta interna (da noi): (da definire)")
            else:
                lines.append("- (da definire)")

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
        lines += ["", "DETTAGLI PERSONALIZZAZIONE:"]
        lines.append(det if det else "(da compilare)")

    return "\n".join(lines)


# -------------------------
# PDF: genera contratto
# -------------------------
def contract_pdf_bytes(booking_row: sqlite3.Row) -> bytes:
    buf = io.BytesIO()
    c = pdfcanvas.Canvas(buf, pagesize=A4)
    w, h = A4

    c.setTitle(f"Contratto Lullyland - Prenotazione #{booking_row['id']}")

    y = h - 2 * cm
    c.setFont("Helvetica-Bold", 16)
    c.drawString(2 * cm, y, f"Contratto - {APP_NAME}")
    y -= 0.8 * cm

    c.setFont("Helvetica", 10)
    c.drawString(2 * cm, y, f"Prenotazione #{booking_row['id']}  |  Creato: {booking_row['created_at']}")
    y -= 0.6 * cm

    c.setFont("Helvetica-Bold", 11)
    c.drawString(2 * cm, y, "Dati evento")
    y -= 0.5 * cm
    c.setFont("Helvetica", 10)
    c.drawString(
        2 * cm,
        y,
        f"Data: {booking_row['event_date'] or '-'}   Slot: {slot_label_from_code(booking_row['slot_code'] or '')}   Area: {booking_row['area'] or '-'}",
    )
    y -= 0.6 * cm

    c.setFont("Helvetica-Bold", 11)
    c.drawString(2 * cm, y, "Festeggiato")
    y -= 0.5 * cm
    c.setFont("Helvetica", 10)
    c.drawString(2 * cm, y, f"{booking_row['nome_festeggiato'] or '-'}  -  Età: {booking_row['eta_festeggiato'] or '-'}")
    y -= 0.7 * cm

    c.setFont("Helvetica-Bold", 11)
    c.drawString(2 * cm, y, "Dettagli (contratto)")
    y -= 0.5 * cm

    c.setFont("Helvetica", 9)
    text = (booking_row["dettagli_contratto_text"] or "").strip()
    if not text:
        text = "(Nessun dettaglio contratto disponibile.)"

    max_chars = 105
    lines = []
    for raw in text.split("\n"):
        raw = raw.rstrip()
        if not raw:
            lines.append("")
            continue
        while len(raw) > max_chars:
            lines.append(raw[:max_chars])
            raw = raw[max_chars:]
        lines.append(raw)

    for ln in lines:
        if y < 3 * cm:
            c.showPage()
            y = h - 2 * cm
            c.setFont("Helvetica", 9)
        c.drawString(2 * cm, y, ln)
        y -= 0.35 * cm

    sig = booking_row["firma_png_base64"] or ""
    if sig.startswith("data:image/png;base64,"):
        try:
            b64 = sig.split(",", 1)[1]
            img_bytes = base64.b64decode(b64)
            img = ImageReader(io.BytesIO(img_bytes))

            if y < 7 * cm:
                c.showPage()
                y = h - 2 * cm

            c.setFont("Helvetica-Bold", 11)
            c.drawString(2 * cm, y, "Firma genitore")
            y -= 0.5 * cm

            c.drawImage(
                img,
                2 * cm,
                y - 5 * cm,
                width=10 * cm,
                height=4 * cm,
                preserveAspectRatio=True,
                mask="auto",
            )
            y -= 5.5 * cm
        except Exception:
            pass

    c.showPage()
    c.save()
    return buf.getvalue()


# ====== FINE PEZZO 1/5 ======
# -------------------------
# AUTH
# -------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("pin") == APP_PIN:
            session["ok"] = True
            return redirect(url_for("calendar_month"))
        return render_template_string(LOGIN_HTML, error="PIN errato", app_name=APP_NAME)
    return render_template_string(LOGIN_HTML, error=None, app_name=APP_NAME)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# -------------------------
# HOME → redirect calendario
# -------------------------
@app.route("/")
def home():
    if not is_logged_in():
        return redirect(url_for("login"))
    return redirect(url_for("calendar_month"))


# -------------------------
# CALENDARIO MESE
# -------------------------
@app.route("/calendar")
def calendar_month():
    if not is_logged_in():
        return redirect(url_for("login"))

    today = date.today()
    year = int(request.args.get("year", today.year))
    month = int(request.args.get("month", today.month))

    first_day = date(year, month, 1)
    _, days_in_month = calendar.monthrange(year, month)

    conn = get_db()
    rows = conn.execute(
        """
        SELECT event_date, COUNT(*) as cnt
        FROM bookings
        GROUP BY event_date
        """
    ).fetchall()
    conn.close()

    events_by_day = {r["event_date"]: r["cnt"] for r in rows}

    # NOTA: nel template uso calendar.month_name, quindi lo passo esplicitamente
    return render_template_string(
        CALENDAR_MONTH_HTML,
        app_name=APP_NAME,
        year=year,
        month=month,
        month_name=calendar.month_name,
        days=range(1, days_in_month + 1),
        first_weekday=first_day.weekday(),  # lun(0)..dom(6)
        events_by_day=events_by_day,
    )


# -------------------------
# GIORNO → SLOT + LISTA EVENTI
# -------------------------
@app.route("/calendar/<event_date>")
def calendar_day(event_date):
    if not is_logged_in():
        return redirect(url_for("login"))

    slots = get_slots_for_date(event_date)

    conn = get_db()
    rows = conn.execute(
        """
        SELECT id, slot_code, area, nome_festeggiato, eta_festeggiato,
               invitati_bambini, invitati_adulti, tema_evento, pacchetto
        FROM bookings
        WHERE event_date = ?
        ORDER BY slot_code, area
        """,
        (event_date,),
    ).fetchall()
    conn.close()

    by_slot = {}
    for r in rows:
        by_slot.setdefault(r["slot_code"], []).append(r)

    return render_template_string(
        CALENDAR_DAY_HTML,
        app_name=APP_NAME,
        event_date=event_date,
        slots=slots,
        by_slot=by_slot,
    )


# -------------------------
# ELIMINA EVENTO
# -------------------------
@app.route("/event/<int:booking_id>/delete", methods=["POST"])
def delete_event(booking_id):
    if not is_logged_in():
        return redirect(url_for("login"))

    conn = get_db()
    row = conn.execute(
        "SELECT event_date FROM bookings WHERE id = ?",
        (booking_id,),
    ).fetchone()

    if row:
        event_date = row["event_date"]
        conn.execute("DELETE FROM bookings WHERE id = ?", (booking_id,))
        conn.commit()
        conn.close()
        return redirect(url_for("calendar_day", event_date=event_date))

    conn.close()
    return redirect(url_for("calendar_month"))


# ====== FINE PEZZO 2/5 ======
# -------------------------
# Helpers calendario
# -------------------------
def parse_event_date(s: str) -> date:
    # formato atteso: YYYY-MM-DD
    return datetime.strptime(s, "%Y-%m-%d").date()


def get_slots_for_date(event_date: str):
    d = parse_event_date(event_date)
    return slots_for_date(d)


# -------------------------
# BOOKING: nuova prenotazione da calendario
# URL: /booking/new?event_date=YYYY-MM-DD&slot_code=AFTERNOON|MORNING
# -------------------------
@app.route("/booking/new", methods=["GET", "POST"])
def booking_new():
    if not is_logged_in():
        return redirect(url_for("login"))

    event_date = (request.args.get("event_date") or "").strip()
    slot_code = (request.args.get("slot_code") or "").strip()

    if not event_date or not slot_code:
        return redirect(url_for("calendar_month"))

    slot_label = slot_label_from_code(slot_code)

    conn = get_db()
    count = slot_count(conn, event_date, slot_code)
    area = next_area_for_slot(count)

    is_full = (count >= 2)       # Area1+Area2 occupate → serve conferma Area3
    is_hard_full = (count >= 3)  # già 3 eventi → blocco

    if request.method == "POST":
        # Se già 3 presenti, blocco definitivo
        if is_hard_full:
            conn.close()
            return render_template_string(
                BOOKING_HTML,
                app_name=APP_NAME,
                error="Giorno/slot già pieno (Area 1, 2 e 3 occupate).",
                today=datetime.now().strftime("%Y-%m-%d"),
                form=request.form,
                package_labels=PACKAGE_LABELS,
                catering_baby_options=CATERING_BABY_OPTIONS,
                dessert_options=DESSERT_OPTIONS,
                torta_interna_flavors=TORTA_INTERNA_FLAVORS,
                extra_servizi=EXTRA_SERVIZI,
                extra_servizi_ai=EXTRA_SERVIZI_ALL_INCLUSIVE,
                event_date=event_date,
                slot_code=slot_code,
                slot_label=slot_label,
                area=area,
                is_full=is_full,
            )

        # Se 2 già presenti, serve conferma Area 3
        confirm_area3 = 1 if request.form.get("confirm_area3") else 0
        if is_full and confirm_area3 != 1:
            conn.close()
            return render_template_string(
                BOOKING_HTML,
                app_name=APP_NAME,
                error="Slot già pieno (Area 1 e 2). Spunta la conferma per inserire in Area 3.",
                today=datetime.now().strftime("%Y-%m-%d"),
                form=request.form,
                package_labels=PACKAGE_LABELS,
                catering_baby_options=CATERING_BABY_OPTIONS,
                dessert_options=DESSERT_OPTIONS,
                torta_interna_flavors=TORTA_INTERNA_FLAVORS,
                extra_servizi=EXTRA_SERVIZI,
                extra_servizi_ai=EXTRA_SERVIZI_ALL_INCLUSIVE,
                event_date=event_date,
                slot_code=slot_code,
                slot_label=slot_label,
                area=3,
                is_full=is_full,
            )

        consenso_privacy = 1 if request.form.get("consenso_privacy") else 0
        consenso_foto = 1 if request.form.get("consenso_foto") else 0
        if consenso_privacy != 1:
            conn.close()
            return render_template_string(
                BOOKING_HTML,
                app_name=APP_NAME,
                error="Devi accettare l'informativa privacy per continuare.",
                today=datetime.now().strftime("%Y-%m-%d"),
                form=request.form,
                package_labels=PACKAGE_LABELS,
                catering_baby_options=CATERING_BABY_OPTIONS,
                dessert_options=DESSERT_OPTIONS,
                torta_interna_flavors=TORTA_INTERNA_FLAVORS,
                extra_servizi=EXTRA_SERVIZI,
                extra_servizi_ai=EXTRA_SERVIZI_ALL_INCLUSIVE,
                event_date=event_date,
                slot_code=slot_code,
                slot_label=slot_label,
                area=(3 if is_full else area),
                is_full=is_full,
            )

        firma_png_base64 = (request.form.get("firma_png_base64") or "").strip()
        data_firma = (request.form.get("data_firma") or "").strip()

        if not data_firma:
            conn.close()
            return render_template_string(
                BOOKING_HTML,
                app_name=APP_NAME,
                error="Inserisci la data firma.",
                today=datetime.now().strftime("%Y-%m-%d"),
                form=request.form,
                package_labels=PACKAGE_LABELS,
                catering_baby_options=CATERING_BABY_OPTIONS,
                dessert_options=DESSERT_OPTIONS,
                torta_interna_flavors=TORTA_INTERNA_FLAVORS,
                extra_servizi=EXTRA_SERVIZI,
                extra_servizi_ai=EXTRA_SERVIZI_ALL_INCLUSIVE,
                event_date=event_date,
                slot_code=slot_code,
                slot_label=slot_label,
                area=(3 if is_full else area),
                is_full=is_full,
            )

        if not firma_png_base64.startswith("data:image/png;base64,"):
            conn.close()
            return render_template_string(
                BOOKING_HTML,
                app_name=APP_NAME,
                error="Firma mancante: firma nel riquadro prima di salvare.",
                today=datetime.now().strftime("%Y-%m-%d"),
                form=request.form,
                package_labels=PACKAGE_LABELS,
                catering_baby_options=CATERING_BABY_OPTIONS,
                dessert_options=DESSERT_OPTIONS,
                torta_interna_flavors=TORTA_INTERNA_FLAVORS,
                extra_servizi=EXTRA_SERVIZI,
                extra_servizi_ai=EXTRA_SERVIZI_ALL_INCLUSIVE,
                event_date=event_date,
                slot_code=slot_code,
                slot_label=slot_label,
                area=(3 if is_full else area),
                is_full=is_full,
            )

        pacchetto = (request.form.get("pacchetto") or "").strip()

        # extra selezionati
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
            "event_date": event_date,
            "slot_code": slot_code,
            "area": (3 if is_full else area),

            "nome_festeggiato": (request.form.get("nome_festeggiato") or "").strip(),
            "eta_festeggiato": to_int(request.form.get("eta_festeggiato")),
            "data_compleanno": (request.form.get("data_compleanno") or "").strip(),

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
            "torta_interna_choice": (request.form.get("torta_interna_choice") or "").strip(),
            "torta_gusto_altro": (request.form.get("torta_gusto_altro") or "").strip(),

            "extra_keys": extra_keys,
        }

        # Validazioni minime
        if not payload["nome_festeggiato"]:
            conn.close()
            return render_template_string(
                BOOKING_HTML,
                app_name=APP_NAME,
                error="Inserisci il nome del festeggiato.",
                today=datetime.now().strftime("%Y-%m-%d"),
                form=request.form,
                package_labels=PACKAGE_LABELS,
                catering_baby_options=CATERING_BABY_OPTIONS,
                dessert_options=DESSERT_OPTIONS,
                torta_interna_flavors=TORTA_INTERNA_FLAVORS,
                extra_servizi=EXTRA_SERVIZI,
                extra_servizi_ai=EXTRA_SERVIZI_ALL_INCLUSIVE,
                event_date=event_date,
                slot_code=slot_code,
                slot_label=slot_label,
                area=(3 if is_full else area),
                is_full=is_full,
            )

        if payload["pacchetto"] not in PACKAGE_LABELS.keys():
            conn.close()
            return render_template_string(
                BOOKING_HTML,
                app_name=APP_NAME,
                error="Seleziona un pacchetto valido.",
                today=datetime.now().strftime("%Y-%m-%d"),
                form=request.form,
                package_labels=PACKAGE_LABELS,
                catering_baby_options=CATERING_BABY_OPTIONS,
                dessert_options=DESSERT_OPTIONS,
                torta_interna_flavors=TORTA_INTERNA_FLAVORS,
                extra_servizi=EXTRA_SERVIZI,
                extra_servizi_ai=EXTRA_SERVIZI_ALL_INCLUSIVE,
                event_date=event_date,
                slot_code=slot_code,
                slot_label=slot_label,
                area=(3 if is_full else area),
                is_full=is_full,
            )

        if payload["pacchetto"] == "Personalizzato" and not payload["pacchetto_personalizzato_dettagli"]:
            conn.close()
            return render_template_string(
                BOOKING_HTML,
                app_name=APP_NAME,
                error="Hai scelto Personalizzato: inserisci i dettagli della personalizzazione.",
                today=datetime.now().strftime("%Y-%m-%d"),
                form=request.form,
                package_labels=PACKAGE_LABELS,
                catering_baby_options=CATERING_BABY_OPTIONS,
                dessert_options=DESSERT_OPTIONS,
                torta_interna_flavors=TORTA_INTERNA_FLAVORS,
                extra_servizi=EXTRA_SERVIZI,
                extra_servizi_ai=EXTRA_SERVIZI_ALL_INCLUSIVE,
                event_date=event_date,
                slot_code=slot_code,
                slot_label=slot_label,
                area=(3 if is_full else area),
                is_full=is_full,
            )

        # Validazioni pacchetti (come nel tuo software)
        if payload["pacchetto"] == "Lullyland Experience":
            if payload["catering_baby_choice"] not in CATERING_BABY_OPTIONS.keys():
                conn.close()
                return render_template_string(
                    BOOKING_HTML,
                    app_name=APP_NAME,
                    error="Per Experience scegli il Catering baby (Menu pizza o Box merenda).",
                    today=datetime.now().strftime("%Y-%m-%d"),
                    form=request.form,
                    package_labels=PACKAGE_LABELS,
                    catering_baby_options=CATERING_BABY_OPTIONS,
                    dessert_options=DESSERT_OPTIONS,
                    torta_interna_flavors=TORTA_INTERNA_FLAVORS,
                    extra_servizi=EXTRA_SERVIZI,
                    extra_servizi_ai=EXTRA_SERVIZI_ALL_INCLUSIVE,
                    event_date=event_date,
                    slot_code=slot_code,
                    slot_label=slot_label,
                    area=(3 if is_full else area),
                    is_full=is_full,
                )

            if payload["torta_choice"] not in ("esterna", "interna"):
                conn.close()
                return render_template_string(
                    BOOKING_HTML,
                    app_name=APP_NAME,
                    error="Per Experience scegli la torta: Esterna (+EUR 1 a persona) oppure Interna (EUR 24/kg).",
                    today=datetime.now().strftime("%Y-%m-%d"),
                    form=request.form,
                    package_labels=PACKAGE_LABELS,
                    catering_baby_options=CATERING_BABY_OPTIONS,
                    dessert_options=DESSERT_OPTIONS,
                    torta_interna_flavors=TORTA_INTERNA_FLAVORS,
                    extra_servizi=EXTRA_SERVIZI,
                    extra_servizi_ai=EXTRA_SERVIZI_ALL_INCLUSIVE,
                    event_date=event_date,
                    slot_code=slot_code,
                    slot_label=slot_label,
                    area=(3 if is_full else area),
                    is_full=is_full,
                )

            if payload["torta_choice"] == "interna":
                if payload["torta_interna_choice"] not in TORTA_INTERNA_FLAVORS.keys():
                    conn.close()
                    return render_template_string(
                        BOOKING_HTML,
                        app_name=APP_NAME,
                        error="Se hai scelto Torta interna, seleziona il gusto (standard o altro).",
                        today=datetime.now().strftime("%Y-%m-%d"),
                        form=request.form,
                        package_labels=PACKAGE_LABELS,
                        catering_baby_options=CATERING_BABY_OPTIONS,
                        dessert_options=DESSERT_OPTIONS,
                        torta_interna_flavors=TORTA_INTERNA_FLAVORS,
                        extra_servizi=EXTRA_SERVIZI,
                        extra_servizi_ai=EXTRA_SERVIZI_ALL_INCLUSIVE,
                        event_date=event_date,
                        slot_code=slot_code,
                        slot_label=slot_label,
                        area=(3 if is_full else area),
                        is_full=is_full,
                    )
                if payload["torta_interna_choice"] == "altro" and not payload["torta_gusto_altro"]:
                    conn.close()
                    return render_template_string(
                        BOOKING_HTML,
                        app_name=APP_NAME,
                        error="Hai scelto gusto torta 'Altro': scrivi il gusto concordato.",
                        today=datetime.now().strftime("%Y-%m-%d"),
                        form=request.form,
                        package_labels=PACKAGE_LABELS,
                        catering_baby_options=CATERING_BABY_OPTIONS,
                        dessert_options=DESSERT_OPTIONS,
                        torta_interna_flavors=TORTA_INTERNA_FLAVORS,
                        extra_servizi=EXTRA_SERVIZI,
                        extra_servizi_ai=EXTRA_SERVIZI_ALL_INCLUSIVE,
                        event_date=event_date,
                        slot_code=slot_code,
                        slot_label=slot_label,
                        area=(3 if is_full else area),
                        is_full=is_full,
                    )

        if payload["pacchetto"] == "Lullyland all-inclusive":
            need_torta = (payload["dessert_bimbi_choice"] == "torta_compleanno") or (
                payload["dessert_adulti_choice"] == "torta_compleanno"
            )
            if need_torta:
                if payload["torta_choice"] not in ("esterna", "interna"):
                    conn.close()
                    return render_template_string(
                        BOOKING_HTML,
                        app_name=APP_NAME,
                        error="Per All-inclusive: se scegli la torta come dessert, seleziona Torta esterna oppure Interna.",
                        today=datetime.now().strftime("%Y-%m-%d"),
                        form=request.form,
                        package_labels=PACKAGE_LABELS,
                        catering_baby_options=CATERING_BABY_OPTIONS,
                        dessert_options=DESSERT_OPTIONS,
                        torta_interna_flavors=TORTA_INTERNA_FLAVORS,
                        extra_servizi=EXTRA_SERVIZI,
                        extra_servizi_ai=EXTRA_SERVI

# ====== FINE PEZZO 3/5 ======
                                            extra_servizi_ai=EXTRA_SERVIZI_ALL_INCLUSIVE,
                    event_date=event_date,
                    slot_code=slot_code,
                    slot_label=slot_label,
                    area=(3 if is_full else area),
                    is_full=is_full,
                )
                if payload["torta_choice"] == "interna":
                    if payload["torta_interna_choice"] not in TORTA_INTERNA_FLAVORS.keys():
                        conn.close()
                        return render_template_string(
                            BOOKING_HTML,
                            app_name=APP_NAME,
                            error="Per All-inclusive: se hai scelto Torta interna, seleziona il gusto (standard o altro).",
                            today=datetime.now().strftime("%Y-%m-%d"),
                            form=request.form,
                            package_labels=PACKAGE_LABELS,
                            catering_baby_options=CATERING_BABY_OPTIONS,
                            dessert_options=DESSERT_OPTIONS,
                            torta_interna_flavors=TORTA_INTERNA_FLAVORS,
                            extra_servizi=EXTRA_SERVIZI,
                            extra_servizi_ai=EXTRA_SERVIZI_ALL_INCLUSIVE,
                            event_date=event_date,
                            slot_code=slot_code,
                            slot_label=slot_label,
                            area=(3 if is_full else area),
                            is_full=is_full,
                        )
                    if payload["torta_interna_choice"] == "altro" and not payload["torta_gusto_altro"]:
                        conn.close()
                        return render_template_string(
                            BOOKING_HTML,
                            app_name=APP_NAME,
                            error="Per All-inclusive: hai scelto gusto torta 'Altro': scrivi il gusto concordato.",
                            today=datetime.now().strftime("%Y-%m-%d"),
                            form=request.form,
                            package_labels=PACKAGE_LABELS,
                            catering_baby_options=CATERING_BABY_OPTIONS,
                            dessert_options=DESSERT_OPTIONS,
                            torta_interna_flavors=TORTA_INTERNA_FLAVORS,
                            extra_servizi=EXTRA_SERVIZI,
                            extra_servizi_ai=EXTRA_SERVIZI_ALL_INCLUSIVE,
                            event_date=event_date,
                            slot_code=slot_code,
                            slot_label=slot_label,
                            area=(3 if is_full else area),
                            is_full=is_full,
                        )

        totals = compute_totals(payload)
        contract_text = build_contract_text(payload)

        conn.execute(
            """
            INSERT INTO bookings (
                created_at,
                event_date, slot_code, area,
                nome_festeggiato, eta_festeggiato, data_compleanno,
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
                dettagli_contratto_text
            ) VALUES (
                :created_at,
                :event_date, :slot_code, :area,
                :nome_festeggiato, :eta_festeggiato, :data_compleanno,
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
                :dettagli_contratto_text
            )
            """,
            {
                **payload,
                "extra_keys_csv": ",".join(payload["extra_keys"]),
                "totale_stimato_eur": str(totals["totale"]),
                "dettagli_contratto_text": contract_text,
            },
        )
        conn.commit()
        conn.close()

        return redirect(url_for("calendar_day", event_date=event_date))

    # GET
    conn.close()
    return render_template_string(
        BOOKING_HTML,
        app_name=APP_NAME,
        error=None,
        today=datetime.now().strftime("%Y-%m-%d"),
        form={},
        package_labels=PACKAGE_LABELS,
        catering_baby_options=CATERING_BABY_OPTIONS,
        dessert_options=DESSERT_OPTIONS,
        torta_interna_flavors=TORTA_INTERNA_FLAVORS,
        extra_servizi=EXTRA_SERVIZI,
        extra_servizi_ai=EXTRA_SERVIZI_ALL_INCLUSIVE,
        event_date=event_date,
        slot_code=slot_code,
        slot_label=slot_label,
        area=area,
        is_full=is_full,
    )


# -------------------------
# LISTA PRENOTAZIONI (per link dal form)
# -------------------------
@app.route("/prenotazioni")
def prenotazioni():
    if not is_logged_in():
        return redirect(url_for("login"))

    conn = get_db()
    rows = conn.execute(
        """
        SELECT id, created_at, event_date, slot_code, area, nome_festeggiato,
               pacchetto, invitati_bambini, invitati_adulti, totale_stimato_eur
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
            torta_kg = (Decimal(tot_persone) * KG_PER_PERSON).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            torta_info = f"{tot_persone} persone -> ~ {torta_kg} kg (100g a testa) a EUR {eur(TORTA_PRICE_EUR_PER_KG)}/kg"
        elif tc == "esterna":
            svc_tot = (TORTA_ESTERNASVC_EUR_PER_PERSON * Decimal(tot_persone)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            torta_info = f"{tot_persone} persone -> Servizio torta: EUR {eur(TORTA_ESTERNASVC_EUR_PER_PERSON)} x {tot_persone} = EUR {eur(svc_tot)}"

    elif row["pacchetto"] == "Lullyland all-inclusive":
        need_torta = (row["dessert_bimbi_choice"] == "torta_compleanno") or (
            row["dessert_adulti_choice"] == "torta_compleanno"
        )
        if need_torta:
            tc = (row["torta_choice"] or "").strip()
            if tc == "esterna":
                torta_info = "Torta esterna (inclusa) - con certificazione alimentare del fornitore"
            elif tc == "interna":
                ti = (row["torta_interna_choice"] or "").strip()
                if ti == "standard":
                    torta_info = f"Torta interna (inclusa) - {TORTA_INTERNA_FLAVORS['standard']}"
                elif ti == "altro":
                    gust = (row["torta_gusto_altro"] or "").strip() or "(da compilare)"
                    torta_info = f"Torta interna (inclusa) - Gusto: {gust}"
                else:
                    torta_info = "Torta interna (inclusa) - (da definire)"
            else:
                torta_info = "(da definire)"

    return render_template_string(
        DETAIL_HTML,
        app_name=APP_NAME,
        b=row,
        tot_persone=tot_persone,
        torta_info=torta_info,
    )


# -------------------------
# PDF CONTRATTO
# -------------------------
@app.route("/prenotazioni/<int:booking_id>/contratto.pdf")
def prenotazione_pdf(booking_id: int):
    if not is_logged_in():
        return redirect(url_for("login"))

    conn = get_db()
    row = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
    conn.close()
    if not row:
        abort(404)

    pdf_bytes = contract_pdf_bytes(row)
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"contratto_lullyland_{booking_id}.pdf",
    )


# -------------------------
# HTML TEMPLATES
# -------------------------
              LOGIN_HTML = """
<!doctype html>
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
    .err { color: #b00020; font-weight:700; }
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


CALENDAR_MONTH_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>{{app_name}} - Calendario</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body { font-family: Arial, sans-serif; padding: 16px; background:#f6f7fb; }
    .card { max-width: 980px; margin: 16px auto; background:#fff; padding: 16px; border-radius: 12px; border:1px solid #e8e8e8; }
    .topbar { display:flex; justify-content:space-between; align-items:center; gap:10px; flex-wrap:wrap; }
    .btn { display:inline-block; padding:10px 12px; border-radius:10px; background:#0a84ff; color:#fff; text-decoration:none; font-weight:800; }
    .btn2 { display:inline-block; padding:10px 12px; border-radius:10px; background:#111; color:#fff; text-decoration:none; font-weight:800; }
    .nav { display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
    .grid { display:grid; grid-template-columns: repeat(7, 1fr); gap:8px; margin-top:12px; }
    .dow { font-size:12px; color:#666; font-weight:800; text-align:center; }
    .cell {
      background:#fff; border:1px solid #eee; border-radius:12px;
      padding:10px; min-height:64px; position:relative;
      cursor:pointer;
    }
    .cell:hover { border-color:#cfe3ff; }
    .day { font-weight:900; }
    .badge {
      position:absolute; right:8px; bottom:8px;
      background:#e5f7ee; color:#0b6b3a;
      font-weight:900; font-size:12px;
      padding:4px 8px; border-radius:999px;
      border:1px solid #bfead2;
    }
    .empty { background:transparent; border:none; cursor:default; }
    .muted { color:#666; }
  </style>
</head>
<body>
  {% set months = ["", "Gennaio","Febbraio","Marzo","Aprile","Maggio","Giugno","Luglio","Agosto","Settembre","Ottobre","Novembre","Dicembre"] %}
  <div class="card">
    <div class="topbar">
      <div>
        <div style="font-size:20px; font-weight:900;">📆 Calendario {{app_name}}</div>
        <div class="muted">Clicca un giorno per vedere slot ed eventi</div>
      </div>
      <div class="nav">
        <a class="btn2" href="/prenotazioni">📄 Prenotazioni</a>
        <a class="btn2" href="/logout">Esci</a>
      </div>
    </div>

    <div class="nav" style="margin-top:12px;">
      <a class="btn2" href="/calendar?year={{year}}&month={{month-1 if month>1 else 12}}{% if month==1 %}&year={{year-1}}{% endif %}">◀</a>

      <div style="font-weight:900; font-size:18px;">
        {{months[month]}} {{year}}
      </div>

      <a class="btn2" href="/calendar?year={{year}}&month={{month+1 if month<12 else 1}}{% if month==12 %}&year={{year+1}}{% endif %}">▶</a>
    </div>

    <div class="grid" style="margin-top:14px;">
      <div class="dow">Lun</div><div class="dow">Mar</div><div class="dow">Mer</div><div class="dow">Gio</div><div class="dow">Ven</div><div class="dow">Sab</div><div class="dow">Dom</div>

      {% for i in range(first_weekday) %}
        <div class="cell empty"></div>
      {% endfor %}

      {% for d in days %}
        {% set ds = "%04d-%02d-%02d"|format(year, month, d) %}
        <a class="cell" href="/calendar/{{ds}}" style="text-decoration:none; color:inherit;">
          <div class="day">{{d}}</div>
          {% if events_by_day.get(ds) %}
            <div class="badge">{{events_by_day.get(ds)}} eventi</div>
          {% endif %}
        </a>
      {% endfor %}
    </div>
  </div>
</body>
</html>
"""


CALENDAR_DAY_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>{{app_name}} - {{event_date}}</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body { font-family: Arial, sans-serif; padding: 16px; background:#f6f7fb; }
    .card { max-width: 980px; margin: 16px auto; background:#fff; padding: 16px; border-radius: 12px; border:1px solid #e8e8e8; }
    .topbar { display:flex; justify-content:space-between; align-items:center; gap:10px; flex-wrap:wrap; }
    .btn { display:inline-block; padding:10px 12px; border-radius:10px; background:#0a84ff; color:#fff; text-decoration:none; font-weight:900; }
    .btn2 { display:inline-block; padding:10px 12px; border-radius:10px; background:#111; color:#fff; text-decoration:none; font-weight:900; }
    .slot { border:1px solid #eee; border-radius:12px; padding:12px; margin-top:12px; }
    .slothead { display:flex; align-items:center; justify-content:space-between; gap:10px; flex-wrap:wrap; }
    .pill { display:inline-block; padding:6px 10px; border-radius:999px; font-weight:900; font-size:12px; }
    .green { background:#e7f8ee; color:#0b6b3a; border:1px solid #bfead2; }
    .yellow { background:#fff7db; color:#7a5a00; border:1px solid #f1de9a; }
    .red { background:#ffe2e2; color:#8b0000; border:1px solid #ffb3b3; }
    .event { padding:10px; border-radius:12px; background:#f6f7fb; border:1px solid #e8e8e8; margin-top:10px; }
    .eventline { font-weight:900; }
    .muted { color:#666; font-size:13px; margin-top:4px; }
    form { display:inline; }
    button.danger { border:none; background:#c62828; color:#fff; font-weight:900; padding:8px 10px; border-radius:10px; cursor:pointer; }
    a.link { color:#0a84ff; font-weight:900; text-decoration:none; }
  </style>
</head>
<body>
  <div class="card">
    <div class="topbar">
      <div>
        <div style="font-size:18px; font-weight:900;">📅 {{event_date}}</div>
        <div class="muted">Slot mattina solo Sab/Dom. 2 aree ok, 3ª con conferma.</div>
      </div>
      <div style="display:flex; gap:10px; flex-wrap:wrap;">
        <a class="btn2" href="/calendar">📆 Calendario</a>
        <a class="btn2" href="/prenotazioni">📄 Prenotazioni</a>
      </div>
    </div>

    {% for scode, slabel in slots %}
      {% set events = by_slot.get(scode, []) %}
      {% set c = events|length %}
      {% if c == 0 %}
        {% set cls = "green" %}
        {% set txt = "LIBERO" %}
      {% elif c == 1 %}
        {% set cls = "yellow" %}
        {% set txt = "1 AREA OCCUPATA" %}
      {% else %}
        {% set cls = "red" %}
        {% set txt = "PIENO (Area 1 e 2)" %}
      {% endif %}

      <div class="slot">
        <div class="slothead">
          <div style="font-weight:900;">{{slabel}} ({{"MATTINA" if scode=="MORNING" else "POMERIDIANO/SERALE"}})</div>
          <div style="display:flex; gap:10px; align-items:center; flex-wrap:wrap;">
            <span class="pill {{cls}}">{{txt}}</span>
            <a class="btn" href="/booking/new?event_date={{event_date}}&slot_code={{scode}}">+ Aggiungi evento</a>
          </div>
        </div>

        {% if c == 0 %}
          <div class="muted">Nessun evento in questo slot.</div>
        {% else %}
          {% for e in events %}
            <div class="event">
              <div class="eventline">
                Area {{e['area']}}: {{e['nome_festeggiato']}} – {{e['eta_festeggiato'] or '-'}} anni
                — {{(e['invitati_bambini'] or 0)}} bimbi / {{(e['invitati_adulti'] or 0)}} adulti
              </div>
              <div class="muted">Tema: {{e['tema_evento'] or '-'}} — Pacchetto: {{e['pacchetto'] or '-'}}</div>
              <div style="margin-top:8px; display:flex; gap:10px; flex-wrap:wrap;">
                <a class="link" href="/prenotazioni/{{e['id']}}">Apri dettaglio</a>
                <form method="post" action="/event/{{e['id']}}/delete" onsubmit="return confirm('Confermi eliminazione evento?');">
                  <button class="danger" type="submit">Elimina</button>
                </form>
              </div>
            </div>
          {% endfor %}
        {% endif %}
      </div>
    {% endfor %}

  </div>
</body>
</html>
"""


# BOOKING_HTML è GIÀ DEFINITO nel pezzo 4 (non duplicare qui)


LIST_HTML = """
<!doctype html>
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
    a.btn2 { display:inline-block; padding:10px 12px; border-radius:10px; background:#111; color:#fff; text-decoration:none; font-weight:900; }
    a.link { color:#0a84ff; font-weight:900; text-decoration:none; }
    .muted { color:#666; }
    .pill { display:inline-block; padding:6px 10px; border-radius:999px; background:#f0f2f7; font-weight:900; }
  </style>
</head>
<body>
  <div class="card">
    <h2>Prenotazioni - {{app_name}}</h2>
    <p style="display:flex; gap:10px; flex-wrap:wrap;">
      <a class="btn2" href="/calendar">📆 Calendario</a>
      <a class="btn2" href="/logout">Esci</a>
    </p>

    {% if rows|length == 0 %}
      <p class="muted">Nessuna prenotazione salvata ancora.</p>
    {% else %}
      <table>
        <thead>
          <tr>
            <th>ID</th>
            <th>Creato</th>
            <th>Evento</th>
            <th>Slot/Area</th>
            <th>Festeggiato</th>
            <th>Pacchetto</th>
            <th>Invitati</th>
            <th>Totale</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {% for r in rows %}
            <tr>
              <td>{{r['id']}}</td>
              <td>{{r['created_at']}}</td>
              <td>{{r['event_date']}}</td>
              <td>{{r['slot_code']}} / A{{r['area']}}</td>
              <td>{{r['nome_festeggiato']}}</td>
              <td>{{r['pacchetto']}}</td>
              <td>{{(r['invitati_bambini'] or 0)}} bimbi / {{(r['invitati_adulti'] or 0)}} adulti</td>
              <td>
                {% if r['totale_stimato_eur'] %}
                  <span class="pill">EUR {{"{:0.2f}".format(r['totale_stimato_eur']|float).replace(".", ",")}}</span>
                {% else %}
                  -
                {% endif %}
              </td>
              <td><a class="link" href="/prenotazioni/{{r['id']}}">Apri</a></td>
            </tr>
          {% endfor %}
        </tbody>
      </table>
    {% endif %}
  </div>
</body>
</html>
"""


DETAIL_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>{{app_name}} - Dettaglio prenotazione</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body { font-family: Arial, sans-serif; padding: 18px; background:#f6f7fb; }
    .card { max-width: 980px; margin: 18px auto; background:#fff; padding: 18px; border-radius: 12px; border:1px solid #e8e8e8; }
    .grid { display:flex; gap:12px; flex-wrap:wrap; }
    .box { flex:1; min-width: 280px; border:1px solid #eee; border-radius:12px; padding:12px; }
    .k { color:#666; font-size: 12px; margin-bottom:4px; }
    .v { font-weight: 900; margin-bottom:10px; }
    img { max-width: 760px; width:100%; border:1px solid #ddd; border-radius:12px; background:#fff; }
    .pill { display:inline-block; padding:6px 10px; border-radius:999px; background:#f0f2f7; font-weight:900; }
    .contract {
      white-space: pre-wrap;
      font-family: Arial, sans-serif;
      font-size: 14px;
      line-height: 1.45;
      background:#f6f7fb;
      color:#111;
      padding: 14px;
      border-radius: 12px;
      border:1px solid #e8e8e8;
    }
    a.btn { display:inline-block; padding:10px 12px; border-radius:10px; background:#0a84ff; color:#fff; text-decoration:none; font-weight:900; }
    a.btn2 { display:inline-block; padding:10px 12px; border-radius:10px; background:#111; color:#fff; text-decoration:none; font-weight:900; }
  </style>
</head>
<body>
  <div class="card">
    <p style="display:flex; gap:10px; flex-wrap:wrap;">
      <a class="btn2" href="/calendar/{{b['event_date']}}">⬅ Giorno</a>
      <a class="btn2" href="/calendar">📆 Calendario</a>
      <a class="btn2" href="/prenotazioni">📄 Prenotazioni</a>
      <a class="btn" href="/prenotazioni/{{b['id']}}/contratto.pdf">⬇ Scarica PDF</a>
    </p>

    <h2>Dettaglio prenotazione #{{b['id']}} - {{app_name}}</h2>

    <div class="grid">
      <div class="box">
        <div class="k">Evento</div>
        <div class="v">{{b['event_date']}} — {{b['slot_code']}} — Area {{b['area']}}</div>

        <div class="k">Festeggiato</div>
        <div class="v">{{b['nome_festeggiato']}} ({{b['eta_festeggiato'] or '-'}})</div>

        <div class="k">Data compleanno</div>
        <div class="v">{{b['data_compleanno'] or '-'}}</div>

        <div class="k">Pacchetto</div>
        <div class="v">{{b['pacchetto']}}</div>

        <div class="k">Tema</div>
        <div class="v">{{b['tema_evento'] or '-'}}</div>

        <div class="k">Acconto</div>
        <div class="v">{{b['acconto_eur'] or '-'}}</div>

        <div class="k">Totale stimato</div>
        <div class="v">
          {% if b['totale_stimato_eur'] %}
            <span class="pill">EUR {{"{:0.2f}".format(b['totale_stimato_eur']|float).replace(".", ",")}}</span>
          {% else %}
            -
          {% endif %}
        </div>
      </div>

      <div class="box">
        <div class="k">Madre</div>
        <div class="v">{{b['madre_nome_cognome'] or '-'}} - {{b['madre_telefono'] or '-'}}</div>

        <div class="k">Padre</div>
        <div class="v">{{b['padre_nome_cognome'] or '-'}} - {{b['padre_telefono'] or '-'}}</div>

        <div class="k">Email</div>
        <div class="v">{{b['email'] or '-'}}</div>

        <div class="k">Residenza</div>
        <div class="v">{{b['indirizzo_residenza'] or '-'}}</div>

        <div class="k">Invitati</div>
        <div class="v">{{b['invitati_bambini'] or 0}} bimbi - {{b['invitati_adulti'] or 0}} adulti</div>

        <div class="k">Torta</div>
        <div class="v">{{torta_info}}</div>
      </div>

      <div class="box" style="flex-basis:100%;">
        <div class="k">Dettagli pacchetto (contratto)</div>
        <div class="contract">{{b['dettagli_contratto_text'] or ''}}</div>

        <div class="k" style="margin-top:12px;">Note</div>
        <div class="v">{{b['note'] or '-'}}</div>

        <div class="k">Consensi</div>
        <div class="v">
          <span class="pill">Privacy: {{'SI' if b['consenso_privacy']==1 else 'NO'}}</span>
          <span class="pill" style="margin-left:8px;">Foto/Video: {{'SI' if b['consenso_foto']==1 else 'NO'}}</span>
        </div>

        <div class="k">Data firma</div>
        <div class="v">{{b['data_firma']}}</div>

        <div class="k">Firma</div>
        <img src="{{b['firma_png_base64']}}" alt="Firma genitore" />
      </div>
    </div>
  </div>
</body>
</html>
"""


# -------------------------
# MAIN
# -------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))          
