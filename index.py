"""Punto de entrada para Vercel (en local se usa `python app.py`).

Vercel cargaba app.py como el módulo "app", que choca con el paquete app/ y provocaba
ModuleNotFoundError: No module named 'app.main'. Este archivo tiene un nombre sin conflicto.
"""
from app.main import app  # noqa: F401
