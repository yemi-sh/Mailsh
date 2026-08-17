"""
Contact list management commands.

Commands: contacts (import/update/preview/validate/list/remove)
"""

from typing import Dict, List, Optional, Any
import csv
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


class ContactsCommands:
    """Mixin class providing contacts-related commands."""

    def cmd_contacts(self, args: List[str]):
        """Manage contact lists"""
        if not args:
            self._print("Usage: contacts <import|update|preview|validate|list|remove>", "error")
            self._print("Type 'help contacts' for more information", "info")
            return

        action = args[0]

        if action == "import":
            if len(args) < 2:
                self._print("Usage: contacts import <csv_file> [--name <contact_name>]", "error")
                return

            csv_file = args[1]
            contact_name = None

            # Check for --name flag
            if "--name" in args:
                name_idx = args.index("--name")
                if name_idx + 1 < len(args):
                    contact_name = args[name_idx + 1]
                else:
                    self._print("Usage: contacts import <csv_file> [--name <contact_name>]", "error")
                    return

            # If no name provided, generate a random one
            if not contact_name:
                contact_name = self.contacts_manager.generate_random_name()

            # Check if contact list already exists
            if self.contacts_manager.contact_exists(contact_name):
                if not self.confirm_action(
                    f"Contact list '{contact_name}' already exists. Overwrite? (y/n): ",
                    context={
                        "action": "contact_import_overwrite", 
                        "contact_name": contact_name,
                        "csv_file": csv_file
                    },
                    cancel_message="Import cancelled"
                ):
                    return

            # Import contacts
            result = self.contacts_manager.import_contacts(contact_name, csv_file, append=False)
            success = result[0]
            invalid_list = result[1] if len(result) > 1 else []
            message = result[2] if len(result) > 2 else ("Error" if not success else "Success")
            
            if success:
                # When successful, message is in result[1] (the success message)
                self._print(result[1], "success")
            else:
                # Check if we have invalid emails to display
                if isinstance(invalid_list, list) and len(invalid_list) > 0:
                    # When there are invalid emails, display them properly
                    self._print(f"Found {len(invalid_list)} invalid emails:", "error")
                    for invalid_email in invalid_list:
                        print(f"  {invalid_email}")
                else:
                    # When there's an error but no invalid emails (like file not found, no email column, etc.)
                    self._print(message, "error")

        elif action == "update":
            if len(args) < 2:
                self._print("Usage: contacts update <contact_name> <csv_file>", "error")
                return

            contact_name = args[1]
            csv_file = args[2] if len(args) > 2 else None

            # Handle the --name flag differently - if --name is provided, the format is different
            # The original logic was: contacts update <csv_file> <contact_name> or contacts update <csv_file> --name <contact_name>
            # Now we want: contacts update <contact_name> <csv_file>
            # So if --name is in args, it's likely old usage that we should not support anymore
            if "--name" in args:
                self._print("Usage: contacts update <contact_name> <csv_file>", "error")
                return

            if not csv_file:
                self._print("Usage: contacts update <contact_name> <csv_file>", "error")
                return

            if not self.contacts_manager.contact_exists(contact_name):
                self._print(f"Contact list '{contact_name}' does not exist", "error")
                return

            if not self.contacts_manager.contact_exists(contact_name):
                self._print(f"Contact list '{contact_name}' does not exist", "error")
                return

            # Update contacts (append mode)
            result = self.contacts_manager.import_contacts(contact_name, csv_file, append=True)
            success = result[0]
            invalid_list = result[1] if len(result) > 1 else []
            message = result[2] if len(result) > 2 else ("Error" if not success else "Success")
            
            if success:
                # When successful, message is in result[1] (the success message)
                self._print(result[1], "success")
            else:
                # Check if we have invalid emails to display
                if isinstance(invalid_list, list) and len(invalid_list) > 0:
                    # When there are invalid emails, display them properly
                    self._print(f"Found {len(invalid_list)} invalid emails:", "error")
                    for invalid_email in invalid_list:
                        print(f"  {invalid_email}")
                else:
                    # When there's an error but no invalid emails (like file not found, no email column, etc.)
                    self._print(message, "error")

        elif action == "preview":
            if len(args) < 2:
                self._print("Usage: contacts preview <contact_name> [--limit <n>]", "error")
                return

            contact_name = args[1]
            limit = 5

            if "--limit" in args:
                limit_idx = args.index("--limit")
                if limit_idx + 1 < len(args):
                    try:
                        limit = int(args[limit_idx + 1])
                    except ValueError:
                        self._print("Invalid limit value", "error")
                        return

            success, rows, error = self.contacts_manager.get_contacts(contact_name)
            if not success:
                self._print(error, "error")
                return

            self._print(f"Contact List Preview (showing {min(limit, len(rows))} of {len(rows)} rows):", "info")
            print()
            for i, row in enumerate(rows[:limit], 1):
                print(f"{i}. Email: {row.get('email', 'N/A')}")
                for key, value in row.items():
                    if key != 'email':
                        print(f"   {key}: {value}")
                print()

            if len(rows) > limit:
                print(f"... and {len(rows) - limit} more rows")

        elif action == "validate":
            if len(args) < 2:
                self._print("Usage: contacts validate <contact_name>", "error")
                return

            contact_name = args[1]

            # Check for additional flags - for now just basic or advanced validation
            validate_mx = "--mx" in args  # This would enable MX validation if we implement it

            success, invalid, message = self.contacts_manager.validate_contacts(contact_name, validate_mx)
            if not success:
                self._print(message, "error")
                return

            if invalid:
                self._print(f"Found {len(invalid)} invalid entries:", "error")
                for row_num, issue in invalid:
                    print(f"  Row {row_num}: {issue}")
            else:
                self._print(f"✓ All {len(self.contacts_manager.get_contacts(contact_name)[1])} email addresses are valid", "success")

        elif action == "list":
            contacts = self.contacts_manager.list_contacts()
            if contacts:
                self._print(f"Available contacts ({len(contacts)}):", "info")
                for contact in contacts:
                    print(f"  - {contact}")
            else:
                self._print("No contacts available", "info")

        elif action == "remove":
            if len(args) < 2:
                self._print("Usage: contacts remove <contact_name>", "error")
                return

            contact_name = args[1]

            # Use universal confirmation method
            contact_path = self.contacts_manager._get_contact_path(contact_name)
            if not self.confirm_action(
                f"Remove contact list '{contact_name}'? (y/n):",
                context={"contact_name": contact_name, "contact_path": str(contact_path)}
            ):
                return

            success, message = self.contacts_manager.remove_contact(contact_name)
            if success:
                self._print(message, "success")
            else:
                self._print(message, "error")

        else:
            self._print(f"Unknown action: {action}", "error")
            self._print("Valid actions: import, update, preview, validate, list, remove", "info")
