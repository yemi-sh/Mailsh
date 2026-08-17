"""
Core modules for Mailsh.

This module provides re-exports for core classes
to make them easily importable from the core package.
"""

from .config import Config
from .profile import Profile
from .composer import EmailComposer
from .sender import EmailSender
from .history import History
from .state_manager import CommandStateManager, ConfirmationRequest, ExecutionMode, MCPError, InvalidTokenError, CommandExecutionError, StateManagerError

__all__ = [
    'Config',
    'Profile',
    'EmailComposer',
    'EmailSender',
    'History',
    'CommandStateManager',
    'ConfirmationRequest',
    'ExecutionMode',
    'MCPError',
    'InvalidTokenError',
    'CommandExecutionError',
    'StateManagerError',
]