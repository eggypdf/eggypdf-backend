"""Production WSGI entrypoint for EggyPDF.

Render should use `gunicorn wsgi:app` once this branch is deployed.
"""
from app import app
from career_routes import career_bp

app.register_blueprint(career_bp)
