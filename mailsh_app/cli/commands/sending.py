"""
Email sending and scheduling commands.

Commands: send, send bulk, schedule (send/list/show/cancel/clear)
"""

from pathlib import Path
from typing import Dict, List, Optional, Any
import time
import threading
from datetime import datetime, timedelta
import re
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
from ...utils.email_parser import extract_body
from ...core.config import Config
from ...core.profile import Profile
from ...core.history import History
from ...features.templates import TemplateEngine
from ...core.composer import EmailComposer
from ...core.sender import EmailSender
from ...features.scheduler import ScheduleManager, ScheduledEmail
from ...features.contacts import ContactsManager
from ...features.safety import SafetyFeatureManager
from ...core.tasks import TaskStatus
from ...utils.colors import color_for_schedule_status


class SendingCommands:
    """Mixin class providing sending and scheduling commands."""
    
    def cmd_send(self, args: List[str]):
        """Send current email"""
        if not self.current_profile:
            self._print("Not connected to any profile. Use 'connect <profile>'", "error")
            return
        
        # Check if this is a bulk send operation (subcommand)
        if args and (args[0] == 'bulk'):
            # This is a bulk send operation using the send command with 'bulk' subcommand
            if len(args) < 2:
                self._print("Usage: send bulk --contacts <contact_name> [--dry-run] [--template <name>]", "error")
                return
            
            # Parse args to find flags and the contact name
            # Extract flag values
            all_args = args[1:]  # Skip 'bulk'
            using_contacts = '--contacts' in all_args
            dry_run = '--dry-run' in all_args
            template_name = None
            
            if '--template' in all_args:
                template_idx = all_args.index('--template')
                if template_idx + 1 < len(all_args):
                    template_name = all_args[template_idx + 1]
            
            # For contacts mode, we require the --contacts flag and find the contact name
            if using_contacts:
                # Find the contact name argument (non-flag argument that comes after --contacts)
                contact_name = None
                contacts_idx = all_args.index('--contacts')
                if contacts_idx + 1 < len(all_args):
                    possible_name = all_args[contacts_idx + 1]
                    if not possible_name.startswith('-'):  # Make sure it's not another flag
                        contact_name = possible_name
                
                if not contact_name:
                    self._print("Usage: send bulk --contacts <contact_name> [--dry-run] [--template <name>]", "error")
                    return
                
                success, rows, error = self.contacts_manager.get_contacts(contact_name)
                if not success:
                    self._print(error, "error")
                    return
            else:
                # If --contacts flag is not provided, show error
                self._print("Usage: send bulk --contacts <contact_name> [--dry-run] [--template <name>]", "error")
                return
            
            # Load template if specified
            template_body = None
            if template_name:
                template_body = self.templates.load(template_name)
                if not template_body:
                    self._print(f"Template not found: {template_name}", "error")
                    return
            
            self._print(f"Found {len(rows)} recipients", "info")
            
            # Run safety checks for bulk send before confirmation
            if not dry_run:
                if (self.config.get('safety_features.enabled') if self.config.get('safety_features.enabled') is not None else True):
                    # For bulk send, we need to check the template or base email content
                    check_composer = self.composer
                    if template_name and template_body:
                        # Create temporary composer with template content for safety checks
                        temp_composer = EmailComposer()
                        temp_composer.to = self.composer.to.copy()  # Base recipients from current composer
                        temp_composer.cc = self.composer.cc.copy()
                        temp_composer.bcc = self.composer.bcc.copy()
                        temp_composer.subject = self.composer.subject
                        temp_composer.body = template_body  # Use template content for checking
                        temp_composer.attachments = self.composer.attachments.copy()
                        temp_composer.headers = self.composer.headers.copy()
                        temp_composer.html = self.composer.html
                        check_composer = temp_composer
                    # else: use self.composer as is

                    # Run safety checks on the template/base email content
                    # For bulk send, use the first row as sample data to validate template variables
                    sample_data = rows[0] if rows else None
                    safety_results = self.safety_manager.run_all_checks(
                        check_composer,
                        self.current_profile,
                        template_name,
                        sample_data
                    )
                    
                    # Get unsafe issues
                    safety_issues = self.safety_manager.get_unsafe_issues(safety_results)
                    
                    # If there are unsafe issues, prompt user for confirmation
                    if safety_issues:
                        self._print("Potential safety issues detected in template/base email:", "warning")
                        for i, issue in enumerate(safety_issues, 1):
                            self._print(f"  {i}. {issue}", "warning")
                        
                        if not self.confirm_multiple_actions(
                            f"\nSend bulk emails despite these {len(safety_issues)} safety issue(s)? (y/n): ",
                            context={
                                "action": "bulk_send", 
                                "contact_name": contact_name, 
                                "template_name": template_name, 
                                "dry_run": dry_run,
                                "safety_issues": safety_issues
                            },
                            cancel_message="Bulk send cancelled due to safety issues"
                        ):
                            return
                    else:
                        # If no safety issues, proceed with the normal confirmation
                        if not self.confirm_multiple_actions(
                            f"Send {len(rows)} emails using profile '{self.current_profile}'? (y/n): ",
                            context={"action": "bulk_send", "contact_name": contact_name, "template_name": template_name, "dry_run": dry_run},
                            cancel_message="Bulk send cancelled"
                        ):
                            return
                else:
                    # Safety features disabled - proceed with normal confirmation
                    if not self.confirm_multiple_actions(
                        f"Send {len(rows)} emails using profile '{self.current_profile}'? (y/n): ",
                        context={"action": "bulk_send", "contact_name": contact_name, "template_name": template_name, "dry_run": dry_run},
                        cancel_message="Bulk send cancelled"
                    ):
                        return
            else:
                self._print("Running in DRY-RUN mode (no emails will be sent)", "warning")
            
            # Check if this is a dry run or a regular run
            if dry_run:
                # For dry run, run the old way but without the background task
                profile = self.profiles.get(self.current_profile)
                sender = EmailSender(profile, self.config, task_log_file=None)
                
                delay_between_emails_ms = self.config.get('rate_limiting.delay_between_emails_ms')
                if delay_between_emails_ms is None:
                    delay_between_emails_ms = 1000  # Default value
                rate_limit = delay_between_emails_ms / 1000
                
                retry_attempts_default = self.config.get('bulk_send.retry_attempts')
                retry_attempts = retry_attempts_default if retry_attempts_default is not None else 3
                
                continue_on_error = self.config.get('bulk_send.continue_on_error')
                if continue_on_error is None:
                    continue_on_error = True  # Default value
                
                success_count = 0
                failed_count = 0
                # Helper to create a short single-line snippet from error messages
                def _snippet(text: Optional[str], length: int = 120) -> str:
                    if not text:
                        return ''
                    s = str(text).replace('\n', ' ').replace('\r', ' ').strip()
                    if len(s) <= length:
                        return s
                    return s[:length-1].rstrip() + '…'
                
                print()
                for i, row in enumerate(rows, 1):
                    email = row.get('email', '').strip()
                    
                    if not email:
                        self._print(f"Row {i}: No email address", "warning")
                        continue
                    
                    # Create email from row data
                    temp_composer = EmailComposer()
                    temp_composer.to = [email]
                    temp_composer.subject = row.get('subject', self.composer.subject)
                    
                    # Render template with row data
                    if template_body:
                        temp_composer.body = self.templates.render(template_body, row)
                    else:
                        temp_composer.body = self.templates.render(self.composer.body, row)
                    
                    temp_composer.html = self.composer.html
                    temp_composer.attachments = self.composer.attachments.copy()
                    temp_composer.headers = self.composer.headers.copy()
                    
                    # For dry run
                    print(f"[{i}/{len(rows)}] Would send to: {email}")
                    success_count += 1
                
                # Summary for dry run
                print("\n" + "="*70)
                self._print("DRY RUN COMPLETE", "theme")
                print("="*70)
                print(f"Total: {len(rows)}")
                print(f"Would send: {success_count}")
                print(f"Failed: {failed_count}")
                print("="*70 + "\n")
            else:
                # Start background task instead of running synchronously
                task_id = self.task_manager.create_task_id()
                
                # Create a copy of the current profile data for the task
                profile = self.profiles.get(self.current_profile)
                
                # Start the background task
                success = self.task_manager.start_bulk_send_task(
                    task_id=task_id,
                    profile=profile,
                    config=self.config,
                    composer=self.composer,
                    contact_name=contact_name,
                    template_name=template_name,
                    profile_name=self.current_profile,
                    dry_run=False,
                    original_schedule_id=None,
                    scheduled_manager=None
                )
                
                if success:
                    self._print(f"Started background sending task {task_id}", "success")
                    self._print(f"Use 'task' command to manage tasks", "info")
                else:
                    self._print(f"Failed to start background task", "error")
                    # Fallback to synchronous execution if background task fails
                    # (this shouldn't happen under normal circumstances)
                    profile = self.profiles.get(self.current_profile)
                    sender = EmailSender(profile, self.config, task_log_file=None)
                    
                    delay_between_emails_ms = self.config.get('rate_limiting.delay_between_emails_ms')
                    if delay_between_emails_ms is None:
                        delay_between_emails_ms = 1000  # Default value
                    rate_limit = delay_between_emails_ms / 1000
                    
                    retry_attempts_default = self.config.get('bulk_send.retry_attempts')
                    retry_attempts = retry_attempts_default if retry_attempts_default is not None else 3
                    
                    continue_on_error = self.config.get('bulk_send.continue_on_error')
                    if continue_on_error is None:
                        continue_on_error = True  # Default value
                    
                    success_count = 0
                    failed_count = 0
                    # Helper to create a short single-line snippet from error messages
                    def _snippet(text: Optional[str], length: int = 120) -> str:
                        if not text:
                            return ''
                        s = str(text).replace('\n', ' ').replace('\r', ' ').strip()
                        if len(s) <= length:
                            return s
                        return s[:length-1].rstrip() + '…'
                    
                    print()
                    for i, row in enumerate(rows, 1):
                        email = row.get('email', '').strip()
                        
                        if not email:
                            self._print(f"Row {i}: No email address", "warning")
                            continue
                        
                        # Create email from row data
                        temp_composer = EmailComposer()
                        temp_composer.to = [email]
                        temp_composer.subject = row.get('subject', self.composer.subject)
                        
                        # Render template with row data
                        if template_body:
                            temp_composer.body = self.templates.render(template_body, row)
                        else:
                            temp_composer.body = self.templates.render(self.composer.body, row)
                        
                        temp_composer.html = self.composer.html
                        temp_composer.attachments = self.composer.attachments.copy()
                        temp_composer.headers = self.composer.headers.copy()
                        
                        print(f"[{i}/{len(rows)}] Sending to: {email}...", end=' ')
                        success, message, smtp_response = sender.send(temp_composer)
                        
                        # Log to history
                        history_entry = {
                            "timestamp": datetime.now().isoformat(),
                            "profile": self.current_profile,
                            "to": [email],
                            "subject": temp_composer.subject,
                            "status": "sent" if success else "failed",
                            "message": message,
                            "smtp_response": smtp_response,
                            "bulk_send": True
                        }
                        self.history.add(history_entry)
                        
                        if success:
                            self._print("✓", "success")
                            success_count += 1
                        else:
                            # Show a short snippet of the error to aid debugging inline
                            snippet = _snippet(message or smtp_response)
                            if snippet:
                                self._print(f"✗ FAILED ({snippet})", "error")
                            else:
                                self._print(f"✗ FAILED", "error")
                            failed_count += 1
                            if not continue_on_error:
                                self._print("\nStopping bulk send due to error", "error")
                                break
                    
                        # Rate limiting
                        if success and i < len(rows):
                            time.sleep(rate_limit)
                        
                        if not continue_on_error and failed_count > 0:
                            break
                    
                    # Summary
                    print("\n" + "="*70)
                    self._print("BULK SEND COMPLETE", "theme")
                    print("="*70)
                    print(f"Total: {len(rows)}")
                    print(f"Sent: {success_count}")
                    print(f"Failed: {failed_count}")
                    if success_count > 0:
                        print(f"Success Rate: {(success_count/(success_count+failed_count)*100):.1f}%")
                    print("="*70 + "\n")
        
        else:
            # Regular send operation
            # Parse template flag
            template_name = None
            # Need to handle template flag even when there are subcommands
            if '--template' in args:
                template_idx = args.index('--template')
                if template_idx + 1 < len(args):
                    template_name = args[template_idx + 1]
                else:
                    self._print("Usage: send --template <template_name>", "error")
                    return
            
            # Check if we have no recipients for regular send
            if not self.composer.to and not args and not template_name:
                self._print("No recipients specified", "error")
                self._print("Use 'set to <emails>' or 'compose' to add recipients", "info")
                return
            
            # If we have args but not a valid flag, it's an error for regular send
            if args and args[0] != '--template':
                self._print(f"Unknown subcommand: {args[0]}", "error")
                self._print("Usage: send [--template <name>] or send bulk --contacts <contact_name>", "info")
                return
            
            # Load template if specified
            if template_name:
                template_body = self.templates.load(template_name)
                if not template_body:
                    self._print(f"Template not found: {template_name}", "error")
                    self._print("Use 'template list' to see available templates", "info")
                    return
            
            if not self.composer.subject and not self.composer.body and not template_name:
                self._print("Email has no content", "warning")
            
            # Validation
            if self.config.get('validation.check_email_format'):
                for email in self.composer.to + self.composer.cc + self.composer.bcc:
                    if not self._validate_email(email):
                        self._print(f"Invalid email address: {email}", "error")
                        return
            
            # Run safety checks before preview
            safety_issues = []
            if (self.config.get('safety_features.enabled') if self.config.get('safety_features.enabled') is not None else True):
                # Determine which composer to use for safety checks
                check_composer = self.composer
                if template_name:
                    # Create temporary composer with template for safety checks
                    temp_composer = EmailComposer()
                    temp_composer.to = self.composer.to.copy()
                    temp_composer.cc = self.composer.cc.copy()
                    temp_composer.bcc = self.composer.bcc.copy()
                    temp_composer.subject = self.composer.subject
                    temp_composer.body = self.templates.load(template_name) or self.composer.body
                    temp_composer.attachments = self.composer.attachments.copy()
                    temp_composer.headers = self.composer.headers.copy()
                    temp_composer.html = self.composer.html
                    check_composer = temp_composer

                # Run safety checks
                safety_results = self.safety_manager.run_all_checks(
                    check_composer, 
                    self.current_profile, 
                    template_name
                )
                
                # Get unsafe issues
                safety_issues = self.safety_manager.get_unsafe_issues(safety_results)

            # Show preview or handle safety issues
            if safety_issues:
                self._print("Potential safety issues detected:", "warning")
                for i, issue in enumerate(safety_issues, 1):
                    self._print(f"  {i}. {issue}", "warning")
                
                if not self.confirm_action(
                    f"\nSend email despite these {len(safety_issues)} safety issue(s)? (y/n): ",
                    context={
                        "action": "send_email", 
                        "template_name": template_name,
                        "safety_issues": safety_issues
                    },
                    cancel_message="Send cancelled due to safety issues"
                ):
                    return
            else:
                # Show preview
                self._print(f"\nSending to {len(self.composer.to)} recipient(s):", "warning")
                print(f"  To: {", ".join(self.composer.to)}")
                if self.composer.cc:
                    print(f"  Cc: {", ".join(self.composer.cc)}")
                if self.composer.bcc:
                    print(f"  Bcc: {", ".join(self.composer.bcc)}")
                print(f"  Subject: {self.composer.subject}")
                if template_name:
                    print(f"  Template: {template_name}")
            
                # Confirm using universal method
                if not self.confirm_action(
                    "\nConfirm send? (y/n): ",
                    context={"action": "send_email", "template_name": template_name},
                    cancel_message="Send cancelled"
                ):
                    return
            # Send
            profile = self.profiles.get(self.current_profile)
            sender = EmailSender(profile, self.config, task_log_file=None)
            
            # Use template if specified, otherwise use current composer
            if template_name:
                # Create a temporary composer with template content
                temp_composer = EmailComposer()
                temp_composer.to = self.composer.to.copy()
                temp_composer.cc = self.composer.cc.copy()
                temp_composer.bcc = self.composer.bcc.copy()
                temp_composer.subject = self.composer.subject
                temp_composer.body = template_body
                temp_composer.attachments = self.composer.attachments.copy()
                temp_composer.headers = self.composer.headers.copy()
                temp_composer.html = self.composer.html
                
                self._print("Sending...", "info")
                success, message, smtp_response = sender.send(temp_composer)
            else:
                self._print("Sending...", "info")
                success, message, smtp_response = sender.send(self.composer)
            
            # Log to history
            history_entry = {
                "timestamp": datetime.now().isoformat(),
                "profile": self.current_profile,
                "to": self.composer.to,
                "cc": self.composer.cc,
                "bcc": self.composer.bcc,
                "subject": self.composer.subject,
                "status": "sent" if success else "failed",
                "message": message,
                "smtp_response": smtp_response
            }
            self.history.add(history_entry)
            
            if success:
                self._print(message, "success")
                self.composer.reset()
                self._save_session()
            else:
                self._print(message, "error")
    
    def cmd_schedule(self, args: List[str]):
        """Schedule emails for later sending"""
        if not args:
            self._print("Usage: schedule <send|list|show|cancel|clear> [options]", "error")
            self._print("Type 'help schedule' for more information", "info")
            return
        
        action = args[0].lower()
        
        if action == "send":
            if not self.current_profile:
                self._print("Not connected to any profile. Use 'connect <profile>'", "error")
                return
            
            # Check if --contacts flag is present to enable bulk send mode
            using_contacts = '--contacts' in args
            
            if not using_contacts and not self.composer.to:
                self._print("No recipients specified", "error")
                self._print("Use 'set to <emails>' or 'compose' to add recipients", "info")
                return
            
            if len(args) < 2:
                if using_contacts:
                    self._print("Usage: schedule send <time_spec> --contacts <contact_name> [--template <name>]", "error")
                else:
                    self._print("Usage: schedule send <time_spec> [--template <name>]", "error")
                self._print("Time specs: '30m', '2h', '1d', '2025-12-25 14:30', 'tomorrow', etc.", "info")
                return
            
            # Parse template flag if present
            template_name = None
            contact_name = None
            
            # Process all flags
            time_parts = []
            i = 1
            while i < len(args):
                if args[i] == '--template' and i + 1 < len(args):
                    template_name = args[i + 1]
                    i += 2  # Skip flag and value
                elif args[i] == '--contacts' and i + 1 < len(args):
                    contact_name = args[i + 1]
                    i += 2  # Skip flag and value
                elif args[i] == '--template':
                    self._print("Usage: schedule send <time_spec> [--template <name>] [--contacts <contact_name>]", "error")
                    return
                elif args[i] == '--contacts':
                    self._print("Usage: schedule send <time_spec> [--template <name>] [--contacts <contact_name>]", "error")
                    return
                else:
                    time_parts.append(args[i])
                    i += 1
            
            # Extract time spec from remaining parts
            if len(time_parts) == 0:
                self._print("Usage: schedule send <time_spec> [--template <name>] [--contacts <contact_name>]", "error")
                return
            elif len(time_parts) == 1:
                time_spec = time_parts[0]
            else:
                # Handle multi-word time specs
                time_spec = ' '.join(time_parts)
            
            # Parse the time specification
            send_time = None
            # First try time offset format
            send_time = self._parse_time_offset(time_spec)
            if not send_time:
                # Try specific date/time format
                send_time = self._parse_date_time(time_spec)
            
            if not send_time:
                self._print(f"Could not parse time specification: {time_spec}", "error")
                self._print("Examples: '30m', '2h', 'tomorrow', '2025-12-25 14:30', 'next friday'", "info")
                return
            
            # Check if the time is in the past
            if send_time <= datetime.now():
                self._print(f"Scheduled time is in the past: {send_time.strftime('%Y-%m-%d %H:%M:%S')}", "error")
                return
            
            # Load template if specified
            if template_name:
                template_body = self.templates.load(template_name)
                if not template_body:
                    self._print(f"Template not found: {template_name}", "error")
                    return
            
            # Handle bulk send with contacts if --contacts flag is provided
            if contact_name:
                # Get contacts
                success, rows, error = self.contacts_manager.get_contacts(contact_name)
                if not success:
                    self._print(error, "error")
                    return
                
                # Run safety checks for scheduled bulk send before creating the scheduled task
                if (self.config.get('safety_features.enabled') if self.config.get('safety_features.enabled') is not None else True):
                    # For scheduled bulk send, we need to check the template with contact data
                    check_composer = self.composer
                    if template_name and 'template_body' in locals() and template_body:
                        # Create temporary composer with template for safety checks
                        temp_composer = EmailComposer()
                        temp_composer.to = self.composer.to.copy()  # Base recipients from current composer
                        temp_composer.cc = self.composer.cc.copy()
                        temp_composer.bcc = self.composer.bcc.copy()
                        temp_composer.subject = self.composer.subject
                        temp_composer.body = template_body  # Use template content for checking
                        temp_composer.attachments = self.composer.attachments.copy()
                        temp_composer.headers = self.composer.headers.copy()
                        temp_composer.html = self.composer.html
                        check_composer = temp_composer

                    # Run safety checks - use first row as sample data to validate template variables
                    sample_data = rows[0] if rows else None
                    safety_results = self.safety_manager.run_all_checks(
                        check_composer,
                        self.current_profile,
                        template_name,
                        sample_data
                    )

                    # Get unsafe issues
                    safety_issues = self.safety_manager.get_unsafe_issues(safety_results)

                    # If there are unsafe issues, prompt user for confirmation
                    if safety_issues:
                        self._print("Potential safety issues detected in scheduled bulk email:", "warning")
                        for i, issue in enumerate(safety_issues, 1):
                            self._print(f"  {i}. {issue}", "warning")

                        if not self.confirm_action(
                            f"\nSchedule bulk email despite these {len(safety_issues)} safety issue(s)? (y/n): ",
                            context={
                                "action": "schedule_send_bulk",
                                "contact_name": contact_name,
                                "template_name": template_name,
                                "safety_issues": safety_issues
                            },
                            cancel_message="Scheduled bulk email cancelled due to safety issues"
                        ):
                            return
                
                self._print(f"Found {len(rows)} recipients in contact list '{contact_name}'", "info")
                
                # Copy resources to temp directory to prevent issues if original resources are removed
                # This ensures scheduled tasks will still work even if contacts/templates are deleted
                temp_resources = self._copy_scheduled_resources(
                    contact_name=contact_name,
                    template_name=template_name,
                    attachments=self.composer.attachments
                )
                
                # Create a single scheduled task that will be converted to a regular task when the time arrives
                import string
                import random
                schedule_id = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
                
                # Prepare composer data for the bulk operation
                # We'll store the original composer and the contact list name
                composer_data = self.composer.to_dict()
                composer_data["contact_list_name"] = contact_name  # Store contact list name for later use
                if template_name:
                    composer_data["template_name"] = template_name  # Store template name for later use
                
                # Store temporary resource information so we know what to use when the task executes
                composer_data["temp_resources"] = temp_resources
                
                # Confirm before scheduling bulk operation
                if not self.confirm_action(
                    f"\nSchedule bulk operation for {send_time.strftime('%Y-%m-%d %H:%M:%S')} with {len(rows)} recipients? (y/n): ",
                    context={
                        "action": "schedule_send_bulk",
                        "schedule_id": schedule_id,
                        "send_time": send_time.isoformat(),
                        "contact_name": contact_name,
                        "recipient_count": len(rows)
                    },
                    cancel_message="Bulk operation scheduling cancelled"
                ):
                    return

                # Create a single scheduled task (with is_bulk_operation=True)
                scheduled_task = ScheduledEmail(
                    id=schedule_id,
                    composer_data=composer_data,
                    send_time=send_time,
                    profile_name=self.current_profile,
                    is_bulk_operation=True  # Mark as bulk operation to be handled differently by scheduler
                )
                
                # Add the scheduled task to the scheduler
                self.scheduled_manager.add(scheduled_task)
                
                self._print(f"Bulk operation scheduled for {send_time.strftime('%Y-%m-%d %H:%M:%S')} (ID: {schedule_id}). Will push to tasks upon due time.", "success")
                
            else:
                # Regular schedule send (non-bulk)
                
                # Run safety checks for scheduled email before scheduling
                if (self.config.get('safety_features.enabled') if self.config.get('safety_features.enabled') is not None else True):
                    # Determine which composer to use for safety checks
                    check_composer = self.composer
                    if template_name and template_body:
                        # Create temporary composer with template for safety checks
                        temp_composer = EmailComposer()
                        temp_composer.to = self.composer.to.copy()
                        temp_composer.cc = self.composer.cc.copy()
                        temp_composer.bcc = self.composer.bcc.copy()
                        temp_composer.subject = self.composer.subject
                        temp_composer.body = template_body  # Use template content for checking
                        temp_composer.attachments = self.composer.attachments.copy()
                        temp_composer.headers = self.composer.headers.copy()
                        temp_composer.html = self.composer.html
                        check_composer = temp_composer

                    # Run safety checks
                    safety_results = self.safety_manager.run_all_checks(
                        check_composer, 
                        self.current_profile, 
                        template_name
                    )
                    
                    # Get unsafe issues
                    safety_issues = self.safety_manager.get_unsafe_issues(safety_results)
                    
                    # If there are unsafe issues, prompt user for confirmation
                    if safety_issues:
                        self._print("Potential safety issues detected in scheduled email:", "warning")
                        for i, issue in enumerate(safety_issues, 1):
                            self._print(f"  {i}. {issue}", "warning")
                        
                        if not self.confirm_action(
                            f"\nSchedule email despite these {len(safety_issues)} safety issue(s)? (y/n): ",
                            context={
                                "action": "schedule_send", 
                                "template_name": template_name,
                                "safety_issues": safety_issues
                            },
                            cancel_message="Email scheduling cancelled due to safety issues"
                        ):
                            return

                import string
                import random
                schedule_id = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
                
                # Prepare composer data (use template if specified)
                composer_data = self.composer.to_dict()
                if template_name and template_body:
                    # Use the template body temporarily to create the scheduled email
                    composer_data["body"] = template_body  # This will be rendered when actually sent
                
                # Confirm before scheduling
                if not self.confirm_action(
                    f"\nSchedule email for {send_time.strftime('%Y-%m-%d %H:%M:%S')}? (y/n): ",
                    context={
                        "action": "schedule_send",
                        "schedule_id": schedule_id,
                        "send_time": send_time.isoformat()
                    },
                    cancel_message="Email scheduling cancelled"
                ):
                    return

                scheduled_email = ScheduledEmail(
                    id=schedule_id,
                    composer_data=composer_data,
                    send_time=send_time,
                    profile_name=self.current_profile
                )
                
                # Add to scheduler
                self.scheduled_manager.add(scheduled_email)
                
                self._print(f"Email scheduled for {send_time.strftime('%Y-%m-%d %H:%M:%S')} (ID: {schedule_id})", "success")
            
        elif action == "list":
            scheduled_emails = self.scheduled_manager.get_all()
            if not scheduled_emails:
                self._print("No scheduled emails", "info")
                return
            
            # Parse flags for pagination
            top_count = None
            bottom_count = None
            show_all = False
            
            if len(args) > 1:
                i = 1
                while i < len(args):
                    if args[i] == "--top" and i + 1 < len(args):
                        try:
                            top_count = int(args[i + 1])
                            if top_count <= 0:
                                self._print("Error: Count must be positive", "error")
                                return
                            i += 2
                        except ValueError:
                            self._print("Usage: schedule list --top <count>", "error")
                            return
                    elif args[i] == "--bottom" and i + 1 < len(args):
                        try:
                            bottom_count = int(args[i + 1])
                            if bottom_count <= 0:
                                self._print("Error: Count must be positive", "error")
                                return
                            i += 2
                        except ValueError:
                            self._print("Usage: schedule list --bottom <count>", "error")
                            return
                    elif args[i] == "--all":
                        show_all = True
                        i += 1
                    else:
                        self._print("Usage: schedule list [--top <count> | --bottom <count> | --all]", "error")
                        return
            
            # Determine which emails to display
            if show_all:
                display_emails = scheduled_emails
            elif top_count:
                display_emails = scheduled_emails[:top_count]
            elif bottom_count:
                display_emails = scheduled_emails[-bottom_count:]
            else:
                # Default: show last 20
                display_emails = scheduled_emails[-20:] if len(scheduled_emails) > 20 else scheduled_emails
            
            import re

            def strip_ansi_codes(s: str) -> str:
                ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
                return ansi_escape.sub('', s)

            def pad_with_ansi(text_with_ansi: str, total_width: int, align: str = 'left') -> str:
                """Pad text which may contain ANSI sequences to a visual width."""
                clean_text = strip_ansi_codes(text_with_ansi)
                padding_needed = total_width - len(clean_text)
                if padding_needed <= 0:
                    return text_with_ansi
                if align == 'left':
                    return text_with_ansi + ' ' * padding_needed
                elif align == 'right':
                    return ' ' * padding_needed + text_with_ansi
                else:
                    left_pad = padding_needed // 2
                    right_pad = padding_needed - left_pad
                    return ' ' * left_pad + text_with_ansi + ' ' * right_pad

            print("\n" + "="*140)
            self._print("SCHEDULED EMAILS", "theme")
            print("="*140)
            print(f"{'ID':<8} {'Time':<20} {'Status':<12} {'Profile':<15} {'Recipients':<25} {'Subject':<35} {'TASK ID':<10}")
            print("-"*140)
            
            for email in display_emails:
                time_str = email.send_time.strftime('%Y-%m-%d %H:%M:%S')
                status_str = email.status
                profile_str = email.profile_name
                task_id_str = ""  # Initialize task ID string
                
                # Check if this is a bulk operation that has been converted and has an associated task
                if email.is_bulk_operation and email.status == "converted_to_task":
                    # Check if the corresponding task is running or has completed
                    converted_task_id = email.composer_data.get('converted_task_id')
                    if converted_task_id and hasattr(self, 'task_manager') and self.task_manager:
                        task_info = self.task_manager.load_task_info(converted_task_id)
                        if task_info:
                            # Map task status to display status for scheduled emails
                            if task_info.status == TaskStatus.RUNNING:
                                status_str = 'started'
                                task_id_str = converted_task_id  # Show the task ID for started tasks
                            elif task_info.status == TaskStatus.COMPLETED:
                                status_str = 'completed'
                            elif task_info.status == TaskStatus.FAILED:
                                status_str = 'failed'
                            elif task_info.status == TaskStatus.ENDED:
                                status_str = 'cancelled'
                            elif task_info.status == TaskStatus.PAUSED:
                                status_str = 'started(paused)'
                                task_id_str = converted_task_id  # Show the task ID for paused tasks
                            elif task_info.status == TaskStatus.INTERRUPTED:
                                status_str = 'started(interrupted)'
                                task_id_str = converted_task_id  # Show the task ID for interrupted tasks
                        else:
                            # If task info is not found (e.g., task was cleaned up), the scheduled email
                            # should have had its status updated by the clean_tasks method to reflect 
                            # the final status of the task before it was removed. If it still has 
                            # "converted_to_task", it means there was an issue updating the status 
                            # when the task completed. In this case, we still shouldn't display the 
                            # internal status to users, so we'll default to 'completed' as the 
                            # most likely outcome for a task that was converted and started.
                            status_str = 'completed'
                
                to_emails = email.composer_data.get('to', [])
                
                # For bulk operations, show contact list name and count instead of individual recipients
                if email.is_bulk_operation:
                    contact_list_name = email.composer_data.get('contact_list_name', 'unknown')
                    # Get contact count if possible
                    contact_count = 0
                    if hasattr(self, 'contacts_manager') and self.contacts_manager:
                        success, rows, error = self.contacts_manager.get_contacts(contact_list_name)
                        if success:
                            contact_count = len(rows)
                    to_str = f"{contact_list_name} ({contact_count})"
                else:
                    to_str = ', '.join(to_emails[:2]) + ('...' if len(to_emails) > 2 else '')  # Show first 2 emails, then ...
                
                subject_str = email.composer_data.get('subject', 'No Subject')
                
                # Truncate subject if too long
                if len(subject_str) > 32:
                    subject_str = subject_str[:32] + '...'
                
                # Use centralized schedule status coloring (and pad ANSI sequences correctly)
                status_color = color_for_schedule_status(status_str, task_info if 'task_info' in locals() else None)
                status_padded = pad_with_ansi(status_color, 12, 'left')

                print(f"{email.id:<8} {time_str:<20} {status_padded} {profile_str:<15} {to_str:<25} {subject_str:<35} {task_id_str:<10}")
            
            print("="*140 + "\n")
            
            # Count started tasks to display at the bottom
            started_tasks_count = 0
            first_started_task_info = None
            
            for email in display_emails:
                # Check if this is a started task that has an associated task ID
                if (email.is_bulk_operation and email.status == "converted_to_task"):
                    converted_task_id = email.composer_data.get('converted_task_id')
                    if converted_task_id and hasattr(self, 'task_manager') and self.task_manager:
                        task_info = self.task_manager.load_task_info(converted_task_id)
                        if task_info and task_info.status in [TaskStatus.RUNNING, TaskStatus.PAUSED, TaskStatus.INTERRUPTED]:
                            started_tasks_count += 1
                            # Store info about the first started task for single task message
                            if started_tasks_count == 1:
                                first_started_task_info = {
                                    'schedule_id': email.id,
                                    'task_id': converted_task_id
                                }
            
            # Display information about started tasks if any exist
            if started_tasks_count == 1 and first_started_task_info:
                self._print(f"Schedule task {first_started_task_info['schedule_id']} started at task {first_started_task_info['task_id']}, use 'task show {first_started_task_info['task_id']}' to manage", "info")
            elif started_tasks_count > 1:
                self._print(f"{started_tasks_count} scheduled tasks started, use 'task' command to manage", "info")
            
            # Print summary if not showing all
            if not show_all and len(scheduled_emails) > len(display_emails):
                self._print(f"Showing {len(display_emails)} of {len(scheduled_emails)} scheduled emails", "info")
                self._print(f"Use 'schedule list --all' to see all emails", "info")
            
        elif action == "show":
            if len(args) < 2:
                self._print("Usage: schedule show <id>", "error")
                return
            
            schedule_id = args[1]
            scheduled_email = self.scheduled_manager.get(schedule_id)
            if not scheduled_email:
                self._print(f"No scheduled email found with ID: {schedule_id}", "error")
                return
            
            print("\n" + "="*50)
            self._print(f"SCHEDULED EMAIL DETAILS (ID: {schedule_id})", "theme")
            print("="*50)
            print(f"Send Time:     {scheduled_email.send_time}")
            print(f"Profile:       {scheduled_email.profile_name}")
            
            # Check if this is a bulk operation that has been converted and has an associated task
            status_display = scheduled_email.status
            if scheduled_email.is_bulk_operation and scheduled_email.status == "converted_to_task":
                # Check if the corresponding task is running or has completed
                converted_task_id = scheduled_email.composer_data.get('converted_task_id')
                if converted_task_id and hasattr(self, 'task_manager') and self.task_manager:
                    # Look for the specific task ID that was created when this was converted
                    task_info = self.task_manager.load_task_info(converted_task_id)
                    if task_info:
                        # Map task status to display status for scheduled emails
                        if task_info.status == TaskStatus.RUNNING:
                            status_display = 'started'
                            colored = color_for_schedule_status('started', task_info)
                            print(f"Status:        {colored} (managed by task {converted_task_id}, use 'task show {converted_task_id}' to monitor)")
                        elif task_info.status == TaskStatus.COMPLETED:
                            status_display = 'completed'
                            colored = color_for_schedule_status('completed', task_info)
                            print(f"Status:        {colored} (task {converted_task_id} finished, sent {task_info.success_count} emails)")
                        elif task_info.status == TaskStatus.FAILED:
                            status_display = 'failed'
                            failure_reason = f" ({task_info.failure_reason})" if task_info.failure_reason else ""
                            colored = color_for_schedule_status('failed', task_info)
                            print(f"Status:        {colored}{failure_reason} (task {converted_task_id}, use 'task show {converted_task_id}' to see details)")
                        elif task_info.status == TaskStatus.ENDED:
                            status_display = 'cancelled'
                            colored = color_for_schedule_status('cancelled', task_info)
                            print(f"Status:        {colored} (task {converted_task_id} was cancelled)")
                        elif task_info.status == TaskStatus.PAUSED:
                            status_display = 'started(paused)'
                            # Use centralized schedule coloring helper
                            colored_status = color_for_schedule_status(status_display, task_info)
                            print(f"Status:        {colored_status} (task {converted_task_id}, use 'task show {converted_task_id}' to monitor)")
                        elif task_info.status == TaskStatus.INTERRUPTED:
                            status_display = 'started(interrupted)'
                            # Use centralized schedule coloring helper
                            colored_status = color_for_schedule_status(status_display, task_info)
                            print(f"Status:        {colored_status} (task {converted_task_id} was interrupted, use 'task show {converted_task_id}' to monitor)")
                        else:
                            print(f"Status:        {scheduled_email.status}")
                    else:
                        # If task info is not found (e.g., task was cleaned up), the scheduled email
                        # should have had its status updated by the clean_tasks method to reflect 
                        # the final status of the task before it was removed. If it still has 
                        # "converted_to_task", it means there was an issue updating the status 
                        # when the task completed. In this case, we still shouldn't display the 
                        # internal status to users, so we'll default to 'completed' as the 
                        # most likely outcome for a task that was converted and started.
                        status_display = 'completed'
                        print(f"Status:        completed (original task {converted_task_id} has been cleaned up)")
                else:
                    print(f"Status:        {scheduled_email.status}")
            else:
                # Use centralized schedule coloring for display
                if status_display == 'failed':
                    colored_status = color_for_schedule_status('failed', None)
                    failure_reason = f" ({scheduled_email.failure_reason})" if getattr(scheduled_email, 'failure_reason', None) else ""
                    print(f"Status:        {colored_status}{failure_reason}")
                else:
                    colored_status = color_for_schedule_status(status_display, None)
                    # If the helper returned an uncolored string (fallback), print raw status_display
                    if isinstance(colored_status, str):
                        print(f"Status:        {colored_status}")
                    else:
                        print(f"Status:        {status_display}")
            
            print(f"Created:       {scheduled_email.created_at}")
            
            # For bulk operations, show contact list information instead of individual recipients
            if scheduled_email.is_bulk_operation:
                contact_list_name = scheduled_email.composer_data.get('contact_list_name', 'unknown')
                print(f"Contact List:  {contact_list_name}")
            else:
                print(f"Recipients:    {scheduled_email.composer_data.get('to', [])}")
            
            if scheduled_email.composer_data.get('cc'):
                print(f"CC:            {scheduled_email.composer_data.get('cc')}")
            if scheduled_email.composer_data.get('bcc'):
                print(f"BCC:           {scheduled_email.composer_data.get('bcc')}")
            print(f"Subject:       {scheduled_email.composer_data.get('subject', 'N/A')}")
            print(f"Attachments:   {len(scheduled_email.composer_data.get('attachments', []))}")
            print(f"HTML:          {scheduled_email.composer_data.get('html', False)}")
            print("="*50 + "\n")
            
        elif action == "cancel":
            if len(args) < 2:
                self._print("Usage: schedule cancel <id> OR schedule cancel --all", "error")
                return
            
            # Check if --all flag is used
            if args[1] == "--all":
                scheduled_emails = self.scheduled_manager.get_upcoming()
                if not scheduled_emails:
                    self._print("No upcoming scheduled emails to cancel", "info")
                    return
                
                if not self.confirm_multiple_actions(
                    f"Cancel all {len(scheduled_emails)} upcoming scheduled emails? (y/n): ",
                    context={"action": "schedule_cancel_all", "count": len(scheduled_emails)},
                    cancel_message="Cancellations cancelled"
                ):
                    return
                
                cancelled_count = 0
                for email in scheduled_emails:
                    # Check if this is a bulk operation that has already been converted to a task
                    if email.is_bulk_operation and email.status == "converted_to_task":
                        # Skip this email as it's already started
                        continue
                    elif email.status == "scheduled":  # Only cancel scheduled (not already cancelled/failed/sent/converted_to_task)
                        email.status = "cancelled"
                        self.scheduled_manager.add(email)
                        cancelled_count += 1
                
                self._print(f"Cancelled {cancelled_count} scheduled emails", "success")
            else:
                schedule_id = args[1]
                scheduled_email = self.scheduled_manager.get(schedule_id)
                if not scheduled_email:
                    self._print(f"No scheduled email found with ID: {schedule_id}", "error")
                    return
                
                # Check if this is a bulk operation that has already been converted to a task
                if scheduled_email.is_bulk_operation and scheduled_email.status == "converted_to_task":
                    # Check if the corresponding task exists and is running/active
                    converted_task_id = scheduled_email.composer_data.get('converted_task_id')
                    if converted_task_id and hasattr(self, 'task_manager') and self.task_manager:
                        task_info = self.task_manager.load_task_info(converted_task_id)
                        if task_info and task_info.status in ['running', 'paused', 'interrupted']:
                            # Task is already started, so schedule cancel won't work
                            self._print(f"Scheduled task '{schedule_id}' already started with task id '{converted_task_id}', run 'task end {converted_task_id}' to cancel.", "warning")
                            return
                
                # For regular scheduled emails or already-completed converted tasks, proceed with cancellation
                if scheduled_email.status == "scheduled":
                    # Confirm cancellation
                    if not self.confirm_action(
                        f"Cancel scheduled email '{schedule_id}'? (y/n): ",
                        context={"action": "schedule_cancel_single", "schedule_id": schedule_id},
                        cancel_message="Cancellation cancelled"
                    ):
                        return
                    
                    # Update status instead of removing completely, to maintain history
                    scheduled_email.status = "cancelled"
                    self.scheduled_manager.add(scheduled_email)  # This will update it
                    self._print(f"Scheduled email '{schedule_id}' cancelled", "success")
                else:
                    # Check if the scheduled email has a status other than scheduled
                    if scheduled_email.status in ["cancelled", "failed", "sent", "completed"]:
                        self._print(f"Scheduled email '{schedule_id}' already has status '{scheduled_email.status}'", "info")
                    elif scheduled_email.status == "converted_to_task":
                        # This case should have been handled above, but just in case
                        converted_task_id = scheduled_email.composer_data.get('converted_task_id')
                        if converted_task_id:
                            self._print(f"Scheduled task '{schedule_id}' already started with task id '{converted_task_id}', run 'task end {converted_task_id}' to cancel.", "warning")
                        else:
                            self._print(f"Scheduled email '{schedule_id}' has status '{scheduled_email.status}' but no associated task ID", "warning")
                    else:
                        self._print(f"Scheduled email '{schedule_id}' has status '{scheduled_email.status}' and cannot be cancelled", "warning")
            
        elif action == "clear":
            # Check if --status flag is used
            status_filter = None
            if len(args) > 1 and args[1] == "--status":
                if len(args) < 3:
                    # Reflect available clearable statuses (exclude 'scheduled')
                    self._print("Usage: schedule clear --status <status> (status: cancelled, failed, sent)", "error")
                    return
                status_filter = args[2]
                valid_statuses = ['cancelled', 'failed', 'sent']
                if status_filter not in valid_statuses:
                    self._print(f"Invalid status. Valid statuses: {', '.join(valid_statuses)}", "error")
                    return
            
            if status_filter:
                # Get all emails with the specified status
                all_emails = self.scheduled_manager.get_all()
                scheduled_emails = [email for email in all_emails if email.status == status_filter]
            else:
                # Get all emails (clear everything) but filter out active running tasks
                all_emails = self.scheduled_manager.get_all()
                # Filter out emails that are bulk operations with status "converted_to_task" and have an active task
                scheduled_emails = []
                for email in all_emails:
                    should_exclude = False

                    # Check if this is a bulk operation that has been converted to a task AND is still active
                    if (email.is_bulk_operation and email.status == "converted_to_task"):
                        # Only check for active tasks if task_manager is available
                        if hasattr(self, 'task_manager') and self.task_manager:
                            converted_task_id = email.composer_data.get('converted_task_id')
                            if converted_task_id:
                                task_info = self.task_manager.load_task_info(converted_task_id)
                                # Exclude if the task exists and is in an active state (running, paused, or interrupted)
                                # TaskStatus.RUNNING corresponds to 'started' in display, TaskStatus.PAUSED to 'started(paused)', 
                                # and TaskStatus.INTERRUPTED to 'started(interrupted)' - these should not be cleared
                                if task_info and task_info.status in [TaskStatus.RUNNING, TaskStatus.PAUSED, TaskStatus.INTERRUPTED]:
                                    should_exclude = True  # Mark for exclusion

                    # Skip emails that are still 'scheduled' when doing a full clear
                    if getattr(email, 'status', None) == 'scheduled':
                        continue

                    # Only add to scheduled_emails if not marked for exclusion
                    if not should_exclude:
                        scheduled_emails.append(email)
            
            if not scheduled_emails:
                if status_filter:
                    self._print(f"No scheduled emails with status '{status_filter}'", "info")
                else:
                    self._print("No canceled/failed/sent emails to clear", "info")
                return
            
            if status_filter:
                confirm_msg = f"Completely remove all {len(scheduled_emails)} scheduled emails with status '{status_filter}'? (y/n): "
            else:
                confirm_msg = f"Completely remove all {len(scheduled_emails)} canceled/failed/sent emails? (y/n): "
            
            if not self.confirm_multiple_actions(
                confirm_msg,
                context={"action": "schedule_clear", "count": len(scheduled_emails), "status_filter": status_filter},
                cancel_message="Clear operation cancelled"
            ):
                return
            
            removed_count = 0
            for email in scheduled_emails:
                self.scheduled_manager.remove(email.id)  # Actually remove from storage
                removed_count += 1
            
            if status_filter:
                self._print(f"Removed {removed_count} scheduled emails with status '{status_filter}'", "success")
            else:
                self._print(f"Removed {removed_count} scheduled emails", "success")
            
        else:
            self._print(f"Unknown action: {action}", "error")
            self._print("Valid actions: send, list, show, cancel, clear", "info")
