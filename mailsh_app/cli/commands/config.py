"""
Configuration management commands.

Commands: config (show/get/set/reset)
"""

from typing import Dict, List, Optional, Any
import json
from ...utils.validators import (
    is_email,
    normalize_email,
    validate_port,
    validate_security_mode,
    is_hostname_or_ip,
    safe_resolve_path,
    validate_attachment,
    filesize_mb,
)
from ...core.config import Config
from ...core.profile import Profile
from ...core.history import History
from ...features.templates import TemplateEngine
from ...core.composer import EmailComposer
from ...features.scheduler import ScheduleManager
from ...features.contacts import ContactsManager


class ConfigCommands:
    """Mixin class providing configuration-related commands."""
    
    def cmd_config(self, args: List[str]):
        """Configuration management"""
        if not args:
            self._print("Usage: config <get|set|show|reset>", "error")
            self._print("Type 'help config' for more information", "info")
            return
        
        action = args[0]
        
        import json
        if action == "show":
            print(json.dumps(self.config.data, indent=2))
        
        elif action == "get":
            if len(args) < 2:
                self._print("Usage: config get <key>", "error")
                return
            
            key = args[1]
            value = self.config.get(key)
            if value is not None:
                import json
                print(f"{key} = {json.dumps(value, indent=2)}")
            else:
                self._print(f"Config key not found: {key}", "error")
        
        elif action == "set":
            if len(args) < 3:
                self._print("Usage: config set <key> <value>", "error")
                return

            key = args[1]
            value_str = ' '.join(args[2:])

            # Remove support for 'default' as a special value (use config reset instead)
            if value_str.lower() == 'default':
                self._print(f"Setting to 'default' is no longer supported. Use 'config reset {key}' instead.", "error")
                return

            # Special handling for syntax highlighting colors
            if key.startswith('syntax_highlighting.'):
                if 'commands' in key or 'flags' in key or 'default' in key:
                    # Validate color format (should be in #RRGGBB format)
                    if not self._is_valid_color(value_str):
                        self._print(f"Invalid color format: {value_str}. Use #RRGGBB format (e.g., #00d7ff)", "error")
                        return

            # Special handling for prompt color
            if key.startswith('prompt.color'):
                # Validate color format (should be in #RRGGBB format, possibly with modifiers)
                if not self._is_valid_color_with_modifiers(value_str):
                    self._print(f"Invalid color format: {value_str}. Use #RRGGBB format (e.g., #00d7ff) with optional modifiers like 'bold', 'italic'", "error")
                    return

            # Check if prompt color is being updated
            is_prompt_color = key.startswith('prompt.color')

            success, message = self.config.set_from_string(key, value_str)
            if success:
                # Special handling for syntax highlighting colors
                if key.startswith('syntax_highlighting.'):
                    if 'commands' in key or 'flags' in key or 'default' in key:
                        # Validate color format (should be in #RRGGBB format)
                        if not self._is_valid_color(value_str):
                            self._print(f"Invalid color format: {value_str}. Use #RRGGBB format (e.g., #00d7ff)", "error")
                            return

                # Special handling for prompt color
                if key.startswith('prompt.color'):
                    # Validate color format (should be in #RRGGBB format, possibly with modifiers)
                    if not self._is_valid_color_with_modifiers(value_str):
                        self._print(f"Invalid color format: {value_str}. Use #RRGGBB format (e.g., #00d7ff) with optional modifiers like 'bold', 'italic'", "error")
                        return

                # Check if prompt color is being updated
                is_prompt_color = key.startswith('prompt.color')

                success, message = self.config.set_from_string(key, value_str)
                if success:
                    # If syntax highlighting settings changed, update the highlighter
                    if key.startswith('syntax_highlighting.'):
                        if hasattr(self, 'update_syntax_highlighter'):
                            self.update_syntax_highlighter()

                    # If prompt color changed, update the prompt style
                    if is_prompt_color:
                        if hasattr(self, 'update_prompt_style'):
                            self.update_prompt_style()

                    self._print(message, "success")
                else:
                    self._print(message, "error")
        
        elif action == "reset":
            if len(args) < 2:
                # Use universal confirmation method for full reset
                if not self.confirm_action(
                    "This will reset ALL configuration to defaults! Are you sure? (y/n): ",
                    context={"action": "config_reset"},
                    cancel_message="Reset cancelled"
                ):
                    return
                # Full reset
                self.config.reset()

                # Update syntax highlighter and prompt style after reset
                if hasattr(self, 'update_syntax_highlighter'):
                    self.update_syntax_highlighter()

                if hasattr(self, 'update_prompt_style'):
                    self.update_prompt_style()

                self._print("Configuration reset to defaults", "success")
            else:
                # Reset only specific keys
                keys_to_reset = args[1:]  # All arguments after 'reset' are keys to reset

                # Validate that all keys exist before proceeding
                invalid_keys = []
                for key in keys_to_reset:
                    if self.config.get_default(key) is None:
                        invalid_keys.append(key)

                if invalid_keys:
                    self._print(f"Invalid configuration keys: {', '.join(invalid_keys)}", "error")
                    return

                # Reset the specified keys
                for key in keys_to_reset:
                    try:
                        self.config._reset_single_key(key)

                        # Check if syntax highlighting settings changed
                        if key.startswith('syntax_highlighting.'):
                            if hasattr(self, 'update_syntax_highlighter'):
                                self.update_syntax_highlighter()

                        # Check if prompt settings changed
                        if key.startswith('prompt.'):
                            if hasattr(self, 'update_prompt_style'):
                                self.update_prompt_style()

                    except KeyError as e:
                        self._print(str(e), "error")
                        return

                self._print(f"Reset {len(keys_to_reset)} key(s) to defaults: {', '.join(keys_to_reset)}", "success")
        
        else:
            self._print(f"Unknown action: {action}", "error")
            self._print("Valid actions: get, set, show, reset", "info")

    def _is_valid_color(self, color_str: str) -> bool:
        """Check if color string is in valid #RRGGBB format."""
        import re
        pattern = r'^#[0-9a-fA-F]{6}$'
        return bool(re.match(pattern, color_str))

    def _is_valid_color_with_modifiers(self, color_str: str) -> bool:
        """Check if color string is in valid #RRGGBB format with optional modifiers."""
        import re
        # Remove modifiers like 'bold', 'italic', etc., from the string
        # Split by spaces and get the color part
        parts = color_str.strip().split()
        color_part = parts[0]  # First part should be the color
        
        # Check if the color part matches the valid format
        color_pattern = r'^#[0-9a-fA-F]{6}$'
        if not re.match(color_pattern, color_part):
            return False
            
        # Check remaining parts for valid modifiers
        modifiers = set(parts[1:])  # Get modifiers after the color
        valid_modifiers = {'bold', 'italic', 'underline', 'reverse', 'blink', 'blink2', 'dim', 'strike', 'hidden'}
        
        # All modifiers should be in the valid list
        return all(mod in valid_modifiers for mod in modifiers)