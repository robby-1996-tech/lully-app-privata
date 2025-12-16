from flask import Flask

app = Flask(__name__)

@app.route("/")
def home():
    return "Lully Land App Privata – online 🎉"
