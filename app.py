import os
import sqlite3
from datetime import datetime
from flask import Flask, request, redirect, url_for, session, render_template_string, abort

app = Flask(__name__)

APP_NAME = "Lullyland"

# IMPORTANTISSIMO: su Render lo mettiamo come Environment Variable
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-key-change-me")
APP_PIN = os.getenv("APP_PIN", "1234")  # su Render lo cambi tu

DB_PATH = os.getenv("DB_PATH", "lullyland.db")

# -------------------------
# Cataloghi prezzi / regole
# -------------------------
PKG_LABELS = {
    "Fai da Te": "Fai da Te €15,00 a persona",
    "Lullyland Experience": "Lullyland Experience €20,00 a persona",
    "Lullyland all-inclusive": "Lullyland all-inclusive",
    "Personalizzato": "Personalizzato",
}

PKG_PRICE_PER_PERSON = {
    "Fai da Te": 15.00,
    "Lullyland Experience": 20.00,
    "Lullyland all-inclusive": 0.00,  # placeholder (lo definiremo quando mi dai i dettagli)
    "Personalizzato": 0.00,           # si gestisce manualmente
}

# Experience - catering baby
EXPERIENCE_BABY_MENU = {
    "menu_pizza": ("Menù pizza", "Pizza Baby, patatine, bottiglietta dell’acqua"),
    "box_merenda": ("Box merenda", "Sandwich con prosciutto cotto, rustico würstel, mini pizzetta, panzerottino, patatine fritte e bottiglietta dell’acqua"),
}

# Torta
CAKE_PRICE_PER_KG = 24.00
CAKE_GRAMS_PER_PERSON = 100  # 100g a testa
CAKE_EXTERNAL_FEE_PER_PERSON = 1.00

# Extra (selezionabili)
EXTRA_SERVIZI = {
    "zucchero_filato": ("Carretto zucchero filato illimitati", 50.00),
    "pop_corn": ("Carretto pop corn illimitati", 50.00),
    "torta_scenografica": ("Noleggio torta scenografica", 45.00),
    "intrattenitore": ("Intrattenitore", 100.00),
    "bolle_sapone": ("Spettacolo bolle di sapone", 200.00),
    "mascotte_standard": ("Servizio mascotte standard", 65.00),
    "mascotte_deluxe": ("Servizio mascotte deluxe", 90.00),
}


# -------------------------
# DB helpers
# -------------------------
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_column(conn, table, col_name, col_type):
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
            pacchetto_personalizzato_dettagli TEXT,

            tema_evento TEXT,
            note TEXT,

            acconto REAL,

            # Experience: catering baby
            exp_catering_baby_choice TEXT,

            # Torta
            torta_scelta TEXT,               -- "esterna" / "interna"
            torta_interna_gusto_choice TEXT, -- "default" / "altro"
            torta_interna_gusto_text TEXT,

            # Extra
            extra_json TEXT,

            data_firma TEXT,
            firma_png_base64 TEXT,

            consenso_privacy INTEGER,
            consenso_foto INTEGER
        )
        """
    )

    # Migrazioni soft (se DB già esisteva)
    ensure_column(conn, "bookings", "pacchetto_personalizzato_dettagli", "TEXT")
    ensure_column(conn, "bookings", "acconto", "REAL")
    ensure_column(conn, "bookings", "exp_catering_baby_choice", "TEXT")
    ensure_column(conn, "bookings", "torta_scelta", "TEXT")
    ensure_column(conn, "bookings", "torta_interna_gusto_choice", "TEXT")
    ensure_column(conn, "bookings", "torta_interna_gusto_text", "TEXT")
    ensure_column(conn, "bookings", "extra_json", "TEXT")

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
# Helpers calcoli
# -------------------------
def to_int(val):
    try:
        return int(val) if val not in (None, "",) else 0
    except:
        return 0


def to_float(val):
    try:
        if val in (None, "",):
            return 0.0
        return float(str(val).replace(",", "."))
    except:
        return 0.0


def eur(x):
    return f"€{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def calc_totals(b):
    n_bimbi = int(b.get("invitati_bambini") or 0)
    n_adulti = int(b.get("invitati_adulti") or 0)
    tot_persone = n_bimbi + n_adulti

    pacchetto = (b.get("pacchetto") or "").strip()
    per_person = PKG_PRICE_PER_PERSON.get(pacchetto, 0.0)
    base = per_person * tot_persone

    # torta
    torta_scelta = (b.get("torta_scelta") or "").strip()  # "esterna" / "interna"
    cake_cost = 0.0
    cake_label = ""
    cake_details = ""
    cake_is_internal = False

    if pacchetto == "Lullyland Experience":
        if torta_scelta == "esterna":
            cake_cost = CAKE_EXTERNAL_FEE_PER_PERSON * tot_persone
            cake_label = "Torta esterna"
            cake_details = f"Servizio torta: €1,00 x {tot_persone} persone"
            cake_is_internal = False
        elif torta_scelta == "interna":
            cake_is_internal = True
            kg = (tot_persone * CAKE_GRAMS_PER_PERSON) / 1000.0
            cake_cost = kg * CAKE_PRICE_PER_KG
            cake_label = "Torta interna (da noi)"
            cake_details = f"{tot_persone} persone → ~ {kg:.2f} kg (100g a testa) a €{str(CAKE_PRICE_PER_KG).replace('.', ',')}/kg"

    # extra
    extras_selected = b.get("extras_selected") or []
    extra_total = 0.0
    extra_lines = []
    for key in extras_selected:
        if key in EXTRA_SERVIZI:
            name, price = EXTRA_SERVIZI[key]
            extra_total += float(price)
            extra_lines.append(f"- {name} {eur(price)}")

    total = base + cake_cost + extra_total
    return {
        "tot_persone": tot_persone,
        "base": base,
        "cake_cost": cake_cost,
        "cake_label": cake_label,
        "cake_details": cake_details,
        "cake_is_internal": cake_is_internal,
        "extra_total": extra_total,
        "extra_lines": extra_lines,
        "total": total,
        "per_person": per_person,
    }


def parse_extras_from_form(form):
    keys = []
    for k in EXTRA_SERVIZI.keys():
        if form.get(f"extra_{k}"):
            keys.append(k)
    return keys


def extras_to_text(keys):
    # testo semplice salvato in DB (evitiamo JSON import, keep minimal)
    # formato: "key1|key2|key3"
    return "|".join(keys)


def extras_from_text(s):
    if not s:
        return []
    return [x for x in s.split("|") if x.strip()]


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
        # Consensi
        consenso_privacy = 1 if request.form.get("consenso_privacy") else 0
        consenso_foto = 1 if request.form.get("consenso_foto") else 0

        if consenso_privacy != 1:
            return render_template_string(
                BOOKING_HTML,
                app_name=APP_NAME,
                error="Devi accettare l’informativa privacy per continuare.",
                today=datetime.now().strftime("%Y-%m-%d"),
                form=request.form,
                pkg_labels=PKG_LABELS,
                baby_menu=EXPERIENCE_BABY_MENU,
                extras=EXTRA_SERVIZI,
            )

        # Firma (obbligatoria)
        firma_png_base64 = (request.form.get("firma_png_base64") or "").strip()
        data_firma = (request.form.get("data_firma") or "").strip()

        if not data_firma:
            return render_template_string(
                BOOKING_HTML,
                app_name=APP_NAME,
                error="Inserisci la data firma.",
                today=datetime.now().strftime("%Y-%m-%d"),
                form=request.form,
                pkg_labels=PKG_LABELS,
                baby_menu=EXPERIENCE_BABY_MENU,
                extras=EXTRA_SERVIZI,
            )

        if not firma_png_base64.startswith("data:image/png;base64,"):
            return render_template_string(
                BOOKING_HTML,
                app_name=APP_NAME,
                error="Firma mancante: firma nel riquadro prima di salvare.",
                today=datetime.now().strftime("%Y-%m-%d"),
                form=request.form,
                pkg_labels=PKG_LABELS,
                baby_menu=EXPERIENCE_BABY_MENU,
                extras=EXTRA_SERVIZI,
            )

        pacchetto = (request.form.get("pacchetto") or "").strip()

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
            "pacchetto_personalizzato_dettagli": (request.form.get("pacchetto_personalizzato_dettagli") or "").strip(),

            "tema_evento": (request.form.get("tema_evento") or "").strip(),
            "note": (request.form.get("note") or "").strip(),

            "acconto": to_float(request.form.get("acconto")),

            "exp_catering_baby_choice": (request.form.get("exp_catering_baby_choice") or "").strip(),

            "torta_scelta": (request.form.get("torta_scelta") or "").strip(),
            "torta_interna_gusto_choice": (request.form.get("torta_interna_gusto_choice") or "").strip(),
            "torta_interna_gusto_text": (request.form.get("torta_interna_gusto_text") or "").strip(),

            "extra_json": extras_to_text(parse_extras_from_form(request.form)),

            "data_firma": data_firma,
            "firma_png_base64": firma_png_base64,

            "consenso_privacy": consenso_privacy,
            "consenso_foto": consenso_foto,
        }

        # Validazioni minime
        if not payload["nome_festeggiato"]:
            return render_template_string(
                BOOKING_HTML,
                app_name=APP_NAME,
                error="Inserisci il nome del festeggiato.",
                today=datetime.now().strftime("%Y-%m-%d"),
                form=request.form,
                pkg_labels=PKG_LABELS,
                baby_menu=EXPERIENCE_BABY_MENU,
                extras=EXTRA_SERVIZI,
            )

        if pacchetto not in ("Fai da Te", "Lullyland Experience", "Lullyland all-inclusive", "Personalizzato"):
            return render_template_string(
                BOOKING_HTML,
                app_name=APP_NAME,
                error="Seleziona un pacchetto valido.",
                today=datetime.now().strftime("%Y-%m-%d"),
                form=request.form,
                pkg_labels=PKG_LABELS,
                baby_menu=EXPERIENCE_BABY_MENU,
                extras=EXTRA_SERVIZI,
            )

        # Experience: controlli minimi
        if pacchetto == "Lullyland Experience":
            if payload["exp_catering_baby_choice"] not in ("menu_pizza", "box_merenda"):
                return render_template_string(
                    BOOKING_HTML,
                    app_name=APP_NAME,
                    error="Seleziona il catering baby (Menù pizza o Box merenda).",
                    today=datetime.now().strftime("%Y-%m-%d"),
                    form=request.form,
                    pkg_labels=PKG_LABELS,
                    baby_menu=EXPERIENCE_BABY_MENU,
                    extras=EXTRA_SERVIZI,
                )
            if payload["torta_scelta"] not in ("esterna", "interna"):
                return render_template_string(
                    BOOKING_HTML,
                    app_name=APP_NAME,
                    error="Seleziona la scelta torta (esterna o interna).",
                    today=datetime.now().strftime("%Y-%m-%d"),
                    form=request.form,
                    pkg_labels=PKG_LABELS,
                    baby_menu=EXPERIENCE_BABY_MENU,
                    extras=EXTRA_SERVIZI,
                )

            if payload["torta_scelta"] == "interna":
                if payload["torta_interna_gusto_choice"] not in ("default", "altro"):
                    return render_template_string(
                        BOOKING_HTML,
                        app_name=APP_NAME,
                        error="Seleziona il gusto torta interna (opzione 1 o altro).",
                        today=datetime.now().strftime("%Y-%m-%d"),
                        form=request.form,
                        pkg_labels=PKG_LABELS,
                        baby_menu=EXPERIENCE_BABY_MENU,
                        extras=EXTRA_SERVIZI,
                    )
                if payload["torta_interna_gusto_choice"] == "altro" and not payload["torta_interna_gusto_text"]:
                    return render_template_string(
                        BOOKING_HTML,
                        app_name=APP_NAME,
                        error="Hai scelto 'Altro': scrivi il gusto concordato.",
                        today=datetime.now().strftime("%Y-%m-%d"),
                        form=request.form,
                        pkg_labels=PKG_LABELS,
                        baby_menu=EXPERIENCE_BABY_MENU,
                        extras=EXTRA_SERVIZI,
                    )

        conn = get_db()
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
                pacchetto, pacchetto_personalizzato_dettagli,
                tema_evento, note,
                acconto,
                exp_catering_baby_choice,
                torta_scelta, torta_interna_gusto_choice, torta_interna_gusto_text,
                extra_json,
                data_firma, firma_png_base64,
                consenso_privacy, consenso_foto
            ) VALUES (
                :created_at,
                :nome_festeggiato, :eta_festeggiato, :data_compleanno, :data_evento,
                :madre_nome_cognome, :madre_telefono,
                :padre_nome_cognome, :padre_telefono,
                :indirizzo_residenza, :email,
                :invitati_bambini, :invitati_adulti,
                :pacchetto, :pacchetto_personalizzato_dettagli,
                :tema_evento, :note,
                :acconto,
                :exp_catering_baby_choice,
                :torta_scelta, :torta_interna_gusto_choice, :torta_interna_gusto_text,
                :extra_json,
                :data_firma, :firma_png_base64,
                :consenso_privacy, :consenso_foto
            )
            """,
            payload,
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
        pkg_labels=PKG_LABELS,
        baby_menu=EXPERIENCE_BABY_MENU,
        extras=EXTRA_SERVIZI,
    )


@app.route("/prenotazioni")
def prenotazioni():
    if not is_logged_in():
        return redirect(url_for("login"))

    conn = get_db()
    rows = conn.execute(
        "SELECT id, created_at, nome_festeggiato, data_evento, pacchetto FROM bookings ORDER BY id DESC"
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

    b = dict(row)
    extras_selected = extras_from_text(b.get("extra_json") or "")
    totals = calc_totals({
        "pacchetto": b.get("pacchetto"),
        "invitati_bambini": b.get("invitati_bambini") or 0,
        "invitati_adulti": b.get("invitati_adulti") or 0,
        "torta_scelta": b.get("torta_scelta") or "",
        "extras_selected": extras_selected,
    })

    contract_html = build_contract_text(b, extras_selected)

    return render_template_string(
        DETAIL_HTML,
        app_name=APP_NAME,
        b=b,
        extras_selected=extras_selected,
        extras_catalog=EXTRA_SERVIZI,
        totals=totals,
        eur=eur,
        pkg_labels=PKG_LABELS,
        contract_html=contract_html,
    )


def build_contract_text(b, extras_selected):
    pacchetto = (b.get("pacchetto") or "").strip()

    # Label pacchetto con prezzo
    pkg_title = PKG_LABELS.get(pacchetto, pacchetto)

    # Include / Non include / Regole per pacchetti
    lines = []
    lines.append(f"PACCHETTO: {pkg_title}")
    lines.append("")
    if pacchetto == "Fai da Te":
        lines.append("INCLUDE:")
        lines += [
            "- Accesso al parco giochi di 350mq",
            "- Pulizia e igienizzazione impeccabili prima e dopo la festa",
            "- Area riservata con tavoli e sedie",
            "- Tavolo torta con gonna e tovaglia monocolore, lavagnetta con nome e anni del festeggiato e sfondo a tema",
        ]
        lines.append("")
        lines.append("NON INCLUDE:")
        lines += [
            "- Piatti, bicchieri, tovaglioli, tovaglie",
            "- Servizio",
            "- Sgombero tavoli",
        ]
        lines.append("")
        lines.append("NOTE IMPORTANTI (REGOLE):")
        lines += [
            "- È obbligatorio fornire certificazione alimentare sia per il buffet che per la torta (fornita dal fornitore da loro scelto)",
            "- È obbligatorio acquistare le bibite al nostro bar, non è possibile introdurre bevande dall’esterno",
            "- È obbligatorio l’utilizzo di calzini antiscivolo per tutti i bambini che usufruiranno del parco",
            "- È severamente vietato entrare all’interno del parco con le scarpe con tacchi (pavimentazione antitrauma in gomma) pena addebito €60,00 per ogni mattonella antitrauma forata",
            "- È obbligatorio l’utilizzo di copri scarpe all’interno del parco (da noi forniti)",
            "- È severamente vietato introdurre cibo e bevande all’interno del parco",
        ]

    elif pacchetto == "Lullyland Experience":
        lines.append("INCLUDE:")
        lines += [
            "- Accesso al parco giochi di 350mq",
            "- Pulizia e igienizzazione impeccabili prima e dopo la festa",
            "- Area riservata con tavoli e sedie",
            "- Tavolo torta con gonna e tovaglia monocolore, lavagnetta con nome e anni del festeggiato e sfondo a tema",
            "- Piatti, bicchieri, tovaglioli",
        ]

        # Catering baby (scelta)
        choice = (b.get("exp_catering_baby_choice") or "").strip()
        if choice in EXPERIENCE_BABY_MENU:
            label, detail = EXPERIENCE_BABY_MENU[choice]
            lines.append(f"- Catering baby: {label}: {detail}")
        else:
            lines.append("- Catering baby: (non specificato)")

        lines.append("- Catering adulti: fritti centrali (panzerottini, patatine, bandidos, crocchette), pizze centrali margherita e bibite centrali da 1,5lt (acqua, Coca-Cola, Fanta)")
        lines.append("")
        lines.append("NON INCLUDE:")
        lines.append("- Torta di compleanno")
        lines.append("")

        torta_scelta = (b.get("torta_scelta") or "").strip()

        # ✅ MODIFICA 1: se torta esterna -> titolo solo "TORTA (ESTERNA)" (senza €/kg)
        if torta_scelta == "esterna":
            lines.append("TORTA (ESTERNA):")
            lines.append("- Torta esterna: +€1,00 a persona (servizio torta)")
        else:
            lines.append(f"TORTA (SCELTA) (€{str(CAKE_PRICE_PER_KG).replace('.', ',')} al chilo):")
            gusto_choice = (b.get("torta_interna_gusto_choice") or "").strip()
            if gusto_choice == "default":
                lines.append("- Torta interna (da noi): Pan di spagna analcolico con crema chantilly e gocce di cioccolato")
            elif gusto_choice == "altro":
                gusto_txt = (b.get("torta_interna_gusto_text") or "").strip() or "(non specificato)"
                lines.append(f"- Torta interna (da noi) – Gusto concordato: {gusto_txt}")
            else:
                lines.append("- Torta interna (da noi) – Gusto concordato: (non specificato)")

        # Extra
        if extras_selected:
            lines.append("")
            lines.append("SERVIZI EXTRA (selezionati):")
            tot = 0.0
            for k in extras_selected:
                if k in EXTRA_SERVIZI:
                    name, price = EXTRA_SERVIZI[k]
                    tot += float(price)
                    lines.append(f"- {name} {eur(float(price))}")
            lines.append(f"Totale extra: {eur(tot)}")

        lines.append("")
        lines.append("NOTE IMPORTANTI (REGOLE):")
        # regola certificazione SOLO se torta esterna
        if torta_scelta == "esterna":
            lines.append("- (Torta esterna) È obbligatorio fornire certificazione alimentare per la torta (fornita dal fornitore da loro scelto)")
        lines += [
            "- È obbligatorio l’utilizzo di calzini antiscivolo per tutti i bambini che usufruiranno del parco",
            "- È severamente vietato entrare all’interno del parco con scarpe con tacchi (pavimentazione antitrauma in gomma): pena addebito €60,00 per ogni mattonella antitrauma forata",
            "- È obbligatorio l’utilizzo di copri scarpe all’interno del parco (da noi forniti)",
            "- È severamente vietato introdurre cibo e bevande all’interno del parco",
        ]

    else:
        # placeholder per altri pacchetti
        lines.append("Dettagli pacchetto: (da definire)")

    # HTML con <br>
    return "<br>".join([l.replace("€", "&euro;") for l in lines])


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
    </p>

    <p><a href="/logout">Esci</a></p>
  </div>
</body>
</html>
"""

BOOKING_HTML = """
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
    .section { margin-top: 16px; padding-top: 12px; border-top: 1px solid #eee; }
    .chip { display:inline-block; padding:8px 10px; border-radius:999px; background:#f0f2f7; font-weight:800; margin:6px 6px 0 0; }
  </style>
</head>
<body>
  <div class="card">
    <h2>Modulo prenotazione evento – {{app_name}}</h2>
    <p><a href="/">← Home</a></p>

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
          <select name="pacchetto" id="pacchettoSelect" required onchange="togglePackageSections()">
            <option value="" {% if p=='' %}selected{% endif %}>Seleziona…</option>
            <option value="Fai da Te" {% if p=='Fai da Te' %}selected{% endif %}>{{pkg_labels['Fai da Te']}}</option>
            <option value="Lullyland Experience" {% if p=='Lullyland Experience' %}selected{% endif %}>{{pkg_labels['Lullyland Experience']}}</option>
            <option value="Lullyland all-inclusive" {% if p=='Lullyland all-inclusive' %}selected{% endif %}>{{pkg_labels['Lullyland all-inclusive']}}</option>
            <option value="Personalizzato" {% if p=='Personalizzato' %}selected{% endif %}>Personalizzato</option>
          </select>
          <div class="hint">Selezioni il pacchetto, i dettagli li vedono nel contratto.</div>
        </div>
        <div class="col">
          <label>Tema evento</label>
          <input name="tema_evento" value="{{form.get('tema_evento','')}}" />
        </div>
      </div>

      <div class="row" id="personalizzatoBox" style="display:none;">
        <div class="col">
          <label>Dettagli personalizzazione</label>
          <textarea name="pacchetto_personalizzato_dettagli">{{form.get('pacchetto_personalizzato_dettagli','')}}</textarea>
        </div>
      </div>

      <div class="row">
        <div class="col">
          <label>Acconto</label>
          <input name="acconto" inputmode="decimal" placeholder="Es. 100" value="{{form.get('acconto','')}}" />
        </div>
      </div>

      <div class="section" id="experienceBox" style="display:none;">
        <h3 style="margin:0 0 10px;">Extra per Lullyland Experience</h3>

        <div class="row">
          <div class="col">
            <label>Catering baby *</label>
            {% set bm = form.get('exp_catering_baby_choice','') %}
            <select name="exp_catering_baby_choice">
              <option value="" {% if bm=='' %}selected{% endif %}>Seleziona…</option>
              <option value="menu_pizza" {% if bm=='menu_pizza' %}selected{% endif %}>Menù pizza</option>
              <option value="box_merenda" {% if bm=='box_merenda' %}selected{% endif %}>Box merenda</option>
            </select>
          </div>
          <div class="col">
            <label>Torta (scelta) *</label>
            {% set ts = form.get('torta_scelta','') %}
            <select name="torta_scelta" id="tortaSelect" onchange="toggleTortaInterna()">
              <option value="" {% if ts=='' %}selected{% endif %}>Seleziona…</option>
              <option value="esterna" {% if ts=='esterna' %}selected{% endif %}>Torta esterna +€1,00 a persona</option>
              <option value="interna" {% if ts=='interna' %}selected{% endif %}>Torta interna (da noi) €24,00/kg</option>
            </select>
          </div>
        </div>

        <div class="row" id="tortaInternaBox" style="display:none;">
          <div class="col">
            <label>Gusto torta interna</label>
            {% set gc = form.get('torta_interna_gusto_choice','') %}
            <select name="torta_interna_gusto_choice" id="gustoChoice" onchange="toggleGustoAltro()">
              <option value="" {% if gc=='' %}selected{% endif %}>Seleziona…</option>
              <option value="default" {% if gc=='default' %}selected{% endif %}>Pan di spagna analcolico con crema chantilly e gocce di cioccolato</option>
              <option value="altro" {% if gc=='altro' %}selected{% endif %}>Altro</option>
            </select>
          </div>
          <div class="col" id="gustoAltroBox" style="display:none;">
            <label>Scrivi gusto concordato</label>
            <input name="torta_interna_gusto_text" value="{{form.get('torta_interna_gusto_text','')}}" />
          </div>
        </div>

        <div class="section">
          <h3 style="margin:0 0 10px;">Servizi extra (selezionabili)</h3>
          {% for k, item in extras.items() %}
            {% set checked = form.get('extra_' ~ k) %}
            <label class="chip" style="font-weight:800;">
              <input type="checkbox" name="extra_{{k}}" {% if checked %}checked{% endif %}>
              {{item[0]}} {{("€%0.2f"|format(item[1]))|replace(".", ",")}}
            </label>
          {% endfor %}
          <div class="hint">Puoi selezionarne uno o più.</div>
        </div>
      </div>

      <label>Note</label>
      <textarea name="note">{{form.get('note','')}}</textarea>

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
function togglePackageSections(){
  const p = document.getElementById("pacchettoSelect").value;
  document.getElementById("experienceBox").style.display = (p === "Lullyland Experience") ? "block" : "none";
  document.getElementById("personalizzatoBox").style.display = (p === "Personalizzato") ? "flex" : "none";
  toggleTortaInterna();
}
function toggleTortaInterna(){
  const p = document.getElementById("pacchettoSelect").value;
  if (p !== "Lullyland Experience") {
    document.getElementById("tortaInternaBox").style.display = "none";
    document.getElementById("gustoAltroBox").style.display = "none";
    return;
  }
  const t = document.getElementById("tortaSelect").value;
  document.getElementById("tortaInternaBox").style.display = (t === "interna") ? "flex" : "none";
  toggleGustoAltro();
}
function toggleGustoAltro(){
  const gc = document.getElementById("gustoChoice").value;
  document.getElementById("gustoAltroBox").style.display = (gc === "altro") ? "block" : "none";
}

(function() {
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

  // init UI
  togglePackageSections();
})();
</script>
</body>
</html>
"""

LIST_HTML = """
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
    a.link { color:#0a84ff; font-weight:700; text-decoration:none; }
    .muted { color:#666; }
  </style>
</head>
<body>
  <div class="card">
    <h2>Prenotazioni – {{app_name}}</h2>
    <p>
      <a class="btn" href="/prenota">+ Nuova prenotazione</a>
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
            <th>Pacchetto</th>
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
              <td>{{r['pacchetto']}}</td>
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
  <title>{{app_name}} – Dettaglio prenotazione</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body { font-family: Arial, sans-serif; padding: 18px; background:#f6f7fb; }
    .card { max-width: 980px; margin: 18px auto; background:#fff; padding: 18px; border-radius: 12px; border:1px solid #e8e8e8; }
    .grid { display:flex; gap:12px; flex-wrap:wrap; }
    .box { flex:1; min-width: 280px; border:1px solid #eee; border-radius:12px; padding:12px; background:#fff; }
    .k { color:#666; font-size: 12px; margin-bottom:4px; }
    .v { font-weight: 800; margin-bottom:10px; }
    img { max-width: 760px; width:100%; border:1px solid #ddd; border-radius:12px; background:#fff; }
    .pill { display:inline-block; padding:6px 10px; border-radius:999px; background:#f0f2f7; font-weight:800; }
    .contract { margin-top: 14px; border:1px solid #eee; border-radius:12px; padding:12px; background:#fff; line-height:1.35; }
    .contract h3 { margin:0 0 10px; }
    .totalbadge { display:inline-block; padding:10px 12px; border-radius:999px; background:#f0f2f7; font-weight:900; }
    .muted { color:#666; font-weight:700; }
  </style>
</head>
<body>
  <div class="card">
    <p><a href="/prenotazioni">← Prenotazioni</a> | <a href="/">Home</a></p>
    <h2>Dettaglio prenotazione #{{b['id']}} – {{app_name}}</h2>

    <div class="grid">
      <div class="box">
        <div class="k">Festeggiato</div>
        <div class="v">{{b['nome_festeggiato']}} ({{b['eta_festeggiato'] or '-'}})</div>

        <div class="k">Data compleanno</div>
        <div class="v">{{b['data_compleanno'] or '-'}}</div>

        <div class="k">Data evento</div>
        <div class="v">{{b['data_evento'] or '-'}}</div>

        <div class="k">Pacchetto</div>
        <div class="v">{{b['pacchetto']}}</div>

        <div class="k">Tema</div>
        <div class="v">{{b['tema_evento'] or '-'}}</div>

        <div class="k">Acconto</div>
        <div class="v">{{b['acconto'] or 0}}</div>

        <div class="k">Totale stimato</div>
        <div class="v"><span class="totalbadge">{{eur(totals.total)}}</span></div>
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
        {% if b['pacchetto']=='Lullyland Experience' and b['torta_scelta']=='esterna' %}
          <!-- ✅ MODIFICA 2: niente kg/100g/€24 quando torta esterna -->
          <div class="v">Torta esterna → servizio torta: €1,00 x {{totals.tot_persone}} persone</div>
        {% elif b['pacchetto']=='Lullyland Experience' and b['torta_scelta']=='interna' %}
          <div class="v">{{totals.cake_details}}</div>
        {% else %}
          <div class="v">-</div>
        {% endif %}
      </div>

      <div class="box" style="flex-basis:100%;">
        <div class="k">Note</div>
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

        <div class="contract">
          <h3>Dettagli pacchetto (contratto)</h3>
          <div class="muted" style="margin-bottom:8px;">
            Totale stimato se il numero degli invitati resta invariato (ci aggiorniamo qualche giorno prima per il numero definitivo).
          </div>
          <div>{{contract_html|safe}}</div>
        </div>
      </div>
    </div>
  </div>
</body>
</html>
"""


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
