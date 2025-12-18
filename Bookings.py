import sqlite3
from datetime import datetime
from flask import request, redirect, url_for, abort

# Pacchetti (base) come da quanto avevamo impostato
PACKAGE_PRICES_EUR = {
    "Fai da Te": 15,
    "Lullyland Experience": 20,
    "Lullyland all-inclusive": 30,
    "Personalizzato": 0,
}

def eur_to_cents(raw: str) -> int:
    if raw is None:
        return 0
    s = raw.strip()
    if not s:
        return 0
    s = s.replace(",", ".")
    try:
        if "." in s:
            a, b = s.split(".", 1)
            b = (b + "00")[:2]
        else:
            a, b = s, "00"
        sign = -1 if a.startswith("-") else 1
        a = a.replace("-", "")
        euros = int(a) if a else 0
        cents = int(b) if b else 0
        return sign * (euros * 100 + cents)
    except Exception:
        return 0

def cents_to_eur_str(c: int) -> str:
    c = int(c or 0)
    sign = "-" if c < 0 else ""
    c = abs(c)
    return f"{sign}{c//100},{c%100:02d}"

def table_columns(db, table_name: str):
    rows = db.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {r[1] if isinstance(r, tuple) else r["name"] for r in rows}

def ensure_schema(db):
    """
    La tabella bookings viene creata in app.py.
    Qui facciamo solo migrazione colonne extra (se mancano).
    """
    cols = table_columns(db, "bookings")
    wanted = {
        "child_age": "INTEGER DEFAULT 0",
        "kids_count": "INTEGER DEFAULT 0",
        "adults_count": "INTEGER DEFAULT 0",
        "theme": "TEXT DEFAULT ''",
        "package": "TEXT DEFAULT ''",
        "package_price_cents": "INTEGER DEFAULT 0",
        "total_cents": "INTEGER DEFAULT 0",
        "notes": "TEXT DEFAULT ''",
    }
    for col, ddl in wanted.items():
        if col not in cols:
            db.execute(f"ALTER TABLE bookings ADD COLUMN {col} {ddl}")
    db.commit()

def count_in_slot(db, event_date: str, slot_code: str) -> int:
    r = db.execute(
        "SELECT COUNT(*) AS c FROM bookings WHERE event_date=? AND slot_code=?",
        (event_date, slot_code)
    ).fetchone()
    return int(r[0] if isinstance(r, tuple) else r["c"])

def next_area(db, event_date: str, slot_code: str) -> int:
    n = count_in_slot(db, event_date, slot_code)
    if n == 0: return 1
    if n == 1: return 2
    return 3

def bookings_for_slot(db, event_date: str, slot_code: str):
    return db.execute("""
        SELECT id, area, child_name, child_age, kids_count, adults_count, theme, package, phone, deposit_cents, total_cents
        FROM bookings
        WHERE event_date=? AND slot_code=?
        ORDER BY area ASC, id ASC
    """, (event_date, slot_code)).fetchall()

def register_booking_routes(app, get_db, topbar_html, base_css, slots_for_date):
    """
    Collega tutte le route del software eventi al flask app
    senza toccare il calendario.
    """

    @app.route("/booking/new", methods=["GET", "POST"])
    def booking_new():
        db = get_db()
        ensure_schema(db)

        event_date = (request.args.get("date") or "").strip()
        slot_code = (request.args.get("slot") or "").strip().upper()

        # Validazioni base
        try:
            d = datetime.strptime(event_date, "%Y-%m-%d").date()
        except Exception:
            abort(400, "Data non valida.")

        allowed = {s["code"] for s in slots_for_date(d)}
        if slot_code not in allowed:
            abort(400, "Slot non valido per questa data.")

        slot = next(s for s in slots_for_date(d) if s["code"] == slot_code)

        # Stato slot
        n = count_in_slot(db, event_date, slot_code)
        suggested_area = next_area(db, event_date, slot_code)
        overbook = n >= 2

        error = ""
        if request.method == "POST":
            child_name = (request.form.get("child_name") or "").strip()
            phone = (request.form.get("phone") or "").strip()
            child_age = int((request.form.get("child_age") or "0").strip() or 0)
            kids_count = int((request.form.get("kids_count") or "0").strip() or 0)
            adults_count = int((request.form.get("adults_count") or "0").strip() or 0)
            theme = (request.form.get("theme") or "").strip()
            package = (request.form.get("package") or "").strip()
            notes = (request.form.get("notes") or "").strip()

            deposit_cents = eur_to_cents(request.form.get("deposit") or "")

            # Prezzi
            base_price_eur = PACKAGE_PRICES_EUR.get(package, 0)
            package_price_cents = base_price_eur * 100

            # Se "Personalizzato", prendi totale custom dal campo
            custom_total_cents = eur_to_cents(request.form.get("custom_total") or "")
            total_cents = custom_total_cents if package == "Personalizzato" else package_price_cents

            confirm_area3 = (request.form.get("confirm_area3") == "on")

            if not child_name:
                error = "Inserisci il nome del festeggiato."
            else:
                # ricontrollo al salvataggio
                n_now = count_in_slot(db, event_date, slot_code)
                area = next_area(db, event_date, slot_code)

                if n_now >= 2 and not confirm_area3:
                    error = "Area 1 e 2 sono già impegnate. Se vuoi inserire comunque, conferma Area 3."
                else:
                    db.execute("""
                        INSERT INTO bookings(
                          event_date, slot_code, start_time, end_time, area,
                          child_name, phone, deposit_cents, created_at,
                          child_age, kids_count, adults_count, theme, package,
                          package_price_cents, total_cents, notes
                        )
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """, (
                        event_date, slot_code, slot["start"], slot["end"], area,
                        child_name, phone, deposit_cents, datetime.now().isoformat(timespec="seconds"),
                        child_age, kids_count, adults_count, theme, package,
                        package_price_cents, total_cents, notes
                    ))
                    db.commit()
                    # torna al giorno
                    return redirect(url_for("day_view", date_iso=event_date))

        # Opzioni pacchetti
        pkg_opts = "".join([f"<option value='{p}'>{p}</option>" for p in PACKAGE_PRICES_EUR.keys()])

        # Mostra eventi già presenti nello slot
        existing = bookings_for_slot(db, event_date, slot_code)
        existing_html = ""
        if existing:
            lines = []
            for r in existing:
                # sqlite row can be tuple or dict; handle both
                def g(k, idx=None):
                    if isinstance(r, tuple):
                        return r[idx]
                    return r[k]
                lines.append(f"""
                  <div class="eventline">
                    <b>Area {g('area',1)}: {g('child_name',2)} – {g('child_age',3)} anni</b>
                    <div class="muted">{g('kids_count',4)} bimbi / {g('adults_count',5)} adulti · Tema: {g('theme',6) or '-'} · Pacchetto: {g('package',7) or '-'}</div>
                    <div class="muted">Tel: {g('phone',8) or '-'} · Acconto: € {cents_to_eur_str(g('deposit_cents',9))} · Totale: € {cents_to_eur_str(g('total_cents',10))}</div>
                  </div>
                """)
            existing_html = "<div style='margin-top:10px;display:grid;gap:8px;'>" + "".join(lines) + "</div>"

        # Banner errore
        error_html = f"<div class='flash'>{error}</div>" if error else ""

        overbook_html = ""
        if overbook:
            overbook_html = """
            <div class="warn">
              <b>Allert:</b> Area 1 e 2 sono già impegnate.
              <div style="margin-top:8px;display:flex;gap:10px;align-items:center;">
                <input style="width:auto" type="checkbox" name="confirm_area3" id="c3">
                <label for="c3"><b>Confermo inserimento Area 3</b></label>
              </div>
            </div>
            """

        return f"""<!doctype html>
<html><head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Nuovo evento</title>
{base_css}
<style>
  .flash{{padding:10px;border-radius:12px;background:#fff3cd;border:1px solid #ffeeba;margin-top:12px;font-weight:800;}}
  .warn{{margin-top:12px;padding:10px;border-radius:12px;background:#ffe1e1;border:1px solid #f2a0a0;}}
  .row{{display:grid;grid-template-columns:1fr 1fr;gap:10px;}}
  @media (max-width:700px){{.row{{grid-template-columns:1fr;}}}}
  input, textarea, select{{width:100%;padding:10px;border:1px solid #ddd;border-radius:12px;font-size:16px;background:#fff;}}
  textarea{{min-height:90px;}}
  .eventline{{padding:10px;border-radius:12px;border:1px solid #eee;background:#fcfcfc;}}
</style>
</head><body>
  {topbar_html("month")}
  <div class="card">
    <h2 style="margin:0;">➕ Nuovo evento</h2>
    <div class="muted" style="margin-top:6px;">
      Data: <b>{event_date}</b> · Slot: <b>{slot['start']}–{slot['end']}</b> ({slot['label']}) · Occupazione: <b>{n}/2</b> · Area suggerita: <b>{suggested_area}</b>
    </div>

    {error_html}

    {existing_html}

    <form method="post" style="margin-top:12px;">
      <div class="row">
        <div>
          <label><b>Nome festeggiato</b></label>
          <input name="child_name" placeholder="Es. Marco" required>
        </div>
        <div>
          <label><b>Età</b></label>
          <input name="child_age" type="number" min="0" inputmode="numeric" placeholder="Es. 5">
        </div>
      </div>

      <div class="row" style="margin-top:10px;">
        <div>
          <label><b>Telefono</b></label>
          <input name="phone" inputmode="tel" placeholder="Es. 320...">
        </div>
        <div>
          <label><b>Acconto (€)</b></label>
          <input name="deposit" inputmode="decimal" placeholder="Es. 50 o 50,00">
        </div>
      </div>

      <div class="row" style="margin-top:10px;">
        <div>
          <label><b>Numero bimbi</b></label>
          <input name="kids_count" type="number" min="0" inputmode="numeric" placeholder="Es. 20">
        </div>
        <div>
          <label><b>Numero adulti</b></label>
          <input name="adults_count" type="number" min="0" inputmode="numeric" placeholder="Es. 20">
        </div>
      </div>

      <div class="row" style="margin-top:10px;">
        <div>
          <label><b>Tema</b></label>
          <input name="theme" placeholder="Es. Spiderman">
        </div>
        <div>
          <label><b>Pacchetto</b></label>
          <select name="package" id="pkg" onchange="toggleCustomTotal()">
            {pkg_opts}
          </select>
        </div>
      </div>

      <div id="customTotalBox" style="display:none; margin-top:10px;">
        <label><b>Totale personalizzato (€)</b></label>
        <input name="custom_total" inputmode="decimal" placeholder="Es. 250 o 250,00">
        <div class="muted" style="margin-top:6px;font-size:12px;">Usato solo se Pacchetto = Personalizzato</div>
      </div>

      <div style="margin-top:10px;">
        <label><b>Note</b></label>
        <textarea name="notes" placeholder="Info extra..."></textarea>
      </div>

      {overbook_html}

      <div class="row" style="margin-top:12px;">
        <button class="btn primary" type="submit" style="cursor:pointer;">Salva evento</button>
        <a class="btn" href="{url_for('day_view', date_iso=event_date)}">Annulla</a>
      </div>
    </form>
  </div>

<script>
function toggleCustomTotal(){{
  const pkg = document.getElementById('pkg').value;
  const box = document.getElementById('customTotalBox');
  box.style.display = (pkg === 'Personalizzato') ? 'block' : 'none';
}}
toggleCustomTotal();
</script>
</body></html>
"""
