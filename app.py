import os
from flask import Flask, request, redirect, url_for, session, render_template_string

app = Flask(__name__)

# Nome ufficiale del brand (una volta per tutte)
APP_NAME = "Lullyland"

# IMPORTANTISSIMO: su Render lo mettiamo come Environment Variable
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-key-change-me")

# PIN: su Render lo imposti come Environment Variable (APP_PIN)
APP_PIN = os.getenv("APP_PIN", "1234")

LOGIN_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>{{ APP_NAME }} - Accesso</title>
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
    <h2>Accesso {{ APP_NAME }}</h2>
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
  <title>{{ APP_NAME }} App Privata – online 🎉</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body>
  <h1>{{ APP_NAME }} App Privata – online 🎉</h1>
  <p>Se vedi questa pagina, il PIN funziona ✅</p>
  <p><a href="/logout">Esci</a></p>
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
        return render_template_string(LOGIN_HTML, error="PIN errato.", APP_NAME=APP_NAME)
    return render_template_string(LOGIN_HTML, error=None, APP_NAME=APP_NAME)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/")
def home():
    if not is_logged_in():
        return redirect(url_for("login"))
    return render_template_string(HOME_HTML, APP_NAME=APP_NAME)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
