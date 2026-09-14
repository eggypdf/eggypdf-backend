"""Production WSGI entrypoint for EggyPDF."""
from app import app
from career_routes import career_bp
from career_free_routes import career_free_bp
from account_routes import account_bp
from career_security_patch import install as install_career_security

install_career_security()

app.register_blueprint(career_bp)
app.register_blueprint(career_free_bp)
app.register_blueprint(account_bp)


def allow_account_authorization_header(response):
    """Keep the shared API CORS policy compatible with Bearer-token requests."""
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return response


# Flask runs after_request handlers in reverse registration order. Insert this
# handler first so it runs last, after app.py's legacy CORS helper.
app.after_request_funcs.setdefault(None, []).insert(0, allow_account_authorization_header)
