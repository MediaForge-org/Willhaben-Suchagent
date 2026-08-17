"""Single source of truth for the application version.

Kept as a plain constant (not read from installed package metadata) so it works
identically from a source checkout, a venv install, and a PyInstaller-frozen
binary, where ``importlib.metadata`` lookups can be unreliable.
"""

__version__ = "1.0.0"
