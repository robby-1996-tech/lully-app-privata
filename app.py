import os
import sqlite3
from datetime import datetime, date
from decimal import Decimal, ROUND_HALF_UP
from calendar import monthcalendar, month_name

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
# Cataloghi e prezzi (TUOI)
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

    # colonne "pacchetti"
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

    # colonne calendario
    ensure_column(conn, "bookings", "event_date", "TEXT")   # YYYY-MM-DD
    ensure_column(conn, "bookings", "slot_code", "TEXT")    # MORNING/AFTERNOON
    ensure_column(conn, "bookings", "start_time", "TEXT")   # 17:00
    ensure_column(conn, "bookings", "end_time", "TEXT")     # 20:00
    ensure_column(conn, "bookings", "area", "INTEGER")      # 1/2/3...

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
        lines.append("")
        lines.append("INCLUDE:")
        lines.append("- Accesso al parco giochi di 350mq")
        lines.append("- Pulizia e igienizzazione impeccabili prima e dopo la festa")
        lines.append("- Area riservata con tavoli e sedie")
        lines.append("- Tavolo torta con gonna e tovaglia monocolore, lavagnetta con nome e anni del festeggiato e sfondo a tema")
        lines.append("")
        lines.append("NON INCLUDE:")
        lines.append("- Piatti, bicchieri, tovaglioli, tovaglie")
        lines.append("- Servizio")
        lines.append("- Sgombero tavoli")
        lines.append("")
        lines.append("NOTE IMPORTANTI (REGOLE):")
        lines.append("- E' obbligatorio fornire certificazione alimentare sia per il buffet che per la torta (fornita dal fornitore da loro scelto)")
        lines.append("- E' obbligatorio acquistare le bibite al nostro bar, non e' possibile introdurre bevande dall'esterno")
        lines.append("- E' obbligatorio l'utilizzo di calzini antiscivolo per tutti i bambini che usufruiranno del parco")
        lines.append("- E' severamente vietato entrare all'interno del parco con scarpe con tacchi (pavimentazione antitrauma in gomma): pena addebito EUR 60,00 per ogni mattonella antitrauma forata")
        lines.append("- E' obbligatorio l'utilizzo di copri scarpe all'interno del parco (da noi forniti)")
        lines.append("- E' severamente vietato introdurre cibo e bevande all'interno del parco")

    elif pacchetto == "Lullyland Experience":
        catering_choice = payload.get("catering_baby_choice") or ""
        torta_choice = payload.get("torta_choice") or ""
        torta_interna_choice = payload.get("torta_interna_choice") or ""
        torta_gusto_altro = payload.get("torta_gusto_altro") or ""

        lines.append("")
        lines.append("INCLUDE:")
        lines.append("- Accesso al parco giochi di 350mq")
        lines.append("- Pulizia e igienizzazione impeccabili prima e dopo la festa")
        lines.append("- Area riservata con tavoli e sedie")
        lines.append("- Tavolo torta con gonna e tovaglia monocolore, lavagnetta con nome e anni del festeggiato e sfondo a tema")
        lines.append("- Piatti, bicchieri, tovaglioli")

        if catering_choice == "menu_pizza":
            lines.append("- Catering baby: Menu pizza: Pizza Baby, patatine, bottiglietta dell'acqua")
        elif catering_choice == "box_merenda":
            lines.append("- Catering baby: Box merenda: sandwich con prosciutto cotto, rustico wurstel, mini pizzetta, panzerottino, patatine fritte, bottiglietta dell'acqua")
        else:
            lines.append("- Catering baby: (da definire)")

        lines.append("- Catering adulti: fritti centrali (panzerottini, patatine, bandidos, crocchette), pizze centrali margherita e bibite centrali da 1,5lt (acqua, Coca-Cola, Fanta)")

        lines.append("")
        lines.append("NON INCLUDE:")
        lines.append("- Torta di compleanno")

        lines.append("")
        if torta_choice == "esterna":
            lines.append("TORTA (ESTERNA):")
            lines.append(f"- Torta esterna: +EUR {eur(TORTA_ESTERNASVC_EUR_PER_PERSON)} a persona (servizio torta)")
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
            lines.append("")
            lines.append("SERVIZI EXTRA (selezionati):")
            tot_extra = Decimal("0.00")
            for k in extra_keys:
                if k in EXTRA_SERVIZI:
                    name, price = EXTRA_SERVIZI[k]
                    tot_extra += price
                    lines.append(f"- {name} EUR {eur(price)}")
            lines.append(f"Totale extra: EUR {eur(tot_extra)}")

        lines.append("")
        lines.append("NOTE IMPORTANTI (REGOLE):")
        if torta_choice == "esterna":
            lines.append("- (Torta esterna) E' obbligatorio fornire certificazione alimentare per la torta (fornita dal fornitore da loro scelto)")
        lines.append("- E' obbligatorio l'utilizzo di calzini antiscivolo per tutti i bambini che usufruiranno del parco")
        lines.append("- E' severamente vietato entrare all'interno del parco con scarpe con tacchi (pavimentazione antitrauma in gomma): pena addebito EUR 60,00 per ogni mattonella antitrauma forata")
        lines.append("- E' obbligatorio l'utilizzo di copri scarpe all'interno del parco (da noi forniti)")
        lines.append("- E' severamente vietato introdurre cibo e bevande all'interno del parco")

    elif pacchetto == "Lullyland all-inclusive":
        catering_choice = payload.get("catering_baby_choice") or ""
        dessert_bimbi = payload.get("dessert_bimbi_choice") or ""
        dessert_adulti = payload.get("dessert_adulti_choice") or ""

        torta_choice = payload.get("torta_choice") or ""
        torta_interna_choice = payload.get("torta_interna_choice") or ""
        torta_gusto_altro = payload.get("torta_gusto_altro") or ""

        lines.append("")
        lines.append("INCLUDE:")
        lines.append("- Accesso al parco giochi di 350mq")
        lines.append("- Pulizia e igienizzazione impeccabili prima e dopo la festa")
        lines.append("- Area riservata con tavoli e sedie")
        lines.append("- Tavolo torta con gonna e tovaglia monocolore, lavagnetta con nome e anni del festeggiato e sfondo a tema")
        lines.append("- Piatti, bicchieri, tovaglioli")

        if catering_choice == "menu_pizza":
            lines.append("- Catering baby: Menu pizza: Pizza Baby, patatine, bottiglietta dell'acqua")
        elif catering_choice == "box_merenda":
            lines.append("- Catering baby: Box merenda: sandwich con prosciutto cotto, rustico wurstel, mini pizzetta, panzerottino, patatine fritte e bottiglietta dell'acqua")
        else:
            lines.append("- Catering baby: (da definire)")

        lines.append("- Catering adulti: tagliere selezione Perina (burratina, ricottina, salumi, ciliegine di mozzarella)")
        lines.append("- Catering adulti: fritti centrali (panzerottini, patatine, bandidos, crocchette)")
        lines.append("- Catering adulti: pizze in modalita giro pizza farcite (fino ad un massimo di una a testa)")
        lines.append("- Bibita a testa tra birra, Coca-Cola, Fanta")

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
            lines.append("")
            lines.append("TORTA (SCELTA) (inclusa nel pacchetto):")
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

        lines.append("- Carretto zucchero filato illimitati")
        lines.append("- Carretto pop corn illimitati")
        lines.append("- Intrattenitore (salvo disponibilita)")
        lines.append("- Torta scenografica (noleggio)")

        extra_keys = payload.get("extra_keys", [])
        if extra_keys:
            lines.append("")
            lines.append("SERVIZI EXTRA (selezionati):")
            tot_extra = Decimal("0.00")
            for k in extra_keys:
                if k in EXTRA_SERVIZI_ALL_INCLUSIVE:
                    name, price = EXTRA_SERVIZI_ALL_INCLUSIVE[k]
                    tot_extra += price
                    lines.append(f"- {name} EUR {eur(price)}")
            lines.append(f"Totale extra: EUR {eur(tot_extra)}")

        lines.append("")
        lines.append("NOTE IMPORTANTI (REGOLE):")
        lines.append("- E' obbligatorio l'utilizzo di calzini antiscivolo per tutti i bambini che usufruiranno del parco")
        lines.append("- E' severamente vietato entrare all'interno del parco con scarpe con tacchi (pavimentazione antitrauma in gomma): pena addebito EUR 60,00 per ogni mattonella antitrauma forata")
        lines.append("- E' obbligatorio l'utilizzo di copri scarpe all'interno del parco (da noi forniti)")
        lines.append("- E' severamente vietato introdurre cibo e bevande all'interno del parco")

    elif pacchetto == "Personalizzato":
        det = (payload.get("pacchetto_personalizzato_dettagli") or "").strip()
        lines.append("")
        lines.append("DETTAGLI PERSONALIZZAZIONE:")
        lines.append(det if det else "(da compilare)")

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

    return {
        "tot_persone": tot_persone,
        "totale_pacchetto": totale_pacchetto,
        "totale_torta": totale_torta,
        "torta_kg": torta_kg,
        "totale_extra": totale_extra,
        "totale": totale,
    }

# -------------------------
# Calendario: slot rules
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


def slot_count(conn, event_date: str, slot_code: str) -> int:
    r = conn.execute(
        "SELECT COUNT(*) AS c FROM bookings WHERE event_date=? AND slot_code=?",
        (event_date, slot_code)
    ).fetchone()
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

# -------------------------
# Calendario: mese / anno / giorno
# -------------------------
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

# -------------------------
# SOFTWARE EVENTO collegato al calendario
# -------------------------
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
    current = slot_count(conn, event_date, slot_code)
    is_full = current >= 2

    if request.method == "POST":
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
                slot=slot,
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
                slot=slot,
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
                slot=slot,
                is_full=is_full,
            )

        pacchetto = (request.form.get("pacchetto") or "").strip()

        # regola 3a festa
        confirm_area3 = (request.form.get("confirm_area3") == "on")
        now_count = slot_count(conn, event_date, slot_code)
        if now_count >= 2 and not confirm_area3:
            conn.close()
            return render_template_string(
                BOOKING_HTML,
                app_name=APP_NAME,
                error="Area 1 e 2 sono già impegnate. Se vuoi inserire comunque, conferma Area 3.",
                today=datetime.now().strftime("%Y-%m-%d"),
                form=request.form,
                package_labels=PACKAGE_LABELS,
                catering_baby_options=CATERING_BABY_OPTIONS,
                dessert_options=DESSERT_OPTIONS,
                torta_interna_flavors=TORTA_INTERNA_FLAVORS,
                extra_servizi=EXTRA_SERVIZI,
                extra_servizi_ai=EXTRA_SERVIZI_ALL_INCLUSIVE,
                event_date=event_date,
                slot=slot,
                is_full=True,
            )

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

            "data_evento": event_date,  # compatibilità

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

        # validazioni base
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
                slot=slot,
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
                slot=slot,
                is_full=is_full,
            )

        # -------------------------
        # VALIDAZIONI PER PACCHETTI
        # -------------------------
        if payload["pacchetto"] == "Personalizzato" and not payload["pacchetto_personalizzato_dettagli"]:
            conn.close()
            return render_template_string(
                BOOKING_HTML,
                app_name=APP_NAME,
                error="Hai scelto 'Personalizzato': inserisci i dettagli della personalizzazione.",
                today=datetime.now().strftime("%Y-%m-%d"),
                form=request.form,
                package_labels=PACKAGE_LABELS,
                catering_baby_options=CATERING_BABY_OPTIONS,
                dessert_options=DESSERT_OPTIONS,
                torta_interna_flavors=TORTA_INTERNA_FLAVORS,
                extra_servizi=EXTRA_SERVIZI,
                extra_servizi_ai=EXTRA_SERVIZI_ALL_INCLUSIVE,
                event_date=event_date,
                slot=slot,
                is_full=is_full,
            )

        if payload["pacchetto"] == "Lullyland Experience":
            if payload["catering_baby_choice"] not in CATERING_BABY_OPTIONS.keys():
                conn.close()
                return render_template_string(
                    BOOKING_HTML,
                    app_name=APP_NAME,
                    error="Per Experience devi scegliere il Catering baby (Menu pizza o Box merenda).",
                    today=datetime.now().strftime("%Y-%m-%d"),
                    form=request.form,
                    package_labels=PACKAGE_LABELS,
                    catering_baby_options=CATERING_BABY_OPTIONS,
                    dessert_options=DESSERT_OPTIONS,
                    torta_interna_flavors=TORTA_INTERNA_FLAVORS,
                    extra_servizi=EXTRA_SERVIZI,
                    extra_servizi_ai=EXTRA_SERVIZI_ALL_INCLUSIVE,
                    event_date=event_date,
                    slot=slot,
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
                    slot=slot,
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
                        slot=slot,
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
                        slot=slot,
                        is_full=is_full,
                    )

        if payload["pacchetto"] == "Lullyland all-inclusive":
            need_torta = (payload["dessert_bimbi_choice"] == "torta_compleanno") or (payload["dessert_adulti_choice"] == "torta_compleanno")
            if need_torta:
                if payload["torta_choice"] not in ("esterna", "interna"):
                    conn.close()
                    return render_template_string(
                        BOOKING_HTML,
                        app_name=APP_NAME,
                        error="All-inclusive: se scegli la torta come dessert, seleziona Torta esterna oppure Interna.",
                        today=datetime.now().strftime("%Y-%m-%d"),
                        form=request.form,
                        package_labels=PACKAGE_LABELS,
                        catering_baby_options=CATERING_BABY_OPTIONS,
                        dessert_options=DESSERT_OPTIONS,
                        torta_interna_flavors=TORTA_INTERNA_FLAVORS,
                        extra_servizi=EXTRA_SERVIZI,
                        extra_servizi_ai=EXTRA_SERVIZI_ALL_INCLUSIVE,
                        event_date=event_date,
                        slot=slot,
                        is_full=is_full,
                    )

                if payload["torta_choice"] == "interna":
                    if payload["torta_interna_choice"] not in TORTA_INTERNA_FLAVORS.keys():
                        conn.close()
                        return render_template_string(
                            BOOKING_HTML,
                            app_name=APP_NAME,
                            error="All-inclusive: se hai scelto Torta interna, seleziona il gusto (standard o altro).",
                            today=datetime.now().strftime("%Y-%m-%d"),
                            form=request.form,
                            package_labels=PACKAGE_LABELS,
                            catering_baby_options=CATERING_BABY_OPTIONS,
                            dessert_options=DESSERT_OPTIONS,
                            torta_interna_flavors=TORTA_INTERNA_FLAVORS,
                            extra_servizi=EXTRA_SERVIZI,
                            extra_servizi_ai=EXTRA_SERVIZI_ALL_INCLUSIVE,
                            event_date=event_date,
                            slot=slot,
                            is_full=is_full,
                        )

                    if payload["torta_interna_choice"] == "altro" and not payload["torta_gusto_altro"]:
                        conn.close()
                        return render_template_string(
                            BOOKING_HTML,
                            app_name=APP_NAME,
                            error="All-inclusive: hai scelto gusto torta 'Altro': scrivi il gusto concordato.",
                            today=datetime.now().strftime("%Y-%m-%d"),
                            form=request.form,
                            package_labels=PACKAGE_LABELS,
                            catering_baby_options=CATERING_BABY_OPTIONS,
                            dessert_options=DESSERT_OPTIONS,
                            torta_interna_flavors=TORTA_INTERNA_FLAVORS,
                            extra_servizi=EXTRA_SERVIZI,
                            extra_servizi_ai=EXTRA_SERVIZI_ALL_INCLUSIVE,
                            event_date=event_date,
                            slot=slot,
                            is_full=is_full,
                        )

        totals = compute_totals(payload)
        contract_text = build_contract_text(payload)
        area = next_area(conn, event_date, slot_code)

        cur = conn.cursor()
        cur.execute(
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
        slot=slot,
        is_full=is_full,
    )

# -------------------------
# Alias compatibilità vecchio link
# -------------------------
@app.route("/prenota", methods=["GET", "POST"])
def prenota():
    return redirect(url_for("calendar_month"))

# -------------------------
# Prenotazioni: lista + dettaglio
# -------------------------
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
        else:
            torta_info = "-"

    return render_template_string(
        DETAIL_HTML,
        app_name=APP_NAME,
        b=row,
        tot_persone=tot_persone,
        torta_info=torta_info,
    )

# -------------------------
# HTML Templates
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

# ✅ INCOLLA QUI IL TUO BOOKING_HTML, LIST_HTML, DETAIL_HTML (se già li hai, NON duplicarli)
# Io non li reincollo qui perché il tuo file li aveva già quasi certamente.

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
