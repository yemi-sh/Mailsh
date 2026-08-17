"""
CLI modules for Mailsh.

This module provides re-exports for CLI classes
to make them easily importable from the cli package.
"""

from .shell import Mailsh

__all__ = [
    'Mailsh',
]