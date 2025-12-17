import os
from flask import Flask, request, redirect, url_for, session, render_template_string

app = Flask(__name__)

APP_NAME = "Lullyland"

app.secret_key = os.getenv("SECRET_KEY", "dev-secret-key-change-me")
APP_PIN = os.getenv("APP_PIN", "1234")

LOGIN_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>{{ app_name }} - Accesso</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body { font-family: Arial, sans-serif; padding: 30px; }
    .box { max-width: 360px; margin: 60px auto; }
    input, select, textarea { width: 100%; padding: 12px; font-size: 16px; margin: 8px 0; }
    button { width: 100%; padding: 12px; font-size: 16px; }
    .err { color: #b00020; }
  </style>
</head>
<body>
  <div class="box">
    <h2>Accesso {{ app_name }}</h2>
    {% if error %}<p class="err">{{ error }}</p>{% endif %}
    <form method="post">
      <input type="password" name="pin" placeholder="Inserisci PIN" required />
      <button type="submit">Entra</button>
    </form>
  </div>
</body>
</html>
"""

FORM_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Nuova prenotazione - {{ app_name }}</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body { font-family: Arial, sans-serif; padding: 20px; }
    input, select, textarea { width: 100%; padding: 10px; margin: 6px 0; }
    label { font-weight: bold; margin-top: 12px; display: block; }
    button { padding: 12px; font-size: 16px; margin-top: 20px; width: 100%; }
  </style>

  <script>
    function togglePersonalizzato() {
      const pkg = document.getElementById("pacchetto").value;
      const box = document.getElementById("personalizzato_box");
      box.style.display = (pkg === "Personalizzato") ? "block" : "none";
    }
  </script>
</head>
<body>

<h2>Modulo Prenotazione Evento</h2>

<form method="post">

<label>Nome festeggiato</label>
<input name="nome_festeggiato" required>

<label>Età festeggiato</label>
<input type="number" name="eta" required>

<label>Data compleanno</label>
<input type="date" name="data_compleanno">

<label>Data evento</label>
<input type="date" name="data_evento" required>

<label>Madre - Nome, Cognome, Telefono</label>
<input name="madre">

<label>Padre - Nome, Cognome, Telefono</label>
<input name="padre">

<label>Email</label>
<input type="email" name="email">

<label>Indirizzo di residenza</label>
<input name="indirizzo">

<label>Numero invitati bambini</label>
<input type="number" name="bambini">

<label>Numero invitati adulti</label>
<input type="number" name="adulti">

<label>Pacchetto scelto</label>
<select name="pacchetto" id="pacchetto" onchange="togglePersonalizzato()" required>
  <option value="">-- Seleziona --</option>
  <option>Fai da Te</option>
  <option>Lullyland Experience</option>
  <option>Lullyland All-Inclusive</option>
  <option>Personalizzato</option>
</select>

<div id="personalizzato_box" style="display:none;">
  <label>Dettagli personalizzazione</label>
  <textarea name="dettagli_personalizzato"></textarea>
</div>

<label>Tema evento</label>
<input name="tema">

<label>Acconto (€)</label>
<input type="number" name="acconto" step="0.01">

<label>Note</label>
<textarea name="note"></textarea>

<label>
  <input type="checkbox" required> Consenso privacy
</label>

<label>
  <input type="checkbox"> Consenso foto/video per social
</label>

<label>Firma genitore (su tablet)</label>
<input placeholder="Firma apposta su tablet" disabled>

<button type="submit">Salva prenotazione</button>

</form>

<p><a href="/">← Torna alla home</a></p>

</body>
</html>
"""

HOME_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>{{ app_name }} App Privata</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body>
  <h1>{{ app_name }} App Privata</h1>
  <p><a href="/nuova">+ Nuova prenotazione</a></p>
  <p><a href="/logout">Esci</a></p>
</body>
</html>
"""

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

@app.route("/")
def home():
    if not is_logged_in():
        return redirect(url_for("login"))
    return render_template_string(HOME_HTML, app_name=APP_NAME)

@app.route("/nuova", methods=["GET", "POST"])
def nuova():
    if not is_logged_in():
        return redirect(url_for("login"))
    if request.method == "POST":
        return redirect(url_for("home"))
    return render_template_string(FORM_HTML, app_name=APP_NAME)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
