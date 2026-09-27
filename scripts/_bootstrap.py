"""Shared app-context bootstrap for the one-off scripts."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import main_app  # noqa: E402


def app_context():
    app = main_app()
    return app.app_context()
