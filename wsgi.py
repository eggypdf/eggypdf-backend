"""Production WSGI entrypoint for EggyPDF."""
from app import app
from career_routes import career_bp
from account_routes import account_bp

app.register_blueprint(career_bp)
app.register_blueprint(account_bp)
