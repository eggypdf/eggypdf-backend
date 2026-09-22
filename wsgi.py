"""Production WSGI entrypoint for EggyPDF."""
from app import app
from career_routes import career_bp
from career_free_routes import career_free_bp
from account_routes import account_bp
from account_recovery_routes import account_recovery_bp
from career_billing_routes import billing_bp
from career_checkout_session_routes import checkout_session_bp
from career_reconcile_routes import reconcile_bp
from career_billing_diagnostics import billing_diagnostics_bp
from career_subscription_routes import subscription_bp
from career_webhook_routes import webhook_bp
from career_security_patch import install as install_career_security
from career_credit_patch import install as install_credit_enforcement

install_career_security()

app.register_blueprint(career_bp)
app.register_blueprint(career_free_bp)
app.register_blueprint(account_bp)
app.register_blueprint(account_recovery_bp)
app.register_blueprint(billing_bp)
app.register_blueprint(checkout_session_bp)
app.register_blueprint(reconcile_bp)
app.register_blueprint(billing_diagnostics_bp)
app.register_blueprint(subscription_bp)
app.register_blueprint(webhook_bp)
install_credit_enforcement(app)


def allow_account_authorization_header(response):
    """Keep the shared API CORS policy compatible with Bearer/idempotency requests."""
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Idempotency-Key"
    return response


# Flask runs after_request handlers in reverse registration order. Insert this
# handler first so it runs last, after app.py's legacy CORS helper.
app.after_request_funcs.setdefault(None, []).insert(0, allow_account_authorization_header)
