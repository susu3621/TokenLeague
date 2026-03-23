import sys
import traceback


def init_app(app):
    @app.errorhandler(Exception)
    def handle_exception(exc):
        print(f"[template-error] {exc}", file=sys.stderr)
        traceback.print_exception(type(exc), exc, exc.__traceback__, file=sys.stderr)
        if getattr(exc, "code", None) and getattr(exc, "name", None):
            return exc
        if app.config.get("TESTING"):
            raise exc
        return {"success": False, "error": "Internal server error"}, 500
