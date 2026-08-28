"""Capa de persistencia SQLite del carrito."""

from .database import inicializar_base_datos, obtener_conexion

__all__ = ["inicializar_base_datos", "obtener_conexion"]