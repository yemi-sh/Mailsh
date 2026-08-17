"""
Utilities for Mailsh.

This module provides re-exports for common utility functions
to make them easily importable from the utils package.
"""

from .paths import get_config_dir
from .email_parser import extract_body
from .validators import (
    is_email,
    normalize_email,
    validate_port,
    validate_security_mode,
    is_hostname_or_ip,
    safe_resolve_path,
    validate_attachment,
    filesize_mb,
)

__all__ = [
    'get_config_dir',
    'extract_body',
    'is_email',
    'normalize_email',
    'validate_port',
    'validate_security_mode',
    'is_hostname_or_ip',
    'safe_resolve_path',
    'validate_attachment',
    'filesize_mb',
]