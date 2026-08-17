"""
Path utilities for Mailsh configuration management.

This module provides functions for locating and creating the centralized
configuration directory for Mailsh.
"""

from pathlib import Path


def get_config_dir() -> Path:
    """Get the centralized config directory path at ~/.config/mailsh"""
    config_dir = Path.home() / '.config' / 'mailsh'
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir