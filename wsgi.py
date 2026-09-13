"""Production WSGI entrypoint for EggyPDF."""
from app import app
from career_routes import career_bp
from account_routes import account_bp

app.register_blueprint(career_bp)
app.register_blueprint(account_bp)


@app.after_request
def allow_account_authorization_header(response):
    """Keep the shared API CORS policy compatible with Bearer-token requests."""
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return response
