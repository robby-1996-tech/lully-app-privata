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
            tema_evento TEXT,
            note TEXT,

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
        pin = request.form.get("pin", "")
        if pin == APP_PIN:
            session["ok"] = True
            return redirect(url_for("home"))
        return render_template_string(LOGIN_HTML, error="PIN errato.")
    return render_template_string(LOGIN_HTML, error=None)


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
            )

        if not firma_png_base64.startswith("data:image/png;base64,"):
            return render_template_string(
                BOOKING_HTML,
                app_name=APP_NAME,
                error="Firma mancante: firma nel riquadro prima di salvare.",
                today=datetime.now().strftime("%Y-%m-%d"),
                form=request.form,
            )

        # Campi
        def to_int(val):
            try:
                return int(val) if val not in (None, "",) else None
            except:
                return None

        payload = {
            "created_at": datetime.now().isoformat(timespec="seconds"),

            "nome_festeggiato": request.form.get("nome_festeggiato", "").strip(),
            "eta_festeggiato": to_int(request.form.get("eta_festeggiato")),
            "data_compleanno": request.form.get("data_compleanno", "").strip(),
            "data_evento": request.form.get("data_evento", "").strip(),

            "madre_nome_cognome": request.form.get("madre_nome_cognome", "").strip(),
            "madre_telefono": request.form.get("madre_telefono", "").strip(),

            "padre_nome_cognome": request.form.get("padre_nome_cognome", "").strip(),
            "padre_telefono": request.form.get("padre_telefono", "").strip(),

            "indirizzo_residenza": request.form.get("indirizzo_residenza", "").strip(),
            "email": request.form.get("email", "").strip(),

            "invitati_bambini": to_int(request.form.get("invitati_bambini")),
            "invitati_adulti": to_int(request.form.get("invitati_adulti")),

            "pacchetto": request.form.get("pacchetto", "").strip(),
            "tema_evento": request.form.get("tema_evento", "").strip(),
            "note": request.form.get("note", "").strip(),

            "data_firma": data_firma,
            "firma_png_base64": firma_png_base64,

            "consenso_privacy": consenso_privacy,
            "consenso_foto": consenso_foto,
        }

        # Validazioni minime (solo per evitare buchi grossi)
        if not payload["nome_festeggiato"]:
            return render_template_string(
                BOOKING_HTML,
                app_name=APP_NAME,
                error="Inserisci il nome del festeggiato.",
                today=datetime.now().strftime("%Y-%m-%d"),
                form=request.form,
            )
        if payload["pacchetto"] not in ("Fai da Te", "Lullyland Experience", "Lullyland all-inclusive"):
            return render_template_string(
                BOOKING_HTML,
                app_name=APP_NAME,
                error="Seleziona un pacchetto valido.",
                today=datetime.now().strftime("%Y-%m-%d"),
                form=request.form,
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
                pacchetto, tema_evento, note,
                data_firma, firma_png_base64,
                consenso_privacy, consenso_foto
            ) VALUES (
                :created_at,
                :nome_festeggiato, :eta_festeggiato, :data_compleanno, :data_evento,
                :madre_nome_cognome, :madre_telefono,
                :padre_nome_cognome, :padre_telefono,
                :indirizzo_residenza, :email,
                :invitati_bambini, :invitati_adulti,
                :pacchetto, :tema_evento, :note,
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

    return render_template_string(DETAIL_HTML, app_name=APP_NAME, b=row)


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
          <select name="pacchetto" required>
            {% set p = form.get('pacchetto','') %}
            <option value="" {% if p=='' %}selected{% endif %}>Seleziona…</option>
            <option value="Fai da Te" {% if p=='Fai da Te' %}selected{% endif %}>Fai da Te</option>
            <option value="Lullyland Experience" {% if p=='Lullyland Experience' %}selected{% endif %}>Lullyland Experience</option>
            <option value="Lullyland all-inclusive" {% if p=='Lullyland all-inclusive' %}selected{% endif %}>Lullyland all-inclusive</option>
          </select>
        </div>
        <div class="col">
          <label>Tema evento</label>
          <input name="tema_evento" value="{{form.get('tema_evento','')}}" />
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
(function() {
  const canvas = document.getElementById('sigCanvas');
  const ctx = canvas.getContext('2d');
  let drawing = false;
  let hasInk = false;

  function resizeCanvas() {
    const rect = canvas.getBoundingClientRect();
    const ratio = window.devicePixelRatio || 1;

    // Imposta dimensioni reali
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

  // Init
  resizeCanvas();
  window.addEventListener('resize', resizeCanvas);

  canvas.addEventListener('mousedown', start);
  canvas.addEventListener('mousemove', move);
  window.addEventListener('mouseup', end);

  canvas.addEventListener('touchstart', start, { passive:false });
  canvas.addEventListener('touchmove', move, { passive:false });
  window.addEventListener('touchend', end, { passive:false });

  // On submit: salva PNG base64
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
    .box { flex:1; min-width: 280px; border:1px solid #eee; border-radius:12px; padding:12px; }
    .k { color:#666; font-size: 12px; margin-bottom:4px; }
    .v { font-weight: 800; margin-bottom:10px; }
    img { max-width: 760px; width:100%; border:1px solid #ddd; border-radius:12px; background:#fff; }
    .pill { display:inline-block; padding:6px 10px; border-radius:999px; background:#f0f2f7; font-weight:800; }
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
      </div>
    </div>
  </div>
</body>
</html>
"""


if __name__ == "__main__":
    # in locale
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
