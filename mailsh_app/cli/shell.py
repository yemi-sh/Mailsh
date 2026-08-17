"""
Main Mailsh shell and command loop.

This module contains the primary Mailsh class that orchestrates all
functionality and provides the interactive command-line interface.
"""

import csv
import getpass
import glob
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import (
    Completer,
    NestedCompleter,
    PathCompleter,
    WordCompleter,
)
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style

from ..core import Config, EmailComposer, EmailSender, History, Profile
from ..core.tasks import TaskManager, TaskStatus
from ..features import ContactsManager, ScheduleManager, TemplateEngine
from ..features.safety import SafetyFeatureManager
from ..utils.email_parser import extract_body
from ..utils.paths import get_config_dir
from ..utils.syntax_highlighter import MailshSyntaxHighlighter
from ..utils.validators import (
    filesize_mb,
    is_email,
    is_hostname_or_ip,
    normalize_email,
    safe_resolve_path,
    validate_attachment,
    validate_port,
    validate_security_mode,
)
from .commands import (
    CompositionCommands,
    ConfigCommands,
    ConnectionCommands,
    ContactsCommands,
    DraftCommands,
    HistoryCommands,
    SendingCommands,
    TaskCommands,
    TemplateCommands,
)
from .completers import DynamicCompleter
from .help import CommandHelp


class Mailsh(
    ConnectionCommands,
    CompositionCommands,
    DraftCommands,
    SendingCommands,
    TemplateCommands,
    ContactsCommands,
    ConfigCommands,
    HistoryCommands,
    TaskCommands,
):
    """Main CLI application"""

    def __init__(self):
        self.config_dir = get_config_dir()

        self.config = Config(self.config_dir)
        self.profiles = Profile(self.config_dir)
        self.history = History(self.config_dir)
        self.templates = TemplateEngine(self.config_dir)
        self.composer = EmailComposer()
        self.scheduled_manager = ScheduleManager(self.config_dir)
        self.contacts_manager = ContactsManager(self.config_dir)
        # Initialize TaskCommands first to set up any necessary attributes
        TaskCommands.__init__(self)

        # Then create and set the TaskManager instance
        from ..core.tasks import TaskManager

        self.task_manager = TaskManager(self.config_dir)

        # Set up the notification callback for task completion
        self.task_manager.set_notification_callback(self._handle_task_completion)

        # Initialize notification system for right prompt
        self.notifications = []
        self.max_notifications = 3  # Maximum number of notifications to display

        # Initialize SafetyFeatureManager
        from ..features.safety import SafetyFeatureManager

        self.safety_manager = SafetyFeatureManager(
            self.config, self.profiles, self.templates
        )

        self.current_profile = None
        self.session_file = self.config_dir / "session.json"
        self.cwd = os.getcwd()  # Track current working directory
        self.last_cwd = self.cwd  # Track previous directory for 'cd -'

        # Load session
        self._load_session()

        # Setup prompt style with configurable color
        prompt_color = self.config.get("prompt.color") or "#00d7ff bold"
        self.style = Style.from_dict(
            {
                "prompt": prompt_color,
                "status": "#888888",
            }
        )

        # Initialize syntax highlighter
        self.syntax_highlighter = MailshSyntaxHighlighter(self.config)

        history_file = str(self.config_dir / "shell_history")

        # Key bindings for word-by-word autosuggestion acceptance
        kb = KeyBindings()

        @kb.add("c-right")
        def accept_suggestion_or_move_word(event):
            """Accept one word from the autosuggestion or move forward by word.

            This computes the remaining suggestion relative to the current
            cursor/text_after_cursor so that inserting the next suggested word
            doesn't duplicate or insert in the wrong place after cursor moves.
            """
            buffer = event.current_buffer
            suggestion = buffer.suggestion

            # If there's an autosuggestion, accept the next word of the remaining suggestion.
            if suggestion:
                try:
                    suggestion_text = suggestion.text or ""
                    doc = buffer.document
                    after = doc.text_after_cursor or ""

                    # If there's already text after the cursor, move over the next
                    # word in that text first (this is the expected Ctrl+Right behavior)
                    # before inserting any suggested tokens.
                    if after:
                        import re

                        m_after = re.match(r"\s*\S+", after)
                        if m_after:
                            buffer.cursor_position = doc.cursor_position + m_after.end()
                            return

                    # If the suggestion already contains the exact text after the cursor,
                    # don't insert the following token in front of it. Instead, move the
                    # cursor past that existing text so Ctrl+Right behaves like a word-step.
                    if after:
                        idx = suggestion_text.find(after)
                        if idx != -1:
                            # Move cursor to the end of the existing 'after' text.
                            buffer.cursor_position = doc.cursor_position + len(after)
                            return

                    # Align the suggestion to the text after the cursor.
                    remaining = suggestion_text
                    if after and suggestion_text.startswith(after):
                        remaining = suggestion_text[len(after) :]
                    else:
                        # If suggestion contains the after-text somewhere, align to the later occurrence.
                        idx = suggestion_text.find(after) if after else -1
                        if idx != -1:
                            remaining = suggestion_text[idx + len(after) :]

                    # If nothing remains, fall back to movement
                    if not remaining:
                        raise ValueError("no remaining suggestion")

                    # Find next word in the remaining suggestion
                    pos = 0
                    # skip leading whitespace
                    while pos < len(remaining) and remaining[pos] in " \t":
                        pos += 1
                    # consume next non-whitespace run (a word)
                    while pos < len(remaining) and remaining[pos] not in " \t":
                        pos += 1

                    if pos > 0:
                        buffer.insert_text(remaining[:pos])
                        return
                except Exception:
                    # fall through to movement behavior
                    pass

            # No usable suggestion -> robust word-forward movement
            try:
                import re

                doc = buffer.document
                abs_cursor = doc.cursor_position
                text = doc.text
                text_after = text[abs_cursor:]

                if not text_after:
                    return

                # Find the next run of non-whitespace and move to its end (word ending)
                m = re.search(r"\S+", text_after)
                if m:
                    new_pos = abs_cursor + m.end()
                else:
                    new_pos = len(text)

                # Clamp and ensure integer
                new_pos = max(0, min(len(text), int(new_pos)))
                if new_pos == abs_cursor and abs_cursor < len(text):
                    # nothing found, move at least one char forward
                    new_pos = abs_cursor + 1

                buffer.cursor_position = new_pos
            except Exception:
                # best-effort fallback: single-char forward
                try:
                    buffer.cursor_position = min(
                        len(buffer.document.text), buffer.document.cursor_position + 1
                    )
                except Exception:
                    pass

        @kb.add("c-left")
        def move_word_left(event):
            """Move cursor to the beginning of the previous word (robust fallback)."""
            buffer = event.current_buffer
            try:
                import re

                doc = buffer.document
                abs_cursor = doc.cursor_position
                text = doc.text
                text_before = text[:abs_cursor]

                if not text_before:
                    return

                # Find last run of non-whitespace before the cursor and go to its start
                matches = list(re.finditer(r"\S+", text_before))
                if matches:
                    m = matches[-1]
                    new_pos = m.start()
                else:
                    new_pos = 0

                new_pos = max(0, min(len(text), int(new_pos)))
                if new_pos == abs_cursor and abs_cursor > 0:
                    # ensure progress at least one char left
                    new_pos = abs_cursor - 1

                buffer.cursor_position = new_pos
            except Exception:
                try:
                    buffer.cursor_position = max(0, buffer.document.cursor_position - 1)
                except Exception:
                    pass

        self.session = PromptSession(
            history=FileHistory(history_file),
            auto_suggest=AutoSuggestFromHistory(),
            style=self.style,
            key_bindings=kb,
            lexer=self.syntax_highlighter,
        )

        # Unstyled session for interactive prompts (no colors)
        self.unstyled_session = PromptSession(
            history=FileHistory(history_file),
            auto_suggest=AutoSuggestFromHistory(),
            key_bindings=kb,
        )

        # Initialize notification system methods
        self._setup_notification_handlers()

        # Start real-time UI refresh
        self._start_ui_refresh_thread()

        # Enhanced command completer
        self._setup_completers()
        self.dynamic_completer = DynamicCompleter(self)

    def _setup_notification_handlers(self):
        """Set up notification handlers for task and schedule events"""
        # Add any necessary hooks for task/schedule notifications
        pass

    def _start_ui_refresh_thread(self):
        """Start background thread that keeps UI alive and responsive to background changes"""
        import threading
        import time
        self._ui_refresh_stop = threading.Event()

        def refresh_loop():
            while not self._ui_refresh_stop.is_set():
                time.sleep(1.0)  # 1 second is more than enough for this use-case
                try:
                    # app may not exist yet during startup – guard against it
                    if hasattr(self.session, "app") and self.session.app.is_running:
                        self.session.app.invalidate()
                except:
                    pass  # silently ignore if app gone (app exit)

        threading.Thread(target=refresh_loop, daemon=True).start()

    def _handle_task_completion(self, task_id, status, success_count, failed_count):
        """Handle task completion notification"""
        # Create the notification message for successful task completion
        if status.name == "COMPLETED":
            message = f"Task {task_id} completed ({success_count} success, {failed_count} failed)"
        elif status.name == "FAILED":
            message = f"Task {task_id} failed ({success_count} success, {failed_count} failed)"
        elif status.name == "ENDED":
            message = f"Task {task_id} ended ({success_count} success, {failed_count} failed)"
        else:
            # For other statuses, we can still display completion info
            message = f"Task {task_id} finished ({success_count} success, {failed_count} failed)"

        # Add the notification to the queue
        notification_type = "success" if status.name == "COMPLETED" else "warning"
        self.add_notification(message, notification_type)

    def add_notification(self, message: str, notification_type: str = "info", duration: float = 5.0):
        """Add a notification to the notification queue"""
        from datetime import datetime

        notification = {
            'message': message,
            'type': notification_type,
            'timestamp': datetime.now(),
            'duration': duration  # Duration in seconds
        }

        self.notifications.append(notification)

        # Keep only the most recent notifications
        if len(self.notifications) > self.max_notifications:
            self.notifications = self.notifications[-self.max_notifications:]

        # Immediate UI update when notification arrives from background thread
        try:
            if hasattr(self.session, "app") and self.session.app.is_running:
                self.session.app.invalidate()
        except:
            pass

    def _get_right_prompt(self):
        """Generate HTML-formatted right prompt showing notifications and current time"""
        from datetime import datetime, timedelta

        # Get current time in 24-hour format
        current_time = datetime.now()
        time_str = current_time.strftime("%H:%M:%S")

        # Filter out expired notifications
        self.notifications = [
            n for n in self.notifications
            if (current_time - n['timestamp']).total_seconds() < n['duration']
        ]

        # Build the right prompt with time and notifications
        if not self.notifications:
            # Show only the time if no notifications
            return HTML(f'<style fg="#808080">{time_str}</style>')

        # Get the most recent notification to show in the right prompt
        latest_notification = self.notifications[-1]
        message = latest_notification['message']

        # Style based on notification type
        if latest_notification['type'] == 'success':
            style = '#00ff00'  # Green color for success
        elif latest_notification['type'] == 'warning':
            style = '#ffff00'  # Yellow color for warning
        elif latest_notification['type'] == 'error':
            style = '#ff4444'  # Red color for error
        else:
            style = '#808080'  # Default gray color

        # Show notification first, then time
        return HTML(f'<style fg="{style}">{message}</style> <style fg="#808080">{time_str}</style>')

    def update_syntax_highlighter(self):
        """Update the syntax highlighter with new configuration."""
        if hasattr(self, "syntax_highlighter"):
            # The highlighter reads config values on each call, so we just need to ensure it's using the right config
            # The syntax highlighter will automatically use the updated config values
            pass

    def update_prompt_style(self):
        """Update the prompt style with new configuration."""
        prompt_color = self.config.get("prompt.color") or "#00d7ff bold"
        status_color = "#888888"  # Default status color, could make this configurable too if needed

        self.style = Style.from_dict(
            {
                "prompt": prompt_color,
                "status": status_color,
            }
        )

        # Update the session style
        self.session.style = self.style

    def _setup_completers(self):
        """Setup enhanced command completers"""
        # Get dynamic data for completion
        profile_names = self.profiles.list()
        template_names = self.templates.list()

        # Enhanced nested completion
        self.completer = NestedCompleter.from_nested_dict(
            {
                "connect": WordCompleter(profile_names, ignore_case=True),
                "profile": NestedCompleter.from_nested_dict(
                    {
                        "add": None,
                        "list": None,
                        "remove": WordCompleter(profile_names, ignore_case=True),
                        "show": WordCompleter(profile_names, ignore_case=True),
                        "connect": WordCompleter(profile_names, ignore_case=True),
                        "disconnect": None,
                        "edit": WordCompleter(profile_names, ignore_case=True),
                    }
                ),
                "draft": NestedCompleter.from_nested_dict(
                    {
                        "compose": None,
                        "preview": None,
                        "clear": None,
                    }
                ),
                "set": NestedCompleter.from_nested_dict(
                    {
                        "to": None,
                        "cc": None,
                        "bcc": None,
                        "subject": None,
                        "body": None,
                        "header": None,
                        "html": WordCompleter(
                            ["true", "false", "yes", "no", "y", "n", "1", "0"],
                            ignore_case=True,
                        ),
                        "attachment": PathCompleter(),
                    }
                ),
                "unset": NestedCompleter.from_nested_dict(
                    {
                        "to": None,
                        "cc": None,
                        "bcc": None,
                        "subject": None,
                        "body": None,
                        "header": None,
                        "html": None,
                        "attachment": None,
                    }
                ),
                "send": NestedCompleter.from_nested_dict(
                    {
                        "--template": WordCompleter(template_names, ignore_case=True),
                        "bulk": PathCompleter(),  # Will be handled by DynamicCompleter
                    }
                ),
                "contacts": NestedCompleter.from_nested_dict(
                    {
                        "import": PathCompleter(),
                        "update": PathCompleter(),
                        "preview": WordCompleter(
                            self.contacts_manager.list_contacts(), ignore_case=True
                        ),
                        "validate": WordCompleter(
                            self.contacts_manager.list_contacts(), ignore_case=True
                        ),
                        "list": None,
                        "remove": WordCompleter(
                            self.contacts_manager.list_contacts(), ignore_case=True
                        ),
                    }
                ),
                "template": NestedCompleter.from_nested_dict(
                    {
                        "list": None,
                        "show": WordCompleter(template_names, ignore_case=True),
                        "create": None,
                        "edit": WordCompleter(template_names, ignore_case=True),
                        "delete": WordCompleter(template_names, ignore_case=True),
                        "test": WordCompleter(template_names, ignore_case=True),
                        "import": None,
                    }
                ),
                "config": NestedCompleter.from_nested_dict(
                    {
                        "show": None,
                        "get": WordCompleter(
                            [
                                "rate_limiting.delay_between_emails_ms",
                                "bulk_send.parallel_connections",
                                "bulk_send.retry_attempts",
                                "bulk_send.retry_delay_seconds",
                                "bulk_send.continue_on_error",
                                "validation.check_email_format",
                                "validation.check_dns_mx",
                                "validation.max_attachment_size_mb",
                                "tracking.request_read_receipt",
                                "logging.level",
                                "logging.save_sent_emails",
                                "editor",
                                "encoding",
                                "syntax_highlighting.commands",
                                "syntax_highlighting.flags",
                                "syntax_highlighting.default",
                                "prompt.color",
                                "prompt.text",
                                "safety_features.enabled",
                            ],
                            ignore_case=True,
                        ),
                        "set": WordCompleter(
                            [
                                "rate_limiting.delay_between_emails_ms",
                                "bulk_send.parallel_connections",
                                "bulk_send.retry_attempts",
                                "bulk_send.retry_delay_seconds",
                                "bulk_send.continue_on_error",
                                "validation.check_email_format",
                                "validation.check_dns_mx",
                                "validation.max_attachment_size_mb",
                                "tracking.request_read_receipt",
                                "logging.level",
                                "logging.save_sent_emails",
                                "editor",
                                "encoding",
                                "syntax_highlighting.commands",
                                "syntax_highlighting.flags",
                                "syntax_highlighting.default",
                                "prompt.color",
                                "prompt.text",
                                "safety_features.enabled",
                            ],
                            ignore_case=True,
                        ),
                        "reset": None,
                    }
                ),
                "history": NestedCompleter.from_nested_dict(
                    {
                        "list": WordCompleter(
                            [
                                "--status",
                                "--profile",
                                "--recipient",
                                "--subject",
                                "--from",
                                "--to",
                                "--top",
                                "--bottom",
                                "--all",
                            ],
                            ignore_case=True,
                        ),
                        "show": None,
                        "stats": None,
                    }
                ),
                "schedule": NestedCompleter.from_nested_dict(
                    {
                        "send": None,
                        "list": None,
                        "show": None,
                        "cancel": None,
                        "clear": None,
                    }
                ),
                "task": NestedCompleter.from_nested_dict(
                    {
                        "list": None,
                        "show": None,
                        "watch": None,
                        "pause": None,
                        "resume": None,
                        "end": None,
                        "clean": None,
                    }
                ),
                "help": WordCompleter(CommandHelp.list_commands(), ignore_case=True),
                "exit": None,
                "quit": None,
            }
        )

    def _get_completer(self, text: str):
        """Get appropriate completer based on current input"""
        # For system commands (starting with .), use path completer
        if text.startswith("."):
            return PathCompleter()

        # For regular commands, use our nested completer
        return self.completer

    def _load_session(self):
        """Load saved session state"""
        if self.session_file.exists():
            with open(self.session_file, "r") as f:
                data = json.load(f)
                self.composer.from_dict(data.get("composer", {}))
                self.current_profile = data.get("current_profile")
                self.cwd = data.get("cwd", os.getcwd())
                self.last_cwd = data.get("last_cwd", self.cwd)
                os.chdir(self.cwd)

    def _save_session(self):
        """Save current session state"""
        try:
            data = {
                "composer": self.composer.to_dict(),
                "current_profile": self.current_profile,
                "cwd": self.cwd,
                "last_cwd": self.last_cwd,
            }
            with open(self.session_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            # Log the error but don't crash
            self._print(f"Warning: Failed to save session: {e}", "error")

    def _print(self, text: str, color: str = ""):
        """Print colored text"""
        # Use centralized color helper
        from ..utils.colors import color_text

        if color:
            try:
                print(color_text(color, text))
            except Exception:
                # Fallback to plain text on any unexpected error
                print(text)
        else:
            print(text)

    def _get_prompt(self) -> HTML:
        """Generate prompt with status"""
        status = ""
        if self.current_profile:
            status = f" ({self.current_profile})"

        if self.composer.to or self.composer.subject:
            status += " [draft]"

        # Get the custom prompt text from configuration, default to "[Mailsh]"
        prompt_text = self.config.get("prompt.text") or "[Mailsh]"

        return HTML(f"<prompt>{prompt_text}</prompt><status>{status}</status> ")

    def _get_bottom_toolbar(self):
        """Generate HTML-formatted toolbar showing status information"""
        # Get task counts
        all_tasks = self.task_manager.get_all_tasks()

        running_count = sum(1 for task in all_tasks if task.status == TaskStatus.RUNNING)
        paused_count = sum(1 for task in all_tasks if task.status == TaskStatus.PAUSED)
        completed_count = sum(1 for task in all_tasks if task.status == TaskStatus.COMPLETED)
        failed_count = sum(1 for task in all_tasks if task.status == TaskStatus.FAILED)
        interrupted_count = sum(1 for task in all_tasks if task.status == TaskStatus.INTERRUPTED)

        # Get scheduled emails
        scheduled_emails = self.scheduled_manager.get_all()
        emails_scheduled_count = len([email for email in scheduled_emails if email.status == "scheduled"])

        # Format current directory (truncate if too long)
        cwd = self.cwd
        # Truncate path if too long, keeping the end part
        if len(cwd) > 30:
            cwd = "..." + cwd[-27:]  # Show last 27 chars with ... prefix

        # Create toolbar content
        active_parts = []
        if running_count > 0:
            active_parts.append(f"{running_count} running")
        if paused_count > 0:
            active_parts.append(f"{paused_count} paused")
        if completed_count > 0:
            active_parts.append(f"{completed_count} completed")
        if failed_count > 0:
            active_parts.append(f"{failed_count} failed")
        if interrupted_count > 0:
            active_parts.append(f"{interrupted_count} interrupted")

        if active_parts:
            task_summary = " ⌯⌲ Tasks: " + ", ".join(active_parts)
        else:
            task_summary = " ⌯⌲ Tasks:"

        # Format connection status
        if self.current_profile:
            connection_status = f'<style fg="ansigreen">●</style> {self.current_profile}'
        else:
            connection_status = '<style fg="ansigray">○</style> Not connected'

        # Get terminal width to calculate equal column widths
        try:
            terminal_width = os.get_terminal_size().columns
        except OSError:
            # Default to 80 if we can't get terminal size
            terminal_width = 80

        # Calculate equal width for each column
        base_width = max(10, terminal_width // 3)  # Minimum width of 10 characters
        remainder = terminal_width % 3  # Get the remainder to distribute

        # Assign extra characters to columns if needed to ensure full width coverage
        left_width = base_width + (1 if remainder > 0 else 0)
        middle_width = base_width + (1 if remainder > 1 else 0)
        right_width = base_width  # Remaining gets the base width

        # Format content to fit in columns with proper alignment - ensure each content fills its allocated width
        left_content = f" 📂 {cwd[:left_width]}".ljust(left_width)  # Left-aligned, fills entire allocated width
        middle_content = task_summary[:middle_width].ljust(middle_width)  # Left-aligned, fills entire allocated width

        # Right column content - right-align the text and ensure it fills its allocated width
        scheduled_text = f'⏰️ scheduled: {emails_scheduled_count}  '
        if len(scheduled_text) <= right_width:
            right_content = scheduled_text.rjust(right_width)
        else:
            right_content = scheduled_text[:right_width].rjust(right_width)  # Truncate if too long

        # Create 3-column layout with calculated widths and text colors
        # Left column (purple text): Current Working Directory (left-aligned)
        left_column = f'<style bg="black" fg="#800080">{left_content}</style>'

        # Middle column (green text): Task statuses (centered)
        middle_column = f'<style bg="black" fg="#008000">{middle_content}</style>'

        # Right column (yellow text): Schedule (right-aligned)
        right_column = f'<style bg="black" fg="#FFFF00">{right_content}</style>'

        return HTML(f'{left_column}{middle_column}{right_column}')

    def _validate_email(self, email: str) -> bool:
        """Delegate to validators.is_email for consistency and optional stronger checks."""
        return is_email(email)

    def _handle_exit(self, is_mcp_mode: bool = False) -> Dict[str, Any]:
        """Handle exit command logic. Returns appropriate response for execute_command or None for run."""
        from ..core.state_manager import ExecutionMode

        active_tasks = self.task_manager.get_active_tasks()
        should_exit = True

        if active_tasks:
            # Check if we're in MCP mode or if user confirms exit despite active tasks
            if is_mcp_mode or ExecutionMode.is_mcp_mode():
                # In MCP mode, we don't ask for confirmation
                pass
            else:
                # In interactive mode, ask for confirmation
                task_count = len(active_tasks)
                task_status = f"{task_count} task{'s' if task_count > 1 else ''}"

                # Print warning in warning color (with emoji)
                self._print(f"⚠️  You have {task_status} running. Exiting will interrupt these tasks, but they are resumable upon app restart.", "warning")

                # Ask for confirmation
                confirm = self._ask_yes_no("Would you like to exit anyway? (y/n): ", default="n")
                if confirm != "y":
                    should_exit = False

        if should_exit:
            if not is_mcp_mode:  # For run() method only - perform cleanup
                # Stop the scheduler before exiting
                if hasattr(self, "_scheduler_running") and self._scheduler_running:
                    self._scheduler_stop = True
                    # Give the scheduler a moment to stop gracefully
                    import time
                    time.sleep(0.1)

                # Stop the UI refresh thread
                if hasattr(self, "_ui_refresh_stop"):
                    self._ui_refresh_stop.set()

                self._save_session()
                self._print("\nGoodbye! 👋", "theme")
                return True  # Signifies that we should break from the loop in run()

            # Return appropriate response for execute_command
            return {"success": True, "output": "Goodbye! 👋\n", "error": ""}

        # Exit was cancelled
        if is_mcp_mode:
            return {"success": True, "output": "Exit cancelled by user.\n", "error": ""}
        else:
            return False  # For run() method, means continue loop

    def _route_command(self, command: str, args: List[str], parts: List[str] = None) -> bool:
        """Route command to appropriate handler. Returns True if handled."""
        if command == "profile":
            # Handle profile subcommands including disconnect
            if args and args[0] == "disconnect":
                self.cmd_disconnect(args[1:])
            else:
                self.cmd_profile(args)
        elif command == "draft":
            self.cmd_draft(args)
        elif command == "set":
            self.cmd_set(args)
        elif command == "unset":
            self.cmd_unset(args)
        elif command == "send":
            self.cmd_send(args)
        elif command == "template":
            self.cmd_template(args)
        elif command == "config":
            self.cmd_config(args)
        elif command == "history":
            self.cmd_history(args)
        elif command == "schedule":
            self.cmd_schedule(args)
        elif command == "contacts":
            self.cmd_contacts(args)
        elif command == "task":
            self.cmd_task(args)
        elif command == "help":
            self.cmd_help(args)
        else:
            # Check if this is a command-specific help request
            if parts and len(parts) >= 2 and parts[1].lower() == "help":
                # Handle command help syntax like "profile help"
                command_name = parts[0].lower()
                help_args = parts[2:] if len(parts) > 2 else []
                self.cmd_help([command_name] + help_args)
                return True
            else:
                return False  # Unknown command

        return True

    def _edit_with_nano(self, initial_content: str = "") -> str:
        """Open nano editor for multi-line input"""
        with tempfile.NamedTemporaryFile(mode="w+", suffix=".txt", delete=False) as tf:
            tf.write(initial_content)
            tf.flush()
            temp_path = tf.name

        try:
            editor = self.config.get("editor") or "nano"
            subprocess.run([editor, temp_path])

            with open(temp_path, "r") as f:
                content = f.read()

            return content
        finally:
            os.unlink(temp_path)

    def _ask_yes_no(self, prompt_text: str, default: Optional[str] = None) -> str:
        """Ask a y/n question using prompt-toolkit so arrow keys and escapes
        are handled gracefully (no raw escape sequences shown).

        Returns the lowercased single-character response ('y' or 'n'). If the
        user presses Enter with no input and default is provided, default is used.
        Keeps prompting until a valid answer is entered.
        """
        # Use the unstyled session to avoid extra colors/styles in confirmations
        while True:
            try:
                resp = self.unstyled_session.prompt(prompt_text + " ")
            except KeyboardInterrupt:
                # Treat Ctrl-C as a 'n' (cancel)
                return "n"
            if not resp and default:
                resp = default
            if not resp:
                # empty, re-prompt
                continue
            resp = resp.strip().lower()
            if resp and resp[0] in ("y", "n"):
                return resp[0]
            # otherwise re-prompt
            self._print("Please answer 'y' or 'n'", "info")

    def _normalize_header_name(self, name: str) -> str:
        """Normalize header names for storage: make hyphen-separated and header-cased.

        Special-case common internal headers to preferred casing.
        """
        if not name:
            return name
        # Replace underscores with hyphens and strip whitespace
        norm = name.replace("_", "-").strip()
        low = norm.lower()
        # Canonical mappings
        if low in ("from-name", "fromname", "from_name"):
            return "From-Name"
        if low in ("from-address", "fromaddress", "from_address"):
            return "From-Address"
        if low in ("reply-to", "replyto", "reply_to"):
            return "Reply-To"

        # Title-case each hyphen-separated token for nicer header appearance
        parts = [p.capitalize() for p in norm.split("-") if p]
        return "-".join(parts)

    def execute_command(self, command_string: str) -> Dict[str, Any]:
        """
        Execute a Mailsh command programmatically and capture the output.

        This method allows programmatic access to Mailsh functionality by executing
        commands as if they were entered at the interactive prompt, but capturing
        the output instead of printing it to stdout.

        Args:
            command_string: The complete command to execute (e.g., "template list")

        Returns:
            A dictionary containing:
            - success: Boolean indicating if command executed without exceptions
            - output: The stdout output that would have been printed
            - error: Any error output (stderr) or exception details
        """
        import io
        import re
        import shlex
        import sys
        from contextlib import redirect_stderr, redirect_stdout

        # Capture original stdout and stderr
        original_stdout = sys.stdout
        original_stderr = sys.stderr

        # Create string buffers to capture output
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()

        try:
            # Validate command string to prevent injection or malicious commands
            if not isinstance(command_string, str):
                return {
                    "success": False,
                    "output": "",
                    "error": "Command must be a string",
                }

            # Parse command
            if not command_string.strip():
                return {"success": True, "output": "", "error": ""}

            # Prevent command injection by checking for unsafe patterns
            if any(sep in command_string for sep in [";", "&&", "||", "&"]):
                return {
                    "success": False,
                    "output": "",
                    "error": f"Command contains unsafe characters: {command_string}",
                }

            parts = shlex.split(command_string)
            command = parts[0].lower()
            args = parts[1:] if len(parts) > 1 else []

            # Check for system commands - these are not safe for MCP server
            if command_string.startswith("."):
                system_cmd = command_string[1:].strip()
                if system_cmd:
                    return {
                        "success": False,
                        "output": "",
                        "error": f"System commands (starting with '.') are not supported in programmatic mode: {command_string}",
                    }

            # Handle exit commands
            if command in ["exit", "quit"]:
                return self._handle_exit(is_mcp_mode=True)

            # Route to appropriate command handler
            with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
                try:
                    if not self._route_command(command, args, parts):
                        self._print(f"Unknown command: {command}", "error")
                        self._print("Type 'help' for available commands", "info")

                    success = True
                except Exception as e:
                    success = False
                    stderr_capture.write(f"Error: {str(e)}\n")
                    import traceback

                    if self.config.get("logging.level") == "DEBUG":
                        stderr_capture.write(traceback.format_exc())

        except (
            ValueError
        ) as e:  # This can happen with shlex.split on invalid quoted strings
            return {
                "success": False,
                "output": "",
                "error": f"Invalid command syntax: {str(e)}",
            }
        except Exception as e:
            # This is an error in our command execution setup
            return {
                "success": False,
                "output": "",
                "error": f"Command execution setup error: {str(e)}",
            }
        finally:
            # Restore original stdout and stderr
            sys.stdout = original_stdout
            sys.stderr = original_stderr

        # Get the captured output
        output = stdout_capture.getvalue()
        error = stderr_capture.getvalue()

        # Clean up ANSI color codes and other control characters from output
        def clean_ansi_codes(text):
            # Remove ANSI color codes and formatting
            ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
            return ansi_escape.sub("", text)

        clean_output = clean_ansi_codes(output)
        clean_error = clean_ansi_codes(error)

        return {"success": success, "output": clean_output, "error": clean_error}

    def _parse_time_offset(self, time_str: str) -> Optional[datetime]:
        """Parse time offset strings like '30m', '2h', '1d', '3d5h30m'"""
        import re

        # Natural language patterns
        if time_str.lower() in ["now", "immediately"]:
            return datetime.now()

        # Pattern for offset: number followed by unit (m=minutes, h=hours, d=days)
        pattern = (
            r"(\d+)\s*(m|min|minute|minutes|h|hour|hours|d|day|days|w|week|weeks)\s*"
        )
        matches = re.findall(pattern, time_str, re.IGNORECASE)

        if not matches and time_str.strip():
            # Check for specific time format: "HH:MM" or "HH:MM AM/PM"
            time_match = re.match(
                r"(\d{1,2}):(\d{2})\s*(AM|PM|am|pm)?", time_str.strip()
            )
            if time_match:
                hour, minute, period = time_match.groups()
                hour = int(hour)
                minute = int(minute)

                if period and period.lower() == "pm" and hour != 12:
                    hour += 12
                elif period and period.lower() == "am" and hour == 12:
                    hour = 0

                now = datetime.now()
                target_time = now.replace(
                    hour=hour, minute=minute, second=0, microsecond=0
                )

                # If the time has passed today, schedule for tomorrow
                if target_time <= now:
                    target_time = target_time + timedelta(days=1)

                return target_time

        total_seconds = 0
        for amount, unit in matches:
            amount = int(amount)
            unit = unit.lower()

            if unit in ["m", "min", "minute", "minutes"]:
                total_seconds += amount * 60
            elif unit in ["h", "hour", "hours"]:
                total_seconds += amount * 3600
            elif unit in ["d", "day", "days"]:
                total_seconds += amount * 86400
            elif unit in ["w", "week", "weeks"]:
                total_seconds += amount * 86400 * 7

        if total_seconds > 0:
            return datetime.now() + timedelta(seconds=total_seconds)

        return None

    def _parse_date_time(self, time_str: str) -> Optional[datetime]:
        """Parse specific date/time formats"""
        import re

        time_str = time_str.strip()

        # Handle natural language like "tomorrow", etc.
        if time_str.lower() in ["now", "immediately"]:
            return datetime.now()
        elif time_str.lower() == "tomorrow":
            now = datetime.now()
            return now.replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(
                days=1
            )  # Default to 9 AM tomorrow
        elif time_str.lower().startswith("in "):
            # Handle "in X minutes/hours/days"
            return self._parse_time_offset(time_str[3:])  # Remove 'in ' prefix
        elif time_str.lower() == "today":
            now = datetime.now()
            return now.replace(
                hour=17, minute=0, second=0, microsecond=0
            )  # Default to 5 PM today if it's not passed yet, otherwise tomorrow

        # Try manual parsing for common formats
        # Format: YYYY-MM-DD HH:MM
        date_time_pattern = r"(\d{4})-(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})"
        match = re.match(date_time_pattern, time_str)
        if match:
            year, month, day, hour, minute = map(int, match.groups())
            try:
                dt = datetime(year, month, day, hour, minute)
                return dt
            except ValueError:
                return None

        # Format: YYYY-MM-DD
        date_pattern = r"(\d{4})-(\d{1,2})-(\d{1,2})"
        match = re.match(date_pattern, time_str)
        if match:
            year, month, day = map(int, match.groups())
            # Default to 9 AM on the specified date
            try:
                dt = datetime(year, month, day, 9, 0)
                return dt
            except ValueError:
                return None

        # Format: MM/DD/YYYY HH:MM
        american_datetime_pattern = r"(\d{1,2})/(\d{1,2})/(\d{4})\s+(\d{1,2}):(\d{2})"
        match = re.match(american_datetime_pattern, time_str)
        if match:
            month, day, year, hour, minute = map(int, match.groups())
            try:
                dt = datetime(year, month, day, hour, minute)
                return dt
            except ValueError:
                return None

        # Format: MM/DD/YYYY
        american_date_pattern = r"(\d{1,2})/(\d{1,2})/(\d{4})"
        match = re.match(american_date_pattern, time_str)
        if match:
            month, day, year = map(int, match.groups())
            try:
                dt = datetime(year, month, day, 9, 0)  # Default to 9 AM
                return dt
            except ValueError:
                return None

        # Handle "next [weekday]" format
        weekdays = {
            "monday": 0,
            "tuesday": 1,
            "wednesday": 2,
            "thursday": 3,
            "friday": 4,
            "saturday": 5,
            "sunday": 6,
        }
        time_str_lower = time_str.lower()
        for day_name, day_num in weekdays.items():
            if f"next {day_name}" in time_str_lower:
                now = datetime.now()
                days_ahead = day_num - now.weekday()
                if days_ahead <= 0:  # Target day already happened this week
                    days_ahead += 7
                next_day = now + timedelta(days=days_ahead)
                return next_day.replace(hour=9, minute=0, second=0, microsecond=0)

        return None


    def _multi_prompt(self, prompts: List[Dict[str, Any]]) -> List[Optional[str]]:
        """Run a sequence of prompts using a prompt-toolkit Application.

        This draws the list of prompts/values in a read-only display and a single
        input field below it. Up/Down navigate steps without printing extra
        duplicate lines; Enter accepts the current step. Returns the list of
        entered values.
        """
        # Local imports to avoid adding new top-level dependencies
        from prompt_toolkit.application import Application
        from prompt_toolkit.layout import Layout
        from prompt_toolkit.layout.containers import HSplit, VSplit, Window
        from prompt_toolkit.layout.controls import FormattedTextControl
        from prompt_toolkit.styles import Style
        from prompt_toolkit.widgets import TextArea

        values: List[Optional[str]] = [p.get("default") for p in prompts]
        index = 0
        status_text = ""

        def render_lines():
            parts = []
            for i, p in enumerate(prompts):
                label = p.get("text", "")
                val = values[i] or ""
                # If this prompt is a password, show masked representation
                if p.get("is_password"):
                    display_val = "*" * len(val) if val else ""
                else:
                    display_val = val

                if i == index:
                    parts.append(("class:current", f"> {label} {display_val}"))
                else:
                    parts.append(("", f"  {label} {display_val}"))
                if i != len(prompts) - 1:
                    parts.append(("", "\n"))
            return parts

        display_control = FormattedTextControl(lambda: render_lines())
        display_window = Window(content=display_control, wrap_lines=False)

        # Small spacer (two lines)
        spacer_top = Window(height=1, char=" ")
        spacer_between = Window(height=1, char=" ")

        # Labeled input indicator and input field on same line
        label_control = FormattedTextControl(
            lambda: [("class:label", "Enter values here >")]
        )
        label_window = Window(content=label_control, width=20, height=1)

        input_field = TextArea(
            text=values[index] or "",
            multiline=False,
            password=prompts[index].get("is_password", False),
        )

        input_row = VSplit([label_window, input_field])

        kb = KeyBindings()

        def set_input_for_index(i):
            input_field.text = values[i] or ""
            input_field.password = bool(prompts[i].get("is_password", False))

        @kb.add("up")
        def _kb_up(event):
            nonlocal index, status_text
            status_text = ""
            values[index] = input_field.text
            if index > 0:
                index -= 1
            set_input_for_index(index)
            event.app.invalidate()
            event.app.layout.focus(input_field)

        @kb.add("down")
        def _kb_down(event):
            nonlocal index, status_text
            status_text = ""
            values[index] = input_field.text
            if index < len(prompts) - 1:
                index += 1
            set_input_for_index(index)
            event.app.invalidate()
            event.app.layout.focus(input_field)

        def _validate_current() -> Tuple[bool, str]:
            v = prompts[index].get("validator")
            if not v:
                return True, ""
            try:
                res = v(input_field.text)
            except Exception as e:
                return False, str(e)
            # If validator returns tuple (ok, message)
            if isinstance(res, tuple):
                return bool(res[0]), str(res[1] or "")
            return (bool(res), "")

        @kb.add("enter")
        def _kb_enter(event):
            nonlocal index, status_text
            ok, msg = _validate_current()
            if not ok:
                status_text = msg or "Invalid value"
                event.app.invalidate()
                return
            status_text = ""
            values[index] = input_field.text
            if index == len(prompts) - 1:
                event.app.exit()
            else:
                index += 1
                set_input_for_index(index)
                event.app.invalidate()
                event.app.layout.focus(input_field)

        @kb.add("c-c")
        def _kb_abort(event):
            raise KeyboardInterrupt()

        status_control = FormattedTextControl(lambda: [("class:status", status_text)])
        status_window = Window(content=status_control, height=1)

        root_container = HSplit(
            [
                display_window,
                spacer_top,
                input_row,
                spacer_between,
                status_window,
            ]
        )

        style = Style.from_dict(
            {"current": "#00FF00 bold", "label": "#00FFFF", "status": "#FF0000 italic"}
        )

        app = Application(
            layout=Layout(root_container),
            key_bindings=kb,
            full_screen=False,
            style=style,
        )

        try:
            app.run()
        except KeyboardInterrupt:
            raise
        finally:
            # Clean up any leftover input label or UI area so subsequent prints
            # (like the "Optional default headers" message) appear tidy.
            try:
                # Clear only the UI rows we added below the prompt list:
                # two spacers, the input row and the status line. This avoids
                # removing the displayed prompt list above.
                lines_to_clear = 4
                for _ in range(lines_to_clear):
                    # Move up one line and clear it
                    sys.stdout.write("\x1b[1A")
                    sys.stdout.write("\x1b[2K")
                # Ensure cursor at start of next fresh line
                sys.stdout.write("\r")
                sys.stdout.flush()
            except Exception:
                pass

        return values

    def _run_system_command(self, command: str):
        """Execute system command"""
        try:
            # Special handling for cd command
            if command.startswith("cd "):
                path = command[3:].strip()
                if not path:
                    path = str(Path.home())
                # Expand ~ and env vars
                path = os.path.expanduser(os.path.expandvars(path))
                # Support 'cd -' to previous directory
                if path == "-":
                    target = self.last_cwd
                else:
                    target = path
                try:
                    prev = os.getcwd()
                    os.chdir(target)
                    self.last_cwd = prev
                    self.cwd = os.getcwd()
                    self._save_session()
                    self._print(f"Changed directory to: {self.cwd}", "info")
                except FileNotFoundError:
                    self._print(f"Directory not found: {path}", "error")
                except PermissionError:
                    self._print(f"Permission denied: {path}", "error")

            elif command == "cd":
                os.chdir(str(Path.home()))
                self.last_cwd = self.cwd
                self.cwd = os.getcwd()
                self._save_session()
                self._print(f"Changed directory to: {self.cwd}", "info")

            else:
                # Execute other commands
                result = subprocess.run(
                    command, shell=True, cwd=self.cwd, capture_output=False
                )

                if result.returncode != 0:
                    self._print(
                        f"Command exited with code {result.returncode}", "warning"
                    )

        except Exception as e:
            self._print(f"Error executing command: {str(e)}", "error")

    def cmd_help(self, args: List[str]):
        """Show help"""
        if not args:
            # General help
            help_text = """

╔══════════════════════════════════════════════════════════════════════╗
║                          MAILSH - Email CLI                          ║
║                     Robust Email Sending Client                      ║
╚══════════════════════════════════════════════════════════════════════╝

COMMAND CATEGORIES:

  Connection & Profiles:
    profile add/list/edit/remove/show/connect/disconnect   Manage SMTP profiles

  Email Composition:
    draft compose/preview/clear           Email/draft composition
    set <field> <value>           Set email field (including attachments)
    unset <field> [index]         Unset email field (including attachments)

  Sending:
    send                          Send current email
    send bulk --contacts          Bulk send using contact lists
    task list/watch/show/pause/resume/end/clean			Manage bulk send tasks
    schedule send/list/show/cancel/clear			Manage scheduled emails

  Templates & Contacts
    template list/show/create/import/edit/delete/test			Manage email templates
    contacts import/list/preview/validate/update/remove		Manage contact lists

  Configuration & History:
    config get/set/show/reset     Manage configuration
    history [list]/show/stats     View email history

  System Commands:
    .<command>                    Execute system command (e.g., .ls, .cd)

  Other:
    help [command]                Show help (detailed help for command)
    exit, quit                    Exit Mailsh

EXAMPLES:
  help send                      Show detailed help for 'send' command
  help contacts                  Show detailed help for contact operations
  help system                    Show help for system commands

TIPS:
  • Use Tab for command completion
  • Arrow up/down for command history
  • Start typing for auto-suggestions
  • Session state is saved automatically
  • Use .cd to change directories
  • Prepend any command with . to run system commands

For detailed help on any command, type: help <command>
"""
            print(help_text)
        else:
            # Command-specific help
            command = args[0]
            if command == "system":
                print(CommandHelp.get("system"))
            elif command in CommandHelp.list_commands():
                print(CommandHelp.get(command))
            else:
                self._print(f"No help available for '{command}'", "error")
                self._print("Type 'help' to see all available commands", "info")

    def _run_scheduler(self):
        """Background scheduler that checks for scheduled emails to send"""
        import threading
        import time

        def scheduler_thread():
            while not hasattr(self, "_scheduler_stop") or not self._scheduler_stop:
                try:
                    # Get past-due individual scheduled emails (not bulk operations)
                    past_due_emails = self.scheduled_manager.get_past_due_emails()

                    # Process individual scheduled emails first (existing behavior)
                    for scheduled_email in past_due_emails:
                        if scheduled_email.status != "scheduled":
                            continue  # Skip if already processed

                        try:
                            # Load the profile associated with this scheduled email
                            profile = self.profiles.get(scheduled_email.profile_name)
                            if not profile:
                                msg = f"Profile '{scheduled_email.profile_name}' not found for scheduled email {scheduled_email.id}"
                                self._print(msg, "error")
                                scheduled_email.status = "failed"
                                scheduled_email.failure_reason = msg
                                self.scheduled_manager.add(
                                    scheduled_email
                                )  # Update status
                                continue

                            # Create a temporary composer from the stored data
                            temp_composer = EmailComposer()
                            temp_composer.from_dict(scheduled_email.composer_data)

                            # Check if this is a bulk send (has bulk_send flag) - for backward compatibility
                            is_bulk_send = scheduled_email.composer_data.get(
                                "bulk_send", False
                            )
                            contact_data = scheduled_email.composer_data.get(
                                "contact_data", {}
                            )

                            # If this is a bulk send, render the template with contact data
                            if is_bulk_send and contact_data:
                                # Update the composer with contact-specific data
                                temp_composer.subject = contact_data.get(
                                    "subject", temp_composer.subject
                                )
                                # Render body with contact data
                                temp_composer.body = self.templates.render(
                                    temp_composer.body, contact_data
                                )

                            # Send the email using the profile
                            sender = EmailSender(profile, self.config, task_log_file=None)
                            success, message, smtp_response = sender.send(temp_composer)

                            # Log to history
                            history_entry = {
                                "timestamp": datetime.now().isoformat(),
                                "profile": scheduled_email.profile_name,
                                "to": temp_composer.to,
                                "cc": temp_composer.cc,
                                "bcc": temp_composer.bcc,
                                "subject": temp_composer.subject,
                                "status": "sent" if success else "failed",
                                "message": message,
                                "smtp_response": smtp_response,
                                "scheduled": True,
                                "schedule_id": scheduled_email.id,
                            }

                            # Add bulk_send flag if this was a bulk send
                            if scheduled_email.composer_data.get("bulk_send", False):
                                history_entry["bulk_send"] = True

                            self.history.add(history_entry)

                            # Update the scheduled email status and optionally record a failure reason
                            scheduled_email.status = "sent" if success else "failed"
                            if not success:
                                scheduled_email.failure_reason = message
                            self.scheduled_manager.add(scheduled_email)

                            if success:
                                self._print(
                                    f"✓ Scheduled email sent: {scheduled_email.id}",
                                    "success",
                                )
                            else:
                                self._print(
                                    f"✗ Scheduled email failed: {scheduled_email.id} - {message}",
                                    "error",
                                )

                        except Exception as e:
                            err = str(e)
                            self._print(
                                f"Error sending scheduled email {scheduled_email.id}: {err}",
                                "error",
                            )
                            scheduled_email.status = "failed"
                            scheduled_email.failure_reason = err
                            self.scheduled_manager.add(scheduled_email)

                    # Now process scheduled bulk tasks (new functionality)
                    past_due_tasks = self.scheduled_manager.get_past_due_tasks()
                    for scheduled_task in past_due_tasks:
                        if scheduled_task.status != "scheduled":
                            continue  # Skip if already processed

                        try:
                            self._convert_scheduled_task_to_regular_task(scheduled_task)
                        except Exception as e:
                            err = str(e)
                            self._print(
                                f"Error converting scheduled task {scheduled_task.id}: {err}",
                                "error",
                            )
                            scheduled_task.status = "failed"
                            scheduled_task.failure_reason = err
                            self.scheduled_manager.add(scheduled_task)

                    # Wait before next check (check every 30 seconds)
                    time.sleep(30)

                except Exception as e:
                    self._print(f"Scheduler error: {str(e)}", "error")
                    time.sleep(30)  # Wait before retrying even if there was an error

            # Mark scheduler as stopped when loop ends
            self._scheduler_running = False

        # Start the scheduler thread
        self._scheduler_stop = False
        self._scheduler_running = True
        scheduler_thread_instance = threading.Thread(
            target=scheduler_thread, daemon=True
        )
        scheduler_thread_instance.start()
        return scheduler_thread_instance

    def run(self):
        """Main run loop"""
        # Print banner in Gominion style
        self._print_banner()

        self._print(
            "\nType 'help' for commands, 'help <command>' for detailed help", "info"
        )
        self._print(
            "Use .<command> to run system commands (e.g., .ls, .cd, .pwd)\n", "info"
        )

        if self.current_profile:
            self._print(
                f"✓ Restored session with profile: {self.current_profile}", "success"
            )

        if self.composer.to or self.composer.subject:
            self._print(f"✓ Restored draft from previous session", "success")

        # Check for interrupted tasks
        interrupted_tasks = [
            t
            for t in self.task_manager.get_all_tasks()
            if t.status == TaskStatus.INTERRUPTED
        ]
        if interrupted_tasks:
            self._print(
                f"⚠️  You have {len(interrupted_tasks)} interrupted task{'s' if len(interrupted_tasks) > 1 else ''}, resume with 'task resume'",
                "warning",
            )

        print()

        # Start the email scheduler
        try:
            scheduler_thread = self._run_scheduler()
            self._print("✓ Email scheduler started", "success")
        except Exception as e:
            self._print(f"⚠️  Email scheduler failed to start: {str(e)}", "warning")

        while True:
            try:
                user_input = self.session.prompt(
                    self._get_prompt(),
                    completer=self.dynamic_completer,
                    bottom_toolbar=self._get_bottom_toolbar,
                    rprompt=self._get_right_prompt
                ).strip()

                if not user_input:
                    continue

                # Check for system command
                if user_input.startswith("."):
                    system_cmd = user_input[1:].strip()
                    if system_cmd:
                        self._run_system_command(system_cmd)
                    continue

                # Parse command
                parts = shlex.split(user_input)
                command = parts[0].lower()
                args = parts[1:]

                # Handle exit
                if command in ["exit", "quit"]:
                    result = self._handle_exit(is_mcp_mode=False)
                    if result is False:  # User cancelled exit
                        continue  # Continue the loop
                    elif result is True:  # Should exit
                        break  # Break from the main loop

                # If user typed '<command> help' show the help for that command
                # This allows both 'help connect' and 'connect help' to work.
                if len(parts) >= 2 and parts[1].lower() == "help":
                    help_args = parts[2:] if len(parts) > 2 else []
                    # Call cmd_help with the command name as the first arg
                    self.cmd_help([command] + help_args)
                    continue

                # Route to command handlers
                else:
                    if not self._route_command(command, args, parts):
                        self._print(f"Unknown command: {command}", "error")
                        self._print("Type 'help' for available commands", "info")

            except KeyboardInterrupt:
                print()
                continue
            except EOFError:
                result = self._handle_exit(is_mcp_mode=False)
                if result is False:  # User cancelled exit
                    continue  # Continue the loop
                elif result is True:  # Should exit
                    break  # Break from the main loop
            except Exception as e:
                self._print(f"Error: {str(e)}", "error")
                import traceback

                if self.config.get("logging.level") == "DEBUG":
                    traceback.print_exc()

    def confirm_action(
        self, prompt: str, context: dict = None, cancel_message: str = "Cancelled"
    ):
        """
        Universal method for handling confirmations in both MCP and CLI modes.

        Args:
            prompt: The confirmation prompt to show
            context: Context data to include with ConfirmationRequest (for MCP mode)
            cancel_message: Message to show when user cancels (CLI mode)

        Returns:
            True if confirmed, False if cancelled
        """
        from ..core.state_manager import ConfirmationRequest, ExecutionMode

        if ExecutionMode.is_mcp_mode():
            raise ConfirmationRequest(prompt_message=prompt, context=context or {})
        else:
            confirm = self._ask_yes_no(prompt)
            if confirm != "y":
                self._print(cancel_message, "info")
                return False
        return True

    def _convert_scheduled_task_to_regular_task(self, scheduled_task):
        """Convert a scheduled bulk task to a regular task and execute it"""
        try:
            # Mark the scheduled task as converted to prevent re-processing
            scheduled_task.status = "converted_to_task"
            scheduled_task.converted_at = datetime.now()
            self.scheduled_manager.add(scheduled_task)

            # Extract the bulk send parameters from the scheduled task
            # The composer_data contains the original email information
            contact_list_name = scheduled_task.composer_data.get(
                "contact_list_name", "unknown"
            )

            # Get the profile for the task
            profile = self.profiles.get(scheduled_task.profile_name)
            if not profile:
                self._print(
                    f"Profile '{scheduled_task.profile_name}' not found for scheduled task {scheduled_task.id}",
                    "error",
                )
                scheduled_task.status = "failed"
                self.scheduled_manager.add(scheduled_task)
                return False

            # Create a temporary composer from the stored data
            temp_composer = EmailComposer()
            temp_composer.from_dict(scheduled_task.composer_data)

            # Get template name if it exists
            template_name = scheduled_task.composer_data.get("template_name")

            # Check if scheduled task has temporary resource paths stored
            stored_temp_resources = scheduled_task.composer_data.get(
                "temp_resources", {}
            )

            # Start background task instead of processing inline
            task_id = self.task_manager.create_task_id()

            # Store the task ID in composer data so we can track it in the scheduled task
            scheduled_task.composer_data["converted_task_id"] = task_id
            # Update the scheduled task with the task ID
            self.scheduled_manager.add(scheduled_task)

            # If we have stored temp resources from scheduling, we need to update the composer
            # to use the copied attachments instead of the original ones
            if stored_temp_resources and stored_temp_resources.get("attachment_paths"):
                # Update the composer's attachments to use the copied ones
                temp_composer.attachments = stored_temp_resources[
                    "attachment_paths"
                ].copy()

            # Start the background task with pre-existing temporary resources
            success = self.task_manager.start_bulk_send_task_with_preexisting_resources(
                task_id=task_id,
                profile=profile,
                config=self.config,
                composer=temp_composer,
                contact_name=contact_list_name,
                template_name=template_name,
                profile_name=scheduled_task.profile_name,
                dry_run=False,
                original_schedule_id=scheduled_task.id,
                scheduled_manager=self.scheduled_manager,
                preexisting_temp_resources=stored_temp_resources,  # Pass the stored temp resources directly
            )

            if success:
                # Add notification instead of printing to the console
                self.add_notification(
                    f"✓ Scheduled task {scheduled_task.id} started at task {task_id}",
                    "success"
                )
                return True
            else:
                self._print(
                    f"✗ Failed to convert scheduled task {scheduled_task.id} to regular task",
                    "error",
                )
                scheduled_task.status = "failed"
                self.scheduled_manager.add(scheduled_task)
                return False

        except Exception as e:
            self._print(
                f"Error converting scheduled task {scheduled_task.id}: {str(e)}",
                "error",
            )
            scheduled_task.status = "failed"
            self.scheduled_manager.add(scheduled_task)
            return False

    def _copy_scheduled_resources(
        self,
        contact_name: str = None,
        template_name: str = None,
        attachments: List[str] = None,
    ) -> Dict[str, Any]:
        """Copy scheduled task resources to temp directory and return paths to copied resources"""
        temp_resources = {
            "contact_path": None,
            "template_path": None,
            "attachment_paths": [],
        }

        # Copy contact list if provided
        if contact_name and hasattr(self, "task_manager") and self.task_manager:
            temp_resources["contact_path"] = self.task_manager._copy_contact_to_tmp(
                contact_name
            )

        # Copy template if provided
        if template_name and hasattr(self, "task_manager") and self.task_manager:
            temp_resources["template_path"] = self.task_manager._copy_template_to_tmp(
                template_name
            )

        # Copy attachments if provided
        if attachments and hasattr(self, "task_manager") and self.task_manager:
            temp_resources["attachment_paths"] = (
                self.task_manager._copy_attachments_to_tmp(attachments)
            )

        return temp_resources

    def confirm_multiple_actions(
        self,
        prompt: str,
        context: dict = None,
        cancel_message: str = "Operation cancelled",
    ):
        """
        Universal method for handling confirmations for bulk/multiple operations.
        Similar to confirm_action but with appropriate default messages for bulk operations.
        """
        return self.confirm_action(prompt, context, cancel_message)

    def _print_banner(self):
        """Print startup banner with ASCII art in Gominion style"""
        import sys

        # Define character representations for "MAILSH"
        M = [
            [' ','┌','─','─','┐',' '],
            [' ','│','│','│','│',' '],
            [' ','┘',' ',' ','└',' ']
        ]

        A = [
            [' ','┌','─','┐',' '],
            [' ','├','─','┤',' '],
            [' ','┴',' ','┴',' ']
        ]

        I = [
            [' ','┬',' ',' '],
            [' ','│',' ',' '],
            [' ','┴',' ',' ']
        ]

        L = [
            [' ','┬',' ',' '],
            [' ','│',' ',' '],
            [' ','┴','─','┘']
        ]

        S = [
            [' ','┌','─','┐',' '],
            [' ','└','─','┐',' '],
            [' ','└','─','┘',' ']
        ]

        H = [
            [' ','┬',' ','┬',' '],
            [' ','├','─','┤',' '],
            [' ','┴',' ','┴',' ']
        ]

        # Build the banner with characters
        banner = [M,A,I,L,S,H]  # M-A-I-L-S-H
        final_lines = []
        init_color = 97  # Starting color value (bright white)

        # Create each row of the banner
        for row in range(3):  # 3 rows
            line = "  "  # Padding
            txt_color = init_color
            for pos in range(len(banner)):
                for i in range(len(banner[pos][row])):
                    char = banner[pos][row][i]
                    if char.strip():  # If it's not a space
                        # Add color codes using terminal colors
                        color_code = f'\033[38;5;{txt_color}m'
                        reset_code = '\033[0m'
                        line += f'{color_code}{char}{reset_code}'
                    else:
                        line += char
                # Increment color at the end of each character (not each character element)
                txt_color += 36  # Increase color for next character
            final_lines.append(line)

        # Print the banner with some formatting
        sys.stdout.write('\n')
        for line in final_lines:
            print(line)

        # Reset color at the end
        print('\033[0m', end='')

        # Print version line below the ASCII art
        print("\n         Mailsh - Command-Line Email Client")
        print()  # Add empty line for spacing
