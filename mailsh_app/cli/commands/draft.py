"""
Draft management commands.

Commands: draft (compose/preview/clear)
"""

from typing import List
from ...core.composer import EmailComposer


class DraftCommands:
    """Mixin class providing draft-related commands."""

    def cmd_draft(self, args: List[str]):
        """Manage email drafts (compose/preview/clear)"""
        if not args:
            self._print("Usage: draft <compose|preview|clear>", "error")
            self._print("Type 'help draft' for more information", "info")
            return

        action = args[0].lower()

        if action == "compose":
            # Call the compose functionality
            self.cmd_compose(args[1:])
        elif action == "preview":
            # Call the preview functionality
            self.cmd_preview(args[1:])
        elif action == "clear":
            # Call the clear functionality
            self.cmd_clear(args[1:])
        else:
            self._print(f"Unknown draft action: {action}", "error")
            self._print("Valid actions: compose, preview, clear", "info")