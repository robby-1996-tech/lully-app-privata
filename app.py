import os
from flask import Flask, request, redirect, url_for, session, render_template_string

app = Flask(__name__)

APP_NAME = "Lullyland"

# IMPORTANTISSIMO: su Render lo mettiamo come Environment Variable
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-key-change-me")

APP_PIN = os.getenv("APP_PIN", "1234")  # su Render lo cambiamo subito

LOGIN_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Lullyland - Accesso</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body { font-family: Arial, sans-serif; padding: 30px; }
    .box { max-width: 360px; margin: 60px auto; }
    input { width: 100%; padding: 12px; font-size: 16px; margin: 10px 0; }
    button { width: 100%; padding: 12px; font-size: 16px; }
    .err { color: #b00020; }
  </style>
</head>
<body>
  <div class="box">
    <h2>Accesso Lullyland</h2>
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
  <title>Lullyland App Privata – online 🎉</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body { font-family: Arial, sans-serif; padding: 30px; }
    a { display: inline-block; margin: 8px 0; }
  </style>
</head>
<body>
  <h1>Lullyland App Privata – online 🎉</h1>
  <p>Se vedi questa pagina, il PIN funziona ✅</p>

  <p><a href="/prenotazione">+ Nuova prenotazione</a></p>

  <p><a href="/logout">Esci</a></p>
</body>
</html>
"""

FORM_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Lullyland - Prenotazione evento</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body { font-family: Arial, sans-serif; padding: 30px; }
    .box { max-width: 720px; margin: 0 auto; }
    label { display:block; margin-top: 12px; font-weight: bold; }
    input, select, textarea { width: 100%; padding: 12px; font-size: 16px; margin: 8px 0; box-sizing: border-box; }
    textarea { min-height: 90px; }
    button { width: 100%; padding: 12px; font-size: 16px; margin-top: 16px; }
    .row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
    .hint { font-size: 13px; opacity: 0.8; margin-top: 4px; }
    .checkline { display:flex; align-items:center; gap:10px; margin: 10px 0; }
    .checkline input { width: auto; margin: 0; }
    .sigbox { border: 1px solid #ddd; border-radius: 8px; padding: 10px; margin-top: 10px; }
    canvas { width: 100%; height: 200px; border: 1px solid #ccc; border-radius: 6px; touch-action: none; }
    .sig-actions { display:flex; gap: 10px; margin-top: 10px; }
    .sig-actions button { width: auto; flex: 1; }
    .err { color: #b00020; }
  </style>

  <script>
    function togglePersonalizzato() {
      const pkg = document.getElementById("pacchetto").value;
      const box = document.getElementById("box_personalizzato");
      box.style.display = (pkg === "Personalizzato") ? "block" : "none";
    }

    // Signature pad (tablet)
    let canvas, ctx, drawing = false, lastX=0, lastY=0;

    function resizeCanvas() {
      // rende il canvas "nitido" su mobile
      const ratio = window.devicePixelRatio || 1;
      const rect = canvas.getBoundingClientRect();
      canvas.width = rect.width * ratio;
      canvas.height = rect.height * ratio;
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      ctx.lineWidth = 2;
      ctx.lineCap = "round";
      ctx.strokeStyle = "#111";
    }

    function getPos(e) {
      const rect = canvas.getBoundingClientRect();
      const touch = e.touches ? e.touches[0] : null;
      const x = (touch ? touch.clientX : e.clientX) - rect.left;
      const y = (touch ? touch.clientY : e.clientY) - rect.top;
      return {x, y};
    }

    function startDraw(e) {
      drawing = true;
      const p = getPos(e);
      lastX = p.x; lastY = p.y;
      e.preventDefault();
    }

    function draw(e) {
      if (!drawing) return;
      const p = getPos(e);
      ctx.beginPath();
      ctx.moveTo(lastX, lastY);
      ctx.lineTo(p.x, p.y);
      ctx.stroke();
      lastX = p.x; lastY = p.y;
      e.preventDefault();
    }

    function endDraw(e) {
      drawing = false;
      e.preventDefault();
    }

    function clearSig() {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      document.getElementById("firma_data").value = "";
    }

    function saveSigToHidden() {
      // salva una versione base64 (dataURL) nel campo nascosto
      const dataURL = canvas.toDataURL("image/png");
      document.getElementById("firma_data").value = dataURL;
    }

    window.addEventListener("load", () => {
      // pacchetto
      togglePersonalizzato();

      // firma
      canvas = document.getElementById("firma");
      ctx = canvas.getContext("2d");
      resizeCanvas();
      window.addEventListener("resize", resizeCanvas);

      canvas.addEventListener("mousedown", startDraw);
      canvas.addEventListener("mousemove", draw);
      canvas.addEventListener("mouseup", endDraw);
      canvas.addEventListener("mouseleave", endDraw);

      canvas.addEventListener("touchstart", startDraw, {passive:false});
      canvas.addEventListener("touchmove", draw, {passive:false});
      canvas.addEventListener("touchend", endDraw, {passive:false});
    });

    function beforeSubmit() {
      saveSigToHidden();
      // Non blocco ancora se firma vuota: domani decidiamo se renderla obbligatoria
      return true;
    }
  </script>
</head>

<body>
  <div class="box">
    <h2>Modulo prenotazione evento</h2>

    {% if error %}<p class="err">{{ error }}</p>{% endif %}

    <form method="post" onsubmit="return beforeSubmit();">

      <label>Nome festeggiato</label>
      <input name="nome_festeggiato" required>

      <div class="row">
        <div>
          <label>Età del festeggiato</label>
          <input type="number" name="eta" min="0">
        </div>
        <div>
          <label>Data del compleanno</label>
          <input type="date" name="data_compleanno">
        </div>
      </div>

      <label>Data dell’evento</label>
      <input type="date" name="data_evento" required>

      <div class="row">
        <div>
          <label>Madre - Nome e Cognome</label>
          <input name="madre_nome">
        </div>
        <div>
          <label>Madre - Telefono</label>
          <input name="madre_tel">
        </div>
      </div>

      <div class="row">
        <div>
          <label>Padre - Nome e Cognome</label>
          <input name="padre_nome">
        </div>
        <div>
          <label>Padre - Telefono</label>
          <input name="padre_tel">
        </div>
      </div>

      <label>Indirizzo di residenza</label>
      <input name="indirizzo">

      <label>Email</label>
      <input type="email" name="email">

      <div class="row">
        <div>
          <label>Numero invitati bambini</label>
          <input type="number" name="inv_bambini" min="0">
        </div>
        <div>
          <label>Numero invitati adulti</label>
          <input type="number" name="inv_adulti" min="0">
        </div>
      </div>

      <label>Pacchetto scelto</label>
      <select name="pacchetto" id="pacchetto" onchange="togglePersonalizzato()" required>
        <option value="">Seleziona</option>
        <option>Fai da Te</option>
        <option>Lullyland Experience</option>
        <option>Lullyland all-inclusive</option>
        <option>Personalizzato</option>
      </select>

      <div id="box_personalizzato" style="display:none;">
        <label>Dettagli personalizzazione</label>
        <textarea name="dettagli_personalizzato" placeholder="Scrivi qui i dettagli del pacchetto personalizzato..."></textarea>
      </div>

      <label>Tema evento</label>
      <input name="tema_evento">

      <label>Note</label>
      <textarea name="note"></textarea>

      <label>Acconto (€)</label>
      <input type="number" name="acconto" step="0.01" min="0" placeholder="Es. 50">

      <div class="checkline">
        <input type="checkbox" name="consenso_privacy" required>
        <div>
          <b>Consenso privacy</b> <span class="hint">(obbligatorio)</span>
        </div>
      </div>

      <div class="checkline">
        <input type="checkbox" name="consenso_foto">
        <div>
          <b>Consenso foto/video per social</b> <span class="hint">(facoltativo)</span>
        </div>
      </div>

      <label>Data e firma genitore (firma su tablet)</label>
      <div class="sigbox">
        <div class="hint">Firma qui con il dito o la penna (tablet).</div>
        <canvas id="firma"></canvas>
        <input type="hidden" name="firma_data" id="firma_data" />
        <div class="sig-actions">
          <button type="button" onclick="clearSig()">Cancella firma</button>
        </div>
      </div>

      <button type="submit">Salva</button>
    </form>

    <p style="margin-top:16px;"><a href="/">← Torna alla home</a></p>
  </div>
</body>
</html>
"""

SAVED_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Lullyland - Salvato</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body { font-family: Arial, sans-serif; padding: 30px; }
    .box { max-width: 720px; margin: 60px auto; }
  </style>
</head>
<body>
  <div class="box">
    <h2>Prenotazione salvata ✅</h2>
    <p>(Per ora la salviamo “logicamente”: nel prossimo step la memorizziamo davvero e generiamo PDF + email.)</p>
    <p><a href="/prenotazione">+ Nuova prenotazione</a></p>
    <p><a href="/">Torna alla home</a></p>
  </div>
</body>
</html>
"""

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

@app.route("/")
def home():
    if not is_logged_in():
        return redirect(url_for("login"))
    return render_template_string(HOME_HTML)

@app.route("/prenotazione", methods=["GET", "POST"])
def prenotazione():
    if not is_logged_in():
        return redirect(url_for("login"))

    if request.method == "POST":
        # Per ora non persistiamo ancora (step successivo: database + PDF + email)
        return render_template_string(SAVED_HTML)

    return render_template_string(FORM_HTML, error=None)

if __name__ == "__main__":
    # in locale
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
