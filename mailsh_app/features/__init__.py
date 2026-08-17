"""
Feature modules for Mailsh.

This module provides re-exports for feature classes
to make them easily importable from the features package.
"""

from .templates import TemplateEngine
from .scheduler import ScheduledEmail, ScheduleManager
from .contacts import ContactsManager

__all__ = [
    'TemplateEngine',
    'ScheduledEmail',
    'ScheduleManager',
    'ContactsManager',
]