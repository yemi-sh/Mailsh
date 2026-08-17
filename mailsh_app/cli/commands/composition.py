"""
Email composition commands.

Commands: compose, set, unset, preview, clear
"""

from typing import Dict, List, Optional, Any
import tempfile
import subprocess
import time
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


class CompositionCommands:
    """Mixin class providing composition-related commands."""

    def cmd_compose(self, args: List[str]):
        """Interactive email composition"""
        self._print("=== Email Composition ===", "theme")

        # Validators that run during the multi_prompt so the user cannot move on
        def _validate_required_emails(val: str):
            # At least one email required and each must validate
            items = [e.strip() for e in (val or "").split(",") if e.strip()]
            if not items:
                return (False, "At least one recipient required")
            for e in items:
                if not is_email(e):
                    return (False, f"Invalid email: {e}")
            return (True, "")

        def _validate_optional_email_list(val: str):
            v = (val or "").strip()
            if not v:
                return (True, "")
            items = [e.strip() for e in v.split(",") if e.strip()]
            for e in items:
                if not is_email(e):
                    return (False, f"Invalid email: {e}")
            return (True, "")

        prompts = [
            {"text": "To (comma-separated):", "validator": _validate_required_emails},
            {"text": "Cc (optional):", "validator": _validate_optional_email_list},
            {"text": "Bcc (optional):", "validator": _validate_optional_email_list},
            {"text": "From name (optional):"},
            {
                "text": "From address (optional):",
                "validator": lambda v: (is_email(v) or v == "", "Invalid email format"),
            },
            {
                "text": "Reply-To (optional):",
                "validator": lambda v: (is_email(v) or v == "", "Invalid email format"),
            },
            {"text": "Subject:"},
            {"text": "HTML email? (y/n) [n]:"},
        ]

        vals = self._multi_prompt(prompts)

        to_input = vals[0] or ""
        # Normalize and validate To addresses
        to_list = [e.strip() for e in to_input.split(",") if e.strip()]
        norm_to = []
        for e in to_list:
            if self.config.get("validation.check_email_format") and not is_email(e):
                self._print(f"Invalid To address: {e}", "error")
                return
            norm_to.append(normalize_email(e))
        self.composer.to = norm_to

        cc_input = vals[1] or ""
        if cc_input:
            cc_list = [e.strip() for e in cc_input.split(",") if e.strip()]
            norm_cc = []
            for e in cc_list:
                if self.config.get("validation.check_email_format") and not is_email(e):
                    self._print(f"Invalid Cc address: {e}", "error")
                    return
                norm_cc.append(normalize_email(e))
            self.composer.cc = norm_cc

        bcc_input = vals[2] or ""
        if bcc_input:
            bcc_list = [e.strip() for e in bcc_input.split(",") if e.strip()]
            norm_bcc = []
            for e in bcc_list:
                if self.config.get("validation.check_email_format") and not is_email(e):
                    self._print(f"Invalid Bcc address: {e}", "error")
                    return
                norm_bcc.append(normalize_email(e))
            self.composer.bcc = norm_bcc

        from_name = vals[3] or ""
        if from_name:
            self.composer.headers[self._normalize_header_name("From-Name")] = from_name

        from_address = vals[4] or ""
        if from_address:
            self.composer.headers[self._normalize_header_name("From-Address")] = (
                from_address
            )

        reply_to = vals[5] or ""
        if reply_to:
            self.composer.headers[self._normalize_header_name("Reply-To")] = reply_to

        self.composer.subject = vals[6] or ""

        html_choice = (vals[7] or "").lower()
        self.composer.html = html_choice == "y"

        # Body
        self._print("Opening editor for body (save and exit when done)...", "info")
        time.sleep(1)
        self.composer.body = self._edit_with_nano(self.composer.body)

        # Attachments
        attach_choice = self.unstyled_session.prompt(
            "Add attachments? (y/n) [n]: "
        ).lower()
        if attach_choice == "y":
            while True:
                filepath = self.unstyled_session.prompt(
                    "Attachment path (empty to finish): "
                )
                if not filepath:
                    break

                # Resolve relative paths
                resolved, err = safe_resolve_path(filepath, must_exist=True)
                if err:
                    self._print(f"File not found: {filepath}", "error")
                    continue
                # Check size against config
                max_mb = self.config.get("validation.max_attachment_size_mb") or 25
                size_mb = filesize_mb(resolved)
                if size_mb is not None and size_mb > max_mb:
                    self._print(
                        f"Attachment exceeds max size ({size_mb:.1f}MB > {max_mb}MB): {resolved}",
                        "error",
                    )
                    continue
                self.composer.attachments.append(resolved)
                self._print(f"Added: {resolved}", "success")

        self._save_session()
        self._print(
            "Email composed. Use 'preview' to review or 'send' to send.", "success"
        )

    def cmd_set(self, args: List[str]):
        """Set email fields"""
        if len(args) < 1:
            self._print("Usage: set <field> <value>", "error")
            self._print(
                "Fields: to, cc, bcc, subject, body, header, html, attachment", "info"
            )
            self._print("Type 'help set' for more information", "info")
            return

        field = args[0].lower()

        if field in ["to", "cc", "bcc"]:
            if len(args) < 2:
                self._print(f"Usage: set {field} <emails>", "error")
                return

            value = " ".join(args[1:])
            emails = [e.strip() for e in value.split(",") if e.strip()]
            norm = []
            for e in emails:
                if self.config.get("validation.check_email_format") and not is_email(e):
                    self._print(f"Invalid {field} address: {e}", "error")
                    return
                norm.append(normalize_email(e))
            setattr(self.composer, field, norm)
            self._print(f"Set {field}: {norm}", "success")

        elif field == "subject":
            if len(args) < 2:
                self._print("Usage: set subject <text>", "error")
                return

            value = " ".join(args[1:])
            self.composer.subject = value
            self._print(f"Set subject: {value}", "success")

        elif field == "body":
            from ...core.state_manager import ExecutionMode

            # Check if we're in MCP mode (programmatic) or CLI mode (interactive)
            if ExecutionMode.is_mcp_mode():
                # In MCP mode, value was passed directly as an argument
                if len(args) < 2:
                    self._print("Usage: set body <content>", "error")
                    return
                value = " ".join(args[1:])
                self.composer.body = value
                self._print("Body updated", "success")
            else:
                # In CLI mode, open editor as before
                self._print("Opening editor...", "info")
                time.sleep(0.5)
                self.composer.body = self._edit_with_nano(self.composer.body)
                self._print("Body updated", "success")

        elif field == "header":
            if len(args) < 3:
                self._print("Usage: set header <name> <value>", "error")
                return

            header_name = args[1]
            header_value = " ".join(args[2:])
            norm_name = self._normalize_header_name(header_name)
            # Validate common headers immediately
            low = norm_name.replace("_", "-").lower()
            if low in ("from-address", "reply-to"):
                if self.config.get("validation.check_email_format") and not is_email(
                    header_value
                ):
                    self._print(
                        f"Invalid email for {norm_name}: {header_value}", "error"
                    )
                    return
                header_value = normalize_email(header_value)

            self.composer.headers[norm_name] = header_value
            self._print(f"Set header {norm_name}: {header_value}", "success")

        elif field == "html":
            if len(args) < 2:
                self._print("Usage: set html <true|false>", "error")
                return

            value = args[1]
            self.composer.html = value.lower() in ["true", "yes", "y", "1"]
            self._print(f"HTML mode: {self.composer.html}", "success")

        elif field == "attachment":
            # Call the attach functionality
            if len(args) < 2:
                self._print("Usage: set attachment <filepath>", "error")
                return

            filepath = " ".join(args[1:])
            resolved, err = validate_attachment(filepath, must_exist=True)
            if err:
                # Provide a clearer user-facing message
                if err == "not found":
                    self._print(f"File not found: {filepath}", "error")
                elif err == "is a directory":
                    self._print(
                        f"Attachment is a directory, please provide a file: {filepath}",
                        "error",
                    )
                elif err == "not a regular file":
                    self._print(
                        f"Attachment is not a regular file: {filepath}", "error"
                    )
                else:
                    self._print(f"Error resolving attachment: {err}", "error")
                return
            # Check size
            max_mb = self.config.get("validation.max_attachment_size_mb") or 25
            size_mb = filesize_mb(resolved)
            if size_mb is not None and size_mb > max_mb:
                self._print(
                    f"Attachment exceeds max size ({size_mb:.1f}MB > {max_mb}MB): {resolved}",
                    "error",
                )
                return
            self.composer.attachments.append(resolved)
            self._save_session()
            self._print(f"Attached: {resolved}", "success")

        else:
            self._print(f"Unknown field: {field}", "error")
            self._print(
                "Valid fields: to, cc, bcc, subject, body, header, html, attachment",
                "info",
            )

        self._save_session()

    def cmd_unset(self, args: List[str]):
        """Unset email fields - clear them to their default values"""
        if len(args) < 1:
            self._print("Usage: unset <field> [header_name|attachment_index]", "error")
            self._print(
                "Fields: to, cc, bcc, subject, body, header, html, attachment", "info"
            )
            self._print(
                "For header field: use 'unset header <name>' to remove a specific header",
                "info",
            )
            self._print(
                "For attachment field: use 'unset attachment <index>' to remove specific attachment",
                "info",
            )
            self._print("Type 'help unset' for more information", "info")
            return

        field = args[0].lower()

        if field in ["to", "cc", "bcc"]:
            setattr(self.composer, field, [])
            self._print(f"Cleared {field}: []", "success")

        elif field == "subject":
            self.composer.subject = ""
            self._print("Cleared subject", "success")

        elif field == "body":
            self.composer.body = ""
            self._print("Cleared body", "success")

        elif field == "header":
            if len(args) < 2:
                self._print("Usage: unset header <name>", "error")
                return

            header_name = args[1]
            norm_name = self._normalize_header_name(header_name)

            if norm_name in self.composer.headers:
                del self.composer.headers[norm_name]
                self._print(f"Removed header: {norm_name}", "success")
            else:
                self._print(f"Header '{norm_name}' not found", "warning")

        elif field == "html":
            self.composer.html = False
            self._print("HTML mode: False", "success")

        elif field == "attachment":
            # Call the detach functionality
            if len(args) < 2:
                if self.composer.attachments:
                    self._print("Attachments:", "info")
                    for i, att in enumerate(self.composer.attachments):
                        print(f"  {i}: {att}")
                    self._print("\nUsage: unset attachment <index>", "info")
                else:
                    self._print("No attachments", "warning")
                return

            try:
                index = int(args[1])
                if 0 <= index < len(self.composer.attachments):
                    removed = self.composer.attachments.pop(index)
                    self._save_session()
                    self._print(f"Removed: {removed}", "success")
                else:
                    self._print(
                        f"Invalid index. Valid range: 0-{len(self.composer.attachments) - 1}",
                        "error",
                    )
            except ValueError:
                self._print("Invalid index. Must be a number.", "error")

        else:
            self._print(f"Unknown field: {field}", "error")
            self._print(
                "Valid fields: to, cc, bcc, subject, body, header, html, attachment",
                "info",
            )

        self._save_session()

    def cmd_preview(self, args: List[str]):
        """Preview current email"""
        print("\n" + "=" * 70)
        self._print("EMAIL PREVIEW", "theme")
        print("=" * 70)
        print(f"To: {', '.join(self.composer.to) if self.composer.to else '(none)'}")
        if self.composer.cc:
            print(f"Cc: {', '.join(self.composer.cc)}")
        if self.composer.bcc:
            print(f"Bcc: {', '.join(self.composer.bcc)}")
        print(
            f"Subject: {self.composer.subject if self.composer.subject else '(none)'}"
        )
        if self.composer.headers:
            print(f"Custom Headers:")
            for k, v in self.composer.headers.items():
                print(f"  {k}: {v}")
        print(f"Type: {'HTML' if self.composer.html else 'Plain Text'}")
        if self.composer.attachments:
            print(f"Attachments ({len(self.composer.attachments)}):")
            for att in self.composer.attachments:
                print(f"  - {att}")
        print("-" * 70)
        print(self.composer.body if self.composer.body else "(no body)")
        print("=" * 70 + "\n")

    def cmd_clear(self, args: List[str]):
        """Clear current draft"""
        if self.composer.to or self.composer.subject or self.composer.body:
            # Use universal confirmation method
            if not self.confirm_action(
                "Clear current draft? (y/n): ",
                context={"current_draft": self.composer.to_dict()},
            ):
                return

        self.composer.reset()
        self._save_session()
        self._print("Draft cleared", "info")
