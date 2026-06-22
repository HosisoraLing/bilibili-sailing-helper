"""Focused route modules for the Flask app."""
from route_handlers.common import admin_bp, internal_bp, main_bp

# Import modules for their route registrations.
from route_handlers import auth as _auth
from route_handlers import internal as _internal
from route_handlers import public as _public
from route_handlers.admin import addresses as _addresses
from route_handlers.admin import companion as _companion
from route_handlers.admin import cookies as _cookies
from route_handlers.admin import dashboard as _dashboard
from route_handlers.admin import gifts as _gifts
from route_handlers.admin import guards as _guards
from route_handlers.admin import users as _users

__all__ = ["admin_bp", "internal_bp", "main_bp"]
