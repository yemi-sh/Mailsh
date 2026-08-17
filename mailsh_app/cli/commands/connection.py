"""
Connection and profile management commands.

Commands: connect, disconnect, profile (add/list/remove/show/connect/edit)
"""

from typing import Dict, List, Optional, Any
from ...utils.validators import (
    is_email,
    normalize_email,
    validate_port,
    validate_security_mode,
    is_hostname_or_ip,
)
from ...core.config import Config
from ...core.profile import Profile
from ...core.history import History
from ...features.templates import TemplateEngine
from ...core.composer import EmailComposer
from ...features.scheduler import ScheduleManager
from ...features.contacts import ContactsManager
from ...core.tasks import TaskStatus


class ConnectionCommands:
    """Mixin class providing connection-related commands."""

    def cmd_connect(self, args: List[str]):
        """Connect to SMTP profile"""
        if not args:
            self._print("Usage: connect <profile_name>", "error")
            self._print("Type 'help connect' for more information", "info")
            return

        profile_name = args[0]
        profile = self.profiles.get(profile_name)

        if not profile:
            self._print(f"Profile '{profile_name}' not found", "error")
            self._print("Use 'profile list' to see available profiles", "info")
            return

        self.current_profile = profile_name
        self._save_session()
        self._print(f"Connected to profile: {profile_name}", "success")

    def cmd_disconnect(self, args: List[str]):
        """Disconnect from current profile"""
        if not self.current_profile:
            self._print("Not connected to any profile", "warning")
            return

        profile_name = self.current_profile
        self.current_profile = None
        self._save_session()
        self._print(f"Disconnected from profile: {profile_name}", "info")

    def cmd_profile(self, args: List[str]):
        """Manage profiles"""
        if not args:
            self._print("Usage: profile <add|list|remove|show|connect|disconnect|edit>", "error")
            self._print("Type 'help profile' for more information", "info")
            return

        action = args[0]

        if action == "list":
            profiles = self.profiles.list()
            if profiles:
                self._print("Available profiles:", "info")
                for p in profiles:
                    marker = " (connected)" if p == self.current_profile else ""
                    print(f"  - {p}{marker}")
            else:
                self._print("No profiles configured", "warning")
                self._print("Use 'profile add' to create a profile", "info")

        elif action == "add":
            self._print("=== Add SMTP Profile ===", "theme")
            prompts = [
                {
                    "text": "Profile name:",
                    "validator": lambda v: (
                        bool(v and v.strip()),
                        "Profile name required",
                    ),
                },
                {
                    "text": "SMTP host:",
                    "validator": lambda v: (
                        is_hostname_or_ip(v.strip()),
                        "Invalid hostname or IP",
                    ),
                },
                {
                    "text": "SMTP port:",
                    "validator": lambda v: (
                        v.isdigit() and validate_port(int(v)),
                        "Port must be integer 1-65535",
                    ),
                },
                {
                    "text": "Username:",
                    "validator": lambda v: (bool(v and v.strip()), "Username required"),
                },
                {"text": "Password:", "is_password": True},
                {
                    "text": "Security (starttls/ssl/none) [starttls]:",
                    "validator": lambda v: (
                        validate_security_mode(v.strip() or "starttls"),
                        "Must be starttls, ssl or none",
                    ),
                },
            ]

            vals = self._multi_prompt(prompts)
            # Unpack results
            name = (vals[0] or "").strip()
            if name in self.profiles.list():
                self._print(f"Profile '{name}' already exists", "error")
                return

            host = (vals[1] or "").strip()
            port_str = (vals[2] or "").strip()
            port = int(port_str) if port_str else 0
            username = (vals[3] or "").strip()
            password = vals[4] or ""
            security = (vals[5] or "starttls") or "starttls"
            # Validate inputs
            if not name:
                self._print("Profile name is required", "error")
                return
            if not host or not is_hostname_or_ip(host):
                self._print(f"Invalid SMTP host: {host}", "error")
                return
            if not validate_port(port):
                self._print(f"Invalid SMTP port: {port}", "error")
                return
            if not username:
                self._print("Username is required", "error")
                return
            if not validate_security_mode(security):
                self._print(
                    f"Invalid security mode: {security}. Use starttls, ssl or none",
                    "error",
                )
                return

            # Optional default headers
            self._print("\nOptional default headers (press Enter to skip):", "info")
            # Immediate validation: invalid emails will prevent moving to next field
            header_prompts = [
                {"text": "Default From name:"},
                {
                    "text": "Default From address:",
                    "validator": lambda v: (
                        is_email(v) or v == "",
                        "Invalid email format",
                    ),
                },
                {
                    "text": "Default Reply-To:",
                    "validator": lambda v: (
                        is_email(v) or v == "",
                        "Invalid email format",
                    ),
                },
            ]
            hvals = self._multi_prompt(header_prompts)
            from_name = (hvals[0] or "").strip()
            from_address = (hvals[1] or "").strip()
            reply_to = (hvals[2] or "").strip()

            default_headers = {}
            if from_name:
                default_headers["from_name"] = from_name
            if from_address:
                default_headers["from_address"] = from_address
            if reply_to:
                default_headers["reply_to"] = reply_to

            self.profiles.add(
                name, host, port, username, password, security, default_headers
            )
            self._print(f"Profile '{name}' added successfully", "success")

        elif action == "remove":
            if len(args) < 2:
                self._print("Usage: profile remove <name>", "error")
                self._print("Type 'help profile' for more information", "info")
                return

            name = args[1]

            if name not in self.profiles.list():
                self._print(f"Profile '{name}' not found", "error")
                return

            # Check if profile is currently in use by active tasks (regular tasks)
            # Only running, paused, and interrupted tasks should prevent removal
            tasks_using_profile = []
            if self.task_manager:
                all_tasks = self.task_manager.get_all_tasks()
                active_statuses = [TaskStatus.RUNNING, TaskStatus.PAUSED, TaskStatus.INTERRUPTED]
                tasks_using_profile = [
                    task for task in all_tasks
                    if task.profile_name == name and task.status in active_statuses
                ]

            # Check if profile is marked for use by scheduled tasks
            # Only scheduled emails (not completed/cancelled ones) should prevent removal
            scheduled_using_profile = []
            if hasattr(self, 'scheduled_manager') and self.scheduled_manager:
                all_scheduled = self.scheduled_manager.get_all()
                scheduled_using_profile = [
                    scheduled for scheduled in all_scheduled
                    if scheduled.profile_name == name and scheduled.status == "scheduled"
                ]

            # If profile is in use by tasks or scheduled tasks, show appropriate error message
            if tasks_using_profile or scheduled_using_profile:
                if tasks_using_profile and not scheduled_using_profile:
                    # Only in use by regular tasks
                    if len(tasks_using_profile) == 1:
                        self._print(f"Profile currently in use by task {tasks_using_profile[0].id}", "error")
                    else:
                        self._print(f"Profile currently in use by {len(tasks_using_profile)} tasks", "error")
                elif not tasks_using_profile and scheduled_using_profile:
                    # Only in use by scheduled tasks
                    if len(scheduled_using_profile) == 1:
                        self._print(f"Profile marked for use by schedule task {scheduled_using_profile[0].id}", "error")
                    else:
                        self._print(f"Profile marked for use by {len(scheduled_using_profile)} schedule tasks", "error")
                else:
                    # In use by both regular tasks and scheduled tasks
                    # Error message should be for regular tasks as specified
                    if len(tasks_using_profile) == 1:
                        self._print(f"Profile currently in use by task {tasks_using_profile[0].id}", "error")
                    else:
                        self._print(f"Profile currently in use by {len(tasks_using_profile)} tasks", "error")
                return

            if not self.confirm_action(
                f"Delete profile '{name}'? (y/n): ",
                context={"action": "profile_delete", "profile_name": name},
                cancel_message="Cancelled",
            ):
                return

            if self.profiles.remove(name):
                if self.current_profile == name:
                    self.current_profile = None
                    self._save_session()
                self._print(f"Profile '{name}' removed", "success")

        elif action == "show":
            if len(args) < 2:
                # If no profile name provided, show the currently connected profile
                if self.current_profile:
                    name = self.current_profile
                    profile = self.profiles.get(name)
                    if profile:
                        # Hide password in display
                        display_profile = dict(profile)
                        if (
                            "smtp" in display_profile
                            and "password" in display_profile["smtp"]
                        ):
                            display_profile["smtp"]["password"] = "********"
                        import json

                        print(json.dumps(display_profile, indent=2))
                    else:
                        self._print(f"Current profile '{name}' not found", "error")
                else:
                    self._print("Usage: profile show <name>", "error")
                    self._print("Type 'help profile' for more information", "info")
                    self._print("No profile currently connected", "info")
                return

            name = args[1]
            profile = self.profiles.get(name)
            if profile:
                # Hide password in display
                display_profile = dict(profile)
                if "smtp" in display_profile and "password" in display_profile["smtp"]:
                    display_profile["smtp"]["password"] = "********"
                import json

                print(json.dumps(display_profile, indent=2))
            else:
                self._print(f"Profile '{name}' not found", "error")

        elif action == "connect":
            if len(args) < 2:
                self._print("Usage: profile connect <name>", "error")
                self._print("Type 'help profile' for more information", "info")
                return

            name = args[1]
            profile = self.profiles.get(name)

            if not profile:
                self._print(f"Profile '{name}' not found", "error")
                self._print("Use 'profile list' to see available profiles", "info")
                return

            self.current_profile = name
            self._save_session()
            self._print(f"Connected to profile: {name}", "success")

        elif action == "disconnect":
            if not self.current_profile:
                self._print("Not connected to any profile", "warning")
                return

            profile_name = self.current_profile
            self.current_profile = None
            self._save_session()
            self._print(f"Disconnected from profile: {profile_name}", "info")

        elif action == "edit":
            if len(args) < 2:
                self._print("Usage: profile edit <name>", "error")
                self._print("Type 'help profile' for more information", "info")
                return

            name = args[1]

            # Check if profile exists
            if name not in self.profiles.list():
                self._print(f"Profile '{name}' not found", "error")
                return

            # Get current profile data
            current_profile = self.profiles.get(name)
            current_smtp = current_profile["smtp"]
            current_headers = current_profile.get("default_headers", {})

            self._print(f"=== Edit SMTP Profile: {name} ===", "theme")
            prompts = [
                {
                    "text": f"Profile name (current: {name}):",
                    "default": name,
                    "validator": lambda v: (
                        bool(v and v.strip()),
                        "Profile name required",
                    ),
                },
                {
                    "text": f"SMTP host (current: {current_smtp['host']}):",
                    "default": current_smtp["host"],
                    "validator": lambda v: (
                        is_hostname_or_ip(v.strip()),
                        "Invalid hostname or IP",
                    ),
                },
                {
                    "text": f"SMTP port (current: {current_smtp['port']}):",
                    "default": str(current_smtp["port"]),
                    "validator": lambda v: (
                        v.isdigit() and validate_port(int(v)),
                        "Port must be integer 1-65535",
                    ),
                },
                {
                    "text": f"Username (current: {current_smtp['username']}):",
                    "default": current_smtp["username"],
                    "validator": lambda v: (bool(v and v.strip()), "Username required"),
                },
                {
                    "text": "Password (leave empty to keep current):",
                    "is_password": True,
                },
                {
                    "text": f"Security (current: {current_smtp['security']}):",
                    "default": current_smtp["security"],
                    "validator": lambda v: (
                        validate_security_mode(v.strip() or "starttls"),
                        "Must be starttls, ssl or none",
                    ),
                },
            ]

            vals = self._multi_prompt(prompts)
            # Unpack results
            new_name = (vals[0] or "").strip()
            if (
                new_name != name and new_name in self.profiles.list()
            ):  # Only check for duplicate if name changed
                self._print(f"Profile '{new_name}' already exists", "error")
                return

            host = (vals[1] or "").strip()
            port_str = (vals[2] or "").strip()
            port = int(port_str) if port_str else 0
            username = (vals[3] or "").strip()
            password = vals[4] or ""  # If empty, keep current password
            security = (vals[5] or "starttls") or "starttls"

            # If password is empty, keep the current password
            if not password:
                password = current_smtp["password"]

            # Validate inputs
            if not new_name:
                self._print("Profile name is required", "error")
                return
            if not host or not is_hostname_or_ip(host):
                self._print(f"Invalid SMTP host: {host}", "error")
                return
            if not validate_port(port):
                self._print(f"Invalid SMTP port: {port}", "error")
                return
            if not username:
                self._print("Username is required", "error")
                return
            if not validate_security_mode(security):
                self._print(
                    f"Invalid security mode: {security}. Use starttls, ssl or none",
                    "error",
                )
                return

            # Optional default headers (use current values as defaults)
            self._print(
                "\nOptional default headers (press Enter to keep current values):",
                "info",
            )
            # Immediate validation: invalid emails will prevent moving to next field
            header_prompts = [
                {
                    "text": f"Default From name (current: {current_headers.get('from_name', '')}):",
                    "default": current_headers.get("from_name", ""),
                },
                {
                    "text": f"Default From address (current: {current_headers.get('from_address', '')}):",
                    "default": current_headers.get("from_address", ""),
                    "validator": lambda v: (
                        is_email(v) or v == "",
                        "Invalid email format",
                    ),
                },
                {
                    "text": f"Default Reply-To (current: {current_headers.get('reply_to', '')}):",
                    "default": current_headers.get("reply_to", ""),
                    "validator": lambda v: (
                        is_email(v) or v == "",
                        "Invalid email format",
                    ),
                },
            ]
            hvals = self._multi_prompt(header_prompts)
            from_name = (hvals[0] or "").strip()
            from_address = (hvals[1] or "").strip()
            reply_to = (hvals[2] or "").strip()

            default_headers = {}
            if from_name:
                default_headers["from_name"] = from_name
            if from_address:
                default_headers["from_address"] = from_address
            if reply_to:
                default_headers["reply_to"] = reply_to

            # Update the profile
            if self.profiles.edit(
                name, host, port, username, password, security, default_headers
            ):
                # If the profile name changed, we need to remove the old one and add the new one
                if new_name != name:
                    # Temporarily store the profile data
                    profile_data = self.profiles.profiles[name]
                    # Remove the old profile
                    del self.profiles.profiles[name]
                    # Add the profile with the new name
                    self.profiles.profiles[new_name] = profile_data
                    # Update current profile if needed
                    if self.current_profile == name:
                        self.current_profile = new_name
                        self._save_session()
                    # Save the updated profiles
                    self.profiles.save()

                self._print(f"Profile '{new_name}' updated successfully", "success")
            else:
                self._print(f"Failed to update profile '{name}'", "error")

        else:
            self._print(f"Unknown action: {action}", "error")
            self._print("Valid actions: add, list, remove, show, connect, disconnect, edit", "info")
