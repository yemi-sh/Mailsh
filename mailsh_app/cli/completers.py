"""
Dynamic tab completion for Mailsh commands.

This module provides intelligent context-aware tab completion for commands,
arguments, file paths, and dynamic data like profile names and templates.

CRITICAL: BEFORE MODIFYING THIS FILE, YOU ARE STRICTLY REQUIRED TO HAVE FIRST READ THE ./completers_guidelines.md FILE!!
"""

import os
import shlex
from typing import List, Dict, Any, Callable, Optional

from prompt_toolkit.completion import Completer, PathCompleter, WordCompleter
from prompt_toolkit.document import Document

# Module-level constants
KNOWN_COMMANDS = {
    "profile",
    "draft",
    "set",
    "unset",
    "send",
    "template",
    "config",
    "history",
    "schedule",
    "contacts",
    "task",
    "help",
    "exit",
    "quit",
}

COMMON_COUNTS = ["5", "10", "20", "50", "100"]
STATUS_OPTIONS = ["cancelled", "failed", "sent"]
TASK_CLEAN_OPTIONS = ["ended", "completed", "failed", "interrupted"]
FIELD_SUGGESTIONS = [
    "to",
    "cc",
    "bcc",
    "subject",
    "body",
    "header",
    "html",
    "attachment",
]
TEMPLATE_FLAGS = ["--html", "--text"]
BOOL_KEYS = {
    "bulk_send.continue_on_error",
    "validation.check_email_format",
    "validation.check_dns_mx",
    "tracking.request_read_receipt",
    "logging.save_sent_emails",
    "safety_features.enabled",
}
LOG_LEVELS = ["DEBUG", "INFO"]


def extract_config_keys_recursive(config_dict, parent_key=''):
    """Extract all possible config keys from a nested config dictionary."""
    keys = []
    for key, value in config_dict.items():
        full_key = f'{parent_key}.{key}' if parent_key else key
        if isinstance(value, dict):
            keys.extend(extract_config_keys_recursive(value, full_key))
        else:
            keys.append(full_key)
    return keys


class PositionTracker:
    """Tracks current position in command input accurately."""
    
    def __init__(self, text: str):
        self.text = text
        self.parts = self._split_parts(text)
        self.has_trailing_space = text.endswith(' ') and len(text) > 0
        
    def _split_parts(self, text: str) -> List[str]:
        """Split text into shell-like parts, fall back to simple split on error."""
        try:
            return shlex.split(text)
        except Exception:
            return text.split()
    
    def current_position(self) -> int:
        """Return 0-indexed position user is currently typing.
        
        If trailing space exists, user is starting next position.
        Otherwise, user is completing current position.
        """
        if self.has_trailing_space:
            return len(self.parts)
        else:
            return max(0, len(self.parts) - 1)
    
    def current_token(self) -> str:
        """Return the token being typed at current position."""
        if self.has_trailing_space:
            return ""
        return self.parts[-1] if self.parts else ""
    
    def is_at_terminal(self, terminal_pos: Optional[int]) -> bool:
        """Check if we've reached terminal position."""
        if terminal_pos is None:
            return False
        return self.current_position() > terminal_pos
    
    def get_part(self, index: int, default: str = "") -> str:
        """Safely get a part by index."""
        if 0 <= index < len(self.parts):
            return self.parts[index]
        return default


class DynamicCompleter(Completer):
    """A completer that dynamically selects the appropriate completer based on input"""

    def __init__(self, mailsh_instance):
        self.mailsh = mailsh_instance
        self._path_completer = PathCompleter(expanduser=True)
        self._init_command_positions()

    def _init_command_positions(self):
        """Initialize command position specifications."""
        # Import Config here to avoid circular imports
        try:
            from ...core.config import Config
        except ImportError:
            from mailsh_app.core.config import Config
        
        all_config_keys = extract_config_keys_recursive(Config.DEFAULT_CONFIG)
        
        self.COMMAND_POSITIONS = {
            # Simple commands
            
            "disconnect": {
                "type": "simple",
                "positions": [],
                "terminal": -1  # No arguments
            },
            
            "compose": {
                "type": "simple",
                "positions": [],
                "terminal": -1
            },
            
            "preview": {
                "type": "simple",
                "positions": [],
                "terminal": -1
            },
            
            "clear": {
                "type": "simple",
                "positions": [],
                "terminal": -1
            },
            
            "exit": {
                "type": "simple",
                "positions": [],
                "terminal": -1
            },
            
            "quit": {
                "type": "simple",
                "positions": [],
                "terminal": -1
            },
            
            "help": {
                "type": "simple",
                "positions": [
                    list(KNOWN_COMMANDS)
                ],
                "terminal": 1
            },
            
            "draft": {
                "type": "subcommand",
                "subcommands": {
                    "compose": {
                        "positions": [],
                        "terminal": 2
                    },
                    "preview": {
                        "positions": [],
                        "terminal": 2
                    },
                    "clear": {
                        "positions": [],
                        "terminal": 2
                    }
                }
            },

            # Subcommand-based commands
            "profile": {
                "type": "subcommand",
                "subcommands": {
                    "add": {
                        "positions": [],
                        "terminal": 2
                    },
                    "list": {
                        "positions": [],
                        "terminal": 2
                    },
                    "remove": {
                        "positions": [
                            lambda self: self.mailsh.profiles.list()
                        ],
                        "terminal": 3
                    },
                    "show": {
                        "positions": [
                            lambda self: self.mailsh.profiles.list()
                        ],
                        "terminal": 3
                    },
                    "connect": {
                        "positions": [
                            lambda self: self.mailsh.profiles.list()
                        ],
                        "terminal": 3
                    },
                    "disconnect": {
                        "positions": [],
                        "terminal": 2
                    },
                    "edit": {
                        "positions": [
                            lambda self: self.mailsh.profiles.list()
                        ],
                        "terminal": 3
                    }
                }
            },
            
            "config": {
                "type": "subcommand",
                "subcommands": {
                    "get": {
                        "positions": [
                            all_config_keys
                        ],
                        "terminal": 3  # config get <key> = 3 positions
                    },
                    "set": {
                        "positions": [
                            all_config_keys,
                            "_context_dependent_values"
                        ],
                        "terminal": 4  # config set <key> <value> = 4 positions
                    },
                    "show": {
                        "positions": [],
                        "terminal": -1
                    },
                    "reset": {
                        "positions": [
                            all_config_keys
                        ],
                        "terminal": 1  # After the first key, continue to allow more keys
                    }
                }
            },
            
            "template": {
                "type": "subcommand",
                "subcommands": {
                    "list": {
                        "positions": [],
                        "terminal": 2
                    },
                    "show": {
                        "positions": [
                            lambda self: self.mailsh.templates.list()
                        ],
                        "terminal": 3
                    },
                    "create": {
                        "positions": [],
                        "terminal": 2
                    },
                    "edit": {
                        "positions": [
                            lambda self: self.mailsh.templates.list()
                        ],
                        "terminal": 3
                    },
                    "delete": {
                        "positions": [
                            lambda self: self.mailsh.templates.list()
                        ],
                        "terminal": 3
                    },
                    "test": {
                        "positions": [
                            lambda self: self.mailsh.templates.list()
                        ],
                        "terminal": 3
                    },
                    "import": {
                        "positions": [
                            "_path",
                            TEMPLATE_FLAGS,
                            lambda self: self.mailsh.templates.list()
                        ],
                        "terminal": 5  # template import <path> <flag> <name> = 5 positions
                    }
                }
            },
            
            "set": {
                "type": "simple",
                "positions": [
                    FIELD_SUGGESTIONS  # Position 1: field name
                ],
                "flag_spec": {
                    "send": {
                        "flags": {
                            "--template": {
                                "value_provider": lambda self: self.mailsh.templates.list(),
                                "multi_value": False
                            },
                            "--contacts": {
                                "value_provider": lambda self: self.mailsh.contacts_manager.list_contacts(),
                                "multi_value": False
                            }
                        },
                        "terminal": 7  # set send --template <n> --contacts <n> = 7 max
                    },
                    "header": {
                        "positions": [
                            lambda self: list(self.mailsh.composer.headers.keys())
                        ],
                        "terminal": 3  # set header <name> = 3 positions
                    },
                    "attachment": {
                        "positions": [
                            "_path"
                        ],
                        "terminal": 3  # set attachment <path> = 3 positions
                    },
                    "html": {
                        "positions": [
                            ["true", "false"]
                        ],
                        "terminal": 3  # set html <bool> = 3 positions
                    }
                }
            },
            
            "unset": {
                "type": "simple",
                "positions": [
                    FIELD_SUGGESTIONS
                ],
                "flag_spec": {
                    "header": {
                        "positions": [
                            lambda self: list(self.mailsh.composer.headers.keys())
                        ],
                        "terminal": 3  # unset header <n> = 3 positions
                    },
                    "attachment": {
                        "positions": [
                            lambda self: [str(i) for i in range(len(self.mailsh.composer.attachments))]
                        ],
                        "terminal": 3  # unset attachment <index> = 3 positions
                    }
                }
            },
            
            "send": {
                "type": "subcommand",
                "subcommands": {
                    "bulk": {
                        "type": "flags",
                        "flags": {
                            "--contacts": {
                                "value_provider": lambda self: self.mailsh.contacts_manager.list_contacts(),
                                "multi_value": False
                            },
                            "--template": {
                                "value_provider": lambda self: self.mailsh.templates.list(),
                                "multi_value": False
                            },
                            "--dry-run": {
                                "value_provider": None,
                                "multi_value": False
                            }
                        },
                        "terminal": 6  # send bulk --contacts <n> --template <n> --dry-run
                    }
                },
                "flags": {
                    "--template": {
                        "value_provider": lambda self: self.mailsh.templates.list(),
                        "multi_value": False
                    }
                },
                "terminal": 3  # send --template <n>
            },
            
            "schedule": {
                "type": "subcommand",
                "subcommands": {
                    "send": {
                        "positions": [
                            None  # time_spec - user must type this, no completions
                        ],
                        "type": "flags",
                        "flags": {
                            "--template": {
                                "value_provider": lambda self: self.mailsh.templates.list(),
                                "multi_value": False
                            },
                            "--contacts": {
                                "value_provider": lambda self: self.mailsh.contacts_manager.list_contacts(),
                                "multi_value": False
                            }
                        },
                        "terminal": 7  # schedule send <time> --template <n> --contacts <n> = 7 max
                    },
                    "list": {
                        "type": "flags",
                        "flags": {
                            "--top": {
                                "value_provider": COMMON_COUNTS,
                                "multi_value": False
                            },
                            "--bottom": {
                                "value_provider": COMMON_COUNTS,
                                "multi_value": False
                            },
                            "--all": {
                                "value_provider": None,
                                "multi_value": False
                            }
                        }
                    },
                    "show": {
                        "positions": [
                            lambda self: [email.id for email in self.mailsh.scheduled_manager.get_all()]
                        ],
                        "terminal": 1
                    },
                    "cancel": {
                        "positions": [
                            lambda self: [
                                email.id
                                for email in self.mailsh.scheduled_manager.get_all()
                                if getattr(email, "status", None) == "scheduled"
                            ]
                        ],
                        "type": "flags",
                        "flags": {
                            "--all": {
                                "value_provider": None,
                                "multi_value": False
                            }
                        },
                        "terminal": 1
                    },
                    "clear": {
                        "type": "flags",
                        "flags": {
                            "--status": {
                                "value_provider": STATUS_OPTIONS,
                                "multi_value": False
                            }
                        }
                    }
                }
            },
            
            "history": {
                "type": "subcommand",
                "subcommands": {
                    "list": {
                        "type": "flags",
                        "flags": {
                            "--top": {
                                "value_provider": COMMON_COUNTS,
                                "multi_value": False
                            },
                            "--bottom": {
                                "value_provider": COMMON_COUNTS,
                                "multi_value": False
                            },
                            "--all": {
                                "value_provider": None,
                                "multi_value": False
                            },
                            "--status": {
                                "value_provider": ["sent", "failed"],
                                "multi_value": False
                            },
                            "--profile": {
                                "value_provider": lambda self: self.mailsh.profiles.list(),
                                "multi_value": False
                            },
                            "--recipient": {
                                "value_provider": None,
                                "multi_value": False
                            },
                            "--subject": {
                                "value_provider": None,
                                "multi_value": False
                            },
                            "--from": {
                                "value_provider": None,
                                "multi_value": False
                            },
                            "--to": {
                                "value_provider": None,
                                "multi_value": False
                            }
                        }
                    },
                    "show": {
                        "positions": [],
                        "terminal": -1
                    },
                    "stats": {
                        "positions": [],
                        "terminal": -1
                    }
                }
            },
            
            "contacts": {
                "type": "subcommand",
                "subcommands": {
                    "import": {
                        "positions": [
                            "_path"
                        ],
                        "type": "flags",
                        "flags": {
                            "--name": {
                                "value_provider": lambda self: (
                                    self.mailsh.contacts_manager.list_contacts() +
                                    [self.mailsh.contacts_manager.generate_random_name()]
                                ),
                                "multi_value": False
                            }
                        },
                        "terminal": 5  # contacts import <path> --name <n> = 5 max
                    },
                    "update": {
                        "positions": [
                            lambda self: self.mailsh.contacts_manager.list_contacts(),
                            "_path"
                        ],
                        "terminal": 4  # contacts update <contact> <path> = exactly 4
                    },
                    "preview": {
                        "positions": [
                            lambda self: self.mailsh.contacts_manager.list_contacts()
                        ],
                        "type": "flags",
                        "flags": {
                            "--limit": {
                                "value_provider": COMMON_COUNTS,
                                "multi_value": False
                            }
                        },
                        "terminal": 5  # contacts preview <contact> --limit <n> = 5 max
                    },
                    "validate": {
                        "positions": [
                            lambda self: self.mailsh.contacts_manager.list_contacts()
                        ],
                        "type": "flags",
                        "flags": {
                            "--mx": {
                                "value_provider": None,
                                "multi_value": False
                            }
                        },
                        "terminal": 4  # contacts validate <contact> --mx = 4 max
                    },
                    "list": {
                        "positions": [],
                        "terminal": -1
                    },
                    "remove": {
                        "positions": [
                            lambda self: self.mailsh.contacts_manager.list_contacts()
                        ],
                        "terminal": 1
                    }
                }
            },
            
            "task": {
                "type": "subcommand",
                "subcommands": {
                    "list": {
                        "positions": [],
                        "terminal": 2
                    },
                    "show": {
                        "positions": [
                            lambda self: [task.id for task in self.mailsh.task_manager.get_all_tasks()]
                        ],
                        "terminal": 3
                    },
                    "watch": {
                        "positions": [
                            lambda self: [
                                task.id
                                for task in self.mailsh.task_manager.get_all_tasks()
                                if task.status.value in ["running", "paused"]
                            ]
                        ],
                        "terminal": 3
                    },
                    "pause": {
                        "positions": [
                            lambda self: [
                                task.id
                                for task in self.mailsh.task_manager.get_all_tasks()
                                if task.status.value == "running"
                            ]
                        ],
                        "type": "flags",
                        "flags": {
                            "--all": {
                                "value_provider": None,
                                "multi_value": False
                            }
                        },
                        "terminal": 3
                    },
                    "resume": {
                        "positions": [
                            lambda self: [
                                task.id
                                for task in self.mailsh.task_manager.get_all_tasks()
                                if task.status.value in ["paused", "interrupted"]
                            ]
                        ],
                        "type": "flags",
                        "flags": {
                            "--all": {
                                "value_provider": None,
                                "multi_value": False
                            }
                        },
                        "terminal": 3
                    },
                    "end": {
                        "positions": [
                            lambda self: [
                                task.id
                                for task in self.mailsh.task_manager.get_all_tasks()
                                if task.status.value in ["running", "paused"]
                            ]
                        ],
                        "type": "flags",
                        "flags": {
                            "--all": {
                                "value_provider": None,
                                "multi_value": False
                            }
                        },
                        "terminal": 3
                    },
                    "clean": {
                        "positions": [
                            TASK_CLEAN_OPTIONS
                        ],
                        "terminal": 3
                    }
                }
            }
        }

    async def _path_completions_async(self, current_arg: str, complete_event):
        """Yield path completions for the provided current_arg asynchronously."""
        arg_document = Document(current_arg, len(current_arg))
        async for completion in self._path_completer.get_completions_async(
            arg_document, complete_event
        ):
            yield completion

    async def _yield_words_async(self, words: List[str], document, complete_event):
        """Yield word completions asynchronously."""
        wc = WordCompleter(words, ignore_case=True, WORD=True)
        async for completion in wc.get_completions_async(document, complete_event):
            yield completion

    def _flagish(self, current_arg: str) -> bool:
        """Return True when the user is likely typing a flag."""
        if not current_arg:
            return True
        return current_arg.startswith("-")

    async def _complete_by_position(
        self,
        spec: Dict[str, Any],
        tracker: PositionTracker,
        document,
        complete_event,
        position_offset: int = 0,
        original_tracker: Optional[PositionTracker] = None
    ):
        """Core engine: yield completions based on position spec.
        
        Args:
            spec: Position specification dict
            tracker: Position tracker (may be adjusted for subcommands)
            document: Document for completions
            complete_event: Completion event
            position_offset: Offset for position calculation
            original_tracker: Original tracker with full command context (for context-dependent values)
        """
        if original_tracker is None:
            original_tracker = tracker
            
        current_pos = tracker.current_position() - position_offset
        
        # Check terminal condition first
        if tracker.is_at_terminal(spec.get("terminal")):
            return
        
        # Get position handler
        positions = spec.get("positions", [])
        if current_pos < 0 or current_pos >= len(positions):
            # Check if this command has flag support
            if spec.get("type") == "flags" or "flags" in spec:
                async for completion in self._complete_flags(
                    spec, original_tracker, document, complete_event, position_offset
                ):
                    yield completion
            return
        
        position_handler = positions[current_pos]
        
        # Handle None position (user must type manually, no completions)
        if position_handler is None:
            return
        
        # Handle different position types
        if position_handler == "_path":
            # File path completion
            async for completion in self._path_completions_async(
                tracker.current_token(), complete_event
            ):
                yield completion
        
        elif position_handler == "_context_dependent_values":
            # Special case: values depend on previous position
            async for completion in self._complete_context_dependent(
                original_tracker, document, complete_event, 0
            ):
                yield completion
        
        elif callable(position_handler):
            # Dynamic completion (e.g., lambda to get profile names)
            suggestions = position_handler(self)
            async for completion in self._yield_words_async(
                suggestions, document, complete_event
            ):
                yield completion
        
        elif isinstance(position_handler, list):
            # Static list of options
            async for completion in self._yield_words_async(
                position_handler, document, complete_event
            ):
                yield completion

    async def _complete_context_dependent(
        self,
        tracker: PositionTracker,
        document,
        complete_event,
        position_offset: int = 0
    ):
        """Handle values that depend on previous position (e.g., config set values)."""
        
        # For 'config set': command=0, subcommand=1, key=2, value=3
        # So when position_offset=0 and we're at adjusted position 1 (value position),
        # we need to look at adjusted position 0 (key position)
        
        # Get the actual parts after offset
        actual_parts = tracker.parts[position_offset:] if position_offset > 0 else tracker.parts
        
        # For 'config set', actual_parts would be ['config', 'set', 'key', 'value']
        # We need to check if first part is 'config' and second is 'set'
        if len(actual_parts) >= 3 and actual_parts[0] == "config" and actual_parts[1] == "set":
            key = actual_parts[2]
            
            # Determine values based on key
            if key in BOOL_KEYS:
                suggestions = ["true", "false"]
            elif key == "logging.level":
                suggestions = LOG_LEVELS
            elif key == "editor":
                suggestions = ["nano", "vim", "vi", "emacs", "gedit", "code", "subl", "atom", "notepad"]
            elif key == "encoding":
                suggestions = ["utf-8", "latin-1", "ascii", "iso-8859-1"]
            elif key.startswith("syntax_highlighting.") or key.startswith("prompt.color"):
                suggestions = ["#00d7ff", "#d700ff", "#ffffff", "#000000", "#ff0000", "#00ff00", "#0000ff"]
            elif key.endswith(".emails_per_minute") or key.endswith(".emails_per_hour") or key.endswith(".delay_between_emails_ms"):
                suggestions = [str(i) for i in [1, 5, 10, 20, 50, 100, 500, 1000]]
            elif key.endswith(".parallel_connections") or key.endswith(".retry_attempts") or key.endswith(".retry_delay_seconds"):
                suggestions = [str(i) for i in [1, 2, 3, 4, 5, 10]]
            elif key.endswith(".max_attachment_size_mb"):
                suggestions = [str(i) for i in [1, 5, 10, 25, 50, 100, 250, 500, 1024]]
            else:
                # For any other config key, no default suggestions
                suggestions = []
            
            async for completion in self._yield_words_async(
                suggestions, document, complete_event
            ):
                yield completion

    async def _complete_flags(
        self,
        spec: Dict[str, Any],
        tracker: PositionTracker,
        document,
        complete_event,
        position_offset: int = 0
    ):
        """Handle flag-based completion."""
        current_token = tracker.current_token()
        
        # Check terminal for this specific flag context
        # CRITICAL: Terminal values in specs are defined relative to subcommand context,
	# but tracker.current_position() returns absolute positions in the full command.
	# We must add position_offset to terminal to correctly compare these values.
	# Example: For "schedule cancel --" where terminal=1 and position_offset=2:
	#   - tracker.current_position() = 2 (absolute: command + subcommand)
	#   - terminal = 1 (relative: one arg after subcommand)
	#   - Correct check: 2 >= (1 + 2) = False ✓ (allows flag completion)
	# Without offset: 2 >= 1 = True ✗ (incorrectly blocks flag completion)
        terminal = spec.get("terminal")
        if terminal is not None and tracker.current_position() >= (terminal + position_offset):
            return
        
        # Determine which flag spec to use
        flag_spec = spec.get("flags", {})
        if "flag_spec" in spec:
            # Check if we have a specific context (like 'send' in 'set send')
            context_key = tracker.get_part(position_offset)
            if context_key in spec["flag_spec"]:
                context_spec = spec["flag_spec"][context_key]
                
                # Check terminal for this specific context
                context_terminal = context_spec.get("terminal")
                if context_terminal is not None and tracker.current_position() >= context_terminal:
                    return
                
                if "flags" in context_spec:
                    flag_spec = context_spec["flags"]
                elif "positions" in context_spec:
                    # Handle positional arguments within flag context
                    adjusted_tracker = PositionTracker(tracker.text)
                    adjusted_tracker.parts = tracker.parts[position_offset + 1:]
                    adjusted_tracker.has_trailing_space = tracker.has_trailing_space
                    
                    # Calculate position within this context
                    context_pos = adjusted_tracker.current_position()
                    positions = context_spec.get("positions", [])
                    
                    # If within positional range and not typing a flag
                    if context_pos < len(positions) and not adjusted_tracker.current_token().startswith("-"):
                        async for completion in self._complete_by_position(
                            context_spec, adjusted_tracker, document, complete_event, 0
                        ):
                            yield completion
                        return
                    
                    # After positions, check for flags in this context
                    if "flags" in context_spec:
                        flag_spec = context_spec["flags"]
                    else:
                        return
        
        # Check if we're completing a flag value
        if len(tracker.parts) >= 2:
            prev_token = tracker.parts[-2] if not tracker.has_trailing_space else tracker.parts[-1]
            if prev_token.startswith("--") and prev_token in flag_spec:
                flag_info = flag_spec[prev_token]
                value_provider = flag_info.get("value_provider")
                
                if value_provider is not None:
                    if callable(value_provider):
                        suggestions = value_provider(self)
                    else:
                        suggestions = value_provider
                    
                    async for completion in self._yield_words_async(
                        suggestions, document, complete_event
                    ):
                        yield completion
                    return
                return
        
        # Suggest available flags
        # Modified to show flags when current token is empty (after space) as requested in the issue
        # This allows flag completions to appear automatically when a space is entered
        if self._flagish(current_token) or (not current_token and tracker.has_trailing_space):
            available_flags = list(flag_spec.keys())
            async for completion in self._yield_words_async(
                available_flags, document, complete_event
            ):
                yield completion

    async def _complete_with_subcommand(
        self,
        command_name: str,
        tracker: PositionTracker,
        document,
        complete_event
    ):
        """Generic handler for commands with subcommands."""
        
        spec = self.COMMAND_POSITIONS.get(command_name, {})
        
        if spec.get("type") != "subcommand":
            return
        
        # Position 1: subcommand selection or top-level flags
        if tracker.current_position() == 1:
            subcommands = list(spec["subcommands"].keys())
            async for completion in self._yield_words_async(
                subcommands, document, complete_event
            ):
                yield completion
            
            # Also complete top-level flags (e.g., send --template)
            if "flags" in spec:
                async for completion in self._complete_flags(
                    spec, tracker, document, complete_event, 1
                ):
                    yield completion
            return
        
        # Position 2+: delegate to subcommand spec
        if len(tracker.parts) < 2:
            return
        
        # Check if position 1 contains a flag instead of a subcommand
        if tracker.parts[1].startswith("--"):
            # We're in the top-level flags context (e.g., send --template)
            if "flags" in spec:
                async for completion in self._complete_flags(
                    spec, tracker, document, complete_event, 1
                ):
                    yield completion
            return
        
        subcommand = tracker.parts[1]
        if subcommand not in spec["subcommands"]:
            return
        
        subcommand_spec = spec["subcommands"][subcommand]
        
        # Create adjusted tracker (remove command + subcommand)
        adjusted_tracker = PositionTracker(tracker.text)
        adjusted_tracker.parts = tracker.parts[2:]
        adjusted_tracker.has_trailing_space = tracker.has_trailing_space
        
        # First try positional completions
        positions = subcommand_spec.get("positions", [])
        current_pos = adjusted_tracker.current_position()
        
        # If we're within the positional range, handle positions first
        if current_pos < len(positions) and not adjusted_tracker.current_token().startswith("-"):
            # If there's a trailing space, we want to provide BOTH positional and flag completions
            async for completion in self._complete_by_position(
                subcommand_spec, adjusted_tracker, document, complete_event, 0, tracker
            ):
                yield completion
            
            # If there's a trailing space after a positional argument, also offer flags
            if tracker.has_trailing_space and "flags" in subcommand_spec:
                async for completion in self._complete_flags(
                    subcommand_spec, tracker, document, complete_event, 2
                ):
                    yield completion
            return
        
        # After positional args or when typing a flag, handle flags
        if "flags" in subcommand_spec:
            async for completion in self._complete_flags(
                subcommand_spec, tracker, document, complete_event, 2
            ):
                yield completion

    def _iter_system_commands(self, prefix: str) -> List[str]:
        """Return list of executable names in PATH matching prefix"""
        paths = os.environ.get("PATH", "").split(os.pathsep)
        seen = set()
        matches = []
        for p in paths:
            try:
                for name in os.listdir(p):
                    if name in seen:
                        continue
                    full = os.path.join(p, name)
                    if os.path.isfile(full) and os.access(full, os.X_OK):
                        seen.add(name)
                        if not prefix or name.startswith(prefix):
                            matches.append(name)
            except Exception:
                continue
        return matches

    def get_completions(self, document, complete_event):
        """Synchronous completion is intentionally unsupported."""
        raise RuntimeError(
            "Synchronous completion path removed; use get_completions_async() instead."
        )

    async def get_completions_async(self, document, complete_event):
        text = document.text_before_cursor

        # Handle system commands (starting with .)
        if text.startswith("."):
            after_dot = text[1:]
            
            is_completing_command = not after_dot or not any(
                c in after_dot for c in [" ", "\t"]
            )

            if is_completing_command:
                try:
                    parts = shlex.split(after_dot)
                except Exception:
                    parts = after_dot.split()
                    
                prefix = parts[0] if parts else ""
                suggestions = self._iter_system_commands(prefix)
                async for completion in self._yield_words_async(
                    suggestions, document, complete_event
                ):
                    yield completion
            else:
                # Complete file paths after command
                last_space_pos = text.rfind(" ")
                current_arg = text[last_space_pos + 1:] if last_space_pos != -1 else ""
                async for completion in self._path_completions_async(
                    current_arg, complete_event
                ):
                    yield completion
            return

        # Create position tracker
        tracker = PositionTracker(text)
        
        if not tracker.parts:
            # No command yet, suggest all commands
            async for completion in self._yield_words_async(
                list(KNOWN_COMMANDS), document, complete_event
            ):
                yield completion
            return
        
        command = tracker.parts[0]
        
        # If user is still typing the first word (no space yet), suggest matching commands
        if tracker.current_position() == 0 and not tracker.has_trailing_space:
            matching_commands = [cmd for cmd in KNOWN_COMMANDS if cmd.startswith(command.lower())]
            if matching_commands:
                async for completion in self._yield_words_async(
                    matching_commands, document, complete_event
                ):
                    yield completion
                return
        
        # Check if command exists in our position specs
        if command not in self.COMMAND_POSITIONS:
            return  # Unknown command, no completions
        
        spec = self.COMMAND_POSITIONS[command]
        
        # Route to appropriate handler based on command type
        if spec.get("type") == "subcommand":
            async for completion in self._complete_with_subcommand(
                command, tracker, document, complete_event
            ):
                yield completion
        
        elif spec.get("type") == "simple":
            # For simple commands, first handle positional completions
            positions = spec.get("positions", [])
            current_pos = tracker.current_position() - 1  # Offset for command itself
            
            # Check if we're in a flag_spec context first (like 'send bulk')
            if "flag_spec" in spec and len(tracker.parts) >= 2:
                context_key = tracker.parts[1]
                if context_key in spec["flag_spec"]:
                    # We're in a specific context (e.g., 'send bulk')
                    async for completion in self._complete_flags(
                        spec, tracker, document, complete_event, 1
                    ):
                        yield completion
                    return
            
            # If we're within positional range and not typing a flag
            if current_pos >= 0 and current_pos < len(positions) and not tracker.current_token().startswith("-"):
                async for completion in self._complete_by_position(
                    spec, tracker, document, complete_event, 1
                ):
                    yield completion
                return
            
            # Then handle flags if available
            if "flags" in spec or "flag_spec" in spec:
                async for completion in self._complete_flags(
                    spec, tracker, document, complete_event, 1
                ):
                    yield completion
