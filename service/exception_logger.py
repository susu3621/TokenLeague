import sys
import traceback

from werkzeug.exceptions import HTTPException


def init_app(app):
    @app.errorhandler(Exception)
    def handle_exception(exc):
        if isinstance(exc, HTTPException):
            return exc
        print(f"[template-error] {exc}", file=sys.stderr)
        traceback.print_exception(type(exc), exc, exc.__traceback__, file=sys.stderr)
        if app.config.get("TESTING"):
            raise exc
        return {"success": False, "error": "Internal server error"}, 500
