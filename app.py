import os
import sqlite3

import importlib.util
from pathlib import Path

def load_local_calendar_module():
    here = Path(__file__).resolve().parent
    cal_path = here / "calendar.py"
    if not cal_path.exists():
        raise RuntimeError(f"calendar.py non trovato in {here}")
    spec = importlib.util.spec_from_file_location("lully_calendar", str(cal_path))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod

lcal = load_local_calendar_module()

from datetime import datetime, date, timedelta
from decimal import Decimal, ROUND_HALF_UP

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

# IMPORTANTISSIMO: su Render lo mettiamo come Environment Variable
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-key-change-me")
APP_PIN = os.getenv("APP_PIN", "1234")

# Se metti un Render Disk, imposta DB_PATH su un path persistente, es:
# /var/data/lullyland.db
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
    "Fai da Te": "Fai da Te €15,00 a persona",
    "Lullyland Experience": "Lullyland Experience €20,00 a persona",
    "Lullyland all-inclusive": "Lullyland All-inclusive €30,00 a persona",
    "Personalizzato": "Personalizzato",
}

# Catering baby (usato da Experience + All-inclusive)
CATERING_BABY_OPTIONS = {
    "menu_pizza": "Menù pizza",
    "box_merenda": "Box merenda",
}

# Torta (Experience: scelta esterna/interna; All-inclusive: come dessert se scelgono torta)
TORTA_PRICE_EUR_PER_KG = Decimal("24.00")
TORTA_ESTERNASVC_EUR_PER_PERSON = Decimal("1.00")
KG_PER_PERSON = Decimal("0.10")  # 100g a testa

TORTA_INTERNA_FLAVORS = {
    "standard": "Pan di spagna analcolico con crema chantilly e gocce di cioccolato",
    "altro": "Altro (scrivi gusto)",
}

# Dessert (All-inclusive)
DESSERT_OPTIONS = {
    "muffin_nutella": "Muffin alla Nutella",
    "torta_compleanno": "Torta di compleanno",
}

# Extra (selezionabili) - usati per Experience
EXTRA_SERVIZI = {
    "zucchero_filato": ("Carretto zucchero filato illimitati", Decimal("50.00")),
    "pop_corn": ("Carretto pop corn illimitati", Decimal("50.00")),
    "torta_scenografica": ("Noleggio torta scenografica", Decimal("45.00")),
    "intrattenitore": ("Intrattenitore", Decimal("100.00")),
    "bolle_sapone": ("Spettacolo bolle di sapone", Decimal("200.00")),
    "mascotte_standard": ("Servizio mascotte standard", Decimal("65.00")),
    "mascotte_deluxe": ("Servizio mascotte deluxe", Decimal("90.00")),
}

# Extra (selezionabili) - usati per All-inclusive (togliamo quelli già inclusi: zucchero, pop, intrattenitore, torta scenografica)
EXTRA_SERVIZI_ALL_INCLUSIVE = {
    "bolle_sapone": ("Spettacolo bolle di sapone", Decimal("200.00")),  # resta 200 anche se tengono intrattenitore
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

    # Migrazioni colonne nuove (se la tabella esiste già)
    ensure_column(conn, "bookings", "acconto_eur", "TEXT")
    ensure_column(conn, "bookings", "pacchetto_personalizzato_dettagli", "TEXT")

    ensure_column(conn, "bookings", "catering_baby_choice", "TEXT")

    ensure_column(conn, "bookings", "torta_choice", "TEXT")              # "esterna" / "interna"
    ensure_column(conn, "bookings", "torta_interna_choice", "TEXT")      # "standard" / "altro"
    ensure_column(conn, "bookings", "torta_gusto_altro", "TEXT")

    # Dessert (All-inclusive)
    ensure_column(conn, "bookings", "dessert_bimbi_choice", "TEXT")      # muffin_nutella / torta_compleanno
    ensure_column(conn, "bookings", "dessert_adulti_choice", "TEXT")     # muffin_nutella / torta_compleanno

    # Extra: salviamo lista in testo (csv keys)
    ensure_column(conn, "bookings", "extra_keys_csv", "TEXT")

    # Totali stimati (bloccati al momento della firma)
    ensure_column(conn, "bookings", "totale_stimato_eur", "TEXT")
    ensure_column(conn, "bookings", "dettagli_contratto_text", "TEXT")

    # ✅ CALENDARIO: colonne slot_key e area_num
    lcal.ensure_calendar_columns(conn)

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
    except:
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
        lines.append(f"PACCHETTO: {pacchetto} – €{eur(price)} a persona")
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
        lines.append("- È obbligatorio fornire certificazione alimentare sia per il buffet che per la torta (fornita dal fornitore da loro scelto)")
        lines.append("- È obbligatorio acquistare le bibite al nostro bar, non è possibile introdurre bevande dall’esterno")
        lines.append("- È obbligatorio l’utilizzo di calzini antiscivolo per tutti i bambini che usufruiranno del parco")
        lines.append("- È severamente vietato entrare all’interno del parco con scarpe con tacchi (pavimentazione antitrauma in gomma): pena addebito €60,00 per ogni mattonella antitrauma forata")
        lines.append("- È obbligatorio l’utilizzo di copri scarpe all’interno del parco (da noi forniti)")
        lines.append("- È severamente vietato introdurre cibo e bevande all’interno del parco")

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
            lines.append("- Catering baby: Menù pizza: Pizza Baby, patatine, bottiglietta dell’acqua")
        elif catering_choice == "box_merenda":
            lines.append("- Catering baby: Box merenda: sandwich con prosciutto cotto, rustico würstel, mini pizzetta, panzerottino, patatine fritte, bottiglietta dell’acqua")
        else:
            lines.append("- Catering baby: (da definire)")

        lines.append("- Catering adulti: fritti centrali (panzerottini, patatine, bandidos, crocchette), pizze centrali margherita e bibite centrali da 1,5lt (acqua, Coca-Cola, Fanta)")

        lines.append("")
        lines.append("NON INCLUDE:")
        lines.append("- Torta di compleanno")

        lines.append("")
        if torta_choice == "esterna":
            lines.append("TORTA (ESTERNA):")
            lines.append(f"- Torta esterna: +€{eur(TORTA_ESTERNASVC_EUR_PER_PERSON)} a persona (servizio torta)")
        else:
            lines.append(f"TORTA (SCELTA) (€{eur(TORTA_PRICE_EUR_PER_KG)} al chilo):")
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
                    lines.append(f"- {name} €{eur(price)}")
            lines.append(f"Totale extra: €{eur(tot_extra)}")

        lines.append("")
        lines.append("NOTE IMPORTANTI (REGOLE):")
        if torta_choice == "esterna":
            lines.append("- (Torta esterna) È obbligatorio fornire certificazione alimentare per la torta (fornita dal fornitore da loro scelto)")
        lines.append("- È obbligatorio l’utilizzo di calzini antiscivolo per tutti i bambini che usufruiranno del parco")
        lines.append("- È severamente vietato entrare all’interno del parco con scarpe con tacchi (pavimentazione antitrauma in gomma): pena addebito €60,00 per ogni mattonella antitrauma forata")
        lines.append("- È obbligatorio l’utilizzo di copri scarpe all’interno del parco (da noi forniti)")
        lines.append("- È severamente vietato introdurre cibo e bevande all’interno del parco")

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

        # Catering baby (tendina - NON obbligatoria)
        if catering_choice == "menu_pizza":
            lines.append("- Catering baby: Menù pizza: Pizza Baby, patatine, bottiglietta dell’acqua")
        elif catering_choice == "box_merenda":
            lines.append("- Catering baby: Box merenda: sandwich con prosciutto cotto, rustico würstel, mini pizzetta, panzerottino, patatine fritte e bottiglietta dell’acqua")
        else:
            lines.append("- Catering baby: (da definire)")

        lines.append("- Catering adulti: tagliere selezione Perina (burratina, ricottina, salumi, ciliegine di mozzarella)")
        lines.append("- Catering adulti: fritti centrali (panzerottini, patatine, bandidos, crocchette)")
        lines.append("- Catering adulti: pizze in modalità “giro pizza” farcite (fino ad un massimo di una a testa)")
        lines.append("- Bibita a testa tra birra, Coca-Cola, Fanta")

        # Dessert bimbi
        if dessert_bimbi == "muffin_nutella":
            lines.append("- Dessert per bambini: Muffin alla Nutella")
        elif dessert_bimbi == "torta_compleanno":
            lines.append("- Dessert per bambini: Torta di compleanno (vedi scelta torta sotto)")
        else:
            lines.append("- Dessert per bambini: (da definire)")

        # Dessert adulti
        if dessert_adulti == "muffin_nutella":
            lines.append("- Dessert per adulti: Muffin alla Nutella")
        elif dessert_adulti == "torta_compleanno":
            lines.append("- Dessert per adulti: Torta di compleanno (vedi scelta torta sotto)")
        else:
            lines.append("- Dessert per adulti: (da definire)")

        # Torta (solo se qualcuno ha scelto torta come dessert)
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
        lines.append("- Intrattenitore (salvo disponibilità)")
        lines.append("- Torta scenografica (noleggio)")

        # Extra selezionati (ALL-INCLUSIVE)
        extra_keys = payload.get("extra_keys", [])
        if extra_keys:
            lines.append("")
            lines.append("SERVIZI EXTRA (selezionati):")
            tot_extra = Decimal("0.00")
            for k in extra_keys:
                if k in EXTRA_SERVIZI_ALL_INCLUSIVE:
                    name, price = EXTRA_SERVIZI_ALL_INCLUSIVE[k]
                    tot_extra += price
                    lines.append(f"- {name} €{eur(price)}")
            lines.append(f"Totale extra: €{eur(tot_extra)}")

        lines.append("")
        lines.append("NOTE IMPORTANTI (REGOLE):")
        lines.append("- È obbligatorio l’utilizzo di calzini antiscivolo per tutti i bambini che usufruiranno del parco")
        lines.append("- È severamente vietato entrare all’interno del parco con scarpe con tacchi (pavimentazione antitrauma in gomma): pena addebito €60,00 per ogni mattonella antitrauma forata")
        lines.append("- È obbligatorio l’utilizzo di copri scarpe all’interno del parco (da noi forniti)")
        lines.append("- È severamente vietato introdurre cibo e bevande all’interno del parco")

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

    # Torta: solo Experience incide sui totali; All-inclusive la torta è inclusa (se scelta come dessert)
    torta_choice = payload.get("torta_choice") or ""
    totale_torta = Decimal("0.00")
    torta_kg = Decimal("0.00")

    if pacchetto == "Lullyland Experience":
        if torta_choice == "esterna":
            totale_torta = TORTA_ESTERNASVC_EUR_PER_PERSON * Decimal(tot_persone)
        elif torta_choice == "interna":
            torta_kg = (Decimal(tot_persone) * KG_PER_PERSON).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            totale_torta = TORTA_PRICE_EUR_PER_KG * torta_kg

    # Extra
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
# Auth
# -------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        pin = request.form.get("pin", "")
        if pin == APP_PIN:
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


# ✅ CALENDARIO (vista mese)
@app.route("/calendario")
def calendario():
    if not is_logged_in():
        return redirect(url_for("login"))

    today = date.today()
    year = to_int(request.args.get("year")) or today.year
    month = to_int(request.args.get("month")) or today.month

    # griglia mese
    grid = lcal.month_grid(year, month)

    # range date da caricare (min/max della griglia)
    all_days = [d for week in grid for d in week if d is not None]
    if not all_days:
        all_days = [date(year, month, 1)]
    start_d = min(all_days)
    end_d = max(all_days)

    conn = get_db()
    events = lcal.get_events_between(conn, start_d, end_d)
    conn.close()

    idx = lcal.build_calendar_index(events)

    # nav mese
    cur_first = date(year, month, 1)
    prev_month = (cur_first - timedelta(days=1)).replace(day=1)
    next_month = (cur_first.replace(day=28) + timedelta(days=4)).replace(day=1)

    return render_template_string(
        CALENDAR_HTML,
        app_name=APP_NAME,
        year=year,
        month=month,
        grid=grid,
        idx=idx,
        slot_labels=lcal.SLOT_LABELS,
        prev_year=prev_month.year,
        prev_month=prev_month.month,
        next_year=next_month.year,
        next_month=next_month.month,
        today=today,
    )


@app.route("/prenota", methods=["GET", "POST"])
def prenota():
    if not is_logged_in():
        return redirect(url_for("login"))

    if request.method == "POST":
        consenso_privacy = 1 if request.form.get("consenso_privacy") else 0
        consenso_foto = 1 if request.form.get("consenso_foto") else 0

        if consenso_privacy != 1:
            return render_template_string(
                BOOKING_HTML,
                app_name=APP_NAME,
                error="Devi accettare l’informativa privacy per continuare.",
                today=datetime.now().strftime("%Y-%m-%d"),
                form=request.form,
                package_labels=PACKAGE_LABELS,
                catering_baby_options=CATERING_BABY_OPTIONS,
                dessert_options=DESSERT_OPTIONS,
                torta_interna_flavors=TORTA_INTERNA_FLAVORS,
                extra_servizi=EXTRA_SERVIZI,
                extra_servizi_ai=EXTRA_SERVIZI_ALL_INCLUSIVE,
            )

        firma_png_base64 = (request.form.get("firma_png_base64") or "").strip()
        data_firma = (request.form.get("data_firma") or "").strip()

        if not data_firma:
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
            )

        if not firma_png_base64.startswith("data:image/png;base64,"):
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
            )

        pacchetto = (request.form.get("pacchetto") or "").strip()

        # Extra keys: dipende dal pacchetto
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
            "data_evento": (request.form.get("data_evento") or "").strip(),

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

        if not payload["nome_festeggiato"]:
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
            )

        if not payload["data_evento"]:
            return render_template_string(
                BOOKING_HTML,
                app_name=APP_NAME,
                error="Seleziona la data dell’evento.",
                today=datetime.now().strftime("%Y-%m-%d"),
                form=request.form,
                package_labels=PACKAGE_LABELS,
                catering_baby_options=CATERING_BABY_OPTIONS,
                dessert_options=DESSERT_OPTIONS,
                torta_interna_flavors=TORTA_INTERNA_FLAVORS,
                extra_servizi=EXTRA_SERVIZI,
                extra_servizi_ai=EXTRA_SERVIZI_ALL_INCLUSIVE,
            )

        if payload["pacchetto"] not in PACKAGE_LABELS.keys():
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
            )

        if payload["pacchetto"] == "Personalizzato" and not payload["pacchetto_personalizzato_dettagli"]:
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
            )

        # Validazioni Experience (come prima)
        if payload["pacchetto"] == "Lullyland Experience":
            if payload["catering_baby_choice"] not in CATERING_BABY_OPTIONS.keys():
                return render_template_string(
                    BOOKING_HTML,
                    app_name=APP_NAME,
                    error="Per Experience scegli il Catering baby (Menù pizza o Box merenda).",
                    today=datetime.now().strftime("%Y-%m-%d"),
                    form=request.form,
                    package_labels=PACKAGE_LABELS,
                    catering_baby_options=CATERING_BABY_OPTIONS,
                    dessert_options=DESSERT_OPTIONS,
                    torta_interna_flavors=TORTA_INTERNA_FLAVORS,
                    extra_servizi=EXTRA_SERVIZI,
                    extra_servizi_ai=EXTRA_SERVIZI_ALL_INCLUSIVE,
                )

            if payload["torta_choice"] not in ("esterna", "interna"):
                return render_template_string(
                    BOOKING_HTML,
                    app_name=APP_NAME,
                    error="Per Experience scegli la torta: Esterna (+€1 a persona) oppure Interna (€24/kg).",
                    today=datetime.now().strftime("%Y-%m-%d"),
                    form=request.form,
                    package_labels=PACKAGE_LABELS,
                    catering_baby_options=CATERING_BABY_OPTIONS,
                    dessert_options=DESSERT_OPTIONS,
                    torta_interna_flavors=TORTA_INTERNA_FLAVORS,
                    extra_servizi=EXTRA_SERVIZI,
                    extra_servizi_ai=EXTRA_SERVIZI_ALL_INCLUSIVE,
                )

            if payload["torta_choice"] == "interna":
                if payload["torta_interna_choice"] not in TORTA_INTERNA_FLAVORS.keys():
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
                    )
                if payload["torta_interna_choice"] == "altro" and not payload["torta_gusto_altro"]:
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
                    )

        # Validazioni All-inclusive (catering NON obbligatorio; dessert se scelgono torta allora chiediamo la scelta torta)
        if payload["pacchetto"] == "Lullyland all-inclusive":
            need_torta = (payload["dessert_bimbi_choice"] == "torta_compleanno") or (payload["dessert_adulti_choice"] == "torta_compleanno")
            if need_torta:
                if payload["torta_choice"] not in ("esterna", "interna"):
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
                        extra_servizi_ai=EXTRA_SERVIZI_ALL_INCLUSIVE,
                    )
                if payload["torta_choice"] == "interna":
                    if payload["torta_interna_choice"] not in TORTA_INTERNA_FLAVORS.keys():
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
                        )
                    if payload["torta_interna_choice"] == "altro" and not payload["torta_gusto_altro"]:
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
                        )

        totals = compute_totals(payload)
        contract_text = build_contract_text(payload)

        conn = get_db()

        # ✅ CALENDARIO: assegna slot + area in base alla data_evento (2 feste max per slot)
        try:
            slot_key, area_num = lcal.auto_assign_slot_and_area(conn, payload["data_evento"], preferred_slot=None)
        except ValueError as e:
            conn.close()
            return render_template_string(
                BOOKING_HTML,
                app_name=APP_NAME,
                error=str(e),
                today=datetime.now().strftime("%Y-%m-%d"),
                form=request.form,
                package_labels=PACKAGE_LABELS,
                catering_baby_options=CATERING_BABY_OPTIONS,
                dessert_options=DESSERT_OPTIONS,
                torta_interna_flavors=TORTA_INTERNA_FLAVORS,
                extra_servizi=EXTRA_SERVIZI,
                extra_servizi_ai=EXTRA_SERVIZI_ALL_INCLUSIVE,
            )

        payload["slot_key"] = slot_key
        payload["area_num"] = area_num

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
                slot_key,
                area_num
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
                :slot_key,
                :area_num
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

        return redirect(url_for("prenotazioni"))

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
               slot_key, area_num
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
            torta_info = f"{tot_persone} persone → ~ {torta_kg} kg (100g a testa) a €{eur(TORTA_PRICE_EUR_PER_KG)}/kg"
        elif tc == "esterna":
            svc_tot = (TORTA_ESTERNASVC_EUR_PER_PERSON * Decimal(tot_persone)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            torta_info = f"{tot_persone} persone → Servizio torta: €{eur(TORTA_ESTERNASVC_EUR_PER_PERSON)} x {tot_persone} = €{eur(svc_tot)}"
    elif row["pacchetto"] == "Lullyland all-inclusive":
        need_torta = (row["dessert_bimbi_choice"] == "torta_compleanno") or (row["dessert_adulti_choice"] == "torta_compleanno")
        if need_torta:
            tc = (row["torta_choice"] or "").strip()
            if tc == "esterna":
                torta_info = "Torta esterna (inclusa) – con certificazione alimentare del fornitore"
            elif tc == "interna":
                ti = (row["torta_interna_choice"] or "").strip()
                if ti == "standard":
                    torta_info = f"Torta interna (inclusa) – {TORTA_INTERNA_FLAVORS['standard']}"
                elif ti == "altro":
                    torta_info = f"Torta interna (inclusa) – Gusto: {(row['torta_gusto_altro'] or '').strip() or '(da compilare)'}"
                else:
                    torta_info = "Torta interna (inclusa) – (da definire)"
            else:
                torta_info = "(da definire)"
        else:
            torta_info = "-"

    slot_key = (row["slot_key"] or "").strip()
    area_num = row["area_num"]

    slot_area_info = "-"
    if slot_key and area_num:
        slot_area_info = f"{slot_key} ({lcal.SLOT_LABELS.get(slot_key,'')}) – Area {area_num}"

    return render_template_string(
        DETAIL_HTML,
        app_name=APP_NAME,
        b=row,
        tot_persone=tot_persone,
        torta_info=torta_info,
        slot_area_info=slot_area_info,
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

HOME_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>{{app_name}} – App privata</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body { font-family: Arial, sans-serif; padding: 26px; background:#f6f7fb; }
    .card { max-width: 700px; margin: 30px auto; background:#fff; padding: 18px; border-radius: 12px; border:1px solid #e8e8e8; }
    a.btn { display:inline-block; padding:12px 14px; border-radius:10px; background:#0a84ff; color:#fff; text-decoration:none; font-weight:700; }
    a.btn2 { display:inline-block; padding:12px 14px; border-radius:10px; background:#111; color:#fff; text-decoration:none; font-weight:700; margin-left:10px;}
    a.btn3 { display:inline-block; padding:12px 14px; border-radius:10px; background:#00a86b; color:#fff; text-decoration:none; font-weight:700; margin-left:10px;}
    .muted { color:#666; }
  </style>
</head>
<body>
  <div class="card">
    <h1>{{app_name}} – App privata ✅</h1>
    <p class="muted">Se vedi questa pagina, il PIN funziona.</p>

    <p>
      <a class="btn" href="/prenota">+ Nuova prenotazione</a>
      <a class="btn2" href="/prenotazioni">Vedi prenotazioni</a>
      <a class="btn3" href="/calendario">Calendario</a>
    </p>

    <p><a href="/logout">Esci</a></p>
  </div>
</body>
</html>
"""

# ✅ Calendario mese
CALENDAR_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>{{app_name}} – Calendario</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body { font-family: Arial, sans-serif; padding: 18px; background:#f6f7fb; }
    .card { max-width: 1100px; margin: 18px auto; background:#fff; padding: 18px; border-radius: 12px; border:1px solid #e8e8e8; }
    .top { display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px; }
    .nav a { text-decoration:none; font-weight:800; padding:10px 12px; border-radius:10px; background:#111; color:#fff; }
    .nav a.primary { background:#0a84ff; }
    table { width:100%; border-collapse: collapse; table-layout: fixed; margin-top:14px; }
    th, td { border:1px solid #eee; vertical-align:top; padding:8px; }
    th { background:#f0f2f7; }
    .daynum { font-weight:900; }
    .today { outline: 3px solid #0a84ff; }
    .slot { margin-top:6px; font-size:12px; padding:6px; border-radius:10px; background:#f6f7fb; border:1px solid #e8e8e8; }
    .badge { display:inline-block; padding:4px 8px; border-radius:999px; background:#111; color:#fff; font-weight:900; font-size:11px; }
    .muted { color:#666; font-size:12px; }
    a.link { color:#0a84ff; font-weight:800; text-decoration:none; }
  </style>
</head>
<body>
  <div class="card">
    <div class="top">
      <div>
        <h2>Calendario – {{app_name}}</h2>
        <div class="muted">Mese: {{month}}/{{year}} • Ogni slot ha Area 1 e Area 2</div>
      </div>
      <div class="nav">
        <a href="/?">Home</a>
        <a class="primary" href="/prenota">+ Prenota</a>
        <a href="/prenotazioni">Lista</a>
        <a href="/calendario?year={{prev_year}}&month={{prev_month}}">←</a>
        <a href="/calendario?year={{next_year}}&month={{next_month}}">→</a>
      </div>
    </div>

    <table>
      <thead>
        <tr>
          <th>Lun</th><th>Mar</th><th>Mer</th><th>Gio</th><th>Ven</th><th>Sab</th><th>Dom</th>
        </tr>
      </thead>
      <tbody>
        {% for week in grid %}
          <tr>
            {% for d in week %}
              {% if d is none %}
                <td></td>
              {% else %}
                {% set ds = d.strftime("%Y-%m-%d") %}
                {% set is_today = (d == today) %}
                <td class="{% if is_today %}today{% endif %}">
                  <div class="daynum">{{d.day}}</div>
                  <div class="muted">{{ds}}</div>

                  {% set day = idx.get(ds, {}) %}

                  {% for slot_key, slot_label in slot_labels.items() %}
                    {% set slot_map = day.get(slot_key, {}) %}
                    
                      <div class="slot">
                        <div><span class="badge">{{slot_key}}</span> <span class="muted">{{slot_label}}</span></div>
                        <div style="margin-top:6px;">
                          {% for area_num in (1,2) %}
                            {% set ev = slot_map.get(area_num) %}
                            {% if ev %}
                              <div>
                                <span class="muted">A{{area_num}}:</span>
                                <a class="link" href="/prenotazioni/{{ev.id}}">{{ev.nome_festeggiato}}</a>
                                <span class="muted">({{ev.pacchetto}})</span>
                              </div>
                            {% else %}
                              <div class="muted">A{{area_num}}: libero</div>
                            {% endif %}
                          {% endfor %}
                        </div>
                      </div>
                    
                  {% endfor %}
                </td>
              {% endif %}
            {% endfor %}
          </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</body>
</html>
"""

# -------------------------
# Le tue 3 HTML principali
# -------------------------


# 🔥 Qui sotto rimetto i tuoi template originali COMPLETI.
# Nota: BOOKING_HTML resta IDENTICO al tuo (non serve modificarlo per far funzionare calendario).
# LIST_HTML e DETAIL_HTML includono slot_key/area_num e slot_area_info.

BOOKING_HTML = r"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>{{app_name}} – Prenotazione festa</title>
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

    /* Signature */
    .sig-wrap { margin-top: 12px; }
    canvas { width:100%; max-width: 760px; height: 220px; border: 2px dashed #bbb; border-radius: 12px; background:#fff; touch-action: none; }
    .sig-actions { display:flex; gap:10px; margin-top:10px; }
    .btn-secondary { background:#333; }
    .section { margin-top: 14px; padding-top: 10px; border-top: 1px solid #eee; }
  </style>
</head>
<body>
  <div class="card">
    <h2>Modulo prenotazione evento – {{app_name}}</h2>
    <p><a href="/">← Home</a> | <a href="/calendario">Calendario</a></p>

    {% if error %}<p class="err">{{error}}</p>{% endif %}

    <form method="post" id="bookingForm">

      <div class="row">
        <div class="col">
          <label>Nome festeggiato *</label>
          <input name="nome_festeggiato" required value="{{form.get('nome_festeggiato','')}}" />
        </div>
        <div class="col">
          <label>Età festeggiato</label>
          <input type="number" name="eta_festeggiato" min="0" value="{{form.get('eta_festeggiato','')}}" />
        </div>
      </div>

      <div class="row">
        <div class="col">
          <label>Data del compleanno</label>
          <input type="date" name="data_compleanno" value="{{form.get('data_compleanno','')}}" />
        </div>
        <div class="col">
          <label>Data dell’evento</label>
          <input type="date" name="data_evento" value="{{form.get('data_evento','')}}" />
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
            <option value="" {% if p=='' %}selected{% endif %}>Seleziona…</option>
            <option value="Fai da Te" {% if p=='Fai da Te' %}selected{% endif %}>{{package_labels['Fai da Te']}}</option>
            <option value="Lullyland Experience" {% if p=='Lullyland Experience' %}selected{% endif %}>{{package_labels['Lullyland Experience']}}</option>
            <option value="Lullyland all-inclusive" {% if p=='Lullyland all-inclusive' %}selected{% endif %}>{{package_labels['Lullyland all-inclusive']}}</option>
            <option value="Personalizzato" {% if p=='Personalizzato' %}selected{% endif %}>{{package_labels['Personalizzato']}}</option>
          </select>
          <div class="hint">I dettagli completi compaiono nel contratto dopo il salvataggio.</div>
        </div>
        <div class="col">
          <label>Tema evento</label>
          <input name="tema_evento" value="{{form.get('tema_evento','')}}" />
        </div>
      </div>

      <div class="row" id="personalizzatoBox" style="display:none;">
        <div class="col" style="flex-basis:100%;">
          <label>Dettagli personalizzazione (solo se “Personalizzato”) *</label>
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
              <option value="">Seleziona…</option>
              <option value="menu_pizza" {% if cb=='menu_pizza' %}selected{% endif %}>Menù pizza</option>
              <option value="box_merenda" {% if cb=='box_merenda' %}selected{% endif %}>Box merenda</option>
            </select>
          </div>

          <div class="col">
            <label>Torta (scelta) *</label>
            {% set tc = form.get('torta_choice','') %}
            <select name="torta_choice" id="torta_choice">
              <option value="">Seleziona…</option>
              <option value="esterna" {% if tc=='esterna' %}selected{% endif %}>Torta esterna (+€1,00 a persona)</option>
              <option value="interna" {% if tc=='interna' %}selected{% endif %}>Torta interna (da noi) (€24,00 al chilo)</option>
            </select>
            <div class="hint">Se interna: calcolo consigliato 100g a testa (bambini+adulti).</div>
          </div>
        </div>

        <div class="row" id="tortaInternaBox" style="display:none;">
          <div class="col">
            <label>Gusto torta interna *</label>
            {% set ti = form.get('torta_interna_choice','') %}
            <select name="torta_interna_choice" id="torta_interna_choice">
              <option value="">Seleziona…</option>
              <option value="standard" {% if ti=='standard' %}selected{% endif %}>{{torta_interna_flavors['standard']}}</option>
              <option value="altro" {% if ti=='altro' %}selected{% endif %}>Altro (scrivi gusto)</option>
            </select>
          </div>
          <div class="col" id="tortaAltroBox" style="display:none;">
            <label>Gusto concordato (se “Altro”) *</label>
            <input name="torta_gusto_altro" id="torta_gusto_altro" value="{{form.get('torta_gusto_altro','')}}" />
          </div>
        </div>

        <div class="section">
          <h3>Servizi extra (seleziona uno o più)</h3>
          <div class="row">
            {% for k, v in extra_servizi.items() %}
              <div class="col" style="min-width:260px;">
                <label style="font-weight:700;">
                  <input type="checkbox" name="extra_{{k}}" {% if form.get('extra_' ~ k) %}checked{% endif %}>
                  {{v[0]}} – €{{"{:0.2f}".format(v[1]).replace(".", ",")}}
                </label>
              </div>
            {% endfor %}
          </div>
          <div class="hint">Gli extra scelti entrano nel totale stimato nel contratto.</div>
        </div>
      </div>

      <div class="section" id="allInclusiveBox" style="display:none;">
        <h3>Opzioni pacchetto All-inclusive</h3>

        <div class="row">
          <div class="col">
            <label>Catering baby (facoltativo)</label>
            {% set cb2 = form.get('catering_baby_choice','') %}
            <select name="catering_baby_choice" id="catering_baby_choice_ai">
              <option value="">Seleziona…</option>
              <option value="menu_pizza" {% if cb2=='menu_pizza' %}selected{% endif %}>Menù pizza</option>
              <option value="box_merenda" {% if cb2=='box_merenda' %}selected{% endif %}>Box merenda</option>
            </select>
            <div class="hint">Se non lo selezioni, resta “da definire”.</div>
          </div>
        </div>

        <div class="row">
          <div class="col">
            <label>Dessert per bambini (facoltativo)</label>
            {% set db = form.get('dessert_bimbi_choice','') %}
            <select name="dessert_bimbi_choice" id="dessert_bimbi_choice">
              <option value="">Seleziona…</option>
              <option value="muffin_nutella" {% if db=='muffin_nutella' %}selected{% endif %}>{{dessert_options['muffin_nutella']}}</option>
              <option value="torta_compleanno" {% if db=='torta_compleanno' %}selected{% endif %}>{{dessert_options['torta_compleanno']}}</option>
            </select>
          </div>

          <div class="col">
            <label>Dessert per adulti (facoltativo)</label>
            {% set da = form.get('dessert_adulti_choice','') %}
            <select name="dessert_adulti_choice" id="dessert_adulti_choice">
              <option value="">Seleziona…</option>
              <option value="muffin_nutella" {% if da=='muffin_nutella' %}selected{% endif %}>{{dessert_options['muffin_nutella']}}</option>
              <option value="torta_compleanno" {% if da=='torta_compleanno' %}selected{% endif %}>{{dessert_options['torta_compleanno']}}</option>
            </select>
          </div>
        </div>

        <div class="row" id="aiTortaBox" style="display:none;">
          <div class="col">
            <label>Torta (scelta) (se hai scelto torta come dessert)</label>
            {% set tc2 = form.get('torta_choice','') %}
            <select name="torta_choice" id="torta_choice_ai">
              <option value="">Seleziona…</option>
              <option value="esterna" {% if tc2=='esterna' %}selected{% endif %}>Torta esterna</option>
              <option value="interna" {% if tc2=='interna' %}selected{% endif %}>Torta interna (da noi)</option>
            </select>
          </div>
        </div>

        <div class="row" id="aiTortaInternaBox" style="display:none;">
          <div class="col">
            <label>Gusto torta interna (se interna)</label>
            {% set ti2 = form.get('torta_interna_choice','') %}
            <select name="torta_interna_choice" id="torta_interna_choice_ai">
              <option value="">Seleziona…</option>
              <option value="standard" {% if ti2=='standard' %}selected{% endif %}>{{torta_interna_flavors['standard']}}</option>
              <option value="altro" {% if ti2=='altro' %}selected{% endif %}>Altro (scrivi gusto)</option>
            </select>
          </div>
          <div class="col" id="aiTortaAltroBox" style="display:none;">
            <label>Gusto concordato (se “Altro”)</label>
            <input name="torta_gusto_altro" id="torta_gusto_altro_ai" value="{{form.get('torta_gusto_altro','')}}" />
          </div>
        </div>

        <div class="section">
          <h3>Servizi extra (seleziona uno o più)</h3>
          <div class="row">
            {% for k, v in extra_servizi_ai.items() %}
              <div class="col" style="min-width:260px;">
                <label style="font-weight:700;">
                  <input type="checkbox" name="extra_{{k}}" {% if form.get('extra_' ~ k) %}checked{% endif %}>
                  {{v[0]}} – €{{"{:0.2f}".format(v[1]).replace(".", ",")}}
                </label>
              </div>
            {% endfor %}
          </div>
          <div class="hint">Gli extra scelti entrano nel totale stimato nel contratto.</div>
        </div>
      </div>

      <div style="margin-top:16px;">
        <label style="font-weight:700;">
          <input type="checkbox" name="consenso_privacy" required
                 {% if form.get('consenso_privacy') %}checked{% endif %}>
          Dichiaro di aver letto e accettato l’informativa privacy di {{app_name}} *
        </label>
        <div class="hint">Obbligatorio.</div>

        <label style="margin-top:10px; font-weight:700;">
          <input type="checkbox" name="consenso_foto"
                 {% if form.get('consenso_foto') %}checked{% endif %}>
          Autorizzo {{app_name}} a scattare foto/video durante l’evento e a utilizzarli sui canali social
        </label>
        <div class="hint">Facoltativo.</div>
      </div>

      <!-- ✅ SPOSTAMENTO: ACCONTO PIÙ GIÙ (prima di firma) -->
      <div class="row" style="margin-top:14px;">
        <div class="col">
          <label>Acconto (€)</label>
          <input type="text" name="acconto_eur" placeholder="Es: 50,00" value="{{form.get('acconto_eur','')}}" />
          <div class="hint">Campo libero.</div>
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
        <button type="submit">Salva prenotazione</button>
        <a class="link" href="/prenotazioni">Vedi prenotazioni</a>
      </div>
    </form>
  </div>

<script>
(function() {
  const pacchetto = document.getElementById('pacchetto');
  const experienceBox = document.getElementById('experienceBox');
  const allInclusiveBox = document.getElementById('allInclusiveBox');
  const personalizzatoBox = document.getElementById('personalizzatoBox');

  // Experience
  const tortaChoice = document.getElementById('torta_choice');
  const tortaInternaBox = document.getElementById('tortaInternaBox');
  const tortaInternaChoice = document.getElementById('torta_interna_choice');
  const tortaAltroBox = document.getElementById('tortaAltroBox');

  // All-inclusive
  const dessertBimbi = document.getElementById('dessert_bimbi_choice');
  const dessertAdulti = document.getElementById('dessert_adulti_choice');
  const aiTortaBox = document.getElementById('aiTortaBox');
  const tortaChoiceAI = document.getElementById('torta_choice_ai');
  const aiTortaInternaBox = document.getElementById('aiTortaInternaBox');
  const tortaInternaChoiceAI = document.getElementById('torta_interna_choice_ai');
  const aiTortaAltroBox = document.getElementById('aiTortaAltroBox');

  function refreshVisibility() {
    const p = pacchetto.value;

    experienceBox.style.display = (p === 'Lullyland Experience') ? 'block' : 'none';
    allInclusiveBox.style.display = (p === 'Lullyland all-inclusive') ? 'block' : 'none';
    personalizzatoBox.style.display = (p === 'Personalizzato') ? 'flex' : 'none';

    // Experience: mostra gusto interno solo se scelta interna
    const tc = tortaChoice ? tortaChoice.value : '';
    tortaInternaBox.style.display = (p === 'Lullyland Experience' && tc === 'interna') ? 'flex' : 'none';
    const ti = tortaInternaChoice ? tortaInternaChoice.value : '';
    tortaAltroBox.style.display = (p === 'Lullyland Experience' && tc === 'interna' && ti === 'altro') ? 'block' : 'none';

    // All-inclusive: mostra box torta solo se almeno uno dei dessert = torta
    const db = dessertBimbi ? dessertBimbi.value : '';
    const da = dessertAdulti ? dessertAdulti.value : '';
    const needTorta = (db === 'torta_compleanno' || da === 'torta_compleanno');

    if (aiTortaBox) aiTortaBox.style.display = (p === 'Lullyland all-inclusive' && needTorta) ? 'flex' : 'none';

    const tc2 = tortaChoiceAI ? tortaChoiceAI.value : '';
    if (aiTortaInternaBox) aiTortaInternaBox.style.display = (p === 'Lullyland all-inclusive' && needTorta && tc2 === 'interna') ? 'flex' : 'none';

    const ti2 = tortaInternaChoiceAI ? tortaInternaChoiceAI.value : '';
    if (aiTortaAltroBox) aiTortaAltroBox.style.display = (p === 'Lullyland all-inclusive' && needTorta && tc2 === 'interna' && ti2 === 'altro') ? 'block' : 'none';
  }

  if (pacchetto) pacchetto.addEventListener('change', refreshVisibility);

  if (tortaChoice) tortaChoice.addEventListener('change', refreshVisibility);
  if (tortaInternaChoice) tortaInternaChoice.addEventListener('change', refreshVisibility);

  if (dessertBimbi) dessertBimbi.addEventListener('change', refreshVisibility);
  if (dessertAdulti) dessertAdulti.addEventListener('change', refreshVisibility);
  if (tortaChoiceAI) tortaChoiceAI.addEventListener('change', refreshVisibility);
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

  window.clearSig = function() {
    hasInk = false;
    resizeCanvas();
  }

  resizeCanvas();
  window.addEventListener('resize', resizeCanvas);

  canvas.addEventListener('mousedown', start);
  canvas.addEventListener('mousemove', move);
  window.addEventListener('mouseup', end);

  canvas.addEventListener('touchstart', start, { passive:false });
  canvas.addEventListener('touchmove', move, { passive:false });
  window.addEventListener('touchend', end, { passive:false });

  document.getElementById('bookingForm').addEventListener('submit', function(e) {
    if (!hasInk) {
      e.preventDefault();
      alert("Firma mancante: firma nel riquadro prima di salvare.");
      return;
    }
    const dataUrl = canvas.toDataURL('image/png');
    document.getElementById('firma_png_base64').value = dataUrl;
  });
})();
</script>
</body>
</html>
"""

LIST_HTML = r"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>{{app_name}} – Prenotazioni</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body { font-family: Arial, sans-serif; padding: 18px; background:#f6f7fb; }
    .card { max-width: 980px; margin: 18px auto; background:#fff; padding: 18px; border-radius: 12px; border:1px solid #e8e8e8; }
    table { width:100%; border-collapse: collapse; }
    th, td { padding: 10px; border-bottom:1px solid #eee; text-align:left; }
    a.btn { display:inline-block; padding:10px 12px; border-radius:10px; background:#0a84ff; color:#fff; text-decoration:none; font-weight:800; }
    a.btn3 { display:inline-block; padding:10px 12px; border-radius:10px; background:#00a86b; color:#fff; text-decoration:none; font-weight:800; margin-left:10px; }
    a.link { color:#0a84ff; font-weight:700; text-decoration:none; }
    .muted { color:#666; }
    .pill { display:inline-block; padding:6px 10px; border-radius:999px; background:#f0f2f7; font-weight:800; }
  </style>
</head>
<body>
  <div class="card">
    <h2>Prenotazioni – {{app_name}}</h2>
    <p>
      <a class="btn" href="/prenota">+ Nuova prenotazione</a>
      <a class="btn3" href="/calendario">Calendario</a>
      <span style="margin-left:10px;"><a href="/">Home</a></span>
    </p>

    {% if rows|length == 0 %}
      <p class="muted">Nessuna prenotazione salvata ancora.</p>
    {% else %}
      <table>
        <thead>
          <tr>
            <th>ID</th>
            <th>Creato</th>
            <th>Festeggiato</th>
            <th>Data evento</th>
            <th>Slot/Area</th>
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
              <td>{{r['created_at']}}</td>
              <td>{{r['nome_festeggiato']}}</td>
              <td>{{r['data_evento']}}</td>
              <td>
                {% if r['slot_key'] and r['area_num'] %}
                  <span class="pill">{{r['slot_key']}} • A{{r['area_num']}}</span>
                {% else %}
                  -
                {% endif %}
              </td>
              <td>{{r['pacchetto']}}</td>
              <td>{{(r['invitati_bambini'] or 0)}} bimbi / {{(r['invitati_adulti'] or 0)}} adulti</td>
              <td>
                {% if r['totale_stimato_eur'] %}
                  <span class="pill">€{{"{:0.2f}".format(r['totale_stimato_eur']|float).replace(".", ",")}}</span>
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

DETAIL_HTML = r"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>{{app_name}} – Dettaglio prenotazione</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body { font-family: Arial, sans-serif; padding: 18px; background:#f6f7fb; }
    .card { max-width: 980px; margin: 18px auto; background:#fff; padding: 18px; border-radius: 12px; border:1px solid #e8e8e8; }
    .grid { display:flex; gap:12px; flex-wrap:wrap; }
    .box { flex:1; min-width: 280px; border:1px solid #eee; border-radius:12px; padding:12px; }
    .k { color:#666; font-size: 12px; margin-bottom:4px; }
    .v { font-weight: 800; margin-bottom:10px; }
    img { max-width: 760px; width:100%; border:1px solid #ddd; border-radius:12px; background:#fff; }
    .pill { display:inline-block; padding:6px 10px; border-radius:999px; background:#f0f2f7; font-weight:800; }

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
  </style>
</head>
<body>
  <div class="card">
    <p><a href="/prenotazioni">← Prenotazioni</a> | <a href="/">Home</a> | <a href="/calendario">Calendario</a></p>
    <h2>Dettaglio prenotazione #{{b['id']}} – {{app_name}}</h2>

    <div class="grid">
      <div class="box">
        <div class="k">Festeggiato</div>
        <div class="v">{{b['nome_festeggiato']}} ({{b['eta_festeggiato'] or '-'}})</div>

        <div class="k">Data compleanno</div>
        <div class="v">{{b['data_compleanno'] or '-'}}</div>

        <div class="k">Data evento</div>
        <div class="v">{{b['data_evento'] or '-'}}</div>

        <div class="k">Slot / Area (calendario)</div>
        <div class="v">{{slot_area_info}}</div>

        <div class="k">Pacchetto</div>
        <div class="v">{{b['pacchetto']}}</div>

        <div class="k">Tema</div>
        <div class="v">{{b['tema_evento'] or '-'}}</div>

        <div class="k">Acconto</div>
        <div class="v">{{b['acconto_eur'] or '-'}}</div>

        <div class="k">Totale stimato</div>
        <div class="v">
          {% if b['totale_stimato_eur'] %}
            <span class="pill">€{{"{:0.2f}".format(b['totale_stimato_eur']|float).replace(".", ",")}}</span>
          {% else %}
            -
          {% endif %}
        </div>
      </div>

      <div class="box">
        <div class="k">Madre</div>
        <div class="v">{{b['madre_nome_cognome'] or '-'}} – {{b['madre_telefono'] or '-'}}</div>

        <div class="k">Padre</div>
        <div class="v">{{b['padre_nome_cognome'] or '-'}} – {{b['padre_telefono'] or '-'}}</div>

        <div class="k">Email</div>
        <div class="v">{{b['email'] or '-'}}</div>

        <div class="k">Residenza</div>
        <div class="v">{{b['indirizzo_residenza'] or '-'}}</div>

        <div class="k">Invitati</div>
        <div class="v">{{b['invitati_bambini'] or 0}} bimbi – {{b['invitati_adulti'] or 0}} adulti</div>

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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
