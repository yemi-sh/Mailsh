"""
Background task management system for Mailsh.

This module handles background tasks for bulk email sending with logging,
persistence and management capabilities.
"""

import json
import os
import sys
import time
import threading
import subprocess
import uuid
import shutil
from datetime import datetime
from pathlib import Path
from enum import Enum
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, asdict

from .config import Config
from .profile import Profile
from .sender import EmailSender
from ..features.contacts import ContactsManager
from ..features.templates import TemplateEngine
from ..utils.paths import get_config_dir
from .composer import EmailComposer


class TaskStatus(Enum):
    """Task status enum"""
    RUNNING = "running"
    PAUSED = "paused"
    ENDED = "ended"  # Manually ended by user
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"  # Task was interrupted by app exit


@dataclass
class TaskInfo:
    """Information about a task"""
    id: str
    command: str
    status: TaskStatus
    start_time: datetime
    end_time: Optional[datetime] = None
    log_file: Optional[str] = None
    progress: str = "0/0"
    success_count: int = 0
    failed_count: int = 0
    total_count: int = 0
    profile_name: Optional[str] = None
    contact_list: Optional[str] = None
    template_name: Optional[str] = None
    original_composer_data: Optional[Dict[str, Any]] = None  # Store original composer data for restart
    dry_run: bool = False  # Whether this was a dry run
    failure_reason: Optional[str] = None  # Reason for task failure
    original_schedule_id: Optional[str] = None  # ID of the original scheduled email that created this task
    original_config: Optional[Dict[str, Any]] = None  # Store original config values for the task
    temp_resources: Optional[Dict[str, Any]] = None  # Store paths to temporary resources (contacts, templates, attachments)


class TaskManager:
    """Manages background tasks for bulk email sending"""

    def __init__(self, config_dir: Path):
        self.config_dir = config_dir
        self.tasks_dir = config_dir / ".tasks"
        self.tasks_dir.mkdir(exist_ok=True)
        self.tmp_dir = config_dir / ".tmp"
        self.tmp_dir.mkdir(exist_ok=True)
        self.active_tasks: Dict[str, threading.Thread] = {}
        self.paused_tasks: Dict[str, Dict[str, Any]] = {}
        self.notification_callback: Optional[callable] = None  # Callback for task completion notifications
        self.temp_resource_refs: Dict[str, int] = {}  # Track reference count for each temp resource

        # Reconstruct reference counts from existing tasks before detecting interrupted tasks
        self._reconstruct_temp_resource_refs()

    def set_notification_callback(self, callback: callable):
        """Set the callback function for task completion notifications"""
        self.notification_callback = callback
        
        # Detect interrupted tasks after initialization
        self.detect_interrupted_tasks()

    def _reconstruct_temp_resource_refs(self):
        """Reconstruct the reference counts for temporary resources from active/running tasks
        
        Only tasks that are not completed/failed/ended should contribute to the reference count,
        since completed tasks should have already decremented their references (or will when they finish).
        """
        all_tasks = self.get_all_tasks()
        
        for task in all_tasks:
            # Only count tasks that are still considered active and may still be using resources
            if task.temp_resources and task.status not in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.ENDED]:
                # Process each type of temp resource
                for resource_type in ['contact_path', 'template_path']:
                    resource_path = task.temp_resources.get(resource_type)
                    if resource_path:
                        self.temp_resource_refs[resource_path] = self.temp_resource_refs.get(resource_path, 0) + 1
                
                # Process attachment paths (which is a list)
                attachment_paths = task.temp_resources.get('attachment_paths', [])
                for attachment_path in attachment_paths:
                    if attachment_path:
                        self.temp_resource_refs[attachment_path] = self.temp_resource_refs.get(attachment_path, 0) + 1

    def create_task_id(self) -> str:
        """Create a unique task ID"""
        return str(uuid.uuid4())[:8]

    def get_task_file_path(self, task_id: str) -> Path:
        """Get the path to a task's metadata file"""
        return self.tasks_dir / f"{task_id}.json"

    def get_log_file_path(self, task_id: str) -> Path:
        """Get the path to a task's log file"""
        return self.tasks_dir / f"{task_id}.log"



    def save_task_info(self, task_info: TaskInfo):
        """Save task information to a file atomically to prevent corruption"""
        task_file = self.get_task_file_path(task_info.id)
        data = asdict(task_info)
        # Convert datetime objects to ISO format strings
        data['start_time'] = task_info.start_time.isoformat()
        if task_info.end_time:
            data['end_time'] = task_info.end_time.isoformat()
        data['status'] = task_info.status.value
        
        # Write to a temporary file first, then rename to prevent corruption
        # due to interruption during write
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', dir=self.tasks_dir, delete=False, suffix='.tmp') as tmp_file:
            tmp_path = tmp_file.name
            json.dump(data, tmp_file, indent=2)
            tmp_file.flush()  # Ensure data is written to disk
            os.fsync(tmp_file.fileno())  # Force OS to write to disk
        
        # Atomically replace the target file with the temporary file
        os.replace(tmp_path, task_file)

    def load_task_info(self, task_id: str) -> Optional[TaskInfo]:
        """Load task information from a file"""
        task_file = self.get_task_file_path(task_id)
        if not task_file.exists():
            return None

        try:
            with open(task_file, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                # Check if the file is empty
                if not content:
                    print(f"Warning: Empty task file {task_file}", file=sys.stderr)
                    return None
                data = json.loads(content)
        except json.JSONDecodeError as e:
            print(f"Warning: Invalid JSON in task file {task_file}: {e}", file=sys.stderr)
            return None
        except Exception as e:
            print(f"Warning: Error reading task file {task_file}: {e}", file=sys.stderr)
            return None

        # Check if data is a dictionary, not a list
        if not isinstance(data, dict):
            print(f"Warning: Task file {task_file} contains invalid data format (not a dictionary)", file=sys.stderr)
            return None

        # Convert ISO format strings back to datetime objects
        try:
            data['start_time'] = datetime.fromisoformat(data['start_time'])
        except (TypeError, ValueError) as e:
            print(f"Warning: Invalid start_time format in task {task_id}: {e}", file=sys.stderr)
            return None

        if data.get('end_time'):
            try:
                data['end_time'] = datetime.fromisoformat(data['end_time'])
            except (TypeError, ValueError) as e:
                print(f"Warning: Invalid end_time format in task {task_id}: {e}", file=sys.stderr)
                return None
        else:
            # Set default value if end_time key is missing
            data['end_time'] = None
        
        # Set default values for other potentially missing fields
        if 'profile_name' not in data:
            data['profile_name'] = None
        if 'contact_list' not in data:
            data['contact_list'] = None
        if 'template_name' not in data:
            data['template_name'] = None
        if 'original_composer_data' not in data:
            data['original_composer_data'] = None
        if 'dry_run' not in data:
            data['dry_run'] = False
        if 'failure_reason' not in data:
            data['failure_reason'] = None
        if 'original_schedule_id' not in data:
            data['original_schedule_id'] = None
        if 'original_config' not in data:
            data['original_config'] = None
        if 'temp_resources' not in data:
            data['temp_resources'] = None
        if 'log_file' not in data:
            data['log_file'] = None
        if 'progress' not in data:
            data['progress'] = "0/0"
        if 'success_count' not in data:
            data['success_count'] = 0
        if 'failed_count' not in data:
            data['failed_count'] = 0
        if 'total_count' not in data:
            data['total_count'] = 0

        try:
            data['status'] = TaskStatus(data['status'])
        except ValueError as e:
            print(f"Warning: Invalid status in task {task_id}: {e}", file=sys.stderr)
            return None

        return TaskInfo(**data)

    def get_all_tasks(self) -> List[TaskInfo]:
        """Get all tasks (active and completed)"""
        tasks = []
        for task_file in self.tasks_dir.glob("*.json"):
            task_id = task_file.stem
            # Skip sent emails tracking files (they end with _sent)
            if task_id.endswith('_sent'):
                continue
            task_info = self.load_task_info(task_id)
            if task_info:
                tasks.append(task_info)
        return tasks

    def get_active_tasks(self) -> List[TaskInfo]:
        """Get only active tasks (running, paused)"""
        all_tasks = self.get_all_tasks()
        active_statuses = [TaskStatus.RUNNING, TaskStatus.PAUSED]
        return [task for task in all_tasks if task.status in active_statuses]

    def get_paused_tasks(self) -> List[TaskInfo]:
        """Get only paused tasks"""
        all_tasks = self.get_all_tasks()
        return [task for task in all_tasks if task.status == TaskStatus.PAUSED]

    def get_ended_tasks(self) -> List[TaskInfo]:
        """Get ended/cancelled tasks"""
        all_tasks = self.get_all_tasks()
        ended_statuses = [TaskStatus.ENDED, TaskStatus.COMPLETED, TaskStatus.FAILED]
        return [task for task in all_tasks if task.status in ended_statuses]

    def start_bulk_send_task(self,
                           task_id: str,
                           profile: Profile,
                           config: Config,
                           composer: EmailComposer,
                           contact_name: str,
                           template_name: Optional[str] = None,
                           profile_name: Optional[str] = None,
                           dry_run: bool = False,
                           original_schedule_id: Optional[str] = None,
                           scheduled_manager: Optional[Any] = None) -> bool:
        """Start a background bulk send task"""
        try:
            # Create log file
            log_file = self.get_log_file_path(task_id)

            # Copy resources to temporary directory
            temp_resources = {
                'contact_path': None,
                'template_path': None,
                'attachment_paths': []
            }
            
            # Copy contact list if provided
            if contact_name:
                temp_resources['contact_path'] = self._copy_contact_to_tmp(contact_name)
            
            # Copy template if provided
            if template_name:
                temp_resources['template_path'] = self._copy_template_to_tmp(template_name)
            
            # Copy attachments from composer
            if composer.attachments:
                temp_resources['attachment_paths'] = self._copy_attachments_to_tmp(composer.attachments)
            
            # Prepare task info
            task_info = TaskInfo(
                id=task_id,
                command=f"send bulk --contacts {contact_name}",
                status=TaskStatus.RUNNING,
                start_time=datetime.now(),
                log_file=str(log_file),
                contact_list=contact_name,
                profile_name=profile_name or 'unknown',
                template_name=template_name,
                original_composer_data=composer.to_dict(),  # Store original composer data for restart
                dry_run=dry_run,
                original_config=self._extract_relevant_config(config),  # Store original config values for the task
                temp_resources=temp_resources
            )
            
            # Store the original schedule ID if provided
            if original_schedule_id:
                task_info.original_schedule_id = original_schedule_id

            # Save initial task info
            self.save_task_info(task_info)

            # Start the background thread
            # Start the background thread
            thread = threading.Thread(
                target=self._execute_bulk_send,
                args=(task_id, profile, config, composer.clone(), contact_name, template_name, dry_run, original_schedule_id, scheduled_manager, self.notification_callback),
                daemon=True
            )
            thread.start()

            # Store the thread reference
            self.active_tasks[task_id] = thread

            return True
        except Exception as e:
            print(f"Error starting task: {str(e)}", file=sys.stderr)
            return False

    def start_bulk_send_task_with_preexisting_resources(self,
                                                      task_id: str,
                                                      profile: Profile,
                                                      config: Config,
                                                      composer: EmailComposer,
                                                      contact_name: str,
                                                      template_name: Optional[str] = None,
                                                      profile_name: Optional[str] = None,
                                                      dry_run: bool = False,
                                                      original_schedule_id: Optional[str] = None,
                                                      scheduled_manager: Optional[Any] = None,
                                                      preexisting_temp_resources: Optional[Dict[str, Any]] = None) -> bool:
        """Start a background bulk send task using pre-existing temporary resources"""
        try:
            # Create log file
            log_file = self.get_log_file_path(task_id)

            # Prepare task info with pre-existing temporary resources
            task_info = TaskInfo(
                id=task_id,
                command=f"send bulk --contacts {contact_name}",
                status=TaskStatus.RUNNING,
                start_time=datetime.now(),
                log_file=str(log_file),
                contact_list=contact_name,
                profile_name=profile_name or 'unknown',
                template_name=template_name,
                original_composer_data=composer.to_dict(),  # Store original composer data for restart
                dry_run=dry_run,
                original_config=self._extract_relevant_config(config),  # Store original config values for the task
                temp_resources=preexisting_temp_resources  # Use pre-existing temporary resources
            )
            
            # Store the original schedule ID if provided
            if original_schedule_id:
                task_info.original_schedule_id = original_schedule_id

            # Save initial task info
            self.save_task_info(task_info)

            # Start the background thread (using the same execution method)
            thread = threading.Thread(
                target=self._execute_bulk_send,
                args=(task_id, profile, config, composer.clone(), contact_name, template_name, dry_run, original_schedule_id, scheduled_manager, self.notification_callback),
                daemon=True
            )
            thread.start()

            # Store the thread reference
            self.active_tasks[task_id] = thread

            return True
        except Exception as e:
            print(f"Error starting task: {str(e)}", file=sys.stderr)
            return False

    def _extract_relevant_config(self, config: 'Config') -> Dict[str, Any]:
        """Extract relevant configuration values that should persist with the task"""
        return {
            'rate_limiting.delay_between_emails_ms': config.get('rate_limiting.delay_between_emails_ms'),
            'bulk_send.retry_attempts': config.get('bulk_send.retry_attempts'),
            'bulk_send.continue_on_error': config.get('bulk_send.continue_on_error'),
            'bulk_send.retry_delay_seconds': config.get('bulk_send.retry_delay_seconds'),
            # Add other relevant config values that should persist with the task
        }
    
    def _copy_contact_to_tmp(self, contact_name: str) -> Optional[str]:
        """Copy contact list to tmp directory and return the path to the copied file"""
        try:
            contacts_manager = ContactsManager(self.config_dir)
            contact_path = contacts_manager._get_contact_path(contact_name)
            
            if not contact_path.exists():
                return None
            
            # Create a unique filename for the copy
            import hashlib
            # Create a hash of the content to detect if it's the same
            with open(contact_path, 'rb') as f:
                content_hash = hashlib.md5(f.read()).hexdigest()
            tmp_filename = f"contact_{contact_name}_{content_hash}.csv"
            tmp_path = self.tmp_dir / tmp_filename
            
            # Only copy if it doesn't exist already
            if not tmp_path.exists():
                shutil.copy2(contact_path, tmp_path)
            
            # Track reference for this temp resource
            tmp_path_str = str(tmp_path)
            if tmp_path_str in self.temp_resource_refs:
                self.temp_resource_refs[tmp_path_str] += 1
            else:
                self.temp_resource_refs[tmp_path_str] = 1
            
            return tmp_path_str
        except Exception as e:
            print(f"Error copying contact {contact_name}: {str(e)}", file=sys.stderr)
            return None
    
    def _copy_template_to_tmp(self, template_name: str) -> Optional[str]:
        """Copy template to tmp directory and return the path to the copied file"""
        try:
            templates = TemplateEngine(self.config_dir)
            template_path = templates.template_dir / f"{template_name}.txt"
            
            if not template_path.exists():
                return None
            
            # Create a unique filename for the copy
            import hashlib
            with open(template_path, 'rb') as f:
                content_hash = hashlib.md5(f.read()).hexdigest()
            tmp_filename = f"template_{template_name}_{content_hash}.txt"
            tmp_path = self.tmp_dir / tmp_filename
            
            # Only copy if it doesn't exist already
            if not tmp_path.exists():
                shutil.copy2(template_path, tmp_path)
            
            # Track reference for this temp resource
            tmp_path_str = str(tmp_path)
            if tmp_path_str in self.temp_resource_refs:
                self.temp_resource_refs[tmp_path_str] += 1
            else:
                self.temp_resource_refs[tmp_path_str] = 1
            
            return tmp_path_str
        except Exception as e:
            print(f"Error copying template {template_name}: {str(e)}", file=sys.stderr)
            return None
    
    def _copy_attachments_to_tmp(self, attachments: List[str]) -> List[str]:
        """Copy attachments to tmp directory and return paths to copied files"""
        copied_attachments = []
        try:
            for attachment_path in attachments:
                original_path = Path(attachment_path)
                if not original_path.exists():
                    continue  # Skip if the original doesn't exist
                
                # Create a unique filename for the copy
                import hashlib
                with open(original_path, 'rb') as f:
                    content_hash = hashlib.md5(f.read()).hexdigest()
                tmp_filename = f"attachment_{original_path.name}_{content_hash}"
                tmp_path = self.tmp_dir / tmp_filename
                
                # Only copy if it doesn't exist already
                if not tmp_path.exists():
                    shutil.copy2(original_path, tmp_path)
                
                tmp_path_str = str(tmp_path)
                # Track reference for this temp resource
                if tmp_path_str in self.temp_resource_refs:
                    self.temp_resource_refs[tmp_path_str] += 1
                else:
                    self.temp_resource_refs[tmp_path_str] = 1
                
                copied_attachments.append(tmp_path_str)
        except Exception as e:
            print(f"Error copying attachments: {str(e)}", file=sys.stderr)
        
        return copied_attachments
    
    def _cleanup_task_resources(self, task_id: str):
        """Clean up temporary resources for a completed task by decrementing reference counts"""
        try:
            # Load the task info to get the temporary resources
            task_info = self.load_task_info(task_id)
            if not task_info or not task_info.temp_resources:
                return
                
            # Get the temporary resources used by this task
            temp_resources = task_info.temp_resources
            resources_to_cleanup = []
            
            for resource_type in ['contact_path', 'template_path', 'attachment_paths']:
                if resource_type in temp_resources:
                    resource_paths = temp_resources[resource_type]
                    if isinstance(resource_paths, list):
                        resources_to_cleanup.extend(resource_paths)
                    elif isinstance(resource_paths, str) and resource_paths:
                        resources_to_cleanup.append(resource_paths)
            
            # For each resource, decrement the reference count and delete if count reaches 0
            for resource_path in resources_to_cleanup:
                if resource_path in self.temp_resource_refs:
                    self.temp_resource_refs[resource_path] -= 1
                    if self.temp_resource_refs[resource_path] <= 0:
                        # Remove the reference from our tracking
                        del self.temp_resource_refs[resource_path]
                        
                        # Delete the file
                        path = Path(resource_path)
                        if path.exists():
                            path.unlink()
        except Exception as e:
            print(f"Error cleaning up resources for task {task_id}: {str(e)}", file=sys.stderr)

    def _log_to_file(self, task_id: str, message: str):
        """Log a message to the task's log file"""
        log_file = self.get_log_file_path(task_id)
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        formatted_message = f"[{timestamp}] {message}\n"

        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(formatted_message)

    def _execute_bulk_send(self,
                          task_id: str,
                          profile: Profile,
                          config: Config,  # This is kept for backward compatibility but we'll use the stored config values
                          composer: EmailComposer,
                          contact_name: str,
                          template_name: Optional[str],
                          dry_run: bool,
                          original_schedule_id: Optional[str] = None,
                          scheduled_manager: Optional[Any] = None,
                          notification_callback: Optional[callable] = None):
        """Execute the bulk send operation in background"""
        try:
            # Get contacts - use copied resource if available, otherwise try original name
            task_info = self.load_task_info(task_id)
            if task_info and task_info.temp_resources and task_info.temp_resources.get('contact_path'):
                # Load contacts from the copied file
                contact_path = Path(task_info.temp_resources['contact_path'])
                if contact_path.exists():
                    try:
                        import csv
                        rows = []
                        with open(contact_path, 'r', newline='', encoding='utf-8') as f:
                            reader = csv.DictReader(f)
                            rows = list(reader)
                        success = True
                        error = None
                    except Exception as e:
                        success = False
                        error = f"Error reading copied contact file: {str(e)}"
                else:
                    success = False
                    error = f"Copied contact file missing: {contact_path}"
            else:
                # Fallback to original method if no copied resource
                contacts_manager = ContactsManager(self.config_dir)
                success, rows, error = contacts_manager.get_contacts(contact_name)
            
            if not success:
                self._log_to_file(task_id, f"ERROR: {error}")
                # Update task status
                if task_info:
                    # If the task was manually ended during execution, preserve that status
                    if task_info.status != TaskStatus.ENDED:
                        task_info.status = TaskStatus.FAILED
                        task_info.failure_reason = "Failed to load contacts"
                    task_info.end_time = datetime.now()
                    self.save_task_info(task_info)
                return

            # Load template if specified - use copied resource if available
            template_body = None
            if template_name:
                task_info = self.load_task_info(task_id)
                if task_info and task_info.temp_resources and task_info.temp_resources.get('template_path'):
                    # Load template from the copied file
                    template_path = Path(task_info.temp_resources['template_path'])
                    if template_path.exists():
                        try:
                            with open(template_path, 'r', encoding='utf-8') as f:
                                template_body = f.read()
                        except Exception as e:
                            self._log_to_file(task_id, f"ERROR: Failed to read copied template file: {str(e)}")
                            # Update task status
                            if task_info:
                                # If the task was manually ended during execution, preserve that status
                                if task_info.status != TaskStatus.ENDED:
                                    task_info.status = TaskStatus.FAILED
                                    task_info.failure_reason = "Failed to read template"
                                task_info.end_time = datetime.now()
                                self.save_task_info(task_info)
                            return
                    else:
                        self._log_to_file(task_id, f"ERROR: Copied template file missing: {template_path}")
                        # Update task status
                        if task_info:
                            # If the task was manually ended during execution, preserve that status
                            if task_info.status != TaskStatus.ENDED:
                                task_info.status = TaskStatus.FAILED
                                task_info.failure_reason = "Template file missing"
                            task_info.end_time = datetime.now()
                            self.save_task_info(task_info)
                        return
                else:
                    # Fallback to original method if no copied resource
                    templates = TemplateEngine(self.config_dir)
                    template_body = templates.load(template_name)
                
                if not template_body:
                    self._log_to_file(task_id, f"ERROR: Template not found: {template_name}")
                    # Update task status
                    if task_info:
                        # If the task was manually ended during execution, preserve that status
                        if task_info.status != TaskStatus.ENDED:
                            task_info.status = TaskStatus.FAILED
                            task_info.failure_reason = "Template not found"
                        task_info.end_time = datetime.now()
                        self.save_task_info(task_info)
                    return

            self._log_to_file(task_id, f"Found {len(rows)} recipients")

            # Prepare to send
            log_file_path = self.get_log_file_path(task_id)
            sender = EmailSender(profile, config, task_log_file=str(log_file_path))

            # Use stored config values from the task, fallback to current config if not available
            task_info = self.load_task_info(task_id)
            stored_config = task_info.original_config if task_info and task_info.original_config else {}
            
            # Get delay between emails from stored config, fallback to current config
            delay_between_emails_ms = stored_config.get('rate_limiting.delay_between_emails_ms')
            if delay_between_emails_ms is None:
                delay_between_emails_ms = config.get('rate_limiting.delay_between_emails_ms')
            if delay_between_emails_ms is None:
                delay_between_emails_ms = 1000  # Default value
            rate_limit = delay_between_emails_ms / 1000

            # Get retry attempts from stored config, fallback to current config
            retry_attempts_default = stored_config.get('bulk_send.retry_attempts')
            if retry_attempts_default is None:
                retry_attempts_default = config.get('bulk_send.retry_attempts')
            retry_attempts = retry_attempts_default if retry_attempts_default is not None else 3

            # Get continue on error from stored config, fallback to current config
            continue_on_error = stored_config.get('bulk_send.continue_on_error')
            if continue_on_error is None:
                continue_on_error = config.get('bulk_send.continue_on_error')
            if continue_on_error is None:
                continue_on_error = True  # Default value

            # Load progress to determine where to resume from
            task_info = self.load_task_info(task_id)
            if task_info:
                # Parse progress in format "X/Y" where X is the number of emails processed so far
                try:
                    progress_parts = task_info.progress.split('/')
                    if len(progress_parts) == 2:
                        already_processed = int(progress_parts[0])
                    else:
                        already_processed = 0
                except (ValueError, IndexError):
                    already_processed = 0
            else:
                already_processed = 0

            # Calculate starting index for resuming
            start_index = already_processed

            # For resuming interrupted tasks, we keep the original success/failed counts
            # but start from the progress index
            success_count = task_info.success_count if task_info else 0
            failed_count = task_info.failed_count if task_info else 0

            # For dry run, reset the counts
            if dry_run:
                success_count = 0
                failed_count = 0
                start_index = 0

            total_count = len(rows)

            # Update task info with counts
            task_info = self.load_task_info(task_id)
            if task_info:
                task_info.total_count = total_count
                task_info.progress = f"{success_count + failed_count}/{total_count}"
                task_info.success_count = success_count
                task_info.failed_count = failed_count
                self.save_task_info(task_info)

            # Helper to create a short single-line snippet from error messages
            def _snippet(text: Optional[str], length: int = 120) -> str:
                if not text:
                    return ''
                s = str(text).replace('\n', ' ').replace('\r', ' ').strip()
                if len(s) <= length:
                    return s
                return s[:length-1].rstrip() + '…'

            self._log_to_file(task_id, "")

            # If not a dry run and we have processed emails before, log the resume info
            if not dry_run and start_index > 0:
                self._log_to_file(task_id, f"Resuming from previous progress: {start_index}/{total_count} emails processed")

            for i in range(start_index, len(rows)):
                row = rows[i]

                # Check if task is paused
                while task_id in self.paused_tasks:
                    time.sleep(0.5)  # Wait while paused

                # Check if task is ended/canceled
                task_info = self.load_task_info(task_id)
                if not task_info or task_info.status in [TaskStatus.ENDED, TaskStatus.FAILED]:
                    break



                email = row.get('email', '').strip()

                if not email:
                    self._log_to_file(task_id, f"Row {i+1}: No email address")
                    continue

                # Create email from row data
                temp_composer = EmailComposer()
                temp_composer.to = [email]
                temp_composer.subject = row.get('subject', composer.subject)

                # Render template with row data
                if template_body:
                    temp_composer.body = TemplateEngine(self.config_dir).render(template_body, row)
                else:
                    temp_composer.body = TemplateEngine(self.config_dir).render(composer.body, row)

                temp_composer.html = composer.html
                
                # Use copied attachments if available
                task_info = self.load_task_info(task_id)
                if task_info and task_info.temp_resources and task_info.temp_resources.get('attachment_paths'):
                    temp_composer.attachments = task_info.temp_resources['attachment_paths'].copy()
                else:
                    # Fallback to original attachments if no copied resources
                    temp_composer.attachments = composer.attachments.copy()
                
                temp_composer.headers = composer.headers.copy()

                # Send with retry
                attempt = 0
                sent = False

                while attempt < retry_attempts and not sent:
                    if dry_run:
                        self._log_to_file(task_id, f"[{i+1}/{len(rows)}] Would send to: {email}")
                        sent = True
                        success_count += 1
                        
                        # Update task progress immediately after dry run "send" to prevent re-processing on restart
                        task_info = self.load_task_info(task_id)
                        if task_info:
                            task_info.progress = f"{i+1}/{total_count}"
                            task_info.success_count = success_count
                            task_info.failed_count = failed_count
                            self.save_task_info(task_info)

                    else:
                        # Check if task is ended/canceled during retry attempts
                        task_info = self.load_task_info(task_id)
                        if not task_info or task_info.status in [TaskStatus.ENDED, TaskStatus.FAILED]:
                            break

                        success, message, smtp_response = sender.send(temp_composer)

                        # Log to history
                        from .history import History
                        history = History(self.config_dir)
                        history_entry = {
                            "timestamp": datetime.now().isoformat(),
                            "profile": task_info.profile_name if task_info else profile.get('name', 'unknown'),
                            "to": [email],
                            "subject": temp_composer.subject,
                            "status": "sent" if success else "failed",
                            "message": message,
                            "smtp_response": smtp_response,
                            "bulk_send": True
                        }
                        history.add(history_entry)

                        if success:
                            self._log_to_file(task_id, f"[{i+1}/{len(rows)}] Sending to: {email}... ✓")
                            success_count += 1
                            sent = True
                            
                            # Update task progress immediately after successful send to prevent resending on restart
                            task_info = self.load_task_info(task_id)
                            if task_info:
                                task_info.progress = f"{i+1}/{total_count}"
                                task_info.success_count = success_count
                                task_info.failed_count = failed_count
                                self.save_task_info(task_info)

                        else:
                            attempt += 1
                            # Show a short snippet of the error to aid debugging inline
                            snippet = _snippet(message or smtp_response)
                            if attempt < retry_attempts:
                                if snippet:
                                    self._log_to_file(task_id, f"[{i+1}/{len(rows)}] Sending to: {email}... ✗ (retry {attempt}/{retry_attempts}) ({snippet})")
                                else:
                                    self._log_to_file(task_id, f"[{i+1}/{len(rows)}] Sending to: {email}... ✗ (retry {attempt}/{retry_attempts})")
                                # Get retry delay from stored config, fallback to current config
                                task_info = self.load_task_info(task_id)
                                stored_config = task_info.original_config if task_info and task_info.original_config else {}
                                retry_delay_seconds = stored_config.get('bulk_send.retry_delay_seconds')
                                if retry_delay_seconds is None:
                                    retry_delay_seconds = config.get('bulk_send.retry_delay_seconds')
                                if retry_delay_seconds is None:
                                    retry_delay_seconds = 5  # Default value
                                time.sleep(retry_delay_seconds)
                            else:
                                if snippet:
                                    self._log_to_file(task_id, f"[{i+1}/{len(rows)}] Sending to: {email}... ✗ FAILED ({snippet})")
                                else:
                                    self._log_to_file(task_id, f"[{i+1}/{len(rows)}] Sending to: {email}... ✗ FAILED")
                                failed_count += 1
                                # Update task progress for failed email too
                                task_info = self.load_task_info(task_id)
                                if task_info:
                                    task_info.progress = f"{i+1}/{total_count}"
                                    task_info.success_count = success_count
                                    task_info.failed_count = failed_count
                                    self.save_task_info(task_info)
                                if not continue_on_error:
                                    self._log_to_file(task_id, "Stopping bulk send due to error")
                                    break

                # Rate limiting
                if sent and i + 1 < len(rows):
                    time.sleep(rate_limit)

                if not continue_on_error and failed_count > 0:
                    break

                # Update task progress if not already updated in success/failure handling
                # (This handles cases where the email was skipped due to validation issues)
                task_info = self.load_task_info(task_id)
                if task_info:
                    # Only update if the progress doesn't already reflect this email index
                    try:
                        progress_parts = task_info.progress.split('/')
                        if len(progress_parts) == 2:
                            current_progress_count = int(progress_parts[0])
                            if current_progress_count < i + 1:
                                # Progress is behind, update to current position
                                task_info.progress = f"{i+1}/{total_count}"
                                task_info.success_count = success_count
                                task_info.failed_count = failed_count
                                self.save_task_info(task_info)
                    except (ValueError, IndexError):
                        # If parsing fails, update anyway
                        task_info.progress = f"{i+1}/{total_count}"
                        task_info.success_count = success_count
                        task_info.failed_count = failed_count
                        self.save_task_info(task_info)

            # Final summary
            self._log_to_file(task_id, "\n" + "="*70)
            self._log_to_file(task_id, "BULK SEND COMPLETE")
            self._log_to_file(task_id, "="*70)
            self._log_to_file(task_id, f"Total: {total_count}")
            self._log_to_file(task_id, f"Sent: {success_count}")
            self._log_to_file(task_id, f"Failed: {failed_count}")
            if success_count + failed_count > 0:
                self._log_to_file(task_id, f"Success Rate: {(success_count/(success_count+failed_count)*100):.1f}%")
            self._log_to_file(task_id, "="*70 + "\n")

            # Update final task status
            task_info = self.load_task_info(task_id)
            if task_info:
                # If the task was manually ended during execution, preserve that status
                if task_info.status == TaskStatus.ENDED:
                    # Just update the counts and progress, but keep ENDED status
                    task_info.end_time = datetime.now()
                    task_info.success_count = success_count
                    task_info.failed_count = failed_count
                    task_info.progress = f"{success_count + failed_count}/{total_count}"
                else:
                    # Task status depends on whether all emails were processed, not on email success/failure
                    task_info.end_time = datetime.now()
                    task_info.success_count = success_count
                    task_info.failed_count = failed_count
                    task_info.progress = f"{success_count + failed_count}/{total_count}"

                    # If all emails were processed (regardless of success/failure), mark as completed
                    if success_count + failed_count == total_count:
                        task_info.status = TaskStatus.COMPLETED
                        task_info.failure_reason = None  # Clear any failure reason for completed tasks
                    # Otherwise, mark as failed (incomplete execution)
                    else:
                        task_info.status = TaskStatus.FAILED
                        task_info.failure_reason = f"Task ended before all emails could be processed ({success_count + failed_count}/{total_count})"

                self.save_task_info(task_info)

                # Update the corresponding scheduled email if provided
                if original_schedule_id and scheduled_manager:
                    try:
                        # Get the scheduled email and update its status based on the task result
                        scheduled_email = scheduled_manager.get(original_schedule_id)
                        if scheduled_email:
                            # Map the task status to a scheduled email status
                            if task_info.status == TaskStatus.COMPLETED:
                                scheduled_email.status = 'completed'
                            elif task_info.status == TaskStatus.FAILED:
                                scheduled_email.status = 'failed'
                            elif task_info.status == TaskStatus.ENDED:
                                scheduled_email.status = 'cancelled'
                            # Save the updated scheduled email
                            scheduled_manager.add(scheduled_email)
                    except Exception as e:
                        # Log the error but don't fail the task execution
                        self._log_to_file(task_id, f"ERROR: Failed to update scheduled email status: {str(e)}")

                # Send notification about task completion if callback is provided
                if notification_callback and task_info:
                    notification_callback(task_info.id, task_info.status, task_info.success_count, task_info.failed_count)

        except Exception as e:
            error_msg = str(e)
            self._log_to_file(task_id, f"ERROR: {error_msg}")
            task_info = self.load_task_info(task_id)
            if task_info:
                # If the task was manually ended, preserve that status even during exception
                if task_info.status != TaskStatus.ENDED:
                    # An exception indicates the task failed to complete normally
                    task_info.status = TaskStatus.FAILED
                    task_info.failure_reason = f"Unexpected error: {error_msg}"
                task_info.end_time = datetime.now()
                self.save_task_info(task_info)
                
                # Update the corresponding scheduled email if provided in case of exception
                if original_schedule_id and scheduled_manager:
                    try:
                        # Get the scheduled email and mark it as failed
                        scheduled_email = scheduled_manager.get(original_schedule_id)
                        if scheduled_email:
                            scheduled_email.status = 'failed'
                            scheduled_manager.add(scheduled_email)
                    except Exception as e_update:
                        # Log the error but don't fail the task execution
                        self._log_to_file(task_id, f"ERROR: Failed to update scheduled email status on exception: {str(e_update)}")
        finally:
            # Remove thread from active tasks
            if task_id in self.active_tasks:
                del self.active_tasks[task_id]

            # Clean up temporary resources
            self._cleanup_task_resources(task_id)

            # Send notification about task completion in case of exception too
            task_info = self.load_task_info(task_id)
            if notification_callback and task_info:
                notification_callback(task_info.id, task_info.status, task_info.success_count, task_info.failed_count)

    def pause_task(self, task_id: str) -> bool:
        """Pause a running task"""
        task_info = self.load_task_info(task_id)
        if not task_info or task_info.status != TaskStatus.RUNNING:
            return False

        # Add to paused tasks
        self.paused_tasks[task_id] = {}

        # Update status
        task_info.status = TaskStatus.PAUSED
        self.save_task_info(task_info)

        return True

    def resume_task(self, task_id: str) -> bool:
        """Resume a paused or interrupted task"""
        task_info = self.load_task_info(task_id)
        if not task_info or task_info.status not in [TaskStatus.PAUSED, TaskStatus.INTERRUPTED]:
            return False

        # For PAUSED tasks, check if they have a running thread
        if task_info.status == TaskStatus.PAUSED:
            # Check if this PAUSED task has an active thread
            # If it doesn't have an active thread, it means it was interrupted while paused
            # and needs to be restarted like an interrupted task
            if task_id not in self.active_tasks:
                # This PAUSED task has no active thread, so it's like an interrupted task that should be resumed
                # Retrieve original task parameters
                original_contact_list = task_info.contact_list
                original_profile_name = task_info.profile_name
                original_template_name = task_info.template_name
                original_composer_data = task_info.original_composer_data
                dry_run = task_info.dry_run
                original_schedule_id = task_info.original_schedule_id  # Preserve original schedule ID
                original_config = task_info.original_config  # Preserve original config values

                if not original_contact_list:
                    print(f"Error: Cannot resume paused task {task_id}, missing contact list", file=sys.stderr)
                    return False

                if not original_profile_name:
                    print(f"Error: Cannot resume paused task {task_id}, missing profile name", file=sys.stderr)
                    return False

                # Get the required objects to restart the task
                from .profile import Profile
                from .config import Config
                from .composer import EmailComposer
                from ..utils.paths import get_config_dir

                config_dir = get_config_dir()
                profiles = Profile(config_dir)
                config = Config(config_dir)

                profile = profiles.get(original_profile_name)
                if not profile:
                    print(f"Error: Cannot resume task {task_id}, profile '{original_profile_name}' not found", file=sys.stderr)
                    return False

                # Reconstruct the composer from stored data
                composer = EmailComposer()
                if original_composer_data:
                    composer.from_dict(original_composer_data)

                # Remove from paused tasks if it's there (critical fix!)
                if task_id in self.paused_tasks:
                    del self.paused_tasks[task_id]

                # Update status to running first before starting the thread
                task_info.status = TaskStatus.RUNNING
                self.save_task_info(task_info)

                # Restart the background thread with the original parameters
                # This will continue from where it left off since the sent emails are tracked
                thread = threading.Thread(
                    target=self._execute_bulk_send,
                    args=(task_id, profile, config, composer, original_contact_list, original_template_name, dry_run, original_schedule_id, getattr(self, 'scheduled_manager', None)),
                    daemon=True
                )
                thread.start()

                # Store the thread reference
                self.active_tasks[task_id] = thread

                return True
            else:
                # This PAUSED task has an active thread, so just remove from paused and update status
                # Remove from paused tasks
                if task_id in self.paused_tasks:
                    del self.paused_tasks[task_id]

                # Update status to running
                task_info.status = TaskStatus.RUNNING
                self.save_task_info(task_info)

                return True

        # For INTERRUPTED tasks, we need to restart the sending process from where it left off
        elif task_info.status == TaskStatus.INTERRUPTED:
            # Retrieve original task parameters
            original_contact_list = task_info.contact_list
            original_profile_name = task_info.profile_name
            original_template_name = task_info.template_name
            original_composer_data = task_info.original_composer_data
            dry_run = task_info.dry_run
            original_schedule_id = task_info.original_schedule_id  # Preserve original schedule ID
            original_config = task_info.original_config  # Preserve original config values

            if not original_contact_list:
                print(f"Error: Cannot resume interrupted task {task_id}, missing contact list", file=sys.stderr)
                return False

            if not original_profile_name:
                print(f"Error: Cannot resume interrupted task {task_id}, missing profile name", file=sys.stderr)
                return False

            # Get the required objects to restart the task
            from .profile import Profile
            from .config import Config
            from .composer import EmailComposer
            from ..utils.paths import get_config_dir

            config_dir = get_config_dir()
            profiles = Profile(config_dir)
            config = Config(config_dir)

            profile = profiles.get(original_profile_name)
            if not profile:
                print(f"Error: Cannot resume task {task_id}, profile '{original_profile_name}' not found", file=sys.stderr)
                return False

            # Reconstruct the composer from stored data
            composer = EmailComposer()
            if original_composer_data:
                composer.from_dict(original_composer_data)

            # Remove from paused tasks if it's there (for interrupted tasks that were paused)
            if task_id in self.paused_tasks:
                del self.paused_tasks[task_id]

            # Update status to running first before starting the thread
            task_info.status = TaskStatus.RUNNING
            self.save_task_info(task_info)

            # Restart the background thread with the original parameters
            # This will continue from where it left off since the sent emails are tracked
            thread = threading.Thread(
                target=self._execute_bulk_send,
                args=(task_id, profile, config, composer, original_contact_list, original_template_name, dry_run, original_schedule_id, getattr(self, 'scheduled_manager', None)),
                daemon=True
            )
            thread.start()

            # Store the thread reference
            self.active_tasks[task_id] = thread

            return True
    def end_task(self, task_id: str) -> bool:
        """End/cancel a running task"""
        task_info = self.load_task_info(task_id)
        if not task_info or task_info.status not in [TaskStatus.RUNNING, TaskStatus.PAUSED]:
            return False

        # Update status
        task_info.status = TaskStatus.ENDED
        task_info.end_time = datetime.now()
        self.save_task_info(task_info)

        # Remove from paused if it was paused
        if task_id in self.paused_tasks:
            del self.paused_tasks[task_id]

        # Thread will check status and exit naturally
        return True

    def clean_tasks(self, statuses: List[TaskStatus] = None, scheduled_manager=None) -> int:
        """Clean up old completed/failed/cancelled tasks"""
        if statuses is None:
            statuses = [TaskStatus.ENDED, TaskStatus.COMPLETED, TaskStatus.FAILED]

        tasks_to_clean = []
        all_tasks = self.get_all_tasks()

        for task in all_tasks:
            if task.status in statuses:
                tasks_to_clean.append(task)

        cleaned_count = 0
        for task in tasks_to_clean:
            # Before removing the task, update the associated scheduled email if it exists and hasn't been updated
            if scheduled_manager and task.original_schedule_id:
                # Get the scheduled email and check if its status is still "converted_to_task"
                # If it is, this means the status update didn't happen properly when the task completed
                scheduled_email = scheduled_manager.get(task.original_schedule_id)
                if scheduled_email and scheduled_email.status == "converted_to_task":
                    # Update the scheduled email's status based on the task's final status
                    if task.status == TaskStatus.COMPLETED:
                        scheduled_email.status = 'completed'
                    elif task.status == TaskStatus.FAILED:
                        scheduled_email.status = 'failed'
                    elif task.status == TaskStatus.ENDED:
                        scheduled_email.status = 'cancelled'
                    elif task.status == TaskStatus.INTERRUPTED:
                        scheduled_email.status = 'started(interrupted)'
                    # PAUSED status shouldn't normally be cleaned up, but if it is:
                    elif task.status == TaskStatus.PAUSED:
                        scheduled_email.status = 'started(paused)'
                    
                    # Save the updated scheduled email
                    scheduled_manager.add(scheduled_email)

            # Remove task metadata file
            task_file = self.get_task_file_path(task.id)
            if task_file.exists():
                task_file.unlink()

            # Remove log file if it exists
            if task.log_file:
                log_path = Path(task.log_file)
                if log_path.exists():
                    log_path.unlink()

            # Remove from active tasks if needed
            if task.id in self.active_tasks:
                del self.active_tasks[task.id]
            if task.id in self.paused_tasks:
                del self.paused_tasks[task.id]

            cleaned_count += 1

        return cleaned_count

    def detect_interrupted_tasks(self):
        """Detect and mark tasks that were running but interrupted by app exit"""
        all_tasks = self.get_all_tasks()

        for task in all_tasks:
            # If a task has status RUNNING but is not in active_tasks, it was interrupted
            if task.status == TaskStatus.RUNNING and task.id not in self.active_tasks:
                # Mark as interrupted
                task.status = TaskStatus.INTERRUPTED
                self.save_task_info(task)

            # If a task has status PAUSED but was interrupted, it stays paused
            # (PAUSED tasks are stored in paused_tasks dict, not active_tasks)
            # We don't need to change them, but if they were in paused_tasks
            # but the thread is no longer running, they're still considered paused