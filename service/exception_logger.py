import sys


def init_app(app):
    @app.errorhandler(Exception)
    def handle_exception(exc):
        print(f"[template-error] {exc}", file=sys.stderr)
        if getattr(exc, "code", None) and getattr(exc, "name", None):
            return exc
        if app.config.get("TESTING"):
            raise exc
        return {"success": False, "error": "Internal server error"}, 500
