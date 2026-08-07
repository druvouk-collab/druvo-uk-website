"""Jinja2 template engine."""

from __future__ import annotations

from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.template_helpers import template_globals

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.globals.update(template_globals())
