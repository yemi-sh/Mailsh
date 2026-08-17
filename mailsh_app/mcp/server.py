"""
Mailsh MCP Server with Continuation Token Support.

This server implements the Model Context Protocol and enables AI agents to interact
with Mailsh while preserving confirmation prompts through a continuation token system.
"""

import asyncio
import json
import time
import threading
import sys
import os
from pathlib import Path
from typing import Dict, Any, List, Optional, Union

# Add the parent directory to the Python path to resolve imports when run as a script
current_file_dir = Path(__file__).parent
parent_dir = current_file_dir.parent.parent
sys.path.insert(0, str(parent_dir))

from mcp.server import Server
from mcp.types import (
    TextContent,
    Tool,
    CallToolResult,
)

from mailsh_app.cli.shell import Mailsh
from mailsh_app.core.state_manager import (
    CommandStateManager,
    ExecutionMode,
    ConfirmationRequest,
    InvalidTokenError,
    generate_token,
    CommandState,
)


# Configuration - easily adjustable timeout for confirmation tokens
CONFIRMATION_TIMEOUT_SECONDS = 300  # 5 minutes

# Load timeout from environment variable if provided
import os

CONFIRMATION_TIMEOUT_SECONDS = int(
    os.getenv("MAILSH_MCP_TIMEOUT", CONFIRMATION_TIMEOUT_SECONDS)
)


def resume_command(state: CommandState, response: str):
    """
    Resumes a command after confirmation response.

    This function recreates the command execution context and continues
    from where the ConfirmationRequest was raised.
    """
    command_name = state.command_name
    command_args = state.command_args
    context = state.context

    # Map response to standardized form
    confirmed = response.lower() in ["y", "yes"]

    # Route to appropriate command handler
    if command_name == "delete_template":
        return resume_delete_template(confirmed, context)
    elif command_name == "delete_contact":
        return resume_delete_contact(confirmed, context)
    elif command_name == "reset_config":
        return resume_reset_config(confirmed, context)
    elif command_name == "remove_contact_list":
        return resume_remove_contact_list(confirmed, context)
    elif command_name == "clear_email_draft":
        return resume_clear_email_draft(confirmed, context)
    elif command_name == "end_task":
        return resume_end_task(confirmed, context)
    elif command_name == "clean_tasks":
        return resume_clean_tasks(confirmed, context)
    elif command_name == "execute_mailsh_command":
        return resume_execute_mailsh_command(confirmed, context)
    elif command_name == "send_email":
        return resume_send_email(confirmed, context)
    elif command_name == "send_bulk_emails":
        return resume_send_email(confirmed, context)
    elif command_name == "cancel_scheduled_email":
        return resume_cancel_scheduled_email(confirmed, context)
    elif command_name == "import_template":
        return resume_import_template(confirmed, context)
    elif command_name == "import_contacts":
        return resume_import_contacts(confirmed, context)
    elif command_name == "pause_task":
        return resume_pause_task(confirmed, context)
    elif command_name == "resume_task":
        return resume_resume_task(confirmed, context)
    # Add more commands as needed
    else:
        raise ValueError(f"Unknown command: {command_name}")


def resume_delete_template(confirmed: bool, context: dict):
    """Resume delete_template after confirmation"""
    if not confirmed:
        return {"message": "Deletion cancelled", "cancelled": True}

    name = context["name"]
    template_path = context["template_path"]

    # Perform the deletion
    path_obj = Path(template_path)
    if path_obj.exists():
        path_obj.unlink()
        return {"message": f"Template '{name}' deleted successfully", "deleted": True}
    else:
        return {
            "message": f"Template '{name}' not found, nothing to delete",
            "deleted": False,
        }


def resume_delete_contact(confirmed: bool, context: dict):
    """Resume delete_contact after confirmation"""
    if not confirmed:
        return {"message": "Contact deletion cancelled", "cancelled": True}

    contact_name = context["contact_name"]
    contact_path = context["contact_path"]

    # Perform the deletion
    path_obj = Path(contact_path)
    if path_obj.exists():
        path_obj.unlink()
        return {
            "message": f"Contact list '{contact_name}' deleted successfully",
            "deleted": True,
        }
    else:
        return {
            "message": f"Contact list '{contact_name}' not found, nothing to delete",
            "deleted": False,
        }


def resume_reset_config(confirmed: bool, context: dict):
    """Resume reset_config after confirmation"""
    if not confirmed:
        return {"message": "Config reset cancelled", "cancelled": True}

    # Actually reset the configuration to defaults
    # Access the global mailsh instance directly to avoid circular imports
    global mailsh

    # Reset the configuration using the config manager
    mailsh.config.reset()

    # Save the reset configuration
    mailsh.config.save()

    return {"message": "Configuration reset to defaults", "reset": True}


def resume_remove_contact_list(confirmed: bool, context: dict):
    """Resume remove_contact_list after confirmation"""
    if not confirmed:
        return {"message": "Contact list removal cancelled", "cancelled": True}

    contact_name = context["contact_name"]
    contact_path = context["contact_path"]

    # Perform the deletion
    path_obj = Path(contact_path)
    if path_obj.exists():
        path_obj.unlink()
        return {
            "message": f"Contact list '{contact_name}' removed successfully",
            "removed": True,
        }
    else:
        return {
            "message": f"Contact list '{contact_name}' not found, nothing to delete",
            "removed": False,
        }


def resume_clear_email_draft(confirmed: bool, context: dict):
    """Resume clear_email_draft after confirmation"""
    if not confirmed:
        return {"message": "Draft clear cancelled", "cancelled": True}

    # Actually clear the current email draft by resetting the composer
    # Access the global mailsh instance directly to avoid circular imports
    global mailsh

    # Reset the email composer to clear the draft
    mailsh.composer.reset()

    # Save the session to persist the cleared state
    mailsh._save_session()

    return {"message": "Draft cleared successfully", "cleared": True}


def resume_end_task(confirmed: bool, context: dict):
    """Resume end_task after confirmation"""
    if not confirmed:
        return {"message": "Task end cancelled", "cancelled": True}

    task_id = context.get("task_id")

    # Actually end the task by interacting with the task manager
    # Access the global mailsh instance directly to avoid circular imports
    global mailsh

    # End the task using the task manager
    if mailsh.task_manager.end_task(task_id):
        return {"message": f"Task '{task_id}' ended successfully", "ended": True}
    else:
        return {"message": f"Failed to end task '{task_id}'", "ended": False}


def resume_clean_tasks(confirmed: bool, context: dict):
    """Resume clean_tasks after confirmation"""
    if not confirmed:
        return {"message": "Task cleanup cancelled", "cancelled": True}

    # The context key is statuses_to_clean, not statuses
    statuses_to_clean = context.get("statuses_to_clean", [])

    # Actually clean tasks by interacting with the task manager
    # Access the global mailsh instance directly to avoid circular imports
    global mailsh

    # Convert string values back to TaskStatus enums if needed
    from mailsh_app.core.tasks import TaskStatus

    statuses_enum = []
    for status_str in statuses_to_clean:
        try:
            # Convert string status back to enum
            status_enum = TaskStatus(status_str)
            statuses_enum.append(status_enum)
        except ValueError:
            # If conversion fails, skip this status
            pass

    # Clean tasks using the task manager
    cleaned_count = mailsh.task_manager.clean_tasks(statuses_enum, getattr(mailsh, 'scheduled_manager', None))

    return {
        "message": f"Cleaned up {cleaned_count} tasks",
        "cleaned": True,
        "count": cleaned_count,
    }


def resume_pause_task(confirmed: bool, context: dict):
    """Resume pause_task after confirmation"""
    if not confirmed:
        return {"message": "Task pause cancelled", "cancelled": True}

    # Access the global mailsh instance directly to avoid circular imports
    global mailsh

    # Get the arguments that were passed to the original tool call
    # The context contains the original arguments passed to the pause_task tool
    task_id = context.get("task_id")

    # The context may come from:
    # 1. Direct MCP tool call with pause_all flag: {"pause_all": True}
    # 2. CLI command confirmation: {"action": "pause_all", "task_count": N}
    pause_all = context.get("pause_all", False) or context.get("action") == "pause_all"

    # If it's a pause_all operation (which requires confirmation)
    if pause_all:
        from mailsh_app.core.tasks import TaskStatus

        # Get all running tasks
        all_tasks = mailsh.task_manager.get_all_tasks()
        running_tasks = [t for t in all_tasks if t.status == TaskStatus.RUNNING]
        paused_count = 0
        for task in running_tasks:
            if mailsh.task_manager.pause_task(task.id):
                paused_count += 1
        return {
            "message": f"Paused {paused_count} task(s)",
            "paused": True,
            "success": True,
        }
    # For single task pause, confirmation is not typically required
    # (The confirmation flow is mainly for bulk operations)
    # So we might not reach this part for single task operations
    else:
        # Handle single task pause if needed
        if task_id:
            if mailsh.task_manager.pause_task(task_id):
                return {
                    "message": f"Task '{task_id}' paused successfully",
                    "paused": True,
                    "success": True,
                }
            else:
                return {
                    "message": f"Failed to pause task '{task_id}'",
                    "paused": False,
                    "success": False,
                    "error": f"Failed to pause task '{task_id}'",
                }
        else:
            return {
                "message": "No task ID provided",
                "paused": False,
                "success": False,
                "error": "No task ID provided",
            }


def resume_resume_task(confirmed: bool, context: dict):
    """Resume resume_task after confirmation"""
    if not confirmed:
        return {"message": "Task resume cancelled", "cancelled": True}

    # Access the global mailsh instance directly to avoid circular imports
    global mailsh

    # Get the arguments that were passed to the original tool call
    # The context contains the original arguments passed to the resume_task tool
    task_id = context.get("task_id")

    # The context may come from:
    # 1. Direct MCP tool call with resume_all flag: {"resume_all": True}
    # 2. CLI command confirmation: {"action": "resume_all", "task_count": N}
    resume_all = (
        context.get("resume_all", False) or context.get("action") == "resume_all"
    )

    # If it's a resume_all operation (which requires confirmation)
    if resume_all:
        from mailsh_app.core.tasks import TaskStatus

        # Get all paused/interrupted tasks
        all_tasks = mailsh.task_manager.get_all_tasks()
        resumable_tasks = [
            t
            for t in all_tasks
            if t.status in [TaskStatus.PAUSED, TaskStatus.INTERRUPTED]
        ]
        resumed_count = 0
        for task in resumable_tasks:
            if mailsh.task_manager.resume_task(task.id):
                resumed_count += 1
        return {
            "message": f"Resumed {resumed_count} task(s)",
            "resumed": True,
            "success": True,
        }
    # For single task resume, confirmation is not typically required
    # (The confirmation flow is mainly for bulk operations)
    # So we might not reach this part for single task operations
    else:
        # Handle single task resume if needed
        if task_id:
            if mailsh.task_manager.resume_task(task_id):
                return {
                    "message": f"Task '{task_id}' resumed successfully",
                    "resumed": True,
                    "success": True,
                }
            else:
                return {
                    "message": f"Failed to resume task '{task_id}'",
                    "resumed": False,
                    "success": False,
                    "error": f"Failed to resume task '{task_id}'",
                }
        else:
            return {
                "message": "No task ID provided",
                "resumed": False,
                "success": False,
                "error": "No task ID provided",
            }


def resume_send_email(confirmed: bool, context: dict):
    """Resume send_email after confirmation"""
    if not confirmed:
        return {"message": "Send cancelled", "cancelled": True}

    # Import datetime at the beginning to avoid UnboundLocalError
    from datetime import datetime

    # Check if this is a bulk send or regular send based on context
    action = context.get("action", "send_email")

    # Access the global mailsh instance directly to avoid circular imports
    global mailsh

    if action == "bulk_send":
        # Handle bulk send confirmation
        contact_name = context.get("contact_name")
        template_name = context.get("template_name")
        dry_run = context.get("dry_run", False)

        if dry_run:
            # For dry run, just return success message - no actual sending
            return {
                "message": f"Dry run completed for {contact_name} contacts",
                "sent": True,
                "success": True,
            }

        if contact_name:
            # Start background bulk send task
            # datetime already imported at the beginning of the function
            import time

            # Start background task instead of running synchronously
            task_id = mailsh.task_manager.create_task_id()

            # Create a copy of the current profile data for the task
            profile = mailsh.profiles.get(mailsh.current_profile)

            if not profile:
                return {
                    "message": f"Profile not found: {mailsh.current_profile}",
                    "success": False,
                    "error": f"Profile not found: {mailsh.current_profile}",
                }

            # Start the background task
            success = mailsh.task_manager.start_bulk_send_task(
                task_id=task_id,
                profile=profile,
                config=mailsh.config,
                composer=mailsh.composer,
                contact_name=contact_name,
                template_name=template_name,
                profile_name=mailsh.current_profile,
                dry_run=False,
                original_schedule_id=None,
                scheduled_manager=None
            )

            if success:
                return {
                    "message": f"Started background sending task {task_id}",
                    "sent": True,
                    "success": True,
                    "task_id": task_id,
                }
            else:
                return {
                    "message": "Failed to start background task",
                    "sent": False,
                    "success": False,
                    "error": "Failed to start background task",
                }
        else:
            return {
                "message": "No contact list specified for bulk send",
                "success": False,
                "error": "No contact list specified",
            }

    else:
        # Handle regular send confirmation
        # Check if we have a profile connected
        if not mailsh.current_profile:
            return {
                "message": "Not connected to any profile. Use 'connect <profile>'",
                "success": False,
                "error": "No profile connected",
            }

        # Check if we have recipients
        if not mailsh.composer.to:
            return {
                "message": "No recipients specified",
                "success": False,
                "error": "No recipients",
            }

        # Validation
        if mailsh.config.get("validation.check_email_format"):
            for email in mailsh.composer.to + mailsh.composer.cc + mailsh.composer.bcc:
                if not mailsh._validate_email(email):
                    return {
                        "message": f"Invalid email address: {email}",
                        "success": False,
                        "error": f"Invalid email: {email}",
                    }

        # Send email using the profile
        profile = mailsh.profiles.get(mailsh.current_profile)
        if not profile:
            return {
                "message": f"Profile not found: {mailsh.current_profile}",
                "success": False,
                "error": f"Profile not found: {mailsh.current_profile}",
            }

        from mailsh_app.core.sender import EmailSender

        sender = EmailSender(profile, mailsh.config, task_log_file=None)

        # Determine if we need to use a template
        template_name = context.get("template_name")
        if template_name:
            # Load template and create temporary composer
            template_body = mailsh.templates.load(template_name)
            if not template_body:
                return {
                    "message": f"Template not found: {template_name}",
                    "success": False,
                    "error": f"Template not found: {template_name}",
                }

            from mailsh_app.core.composer import EmailComposer

            temp_composer = EmailComposer()
            temp_composer.to = mailsh.composer.to.copy()
            temp_composer.cc = mailsh.composer.cc.copy()
            temp_composer.bcc = mailsh.composer.bcc.copy()
            temp_composer.subject = mailsh.composer.subject
            temp_composer.body = template_body
            temp_composer.attachments = mailsh.composer.attachments.copy()
            temp_composer.headers = mailsh.composer.headers.copy()
            temp_composer.html = mailsh.composer.html

            success, message, smtp_response = sender.send(temp_composer)
        else:
            # Send using current composer
            success, message, smtp_response = sender.send(mailsh.composer)

        # Log to history
        if success:
            history_entry = {
                "timestamp": datetime.now().isoformat(),
                "profile": mailsh.current_profile,
                "to": mailsh.composer.to,
                "cc": mailsh.composer.cc,
                "bcc": mailsh.composer.bcc,
                "subject": mailsh.composer.subject,
                "status": "sent" if success else "failed",
                "message": message,
                "smtp_response": smtp_response,
            }
            mailsh.history.add(history_entry)

        if success:
            # Reset composer after successful send
            mailsh.composer.reset()
            mailsh._save_session()
            return {"message": message, "sent": True, "success": True}
        else:
            return {
                "message": message,
                "sent": False,
                "success": False,
                "error": message,
            }


def resume_cancel_scheduled_email(confirmed: bool, context: dict):
    """Resume cancel_scheduled_email after confirmation"""
    if not confirmed:
        return {"message": "Cancellation cancelled", "cancelled": True}

    # Access the global mailsh instance directly to avoid circular imports
    global mailsh

    # Check if we're cancelling all scheduled emails
    if context.get("action") == "schedule_cancel_all":
        # Get upcoming scheduled emails
        scheduled_emails = mailsh.scheduled_manager.get_upcoming()
        cancelled_count = 0

        for email in scheduled_emails:
            if (
                email.status == "scheduled"
            ):  # Only cancel scheduled (not already cancelled/failed/sent)
                email.status = "cancelled"
                # Add back to the scheduler to update it
                mailsh.scheduled_manager.add(email)
                cancelled_count += 1

        return {
            "message": f"Cancelled {cancelled_count} scheduled emails",
            "cancelled": True,
            "success": True,
            "count": cancelled_count,
        }
    else:
        # Canceling a single scheduled email
        schedule_id = context.get("schedule_id")
        if not schedule_id:
            return {
                "message": "No schedule ID provided",
                "cancelled": False,
                "error": "No schedule ID provided",
            }

        scheduled_email = mailsh.scheduled_manager.get(schedule_id)
        if not scheduled_email:
            return {
                "message": f"No scheduled email found with ID: {schedule_id}",
                "cancelled": False,
                "error": f"Scheduled email not found: {schedule_id}",
            }

        # Update status to cancelled
        scheduled_email.status = "cancelled"
        mailsh.scheduled_manager.add(scheduled_email)

        return {
            "message": f"Scheduled email '{schedule_id}' cancelled",
            "cancelled": True,
            "success": True,
            "id": schedule_id,
        }


def resume_import_template(confirmed: bool, context: dict):
    """Resume import_template after confirmation when overwriting existing template"""
    if not confirmed:
        return {"message": "Import cancelled", "cancelled": True}

    # Access the global mailsh instance directly to avoid circular imports
    global mailsh

    # The context could come from different sources:
    # 1. Direct MCP tool call: would include 'eml_file', 'template_name', 'format'
    # 2. CLI command confirmation: would include 'action': 'template_import_overwrite', 'template_name'

    template_name = context.get("template_name")

    if not template_name:
        return {
            "message": "Template name not provided",
            "success": False,
            "error": "Missing template name",
        }

    # If this is from a direct MCP call, we should have the file and format
    eml_file = context.get("eml_file") or context.get("original_eml_file")
    format_type = context.get("format", "text")
    if format_type == "text" and context.get("original_format"):
        format_type = context.get("original_format", "text")

    # The context could come from CLI confirmation (from updated templates.py)
    # which should now include eml_file and format in the context
    if not eml_file and context.get("action") == "template_import_overwrite":
        # This means the confirmation came from the CLI cmd_template method
        # With our update to templates.py, the eml_file and format should be in the context
        eml_file = context.get("eml_file")
        format_type = context.get("format", "text")

    if not eml_file:
        # If we still don't have the EML file, we can't proceed
        # This indicates the context was not set properly in templates.py
        return {
            "message": "Template name or EML file not provided",
            "success": False,
            "error": f"Missing required parameters during import confirmation. Available context keys: {list(context.keys()) if context else 'None'}. Context content: {context}",
        }

    # Extract the body from the EML file
    from mailsh_app.utils.email_parser import extract_body

    body_content = extract_body(eml_file, format_type)

    if body_content is None:
        return {
            "message": "Could not extract email body from EML file",
            "success": False,
            "error": "Failed to extract content from EML file",
        }

    # Save the extracted body as a template (this will overwrite the existing one)
    try:
        mailsh.templates.save(template_name, body_content)
        return {
            "message": f"Template '{template_name}' imported successfully from {eml_file}",
            "success": True,
            "imported": True,
        }
    except Exception as e:
        return {
            "message": f"Failed to save template: {str(e)}",
            "success": False,
            "error": str(e),
        }


def resume_import_contacts(confirmed: bool, context: dict):
    """Resume import_contacts after confirmation when overwriting an existing contact list."""
    if not confirmed:
        return {"message": "Import cancelled", "cancelled": True}

    global mailsh

    # Context expected to include 'contact_name' and 'csv_file' from the original confirmation
    contact_name = context.get("contact_name") or context.get("original_contact_name")
    csv_file = context.get("csv_file") or context.get("original_csv_file")

    if not csv_file or not contact_name:
        return {
            "message": "Missing contact name or CSV file for import",
            "success": False,
            "error": f"Context keys available: {list(context.keys()) if context else 'None'}",
        }

    # Perform the import (overwrite mode -> append=False)
    try:
        success, message = mailsh.contacts_manager.import_contacts(contact_name, csv_file, append=False)
        return {
            "message": message,
            "success": bool(success),
            "imported": bool(success),
            "contact_name": contact_name,
        }
    except Exception as e:
        return {"message": f"Error importing contacts: {str(e)}", "success": False, "error": str(e)}


def resume_execute_mailsh_command(confirmed: bool, context: dict):
    """Resume execute_mailsh_command after confirmation"""
    if not confirmed:
        return {"message": "Command execution cancelled", "cancelled": True}

    # The original command string that was passed to execute_mailsh_command
    # is stored in the enhanced context under 'original_execute_command'
    command = context.get("original_execute_command", "")

    # If not available in the enhanced field, try to get from the command field as fallback
    if not command:
        command = context.get("command", "")

    # If still not available, we have an issue with the context storage
    if not command:
        return {
            "message": "No command to execute - original command string not found in context",
            "executed": False,
            "error": "No original command string found",
        }

    global mailsh

    try:
        # Execute the command, but skip confirmation prompts since we already have user's answer
        import shlex
        from mailsh_app.core.state_manager import ExecutionMode

        # Parse the command
        parts = shlex.split(command)
        cmd = parts[0].lower() if parts else ""
        args = parts[1:] if len(parts) > 1 else []

        # For commands that require confirmation, we need to bypass the confirmation mechanism
        # since we already have the user's "yes" answer. We'll execute the actual operations directly.
        if cmd == "template" and len(args) >= 2 and args[0] == "delete":
            name = args[1]
            # Perform the template deletion directly, same as what cmd_template does after confirmation
            if name in mailsh.templates.list():
                template_path = mailsh.templates.template_dir / f"{name}.txt"
                if template_path.exists():
                    template_path.unlink()
                    return {
                        "message": f"Template '{name}' deleted successfully",
                        "deleted": True,
                        "executed": True,
                        "success": True,
                    }
                else:
                    return {
                        "message": f"Template '{name}' not found, nothing to delete",
                        "deleted": False,
                        "executed": False,
                        "error": f"Template '{name}' not found",
                    }
            else:
                return {
                    "message": f"Template not found: {name}",
                    "executed": False,
                    "error": f"Template not found: {name}",
                }


        elif cmd == "config" and len(args) >= 1 and args[0] == "reset":
            # Perform config reset directly - same as what cmd_config does after confirmation
            mailsh.config.reset()
            mailsh.config.save()
            return {
                "message": "Configuration reset to defaults",
                "reset": True,
                "executed": True,
                "success": True,
            }

        elif cmd == "contacts" and len(args) >= 2 and args[0] == "remove":
            contact_name = args[1]
            contact_path = mailsh.contacts_manager.contacts_dir / f"{contact_name}.csv"
            if contact_path.exists():
                contact_path.unlink()
                return {
                    "message": f"Contact list '{contact_name}' removed successfully",
                    "removed": True,
                    "executed": True,
                    "success": True,
                }
            else:
                return {
                    "message": f"Contact list '{contact_name}' not found, nothing to delete",
                    "removed": False,
                    "executed": False,
                    "error": f"Contact list '{contact_name}' not found",
                }

        elif (
            cmd == "task"
            and len(args) >= 1
            and args[0] in ["end", "clean", "pause", "resume"]
        ):
            # For task commands, use the proper task management methods directly
            from mailsh_app.core.tasks import TaskStatus

            if args[0] == "end":
                if "--all" in args:
                    # Handle end all tasks
                    all_tasks = mailsh.task_manager.get_all_tasks()
                    active_tasks = [
                        t
                        for t in all_tasks
                        if t.status
                        in [
                            TaskStatus.RUNNING,
                            TaskStatus.PAUSED,
                            TaskStatus.INTERRUPTED,
                        ]
                    ]
                    ended_count = 0
                    for task in active_tasks:
                        if mailsh.task_manager.end_task(task.id):
                            ended_count += 1
                    return {
                        "message": f"Ended {ended_count} task(s)",
                        "ended": True,
                        "executed": True,
                        "success": True,
                    }
                else:
                    # Handle single task end
                    task_id = args[1] if len(args) > 1 else None
                    if task_id:
                        if mailsh.task_manager.end_task(task_id):
                            return {
                                "message": f"Task '{task_id}' ended successfully",
                                "ended": True,
                                "executed": True,
                                "success": True,
                            }
                        else:
                            return {
                                "message": f"Failed to end task '{task_id}'",
                                "ended": False,
                                "executed": False,
                                "error": f"Failed to end task '{task_id}'",
                            }
                    else:
                        return {
                            "message": "No task ID specified",
                            "executed": False,
                            "error": "No task ID specified",
                        }

            elif args[0] == "pause":
                if "--all" in args:
                    # Handle pause all tasks
                    all_tasks = mailsh.task_manager.get_all_tasks()
                    running_tasks = [
                        t for t in all_tasks if t.status == TaskStatus.RUNNING
                    ]
                    paused_count = 0
                    for task in running_tasks:
                        if mailsh.task_manager.pause_task(task.id):
                            paused_count += 1
                    return {
                        "message": f"Paused {paused_count} task(s)",
                        "paused": True,
                        "executed": True,
                        "success": True,
                    }
                else:
                    # Handle single task pause (should not have confirmation for single task)
                    return {
                        "message": "Single task pause command not expected to have confirmation",
                        "executed": False,
                        "error": "Unexpected single task pause confirmation",
                    }

            elif args[0] == "resume":
                if "--all" in args:
                    # Handle resume all tasks
                    all_tasks = mailsh.task_manager.get_all_tasks()
                    resumable_tasks = [
                        t
                        for t in all_tasks
                        if t.status in [TaskStatus.PAUSED, TaskStatus.INTERRUPTED]
                    ]
                    resumed_count = 0
                    for task in resumable_tasks:
                        if mailsh.task_manager.resume_task(task.id):
                            resumed_count += 1
                    return {
                        "message": f"Resumed {resumed_count} task(s)",
                        "resumed": True,
                        "executed": True,
                        "success": True,
                    }
                else:
                    # Handle single task resume (should not have confirmation for single task)
                    return {
                        "message": "Single task resume command not expected to have confirmation",
                        "executed": False,
                        "error": "Unexpected single task resume confirmation",
                    }

            elif args[0] == "clean":
                statuses_to_clean = (
                    args[1:]
                    if len(args) > 1
                    else ["ended", "completed", "failed", "interrupted"]
                )
                statuses_enum = []
                for status_str in statuses_to_clean:
                    try:
                        status_enum = TaskStatus(status_str)
                        statuses_enum.append(status_enum)
                    except ValueError:
                        # Skip invalid status
                        continue

                cleaned_count = mailsh.task_manager.clean_tasks(statuses_enum, getattr(mailsh, 'scheduled_manager', None))
                return {
                    "message": f"Cleaned up {cleaned_count} tasks",
                    "cleaned": True,
                    "count": cleaned_count,
                    "executed": True,
                    "success": True,
                }

        else:
            # For other commands or if we don't have a direct implementation,
            # we can try to execute them but need to avoid re-raising ConfirmationRequest
            # We'll temporarily switch to CLI mode to bypass confirmation prompts
            original_execution_mode = ExecutionMode.get_mode()
            try:
                # Execute in CLI mode temporarily to avoid ConfirmationRequest
                ExecutionMode.set_mode("cli")

                if cmd == "profile":
                    action = args[0] if args else None
                    if action == "remove":
                        name = args[1] if len(args) > 1 else None

                        if not name:
                            return {
                                "message": "Usage: profile remove <name>",
                                "executed": False,
                                "error": "Profile name not specified",
                            }

                        if name not in mailsh.profiles.list():
                            return {
                                "message": f"Profile '{name}' not found",
                                "executed": False,
                                "error": f"Profile '{name}' not found",
                            }

                        # Actually remove the profile
                        if mailsh.profiles.remove(name):
                            if mailsh.current_profile == name:
                                mailsh.current_profile = None
                                mailsh._save_session()
                            return {
                                "message": f"Profile '{name}' removed",
                                "removed": True,
                                "executed": True,
                                "success": True,
                            }
                        else:
                            return {
                                "message": f"Failed to remove profile '{name}'",
                                "executed": False,
                                "error": f"Failed to remove profile '{name}'",
                            }
                    elif action == "connect":
                        # Handle profile connect
                        mailsh.cmd_connect(args[1:] if len(args) > 1 else [])
                    elif action == "disconnect":
                        # Handle profile disconnect
                        mailsh.cmd_disconnect(args[1:] if len(args) > 1 else [])
                    else:
                        mailsh.cmd_profile(args)
                elif cmd == "draft":
                    # Handle draft subcommands
                    if args and args[0] == "compose":
                        mailsh.cmd_compose(args[1:] if len(args) > 1 else [])
                    elif args and args[0] == "preview":
                        mailsh.cmd_preview(args[1:] if len(args) > 1 else [])
                    elif args and args[0] == "clear":
                        # Perform draft clearing directly - same as what cmd_clear does after confirmation
                        mailsh.composer.reset()
                        mailsh._save_session()
                        return {
                            "message": "Draft cleared successfully",
                            "cleared": True,
                            "executed": True,
                            "success": True,
                        }
                    else:
                        mailsh.cmd_draft(args)
                elif cmd == "set":
                    mailsh.cmd_set(args)
                elif cmd == "unset":
                    mailsh.cmd_unset(args)
                elif cmd == "send":
                    # Handle send command directly to avoid recursion and asyncio issues
                    # Parse for bulk send first
                    if args and args[0] == "bulk":
                        # Handle bulk send directly
                        all_args = args[1:]  # Skip 'bulk'
                        using_contacts = "--contacts" in all_args
                        dry_run = "--dry-run" in all_args
                        template_name = None

                        if "--template" in all_args:
                            template_idx = all_args.index("--template")
                            if template_idx + 1 < len(all_args):
                                template_name = all_args[template_idx + 1]

                        contact_name = None
                        if using_contacts:
                            contacts_idx = all_args.index("--contacts")
                            if contacts_idx + 1 < len(all_args):
                                possible_name = all_args[contacts_idx + 1]
                                if not possible_name.startswith("-"):
                                    contact_name = possible_name

                        if not contact_name:
                            return {
                                "message": "Usage: send bulk --contacts <contact_name> [--dry-run] [--template <name>]",
                                "executed": False,
                                "error": "No contact name specified",
                            }

                        # Get contacts
                        success, rows, error = mailsh.contacts_manager.get_contacts(
                            contact_name
                        )
                        if not success:
                            return {"message": error, "executed": False, "error": error}

                        # Handle bulk send
                        if not dry_run:
                            # Start background task instead of running synchronously
                            task_id = mailsh.task_manager.create_task_id()
                            profile = mailsh.profiles.get(mailsh.current_profile)

                            if not profile:
                                return {
                                    "message": f"Profile not found: {mailsh.current_profile}",
                                    "success": False,
                                    "error": f"Profile not found: {mailsh.current_profile}",
                                }

                            # Start the background task
                            task_success = mailsh.task_manager.start_bulk_send_task(
                                task_id=task_id,
                                profile=profile,
                                config=mailsh.config,
                                composer=mailsh.composer,
                                contact_name=contact_name,
                                template_name=template_name,
                                profile_name=mailsh.current_profile,
                                dry_run=False,
                                original_schedule_id=None,
                                scheduled_manager=None
                            )

                            if task_success:
                                return {
                                    "message": f"Started background sending task {task_id}",
                                    "sent": True,
                                    "success": True,
                                    "task_id": task_id,
                                }
                            else:
                                return {
                                    "message": "Failed to start background task",
                                    "sent": False,
                                    "success": False,
                                    "error": "Failed to start background task",
                                }
                        else:
                            # Dry run
                            return {
                                "message": f"Dry run completed for {contact_name} contacts",
                                "sent": True,
                                "success": True,
                            }
                    else:
                        # Handle regular send directly
                        # Check if we have a profile connected
                        if not mailsh.current_profile:
                            return {
                                "message": "Not connected to any profile. Use 'connect <profile>'",
                                "success": False,
                                "error": "No profile connected",
                            }

                        # Check if we have recipients
                        if not mailsh.composer.to:
                            return {
                                "message": "No recipients specified",
                                "success": False,
                                "error": "No recipients",
                            }

                        # Validation
                        if mailsh.config.get("validation.check_email_format"):
                            for email in (
                                mailsh.composer.to
                                + mailsh.composer.cc
                                + mailsh.composer.bcc
                            ):
                                if not mailsh._validate_email(email):
                                    return {
                                        "message": f"Invalid email address: {email}",
                                        "success": False,
                                        "error": f"Invalid email: {email}",
                                    }

                        # Parse template flag
                        template_name = None
                        if (
                            "--template" in args
                            and len(args) > args.index("--template") + 1
                        ):
                            template_name = args[args.index("--template") + 1]

                        # Send email using the profile
                        profile = mailsh.profiles.get(mailsh.current_profile)
                        if not profile:
                            return {
                                "message": f"Profile not found: {mailsh.current_profile}",
                                "success": False,
                                "error": f"Profile not found: {mailsh.current_profile}",
                            }

                        from mailsh_app.core.sender import EmailSender

                        sender = EmailSender(profile, mailsh.config, task_log_file=None)

                        # Determine if we need to use a template
                        if template_name:
                            # Load template and create temporary composer
                            template_body = mailsh.templates.load(template_name)
                            if not template_body:
                                return {
                                    "message": f"Template not found: {template_name}",
                                    "success": False,
                                    "error": f"Template not found: {template_name}",
                                }

                            from mailsh_app.core.composer import EmailComposer

                            temp_composer = EmailComposer()
                            temp_composer.to = mailsh.composer.to.copy()
                            temp_composer.cc = mailsh.composer.cc.copy()
                            temp_composer.bcc = mailsh.composer.bcc.copy()
                            temp_composer.subject = mailsh.composer.subject
                            temp_composer.body = template_body
                            temp_composer.attachments = (
                                mailsh.composer.attachments.copy()
                            )
                            temp_composer.headers = mailsh.composer.headers.copy()
                            temp_composer.html = mailsh.composer.html

                            success, message, smtp_response = sender.send(temp_composer)
                        else:
                            # Send using current composer
                            success, message, smtp_response = sender.send(
                                mailsh.composer
                            )

                        # Log to history
                        if success:
                            from datetime import datetime

                            history_entry = {
                                "timestamp": datetime.now().isoformat(),
                                "profile": mailsh.current_profile,
                                "to": mailsh.composer.to,
                                "cc": mailsh.composer.cc,
                                "bcc": mailsh.composer.bcc,
                                "subject": mailsh.composer.subject,
                                "status": "sent" if success else "failed",
                                "message": message,
                                "smtp_response": smtp_response,
                            }
                            mailsh.history.add(history_entry)

                        if success:
                            # Reset composer after successful send
                            mailsh.composer.reset()
                            mailsh._save_session()
                            return {
                                "message": message,
                                "sent": True,
                                "executed": True,
                                "success": True,
                            }
                        else:
                            return {
                                "message": message,
                                "sent": False,
                                "executed": False,
                                "success": False,
                                "error": message,
                            }
                elif cmd == "config":
                    # For config commands other than reset
                    if len(args) >= 1 and args[0] == "reset":
                        # This should have been handled above, but just in case
                        mailsh.config.reset()
                        mailsh.config.save()
                    else:
                        mailsh.cmd_config(args)
                elif cmd == "history":
                    mailsh.cmd_history(args)
                elif cmd == "schedule":
                    action = args[0] if args else None
                    if action == "cancel":
                        # Check if --all flag is present (this should be handled before checking for schedule_id)
                        if "--all" in args:
                            # Handle cancel all scheduled emails
                            scheduled_emails = mailsh.scheduled_manager.get_upcoming()
                            cancelled_count = 0

                            for email in scheduled_emails:
                                if (
                                    email.status == "scheduled"
                                ):  # Only cancel scheduled (not already cancelled/failed/sent)
                                    email.status = "cancelled"
                                    # Add back to the scheduler to update it
                                    mailsh.scheduled_manager.add(email)
                                    cancelled_count += 1

                            return {
                                "message": f"Cancelled {cancelled_count} scheduled emails",
                                "cancelled": True,
                                "success": True,
                                "count": cancelled_count,
                            }
                        else:
                            # Handle cancel specific schedule - get the ID (should be args[1] if args exist)
                            schedule_id = args[1] if len(args) > 1 else None
                            if schedule_id:
                                # Handle cancel specific schedule
                                scheduled_email = mailsh.scheduled_manager.get(
                                    schedule_id
                                )
                                if not scheduled_email:
                                    return {
                                        "message": f"No scheduled email found with ID: {schedule_id}",
                                        "cancelled": False,
                                        "error": f"Scheduled email not found: {schedule_id}",
                                    }

                                # Update status to cancelled
                                scheduled_email.status = "cancelled"
                                mailsh.scheduled_manager.add(scheduled_email)

                                return {
                                    "message": f"Scheduled email '{schedule_id}' cancelled",
                                    "cancelled": True,
                                    "success": True,
                                    "id": schedule_id,
                                }
                            else:
                                return {
                                    "message": "Usage: schedule cancel <id> OR schedule cancel --all",
                                    "executed": False,
                                    "error": "Invalid cancel command",
                                }
                    elif action == "clear":
                        # Handle clear all scheduled emails
                        status_filter = None
                        if len(args) > 1 and args[1] == "--status":
                            if len(args) < 3:
                                return {
                                    "message": "Usage: schedule clear --status <status>",
                                    "executed": False,
                                    "error": "Invalid clear command",
                                }
                            status_filter = args[2]
                            valid_statuses = [
                                "scheduled",
                                "cancelled",
                                "failed",
                                "sent",
                            ]
                            if status_filter not in valid_statuses:
                                return {
                                    "message": f"Invalid status. Valid statuses: {', '.join(valid_statuses)}",
                                    "executed": False,
                                    "error": "Invalid status",
                                }

                        if status_filter:
                            # Get all emails with the specified status
                            all_emails = mailsh.scheduled_manager.get_all()
                            scheduled_emails = [
                                email
                                for email in all_emails
                                if email.status == status_filter
                            ]
                        else:
                            # Get all emails (clear everything)
                            scheduled_emails = mailsh.scheduled_manager.get_all()

                        removed_count = 0
                        for email in scheduled_emails:
                            mailsh.scheduled_manager.remove(
                                email.id
                            )  # Actually remove from storage
                            removed_count += 1

                        if status_filter:
                            return {
                                "message": f"Removed {removed_count} scheduled emails with status '{status_filter}'",
                                "removed": True,
                                "success": True,
                                "count": removed_count,
                            }
                        else:
                            return {
                                "message": f"Removed {removed_count} scheduled emails",
                                "removed": True,
                                "success": True,
                                "count": removed_count,
                            }
                    else:
                        mailsh.cmd_schedule(args)
                elif cmd == "contacts":
                    # For contacts commands other than remove
                    if len(args) >= 1 and args[0] == "remove":
                        # This should have been handled above
                        contact_name = args[1] if len(args) > 1 else None
                        if contact_name:
                            contact_path = (
                                mailsh.contacts_manager.contacts_dir
                                / f"{contact_name}.csv"
                            )
                            if contact_path.exists():
                                contact_path.unlink()
                    else:
                        mailsh.cmd_contacts(args)
                elif cmd == "task":
                    # For task commands other than end/clean
                    mailsh.cmd_task(args)
                elif cmd == "help":
                    mailsh.cmd_help(args)
                else:
                    return {
                        "message": f"Unknown command: {cmd}",
                        "executed": False,
                        "error": f"Unknown command: {cmd}",
                    }

                return {
                    "message": f"Command '{command}' executed successfully",
                    "executed": True,
                    "success": True,
                }
            finally:
                # Restore original execution mode
                ExecutionMode.set_mode(original_execution_mode)

    except Exception as e:
        return {
            "message": f"Error executing command '{command}': {str(e)}",
            "executed": False,
            "error": str(e),
        }


# Create the server instance
server = Server("mailsh-mcp-server")

# Create the state manager
state_manager = CommandStateManager(timeout_seconds=CONFIRMATION_TIMEOUT_SECONDS)

# Create the Mailsh instance for the server (single instance for persistent state)
mailsh = Mailsh()  # Create our own Mailsh instance


def format_response(status: str, data: Any = None, **kwargs) -> Dict[str, Any]:
    """Helper to format standardized responses"""
    response = {"status": status}
    if data is not None:
        response["data"] = data
    response.update(kwargs)
    return response


@server.list_tools()
async def handle_list_tools():
    """Return all the tools available in Mailsh."""
    tools = [
        Tool(
            name="connect_to_profile",
            description="Connect to an SMTP profile",
            inputSchema={
                "type": "object",
                "properties": {
                    "profile_name": {
                        "type": "string",
                        "description": "Name of the SMTP profile to connect to",
                    }
                },
                "required": ["profile_name"],
            },
        ),
        Tool(
            name="disconnect_from_profile",
            description="Disconnect from the current SMTP profile",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="list_profiles",
            description="List all available SMTP profiles",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="add_profile",
            description="Add a new SMTP profile (interactive command not supported via MCP)",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Profile name"},
                    "host": {"type": "string", "description": "SMTP host"},
                    "port": {"type": "integer", "description": "SMTP port"},
                    "username": {"type": "string", "description": "SMTP username"},
                    "password": {"type": "string", "description": "SMTP password"},
                    "security": {
                        "type": "string",
                        "description": "Security mode: starttls, ssl, or none",
                        "default": "starttls",
                    },
                    "from_name": {
                        "type": "string",
                        "description": "Default From name (optional)",
                    },
                    "from_address": {
                        "type": "string",
                        "description": "Default From address (optional)",
                    },
                    "reply_to": {
                        "type": "string",
                        "description": "Default Reply-To address (optional)",
                    },
                },
                "required": ["name", "host", "port", "username", "password"],
            },
        ),
        Tool(
            name="set_email_field",
            description="Set an email field (to, cc, bcc, subject, body, header, html, attachment)",
            inputSchema={
                "type": "object",
                "properties": {
                    "field": {
                        "type": "string",
                        "description": "Field to set (to, cc, bcc, subject, body, header, html, attachment)",
                    },
                    "value": {"type": "string", "description": "Value to set"},
                    "header_name": {
                        "type": "string",
                        "description": "Header name (for header field)",
                    },
                },
                "required": ["field", "value"],
            },
        ),
        Tool(
            name="unset_email_field",
            description="Unset an email field",
            inputSchema={
                "type": "object",
                "properties": {
                    "field": {
                        "type": "string",
                        "description": "Field to unset (to, cc, bcc, subject, body, header, html, attachment)",
                    },
                    "attachment_index": {
                        "type": "integer",
                        "description": "Index of attachment to remove (for attachment field)",
                    },
                    "header_name": {
                        "type": "string",
                        "description": "Header name (for header field)",
                    },
                },
                "required": ["field"],
            },
        ),
        Tool(
            name="preview_email",
            description="Preview the current email draft",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="clear_email_draft",
            description="Clear the current email draft. May return confirmation_required status requiring a follow-up confirm_continuation call.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="send_email",
            description="Send the current email. May return confirmation_required status requiring a follow-up confirm_continuation call.",
            inputSchema={
                "type": "object",
                "properties": {
                    "template_name": {
                        "type": "string",
                        "description": "Name of the template to use (optional)",
                    }
                },
            },
        ),
        Tool(
            name="send_bulk_emails",
            description="Send emails in bulk using a contact list. May return confirmation_required status requiring a follow-up confirm_continuation call.",
            inputSchema={
                "type": "object",
                "properties": {
                    "contact_name": {
                        "type": "string",
                        "description": "Name of the contact list to use",
                    },
                    "template_name": {
                        "type": "string",
                        "description": "Name of the template to use (optional)",
                    },
                    "dry_run": {
                        "type": "boolean",
                        "description": "Whether to run in dry-run mode",
                        "default": False,
                    },
                },
                "required": ["contact_name"],
            },
        ),
        Tool(
            name="list_templates",
            description="List all available email templates",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="show_template",
            description="Show the content of an email template",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Name of the template to show",
                    }
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="create_template",
            description="Create a new email template (interactive command not supported via MCP)",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Name of the template to create",
                    },
                    "content": {
                        "type": "string",
                        "description": "Content of the template",
                    },
                    "expect_interactive": {
                        "type": "boolean",
                        "description": "Whether to expect interactive prompts",
                        "default": True,
                    },
                },
                "required": ["name", "content"],
            },
        ),
        Tool(
            name="delete_template",
            description="Delete an email template. May return confirmation_required status requiring a follow-up confirm_continuation call.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Name of the template to delete",
                    }
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="test_template",
            description="Test an email template with sample data (not implemented in Mailsh)",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Name of the template to test",
                    },
                    "test_data": {
                        "type": "object",
                        "description": "Test data for template variables",
                    },
                },
                "required": ["name", "test_data"],
            },
        ),
        Tool(
            name="import_template",
            description="Import an email template from an EML file",
            inputSchema={
                "type": "object",
                "properties": {
                    "eml_file": {
                        "type": "string",
                        "description": "Path to the EML file to import",
                    },
                    "template_name": {
                        "type": "string",
                        "description": "Name for the new template",
                    },
                    "format": {
                        "type": "string",
                        "description": "Format to extract: 'html' or 'text'",
                        "enum": ["html", "text"],
                        "default": "text",
                    },
                },
                "required": ["eml_file", "template_name"],
            },
        ),
        Tool(
            name="import_contacts",
            description="Import contacts from a CSV file",
            inputSchema={
                "type": "object",
                "properties": {
                    "csv_file": {"type": "string", "description": "Path to CSV file"},
                    "contact_name": {
                        "type": "string",
                        "description": "Name for the contact list (optional, auto-generated if not provided)",
                    },
                },
                "required": ["csv_file"],
            },
        ),
        Tool(
            name="list_contacts",
            description="List all available contact lists",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="preview_contacts",
            description="Preview a contact list",
            inputSchema={
                "type": "object",
                "properties": {
                    "contact_name": {
                        "type": "string",
                        "description": "Name of the contact list",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of contacts to preview",
                        "default": 5,
                    },
                },
                "required": ["contact_name"],
            },
        ),
        Tool(
            name="validate_contacts",
            description="Validate email addresses in a contact list",
            inputSchema={
                "type": "object",
                "properties": {
                    "contact_name": {
                        "type": "string",
                        "description": "Name of the contact list to validate",
                    }
                },
                "required": ["contact_name"],
            },
        ),
        Tool(
            name="remove_contact_list",
            description="Remove a contact list. May return confirmation_required status requiring a follow-up confirm_continuation call.",
            inputSchema={
                "type": "object",
                "properties": {
                    "contact_name": {
                        "type": "string",
                        "description": "Name of the contact list to remove",
                    }
                },
                "required": ["contact_name"],
            },
        ),
        Tool(
            name="show_config",
            description="Show all configuration settings",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="get_config_value",
            description="Get a specific configuration value",
            inputSchema={
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Configuration key to get"}
                },
                "required": ["key"],
            },
        ),
        Tool(
            name="set_config_value",
            description="Set a configuration value",
            inputSchema={
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "Configuration key to set",
                    },
                    "value": {"type": "string", "description": "Value to set"},
                },
                "required": ["key", "value"],
            },
        ),
        Tool(
            name="reset_config",
            description="Reset all configuration to defaults. May return confirmation_required status requiring a follow-up confirm_continuation call.",
            inputSchema={
                "type": "object",
                "properties": {
                    "confirm": {
                        "type": "boolean",
                        "description": "Must be true to confirm reset",
                        "default": False,
                    }
                },
            },
        ),
        Tool(
            name="show_email_history",
            description="Show email sending history",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Number of entries to show (default: 20)",
                    }
                },
            },
        ),
        Tool(
            name="show_email_details",
            description="Show details for a specific email in history",
            inputSchema={
                "type": "object",
                "properties": {
                    "email_number": {
                        "type": "integer",
                        "description": "Email number from history list",
                    }
                },
                "required": ["email_number"],
            },
        ),
        Tool(
            name="show_email_stats",
            description="Show email sending statistics",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="schedule_email",
            description="Schedule an email to be sent later",
            inputSchema={
                "type": "object",
                "properties": {
                    "time_spec": {
                        "type": "string",
                        "description": "Time specification (e.g., '30m', '2h', 'tomorrow', '2025-12-25 14:30')",
                    },
                    "contact_name": {
                        "type": "string",
                        "description": "Contact list for bulk scheduling (optional)",
                    },
                    "template_name": {
                        "type": "string",
                        "description": "Template name to use (optional)",
                    },
                },
                "required": ["time_spec"],
            },
        ),
        Tool(
            name="list_scheduled_emails",
            description="List all scheduled emails",
            inputSchema={
                "type": "object",
                "properties": {
                    "status_filter": {
                        "type": "string",
                        "description": "Filter by status (scheduled, cancelled, failed, sent)",
                    }
                },
            },
        ),
        Tool(
            name="show_scheduled_email",
            description="Show details of a scheduled email",
            inputSchema={
                "type": "object",
                "properties": {
                    "schedule_id": {
                        "type": "string",
                        "description": "ID of the scheduled email",
                    }
                },
                "required": ["schedule_id"],
            },
        ),
        Tool(
            name="cancel_scheduled_email",
            description="Cancel a scheduled email. May return confirmation_required status requiring a follow-up confirm_continuation call.",
            inputSchema={
                "type": "object",
                "properties": {
                    "schedule_id": {
                        "type": "string",
                        "description": "ID of the scheduled email to cancel",
                    },
                    "cancel_all": {
                        "type": "boolean",
                        "description": "Cancel all scheduled emails",
                        "default": False,
                    },
                },
            },
        ),
        Tool(
            name="list_tasks",
            description="List all background tasks",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="show_task_details",
            description="Show details of a specific task",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "ID of the task to show",
                    }
                },
                "required": ["task_id"],
            },
        ),
        Tool(
            name="pause_task",
            description="Pause a running task. May return confirmation_required status requiring a follow-up confirm_continuation call.",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "ID of the task to pause",
                    },
                    "pause_all": {
                        "type": "boolean",
                        "description": "Pause all running tasks",
                        "default": False,
                    },
                },
            },
        ),
        Tool(
            name="resume_task",
            description="Resume a paused task. May return confirmation_required status requiring a follow-up confirm_continuation call.",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "ID of the task to resume",
                    },
                    "resume_all": {
                        "type": "boolean",
                        "description": "Resume all paused/interrupted tasks",
                        "default": False,
                    },
                },
            },
        ),
        Tool(
            name="end_task",
            description="End/cancel a task. May return confirmation_required status requiring a follow-up confirm_continuation call.",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "ID of the task to end",
                    },
                    "end_all": {
                        "type": "boolean",
                        "description": "End all active tasks",
                        "default": False,
                    },
                },
            },
        ),
        Tool(
            name="clean_tasks",
            description="Clean up old completed/failed/cancelled tasks. May return confirmation_required status requiring a follow-up confirm_continuation call.",
            inputSchema={
                "type": "object",
                "properties": {
                    "status": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Task statuses to clean",
                        "default": ["ended", "completed", "failed", "interrupted"],
                    }
                },
            },
        ),
        # New tool for handling continuation tokens
        Tool(
            name="confirm_continuation",
            description="Responds to a confirmation prompt from a previous command. Use this when a command returns status='confirmation_required'.",
            inputSchema={
                "type": "object",
                "properties": {
                    "continuation_token": {
                        "type": "string",
                        "description": "The continuation token received from the command requiring confirmation",
                    },
                    "response": {
                        "type": "string",
                        "description": "Your response to the confirmation prompt (typically 'y' for yes or 'n' for no)",
                        "enum": ["y", "n", "yes", "no"],
                    },
                },
                "required": ["continuation_token", "response"],
            },
        ),
        Tool(
            name="execute_mailsh_command",
            description="Execute any Mailsh command directly with full control over arguments and flags. Useful for commands with specific or complex parameters (e.g., 'history list --status sent --top 5'), getting help ('help <command>'). It's advisable to first run an 'help' command before begining to execute commands through this tool. May return confirmation_required status requiring a follow-up confirm_continuation call.",
            inputSchema={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The complete Mailsh command to execute",
                    }
                },
                "required": ["command"],
            },
        ),
    ]
    return tools


@server.call_tool()
async def handle_call_tool(tool_name: str, arguments: Dict[str, Any]) -> CallToolResult:
    """Execute a Mailsh command based on the tool called."""
    # Import inside function to handle import errors gracefully
    try:
        from mcp.types import TextContent, CallToolResult
    except ImportError:
        raise ImportError("mcp library is not available")

    # Special handling for the confirmation tool
    if tool_name == "confirm_continuation":
        return handle_confirmation(arguments)

    # Capture output using string buffer
    from io import StringIO
    import sys
    from contextlib import redirect_stdout, redirect_stderr

    # Handle each tool by calling the appropriate command method directly
    # This allows ConfirmationRequest exceptions to bubble up properly
    try:
        # Create string buffers to capture output
        stdout_capture = StringIO()
        stderr_capture = StringIO()

        with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
            with ExecutionMode.mcp_mode():
                if tool_name == "connect_to_profile":
                    profile_name = arguments.get("profile_name")
                    mailsh.cmd_connect([profile_name] if profile_name else [])
                elif tool_name == "disconnect_from_profile":
                    mailsh.cmd_disconnect([])
                elif tool_name == "list_profiles":
                    mailsh.cmd_profile(["list"])
                elif tool_name == "add_profile":
                    # Programmatic access for adding SMTP profiles
                    name = arguments.get("name")
                    host = arguments.get("host")
                    port = arguments.get("port")
                    username = arguments.get("username")
                    password = arguments.get("password")
                    security = arguments.get("security", "starttls")
                    from_name = arguments.get("from_name")
                    from_address = arguments.get("from_address")
                    reply_to = arguments.get("reply_to")

                    if not all([name, host, port, username, password]):
                        return CallToolResult(
                            content=[
                                TextContent(
                                    type="text",
                                    text="Error: name, host, port, username, and password are required for add_profile",
                                )
                            ],
                            is_error=True,
                        )

                    # Validate inputs
                    from mailsh_app.utils.validators import (
                        is_hostname_or_ip,
                        validate_port,
                        validate_security_mode,
                        is_email,
                    )

                    if not is_hostname_or_ip(host):
                        return CallToolResult(
                            content=[
                                TextContent(
                                    type="text",
                                    text=f"Error: Invalid hostname or IP address: {host}",
                                )
                            ],
                            is_error=True,
                        )

                    if not validate_port(port):
                        return CallToolResult(
                            content=[
                                TextContent(
                                    type="text",
                                    text=f"Error: Invalid port number: {port}",
                                )
                            ],
                            is_error=True,
                        )

                    if not validate_security_mode(security):
                        return CallToolResult(
                            content=[
                                TextContent(
                                    type="text",
                                    text=f"Error: Invalid security mode: {security}. Must be starttls, ssl, or none.",
                                )
                            ],
                            is_error=True,
                        )

                    # Validate email addresses if provided
                    if from_address and not is_email(from_address):
                        return CallToolResult(
                            content=[
                                TextContent(
                                    type="text",
                                    text=f"Error: Invalid From address: {from_address}",
                                )
                            ],
                            is_error=True,
                        )

                    if reply_to and not is_email(reply_to):
                        return CallToolResult(
                            content=[
                                TextContent(
                                    type="text",
                                    text=f"Error: Invalid Reply-To address: {reply_to}",
                                )
                            ],
                            is_error=True,
                        )

                    # Build default headers
                    default_headers = {}
                    if from_name:
                        default_headers["from_name"] = from_name
                    if from_address:
                        default_headers["from_address"] = from_address
                    if reply_to:
                        default_headers["reply_to"] = reply_to

                    # Add the profile programmatically
                    mailsh.profiles.add(
                        name, host, port, username, password, security, default_headers
                    )
                    return CallToolResult(
                        content=[
                            TextContent(
                                type="text", text=f"Profile '{name}' added successfully"
                            )
                        ],
                        is_error=False,
                    )

                elif tool_name == "set_email_field":
                    field = arguments.get("field")
                    value = arguments.get("value")
                    header_name = arguments.get("header_name")
                    if field == "header" and header_name:
                        mailsh.cmd_set(["header", header_name, value])
                    else:
                        mailsh.cmd_set([field, value])
                elif tool_name == "unset_email_field":
                    field = arguments.get("field")
                    attachment_index = arguments.get("attachment_index")
                    header_name = arguments.get("header_name")
                    if field == "attachment" and attachment_index is not None:
                        # This needs special handling since unset attachment takes an index
                        mailsh.cmd_unset(["attachment", str(attachment_index)])
                    elif field == "header" and header_name:
                        mailsh.cmd_unset(["header", header_name])
                    else:
                        mailsh.cmd_unset([field])
                elif tool_name == "preview_email":
                    mailsh.cmd_preview([])
                elif tool_name == "clear_email_draft":
                    mailsh.cmd_clear([])
                elif tool_name == "send_email":
                    template_name = arguments.get("template_name")
                    if template_name:
                        mailsh.cmd_send(["--template", template_name])
                    else:
                        mailsh.cmd_send([])
                elif tool_name == "send_bulk_emails":
                    contact_name = arguments.get("contact_name")
                    template_name = arguments.get("template_name")
                    cmd_args = ["bulk", "--contacts", contact_name]
                    if template_name:
                        cmd_args.extend(["--template", template_name])
                    if arguments.get("dry_run"):
                        cmd_args.append("--dry-run")
                    mailsh.cmd_send(cmd_args)
                elif tool_name == "list_templates":
                    mailsh.cmd_template(["list"])
                elif tool_name == "show_template":
                    name = arguments.get("name")
                    mailsh.cmd_template(["show", name] if name else ["list"])
                elif tool_name == "create_template":
                    # Programmatic access for creating email templates
                    name = arguments.get("name")
                    content = arguments.get("content")

                    if not name or not content:
                        return CallToolResult(
                            content=[
                                TextContent(
                                    type="text",
                                    text="Error: Both name and content are required for create_template",
                                )
                            ],
                            is_error=True,
                        )

                    # Check if template already exists
                    if name in mailsh.templates.list():
                        return CallToolResult(
                            content=[
                                TextContent(
                                    type="text",
                                    text=f"Error: Template '{name}' already exists. Use template import to overwrite if needed.",
                                )
                            ],
                            is_error=True,
                        )

                    # Save the template with the provided content
                    try:
                        mailsh.templates.save(name, content)
                        return CallToolResult(
                            content=[
                                TextContent(
                                    type="text",
                                    text=f"Template '{name}' created successfully",
                                )
                            ],
                            is_error=False,
                        )
                    except Exception as e:
                        return CallToolResult(
                            content=[
                                TextContent(
                                    type="text",
                                    text=f"Error creating template: {str(e)}",
                                )
                            ],
                            is_error=True,
                        )

                elif tool_name == "delete_template":
                    name = arguments.get("name")
                    if name:
                        mailsh.cmd_template(["delete", name])
                    else:
                        return CallToolResult(
                            content=[
                                TextContent(
                                    type="text",
                                    text="Error: Template name is required for deletion",
                                )
                            ],
                            is_error=True,
                        )
                elif tool_name == "test_template":
                    # This feature is not yet implemented in Mailsh
                    return CallToolResult(
                        content=[
                            TextContent(
                                type="text",
                                text="Error: template testing with sample data is not yet implemented in Mailsh.",
                            )
                        ],
                        is_error=True,
                    )
                elif tool_name == "import_template":
                    eml_file = arguments.get("eml_file")
                    template_name = arguments.get("template_name")
                    format_type = arguments.get("format", "text").lower()

                    if not eml_file or not template_name:
                        return CallToolResult(
                            content=[
                                TextContent(
                                    type="text",
                                    text="Error: Both eml_file and template_name are required for import_template",
                                )
                            ],
                            is_error=True,
                        )

                    # Call the template import command with appropriate arguments
                    # Format: template import <eml_file.eml> --html/--text <template_name>
                    cmd_args = ["import", eml_file, f"--{format_type}", template_name]
                    mailsh.cmd_template(cmd_args)
                elif tool_name == "import_contacts":
                    csv_file = arguments.get("csv_file")
                    contact_name = arguments.get("contact_name")
                    cmd_args = ["import", csv_file]
                    if contact_name:
                        cmd_args.extend(["--name", contact_name])
                    mailsh.cmd_contacts(cmd_args)
                elif tool_name == "list_contacts":
                    mailsh.cmd_contacts(["list"])
                elif tool_name == "preview_contacts":
                    contact_name = arguments.get("contact_name")
                    limit = arguments.get("limit", 5)
                    cmd_args = ["preview", contact_name, "--limit", str(limit)]
                    mailsh.cmd_contacts(cmd_args)
                elif tool_name == "validate_contacts":
                    contact_name = arguments.get("contact_name")
                    mailsh.cmd_contacts(["validate", contact_name])
                elif tool_name == "remove_contact_list":
                    contact_name = arguments.get("contact_name")
                    if contact_name:
                        mailsh.cmd_contacts(["remove", contact_name])
                    else:
                        return CallToolResult(
                            content=[
                                TextContent(
                                    type="text",
                                    text="Error: Contact name is required for removal",
                                )
                            ],
                            is_error=True,
                        )
                elif tool_name == "show_config":
                    mailsh.cmd_config(["show"])
                elif tool_name == "get_config_value":
                    key = arguments.get("key")
                    if key:
                        mailsh.cmd_config(["get", key])
                    else:
                        return CallToolResult(
                            content=[
                                TextContent(
                                    type="text",
                                    text="Error: Configuration key is required",
                                )
                            ],
                            is_error=True,
                        )
                elif tool_name == "set_config_value":
                    key = arguments.get("key")
                    value = arguments.get("value")
                    if key and value:
                        mailsh.cmd_config(["set", key, value])
                    else:
                        return CallToolResult(
                            content=[
                                TextContent(
                                    type="text",
                                    text="Error: Both key and value are required for config set",
                                )
                            ],
                            is_error=True,
                        )
                elif tool_name == "reset_config":
                    # Check if confirmation was provided upfront (for backward compatibility)
                    confirm = arguments.get("confirm", False)
                    if confirm:
                        mailsh.cmd_config(["reset"])
                    else:
                        # This will trigger the confirmation flow
                        mailsh.cmd_config(["reset"])
                elif tool_name == "show_email_history":
                    limit = arguments.get("limit")
                    cmd_args = ["list"]
                    if limit:
                        cmd_args.extend(["--top", str(limit)])
                    mailsh.cmd_history(cmd_args)
                elif tool_name == "show_email_details":
                    email_number = arguments.get("email_number")
                    if email_number is not None:
                        mailsh.cmd_history(["show", str(email_number)])
                    else:
                        return CallToolResult(
                            content=[
                                TextContent(
                                    type="text",
                                    text="Error: Email number is required for details",
                                )
                            ],
                            is_error=True,
                        )
                elif tool_name == "show_email_stats":
                    mailsh.cmd_history(["stats"])
                elif tool_name == "schedule_email":
                    time_spec = arguments.get("time_spec")
                    contact_name = arguments.get("contact_name")
                    template_name = arguments.get("template_name")
                    if not time_spec:
                        return CallToolResult(
                            content=[
                                TextContent(
                                    type="text",
                                    text="Error: Time specification is required for scheduling",
                                )
                            ],
                            is_error=True,
                        )
                    cmd_args = ["send", time_spec]
                    if template_name:
                        cmd_args.extend(["--template", template_name])
                    if contact_name:
                        cmd_args.extend(["--contacts", contact_name])
                    mailsh.cmd_schedule(cmd_args)
                elif tool_name == "list_scheduled_emails":
                    cmd_args = ["list"]
                    status_filter = arguments.get("status_filter")
                    if status_filter:
                        cmd_args.extend(["--status", status_filter])
                    mailsh.cmd_schedule(cmd_args)
                elif tool_name == "show_scheduled_email":
                    schedule_id = arguments.get("schedule_id")
                    if schedule_id:
                        mailsh.cmd_schedule(["show", schedule_id])
                    else:
                        return CallToolResult(
                            content=[
                                TextContent(
                                    type="text", text="Error: Schedule ID is required"
                                )
                            ],
                            is_error=True,
                        )
                elif tool_name == "cancel_scheduled_email":
                    schedule_id = arguments.get("schedule_id")
                    cancel_all = arguments.get("cancel_all", False)
                    if cancel_all:
                        mailsh.cmd_schedule(["cancel", "--all"])
                    elif schedule_id:
                        mailsh.cmd_schedule(["cancel", schedule_id])
                    else:
                        return CallToolResult(
                            content=[
                                TextContent(
                                    type="text",
                                    text="Error: Must provide either schedule_id or set cancel_all to True",
                                )
                            ],
                            is_error=True,
                        )
                elif tool_name == "list_tasks":
                    mailsh.cmd_task(["list"])
                elif tool_name == "show_task_details":
                    task_id = arguments.get("task_id")
                    if task_id:
                        mailsh.cmd_task(["show", task_id])
                    else:
                        return CallToolResult(
                            content=[
                                TextContent(
                                    type="text", text="Error: Task ID is required"
                                )
                            ],
                            is_error=True,
                        )

                elif tool_name == "pause_task":
                    task_id = arguments.get("task_id")
                    pause_all = arguments.get("pause_all", False)
                    if pause_all:
                        mailsh.cmd_task(["pause", "--all"])
                    elif task_id:
                        mailsh.cmd_task(["pause", task_id])
                    else:
                        return CallToolResult(
                            content=[
                                TextContent(
                                    type="text",
                                    text="Error: Must provide either task_id or set pause_all to True",
                                )
                            ],
                            is_error=True,
                        )
                elif tool_name == "resume_task":
                    task_id = arguments.get("task_id")
                    resume_all = arguments.get("resume_all", False)
                    if resume_all:
                        mailsh.cmd_task(["resume", "--all"])
                    elif task_id:
                        mailsh.cmd_task(["resume", task_id])
                    else:
                        return CallToolResult(
                            content=[
                                TextContent(
                                    type="text",
                                    text="Error: Must provide either task_id or set resume_all to True",
                                )
                            ],
                            is_error=True,
                        )
                elif tool_name == "end_task":
                    task_id = arguments.get("task_id")
                    end_all = arguments.get("end_all", False)
                    if end_all:
                        mailsh.cmd_task(["end", "--all"])
                    elif task_id:
                        mailsh.cmd_task(["end", task_id])
                    else:
                        return CallToolResult(
                            content=[
                                TextContent(
                                    type="text",
                                    text="Error: Must provide either task_id or set end_all to True",
                                )
                            ],
                            is_error=True,
                        )
                elif tool_name == "clean_tasks":
                    status = arguments.get(
                        "status", ["ended", "completed", "failed", "interrupted"]
                    )
                    cmd_args = ["clean"] + status
                    mailsh.cmd_task(cmd_args)
                elif tool_name == "execute_mailsh_command":
                    command = arguments.get("command", "")
                    if command:
                        # Command interception for interactive commands
                        import shlex

                        parts = shlex.split(command)
                        cmd = parts[0].lower() if parts else ""
                        args = parts[1:] if len(parts) > 1 else []

                        # Intercept interactive commands and redirect to appropriate tools
                        if cmd == "draft":
                            if args and args[0] == "compose":
                                return CallToolResult(
                                    content=[
                                        TextContent(
                                            type="text",
                                            text="The 'draft compose' command requires interactive input. Please use the 'set_email_field' tool to set the email body programmatically.",
                                        )
                                    ],
                                    is_error=True,
                                )
                        elif cmd == "template":
                            if len(args) > 0:
                                subcommand = args[0].lower()
                                if subcommand == "create":
                                    return CallToolResult(
                                        content=[
                                            TextContent(
                                                type="text",
                                                text="The 'template create' command requires a text editor. Please use the 'create_template' tool to create templates programmatically with all content provided as parameters.",
                                            )
                                        ],
                                        is_error=True,
                                    )
                                elif subcommand == "edit":
                                    return CallToolResult(
                                        content=[
                                            TextContent(
                                                type="text",
                                                text="The 'template edit' command requires a text editor and is not supported over MCP. To modify a template, use the 'create_template' tool to create a new version.",
                                            )
                                        ],
                                        is_error=True,
                                    )
                        elif cmd == "profile":
                            if len(args) > 0 and args[0].lower() == "add":
                                return CallToolResult(
                                    content=[
                                        TextContent(
                                            type="text",
                                            text="The 'profile add' command requires interactive input. Please use the 'add_profile' tool to add profiles programmatically with all parameters provided directly.",
                                        )
                                    ],
                                    is_error=True,
                                )
                            elif len(args) > 0 and args[0].lower() == "edit":
                                return CallToolResult(
                                    content=[
                                        TextContent(
                                            type="text",
                                            text="The 'profile edit' command requires interactive input. Please use the 'add_profile' tool to update profiles programmatically with all parameters provided directly.",
                                        )
                                    ],
                                    is_error=True,
                                )
                        elif cmd == "task":
                            if len(args) > 0 and args[0].lower() == "watch":
                                return CallToolResult(
                                    content=[
                                        TextContent(
                                            type="text",
                                            text="The 'task watch' command is not supported over MCP. Please use the 'show_task_details' tool to retrieve task information.",
                                        )
                                    ],
                                    is_error=True,
                                )
                        elif cmd == "set":
                            if len(args) > 0 and args[0].lower() == "body":
                                return CallToolResult(
                                    content=[
                                        TextContent(
                                            type="text",
                                            text="The 'set body' command requires a text editor. Please use the 'set_email_field' tool to set the email body programmatically.",
                                        )
                                    ],
                                    is_error=True,
                                )

                        # If command is not intercepted, re-dispatch to the appropriate command
                        if cmd == "profile":
                            # Handle profile subcommands (connect/disconnect)
                            if args and args[0] in ["connect", "disconnect"]:
                                if args[0] == "connect":
                                    mailsh.cmd_connect(args[1:] if len(args) > 1 else [])
                                elif args[0] == "disconnect":
                                    mailsh.cmd_disconnect(args[1:] if len(args) > 1 else [])
                            else:
                                mailsh.cmd_profile(args)
                        elif cmd == "draft":
                            # Handle draft subcommands (compose/preview/clear)
                            if args and args[0] in ["compose", "preview", "clear"]:
                                if args[0] == "compose":
                                    mailsh.cmd_compose(args[1:] if len(args) > 1 else [])
                                elif args[0] == "preview":
                                    mailsh.cmd_preview(args[1:] if len(args) > 1 else [])
                                elif args[0] == "clear":
                                    mailsh.cmd_clear(args[1:] if len(args) > 1 else [])
                            else:
                                mailsh.cmd_draft(args)
                        elif cmd == "set":
                            mailsh.cmd_set(args)
                        elif cmd == "unset":
                            mailsh.cmd_unset(args)
                        elif cmd == "send":
                            mailsh.cmd_send(args)
                        elif cmd == "template":
                            mailsh.cmd_template(args)
                        elif cmd == "config":
                            mailsh.cmd_config(args)
                        elif cmd == "history":
                            mailsh.cmd_history(args)
                        elif cmd == "schedule":
                            mailsh.cmd_schedule(args)
                        elif cmd == "contacts":
                            mailsh.cmd_contacts(args)
                        elif cmd == "task":
                            mailsh.cmd_task(args)
                        elif cmd == "help":
                            mailsh.cmd_help(args)
                        else:
                            return CallToolResult(
                                content=[
                                    TextContent(
                                        type="text", text=f"Unknown command: {cmd}"
                                    )
                                ],
                                is_error=True,
                            )
                    else:
                        return CallToolResult(
                            content=[
                                TextContent(
                                    type="text",
                                    text="Error: Command string is required",
                                )
                            ],
                            is_error=True,
                        )
                else:
                    return CallToolResult(
                        content=[
                            TextContent(type="text", text=f"Unknown tool: {tool_name}")
                        ],
                        is_error=True,
                    )

        # If we get here, the command executed successfully without raising ConfirmationRequest
        output = stdout_capture.getvalue()
        error = stderr_capture.getvalue()

        # Clean ANSI codes from output
        import re

        def clean_ansi_codes(text):
            ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
            return ansi_escape.sub("", text)

        clean_output = clean_ansi_codes(output)
        clean_error = clean_ansi_codes(error)

        # Combine output and error for MCP return, with error taking precedence if present
        combined_output = clean_output
        if clean_error:
            combined_output = (
                clean_output + "\n" + clean_error if clean_output else clean_error
            )

        return CallToolResult(
            content=[TextContent(type="text", text=combined_output.strip())],
            is_error=bool(clean_error),
        )

    except ConfirmationRequest as e:
        # Command needs confirmation
        # For execute_mailsh_command, we need to enhance the context to include the original command
        # so that when the resume function runs, it knows what command to re-execute
        enhanced_context = e.context
        if tool_name == "execute_mailsh_command":
            # Add the original command that was executed via execute_mailsh_command
            enhanced_context = e.context.copy() if e.context else {}
            enhanced_context["original_execute_command"] = arguments.get("command", "")

        token = state_manager.create_state(
            command_name=tool_name,
            command_args=arguments,
            prompt_message=e.prompt_message,
            context=enhanced_context,
        )
        confirmation_response = {
            "status": "confirmation_required",
            "prompt": e.prompt_message,
            "continuation_token": token,
            "command": tool_name,
            "expires_at": time.time() + state_manager._timeout_seconds,
        }
        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps(confirmation_response))],
            is_error=False,
        )

    except Exception as e:
        return CallToolResult(
            content=[
                TextContent(
                    type="text", text=f"Error executing tool '{tool_name}': {str(e)}"
                )
            ],
            is_error=True,
        )


def execute_mailsh_command_direct(
    mailsh_instance, command: str, args: List[str] = None
):
    """
    Execute a Mailsh command directly by calling the appropriate command handler,
    allowing ConfirmationRequest exceptions to bubble up to be caught by the MCP server.
    """
    import shlex

    if args is None:
        parts = shlex.split(command) if command.strip() else []
        cmd = parts[0].lower() if parts else ""
        args = parts[1:] if len(parts) > 1 else []
    else:
        # If args are already provided, we just need the command name
        parts = shlex.split(command) if command.strip() else []
        cmd = parts[0].lower() if parts else ""

    try:
        # Route to appropriate command handler - this allows ConfirmationRequest to bubble up
        if cmd == "profile":
            with ExecutionMode.mcp_mode():
                # Handle profile subcommands (connect/disconnect)
                if args and args[0] in ["connect", "disconnect"]:
                    if args[0] == "connect":
                        mailsh_instance.cmd_connect(args[1:] if len(args) > 1 else [])
                    elif args[0] == "disconnect":
                        mailsh_instance.cmd_disconnect(args[1:] if len(args) > 1 else [])
                else:
                    mailsh_instance.cmd_profile(args)
        elif cmd == "draft":
            with ExecutionMode.mcp_mode():
                # Handle draft subcommands (compose/preview/clear)
                if args and args[0] in ["compose", "preview", "clear"]:
                    if args[0] == "compose":
                        mailsh_instance.cmd_compose(args[1:] if len(args) > 1 else [])
                    elif args[0] == "preview":
                        mailsh_instance.cmd_preview(args[1:] if len(args) > 1 else [])
                    elif args[0] == "clear":
                        mailsh_instance.cmd_clear(args[1:] if len(args) > 1 else [])
                else:
                    mailsh_instance.cmd_draft(args)
        elif cmd == "set":
            with ExecutionMode.mcp_mode():
                mailsh_instance.cmd_set(args)
        elif cmd == "unset":
            with ExecutionMode.mcp_mode():
                mailsh_instance.cmd_unset(args)
        elif cmd == "send":
            with ExecutionMode.mcp_mode():
                mailsh_instance.cmd_send(args)
        elif cmd == "template":
            with ExecutionMode.mcp_mode():
                mailsh_instance.cmd_template(args)
        elif cmd == "config":
            with ExecutionMode.mcp_mode():
                mailsh_instance.cmd_config(args)
        elif cmd == "history":
            with ExecutionMode.mcp_mode():
                mailsh_instance.cmd_history(args)
        elif cmd == "schedule":
            with ExecutionMode.mcp_mode():
                mailsh_instance.cmd_schedule(args)
        elif cmd == "contacts":
            with ExecutionMode.mcp_mode():
                mailsh_instance.cmd_contacts(args)
        elif cmd == "task":
            with ExecutionMode.mcp_mode():
                mailsh_instance.cmd_task(args)
        elif cmd == "help":
            with ExecutionMode.mcp_mode():
                mailsh_instance.cmd_help(args)
        else:
            if cmd:  # Only show error if there was actually a command provided
                from mcp.types import TextContent, CallToolResult

                return {
                    "output": "",
                    "error": f"Unknown command: {cmd}",
                    "success": False,
                }
            # For empty commands, just return success with no output
            return {"output": "", "error": "", "success": True}

        # If we get here without an exception, the command completed successfully
        from io import StringIO
        import sys
        from contextlib import redirect_stdout, redirect_stderr

        # Capture output to return to MCP client
        stdout_capture = StringIO()
        stderr_capture = StringIO()

        with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
            # Execute again to capture the output
            # This is a simplified approach - in practice, we'd need to refactor the command methods
            # to not print directly but return structured data
            pass  # The command already executed successfully above

        # For now, just return success since the command ran without exceptions
        return {
            "output": stdout_capture.getvalue(),
            "error": stderr_capture.getvalue(),
            "success": True,
        }

    except Exception as e:
        # This catches any other exceptions that aren't ConfirmationRequest
        return {"output": "", "error": str(e), "success": False}


def handle_confirmation(arguments: Dict[str, Any]) -> CallToolResult:
    """Handle confirmation response for continuation tokens."""
    from mcp.types import TextContent, CallToolResult

    token = arguments.get("continuation_token")
    response = arguments.get("response")

    try:
        # Resolve the state
        state = state_manager.resolve_state(token, response)

        # Resume the command
        result = resume_command(state, response)

        return CallToolResult(
            content=[
                TextContent(
                    type="text", text=json.dumps({"status": "success", "data": result})
                )
            ],
            is_error=False,
        )

    except InvalidTokenError as e:
        return CallToolResult(
            content=[
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "status": "error",
                            "error_type": "InvalidTokenError",
                            "message": str(e),
                        }
                    ),
                )
            ],
            is_error=True,
        )
    except Exception as e:
        return CallToolResult(
            content=[
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "status": "error",
                            "error_type": type(e).__name__,
                            "message": str(e),
                        }
                    ),
                )
            ],
            is_error=True,
        )


async def run_server():
    """Run the MCP server over stdio."""
    from mcp.server.stdio import stdio_server
    from mcp.server import InitializationOptions
    from mcp.types import ServerCapabilities, ToolsCapability

    # Create initialization options with required fields
    init_options = InitializationOptions(
        server_name="mailsh-mcp-server",
        server_version="1.0.0",
        capabilities=ServerCapabilities(tools=ToolsCapability()),
    )

    # The stdio_server function should wrap the server and handle stdio streams
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, init_options)


def main():
    """Entry point for the MCP server."""
    try:
        asyncio.run(run_server())
    except KeyboardInterrupt:
        print("\nMCP Server stopped by user.")
    except Exception as e:
        print(f"Error running MCP server: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()
