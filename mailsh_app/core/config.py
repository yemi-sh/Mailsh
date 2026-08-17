"""
Configuration management for Mailsh.

This module handles loading, saving, and validating configuration settings
including rate limiting, bulk send options, validation rules, and more.
"""

import json
import copy
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple


class Config:
    """Configuration manager"""
    
    DEFAULT_CONFIG = {
        "rate_limiting": {
            "delay_between_emails_ms": 3000
        },
        "bulk_send": {
            "parallel_connections": 1,
            "retry_attempts": 3,
            "retry_delay_seconds": 5,
            "continue_on_error": True
        },
        "validation": {
            "check_email_format": True,
            "check_dns_mx": False,
            "max_attachment_size_mb": 25
        },
        "logging": {
            "level": "INFO",
            "save_sent_emails": True
        },
        "tracking": {
            "request_read_receipt": False
        },
        "editor": "nano",
        "encoding": "utf-8",
        "syntax_highlighting": {
            "commands": "#00d7ff",  # Cyan
            "flags": "#d700ff",    # Magenta
            "default": "#ffffff"   # White
        },
        "prompt": {
            "color": "#00d7ff bold",  # Cyan bold (same as default)
            "text": "[Mailsh]"        # Default prompt text
        },
        "safety_features": {
            "enabled": True
        }
    }
    
    def __init__(self, config_dir: Path):
        self.config_dir = config_dir
        self.config_file = config_dir / "config.json"
        self.data = self.load()
    
    def load(self) -> Dict:
        # Start from a deep copy of defaults to avoid shared nested state
        data = copy.deepcopy(self.DEFAULT_CONFIG)
        if self.config_file.exists():
            with open(self.config_file, 'r') as f:
                try:
                    loaded = json.load(f)
                except Exception:
                    loaded = {}
            data = self._deep_merge(data, loaded)
        return data
    
    def save(self):
        with open(self.config_file, 'w') as f:
            json.dump(self.data, f, indent=2)
    
    def get(self, key: str) -> Any:
        keys = key.split('.')
        value = self.data
        for k in keys:
            value = value.get(k)
            if value is None:
                return None
        return value
    
    def set(self, key: str, value: Any):
        keys = key.split('.')
        data = self.data
        for k in keys[:-1]:
            if k not in data or not isinstance(data[k], dict):
                data[k] = {}
            data = data[k]
        data[keys[-1]] = value
        self.save()

    def set_from_string(self, key: str, value_str: str) -> tuple:
        """Set a config value using a string, coercing to expected type.
        Returns (success: bool, message: str).
        """
        expected_type = self._expected_type_for_key(key)

        # If expected type is unknown, the key is invalid
        if expected_type is None:
            return (False, f"Invalid configuration key: {key}")

        try:
            coerced = self._coerce_value(expected_type, value_str, key)
        except ValueError as e:
            return (False, f"Invalid value for {key}. Expected {expected_type.__name__}: {e}")

        self.set(key, coerced)
        return (True, f"Set {key} = {json.dumps(coerced)}")

    def reset(self):
        # Deep reset to pristine defaults
        self.data = copy.deepcopy(self.DEFAULT_CONFIG)
        self.save()

    def _deep_merge(self, base: Dict, override: Dict) -> Dict:
        """Deep merge override into base (mutates and returns base)."""
        for k, v in (override or {}).items():
            if isinstance(v, dict) and isinstance(base.get(k), dict):
                self._deep_merge(base[k], v)
            else:
                base[k] = v
        return base

    def _expected_type_for_key(self, key: str):
        """Return the expected Python type for a config key based on DEFAULT_CONFIG."""
        keys = key.split('.')
        node = self.DEFAULT_CONFIG
        for k in keys:
            if not isinstance(node, dict) or k not in node:
                return None
            node = node[k]
        # For leaf values, infer type by current default
        return type(node)

    def _coerce_value(self, expected_type, value_str: str, key: Optional[str] = None):
        # Special-case validation for specific keys
        if key == 'logging.level':
            val = value_str.strip().upper()
            allowed = {'DEBUG', 'INFO'}
            if val not in allowed:
                raise ValueError(f"allowed values: {', '.join(sorted(allowed))}")
            return val

        if expected_type is bool:
            normalized = value_str.strip().lower()
            if normalized in ['true', 'yes', 'y', '1']:
                return True
            if normalized in ['false', 'no', 'n', '0']:
                return False
            raise ValueError("accepted: true/false/yes/no/1/0")
        if expected_type is int:
            val = int(value_str.strip())
            # sensible range checks for known integer keys
            if key and key.endswith('delay_between_emails_ms'):
                if val < 0 or val > 60_000 * 60:
                    raise ValueError('delay_between_emails_ms out of range')
            if key and key.endswith('max_attachment_size_mb'):
                if val <= 0 or val > 1024:
                    raise ValueError('max_attachment_size_mb must be 1-1024')
            return val
        if expected_type is float:
            return float(value_str.strip())
        if expected_type is str:
            return value_str
        # Fallback: try JSON for complex types (lists/dicts)
        try:
            return json.loads(value_str)
        except Exception:
            raise ValueError("invalid JSON for complex type")
    
    def get_default(self, key: str) -> Any:
        """Get the default value for a specific config key based on DEFAULT_CONFIG."""
        keys = key.split('.')
        value = self.DEFAULT_CONFIG
        for k in keys:
            if not isinstance(value, dict) or k not in value:
                return None
            value = value[k]
        return value

    def reset(self, keys=None):
        """
        Reset configuration to defaults.

        Args:
            keys: Optional list of specific keys to reset. If None, resets all configuration.
        """
        if keys is None:
            # Full reset to pristine defaults
            self.data = copy.deepcopy(self.DEFAULT_CONFIG)
        else:
            # Reset only specific keys
            for key in keys:
                self._reset_single_key(key)

        self.save()

    def _reset_single_key(self, key: str):
        """Reset a single configuration key to its default value."""
        keys = key.split('.')
        current_data = self.data
        current_defaults = self.DEFAULT_CONFIG

        # Navigate to the parent of the target key
        for k in keys[:-1]:
            if k not in current_data or not isinstance(current_data[k], dict):
                current_data[k] = {}
            current_data = current_data[k]

            if k not in current_defaults or not isinstance(current_defaults[k], dict):
                raise KeyError(f"Default configuration does not contain key: {key}")
            current_defaults = current_defaults[k]

        # Get the final key
        final_key = keys[-1]

        # Check if the final key exists in defaults
        if final_key not in current_defaults:
            raise KeyError(f"Default configuration does not contain key: {key}")

        # Set the key to its default value
        current_data[final_key] = copy.deepcopy(current_defaults[final_key])
