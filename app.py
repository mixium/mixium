import os
from flask import Flask

app = Flask(__name__)

# Necessário para o flash() funcionar (sem isso o Flask levanta RuntimeError).
# Em produção, defina a variável de ambiente FLASK_SECRET_KEY.
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-key-change-me")

from routes import *

if __name__ == "__main__":
    app.run(debug=True)