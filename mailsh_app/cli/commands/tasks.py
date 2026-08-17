"""
Task management commands.

Command: task (list, show, watch, pause, resume, end, clean)
"""

import os
import sys
import time
import threading
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime

from ...core.tasks import TaskManager, TaskStatus
from ...utils.validators import is_email, normalize_email
from ...utils.colors import color_for_task_status


class TaskCommands:
    """Mixin class providing task management commands."""
    
    def __init__(self):
        # This will be initialized when the main Mailsh class is initialized
        # It will be set to self.task_manager
        self.task_manager: Optional[TaskManager] = None
    
    def cmd_task(self, args: List[str]):
        """Task management command with subcommands: list, show, watch, pause, resume, end, clean"""
        if not args:
            self._print("Usage: task <list|show|watch|pause|resume|end|clean> [options]", "error")
            self._print("Type 'help task' for more information", "info")
            return
        
        action = args[0].lower()
        
        if action == "list":
            self._cmd_task_list(args[1:])
        elif action == "show":
            self._cmd_task_show(args[1:])
        elif action == "watch":
            self._cmd_task_watch(args[1:])
        elif action == "pause":
            self._cmd_task_pause(args[1:])
        elif action == "resume":
            self._cmd_task_resume(args[1:])
        elif action == "end":
            self._cmd_task_end(args[1:])
        elif action == "clean":
            self._cmd_task_clean(args[1:])
        else:
            self._print(f"Unknown action: {action}", "error")
            self._print("Valid actions: list, show, watch, pause, resume, end, clean", "info")
    
    def _cmd_task_list(self, args: List[str]):
        """List all tasks (active and ended)"""
        tasks = self.task_manager.get_all_tasks()
        
        if not tasks:
            self._print("No tasks", "info")
            return
        
        import re
        
        def strip_ansi_codes(s):
            """Remove ANSI escape codes from string for proper width calculation"""
            ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
            return ansi_escape.sub('', s)
        
        def pad_with_ansi(text_with_ansi, total_width, align='left'):
            """Pad text with ANSI codes to a specific width, accounting for ANSI codes in calculation"""
            clean_text = strip_ansi_codes(text_with_ansi)
            padding_needed = total_width - len(clean_text)
            
            if padding_needed <= 0:
                return text_with_ansi  # Already at or over the desired width
            
            if align == 'left':
                return text_with_ansi + ' ' * padding_needed
            elif align == 'right':
                return ' ' * padding_needed + text_with_ansi
            else:  # center
                left_pad = padding_needed // 2
                right_pad = padding_needed - left_pad
                return ' ' * left_pad + text_with_ansi + ' ' * right_pad

        print("\n" + "="*100)
        self._print("TASKS", "theme")
        print("="*100)
        print(f"{'ID':<10} {'Status':<12} {'Progress':<12} {'Success':<10} {'Failed':<10} {'Contacts':<30}")
        print("-"*100)
        
        for task in tasks:
            # Show 'canceled' instead of 'ended' for display purposes
            if task.status == TaskStatus.ENDED:
                status_str = "canceled"
            elif task.status == TaskStatus.INTERRUPTED:
                status_str = "interrupted"
            else:
                status_str = task.status.value

            # Centralized coloring for task statuses
            status_display = color_for_task_status(task.status)
            
            contact_str = task.contact_list if task.contact_list else "unknown"
            if len(contact_str) > 27:
                contact_str = contact_str[:27] + '...'
            
            # Use the helper function to properly pad fields with ANSI codes
            id_padded = f"{task.id:<10}"
            status_padded = pad_with_ansi(status_display, 12, 'left')
            progress_padded = f"{task.progress:<12}"
            success_padded = f"{task.success_count:<10}"
            failed_padded = f"{task.failed_count:<10}"
            contacts_padded = f"{contact_str:<30}"
            
            print(f"{id_padded} {status_padded} {progress_padded} {success_padded} {failed_padded} {contacts_padded}")
        
        print("="*100 + "\n")
    
    def _cmd_task_show(self, args: List[str]):
        """Show detailed information about a task"""
        # Get all tasks (active and ended)
        all_tasks = self.task_manager.get_all_tasks()
        
        if not all_tasks:
            self._print("No tasks found", "info")
            return
        
        # If no ID provided and multiple active tasks, show error
        if not args:
            active_tasks = [t for t in all_tasks if t.status in [TaskStatus.RUNNING, TaskStatus.PAUSED]]
            if len(active_tasks) == 0:
                self._print("No active tasks", "info")
                return
            elif len(active_tasks) == 1:
                # If only one active task, show that one
                task = active_tasks[0]
            else:
                self._print("Multiple active tasks found. Please specify task ID:", "error")
                for task in active_tasks:
                    status_str = task.status.value
                    status_color = color_for_task_status(task.status)
                    contact_info = task.contact_list if task.contact_list else "unknown"
                    print(f"  {task.id} - {status_color} - contacts: {contact_info}")
                return
        else:
            # Look for task with specific ID
            task_id = args[0]
            task = self.task_manager.load_task_info(task_id)
            if not task:
                self._print(f"No task found with ID: {task_id}", "error")
                return
        
        print("\n" + "="*60)
        self._print(f"TASK DETAILS (ID: {task.id})", "theme")
        print("="*60)
        print(f"Command:       {task.command}")
        # Show colored status; include failure reason for failed tasks
        status_str = task.status.value
        if task.status == TaskStatus.ENDED:
            status_str = 'canceled'

        colored_status = color_for_task_status(task.status)

        failure_reason = f" ({task.failure_reason})" if task.status == TaskStatus.FAILED and getattr(task, 'failure_reason', None) else ""
        print(f"Status:        {colored_status}{failure_reason}")
        print(f"Start Time:    {task.start_time}")
        if task.end_time:
            print(f"End Time:      {task.end_time}")
        print(f"Progress:      {task.progress}")
        print(f"Success:       {task.success_count}")
        print(f"Failed:         {task.failed_count}")
        print(f"Total:         {task.total_count}")
        if task.contact_list:
            print(f"Contacts:      {task.contact_list}")
        if task.profile_name:
            print(f"Profile:       {task.profile_name}")
        if task.log_file:
            print(f"Log File:      {task.log_file}")
        print("="*60 + "\n")
    
    def _cmd_task_watch(self, args: List[str]):
        """Watch a task's log in real-time (like tail -f)"""
        # Get all tasks (active and ended)
        all_tasks = self.task_manager.get_all_tasks()
        
        if not all_tasks:
            self._print("No tasks found", "info")
            return
        
        # If no ID provided and multiple active tasks, show error
        if not args:
            active_tasks = [t for t in all_tasks if t.status in [TaskStatus.RUNNING, TaskStatus.PAUSED]]
            if len(active_tasks) == 0:
                self._print("No active tasks", "info")
                return
            elif len(active_tasks) == 1:
                # If only one active task, watch that one
                task = active_tasks[0]
            else:
                self._print("Multiple active tasks found. Please specify task ID:", "error")
                for task in active_tasks:
                    status_str = task.status.value
                    # Use centralized color helper for consistent task status formatting
                    status_color = color_for_task_status(task.status)
                    contact_info = task.contact_list if task.contact_list else "unknown"
                    print(f"  {task.id} - {status_color} - contacts: {contact_info}")
                return
        else:
            # Look for task with specific ID
            task_id = args[0]
            task = self.task_manager.load_task_info(task_id)
            if not task:
                self._print(f"No task found with ID: {task_id}", "error")
                return
        
        if not task.log_file:
            self._print(f"No log file found for task {task.id}", "error")
            return
        
        log_path = Path(task.log_file)
        if not log_path.exists():
            self._print(f"Log file does not exist: {task.log_file}", "error")
            return
        
        self._print(f"Watching task {task.id} (Press Ctrl+C to exit)", "info")
        
        try:
            # Start watching the log file
            self._watch_log_file(log_path)
        except KeyboardInterrupt:
            print("\nStopped watching log.")
        except Exception as e:
            self._print(f"Error watching log: {str(e)}", "error")
    
    def _watch_log_file(self, log_path: Path):
        """Watch log file in real-time like tail -f"""
        # First, print the last 8 lines from the log file
        if log_path.exists():
            with open(log_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                # Show last 8 lines if available
                recent_lines = lines[-8:] if len(lines) >= 8 else lines
                for line in recent_lines:
                    colored_line = self._colorize_log_line(line.rstrip('\n'))
                    print(colored_line)
            
            # Get initial position for tail -f functionality
            with open(log_path, 'r', encoding='utf-8') as f:
                f.seek(0, 2)  # Go to end of file
                initial_pos = f.tell()
        else:
            initial_pos = 0
        
        try:
            while True:
                # Check if file exists
                if not log_path.exists():
                    time.sleep(0.1)
                    continue
                
                # Check current file size
                current_size = log_path.stat().st_size
                
                if current_size > initial_pos:
                    with open(log_path, 'r', encoding='utf-8') as f:
                        f.seek(initial_pos)
                        new_content = f.read()
                        if new_content:
                            # Process each line and add colors
                            lines = new_content.split('\n')
                            for i, line in enumerate(lines):
                                if line.strip():  # Only process non-empty lines
                                    colored_line = self._colorize_log_line(line)
                                    # Add newline except for the last line (to handle partial lines)
                                    end_char = '\n' if i < len(lines) - 1 else ''
                                    print(colored_line, end=end_char, flush=True)
                                else:
                                    print()  # Print empty line
                    initial_pos = current_size
                
                time.sleep(0.5)  # Wait before checking again
                
        except KeyboardInterrupt:
            # This is expected - user pressed Ctrl+C to stop watching
            raise
    
    def _colorize_log_line(self, line: str) -> str:
        """Add colors to log line based on content"""
        # Define colors - using the exact same colors as other error messages
        from ...utils.colors import color_text

        result = line

        # Colorize success tick (✓) - only the symbol itself
        if '✓' in result:
            result = result.replace('✓', color_text('success', '✓'))

        # For error messages that contain '✗ FAILED', colorize everything from ✗ onwards
        if '✗ FAILED' in result:
            pos = result.find('✗ FAILED')
            if pos != -1:
                before = result[:pos]
                after = result[pos:]  # From ✗ onwards
                result = before + color_text('error', after)
        # For retry messages that contain '✗' and 'retry', colorize everything from ✗ onwards
        elif '✗' in result and 'retry' in result:
            pos = result.find('✗')
            if pos != -1:
                before = result[:pos]
                after = result[pos:]  # From ✗ onwards
                result = before + color_text('warning', after)

        return result
    
    def _cmd_task_pause(self, args: List[str]):
        """Pause a running task"""
        # Get all tasks (active and ended)
        all_tasks = self.task_manager.get_all_tasks()
        
        # Check if --all flag is present
        if '--all' in args:
            running_tasks = [t for t in all_tasks if t.status == TaskStatus.RUNNING]
            if len(running_tasks) == 0:
                self._print("No running tasks to pause", "info")
                return
            
            # Use universal confirmation method
            if not self.confirm_multiple_actions(
                f"This will pause all {len(running_tasks)} running tasks. Are you sure? (y/n): ",
                context={"task_count": len(running_tasks), "action": "pause_all"},
                cancel_message="Pause all cancelled"
            ):
                return
            
            paused_count = 0
            for task in running_tasks:
                if self.task_manager.pause_task(task.id):
                    paused_count += 1
            
            self._print(f"Paused {paused_count} task(s)", "success")
            return
        
        # If no ID provided and multiple active tasks, show error
        if not args:
            running_tasks = [t for t in all_tasks if t.status == TaskStatus.RUNNING]
            if len(running_tasks) == 0:
                self._print("No running tasks found", "info")
                return
            elif len(running_tasks) == 1:
                # If only one running task, use that one
                task = running_tasks[0]
            else:
                self._print("Multiple running tasks found. Please specify task ID:", "error")
                for task in running_tasks:
                    status_str = task.status.value
                    status_color = color_for_task_status(task.status)
                    contact_info = task.contact_list if task.contact_list else "unknown"
                    print(f"  {task.id} - {status_color} - contacts: {contact_info}")
                return
        else:
            # Look for task with specific ID
            task_id = args[0]
            task = self.task_manager.load_task_info(task_id)
            if not task:
                self._print(f"No task found with ID: {task_id}", "error")
                return
        
        if task.status != TaskStatus.RUNNING:
            self._print(f"Task {task.id} is not running (status: {task.status.value})", "error")
            return
        
        if self.task_manager.pause_task(task.id):
            self._print(f"Task {task.id} paused", "success")
        else:
            self._print(f"Failed to pause task {task.id}", "error")
    
    def _cmd_task_resume(self, args: List[str]):
        """Resume a paused task"""
        # Get all tasks (active and ended)
        all_tasks = self.task_manager.get_all_tasks()
        
        # Check if --all flag is present
        if '--all' in args:
            resumable_tasks = [t for t in all_tasks if t.status in [TaskStatus.PAUSED, TaskStatus.INTERRUPTED]]
            if len(resumable_tasks) == 0:
                self._print("No paused or interrupted tasks to resume", "info")
                return
            
            # Use universal confirmation method
            if not self.confirm_multiple_actions(
                f"This will resume all {len(resumable_tasks)} paused/interrupted tasks. Are you sure? (y/n): ",
                context={"task_count": len(resumable_tasks), "action": "resume_all"},
                cancel_message="Resume all cancelled"
            ):
                return
            
            resumed_count = 0
            for task in resumable_tasks:
                if self.task_manager.resume_task(task.id):
                    resumed_count += 1
            
            self._print(f"Resumed {resumed_count} task(s)", "success")
            return
        
        # If no ID provided and multiple active tasks, show error
        if not args:
            resumable_tasks = [t for t in all_tasks if t.status in [TaskStatus.PAUSED, TaskStatus.INTERRUPTED]]
            if len(resumable_tasks) == 0:
                self._print("No paused or interrupted tasks found", "info")
                return
            elif len(resumable_tasks) == 1:
                # If only one resumable task, use that one
                task = resumable_tasks[0]
            else:
                self._print("Multiple paused/interrupted tasks found. Please specify task ID:", "error")
                for task in resumable_tasks:
                    status_str = task.status.value
                    # Centralize status coloring
                    status_color = color_for_task_status(task.status)
                    contact_info = task.contact_list if task.contact_list else "unknown"
                    print(f"  {task.id} - {status_color} - contacts: {contact_info}")
                return
        else:
            # Look for task with specific ID
            task_id = args[0]
            task = self.task_manager.load_task_info(task_id)
            if not task:
                self._print(f"No task found with ID: {task_id}", "error")
                return
        
        if task.status not in [TaskStatus.PAUSED, TaskStatus.INTERRUPTED]:
            self._print(f"Task {task.id} is not paused or interrupted (status: {task.status.value})", "error")
            return
        
        if self.task_manager.resume_task(task.id):
            # Load the task info again to get updated data
            updated_task = self.task_manager.load_task_info(task.id)
            if updated_task:
                # Parse progress to show how many emails have been processed
                try:
                    progress_parts = updated_task.progress.split('/')
                    if len(progress_parts) == 2:
                        already_processed = int(progress_parts[0])
                        total_count = int(progress_parts[1])
                        remaining = total_count - already_processed
                    else:
                        already_processed = 0
                        remaining = updated_task.total_count if updated_task.total_count else 0
                except (ValueError, IndexError):
                    already_processed = 0
                    remaining = updated_task.total_count if updated_task.total_count else 0
                
                # Check if this is an interrupted task (status is 'interrupted') or if some emails were processed
                # Compare using the value to avoid potential enum comparison issues
                if (updated_task.status.value if hasattr(updated_task.status, 'value') else str(updated_task.status)) == 'interrupted' or already_processed > 0:
                    self._print(f"Already processed: {already_processed} emails", "info")
                    self._print(f"Remaining: {remaining} emails", "info")
                
                self._print(f"Resuming task {task.id}...", "success")
            else:
                self._print(f"Task {task.id} resumed", "success")
        else:
            self._print(f"Failed to resume task {task.id}", "error")
    
    def _cmd_task_end(self, args: List[str]):
        """End/cancel a task"""
        # Get all tasks (active and ended)
        all_tasks = self.task_manager.get_all_tasks()
        
        # Check if --all flag is present
        if '--all' in args:
            active_tasks = [t for t in all_tasks if t.status in [TaskStatus.RUNNING, TaskStatus.PAUSED, TaskStatus.INTERRUPTED]]
            if len(active_tasks) == 0:
                self._print("No active tasks to end", "info")
                return
            
            from ...core.state_manager import ExecutionMode, ConfirmationRequest
            
            # Check execution mode
            # Use universal confirmation method
            if not self.confirm_multiple_actions(
                f"This will cancel all {len(active_tasks)} active tasks. Are you sure? (y/n): ",
                context={"task_count": len(active_tasks), "action": "end_all"},
                cancel_message="End all cancelled"
            ):
                return
            
            ended_count = 0
            for task in active_tasks:
                if self.task_manager.end_task(task.id):
                    ended_count += 1
            
            self._print(f"Ended {ended_count} task(s)", "success")
            return
        
        # If no ID provided and multiple active tasks, show error
        if not args:
            active_tasks = [t for t in all_tasks if t.status in [TaskStatus.RUNNING, TaskStatus.PAUSED, TaskStatus.INTERRUPTED]]
            if len(active_tasks) == 0:
                self._print("No active tasks found", "info")
                return
            elif len(active_tasks) == 1:
                # If only one active task, use that one
                task = active_tasks[0]
            else:
                self._print("Multiple active tasks found. Please specify task ID:", "error")
                for task in active_tasks:
                    status_str = task.status.value
                    # Centralize status coloring
                    status_color = color_for_task_status(task.status)
                    contact_info = task.contact_list if task.contact_list else "unknown"
                    print(f"  {task.id} - {status_color} - contacts: {contact_info}")
                return
        else:
            # Look for task with specific ID
            task_id = args[0]
            task = self.task_manager.load_task_info(task_id)
            if not task:
                self._print(f"No task found with ID: {task_id}", "error")
                return
        
        if task.status not in [TaskStatus.RUNNING, TaskStatus.PAUSED, TaskStatus.INTERRUPTED]:
            self._print(f"Task {task.id} is not active (status: {task.status.value})", "error")
            return
        
        from ...core.state_manager import ExecutionMode, ConfirmationRequest
        
        # Check execution mode
        # Use universal confirmation method
        contact_info = task.contact_list if task.contact_list else "unknown"
        if not self.confirm_action(
            f"This will cancel task {task.id} 'contacts: {contact_info}'. Are you sure? (y/n): ",
            context={"task_id": task.id, "contact_info": contact_info},
            cancel_message="Task cancellation cancelled"
        ):
            return
        
        if self.task_manager.end_task(task.id):
            self._print(f"Task {task.id} ended/canceled", "success")
        else:
            self._print(f"Failed to end interrupted task {task.id}, use 'task clean interrupted' instead", "error")
    
    def _cmd_task_clean(self, args: List[str]):
        """Clean up old completed/failed/cancelled tasks"""
        # Available statuses to clean
        valid_statuses = ["ended", "completed", "failed", "interrupted"]
        
        statuses_to_clean = []
        
        # Parse arguments
        for arg in args:
            if arg in valid_statuses:
                if arg == "ended":
                    statuses_to_clean.append(TaskStatus.ENDED)
                elif arg == "completed":
                    statuses_to_clean.append(TaskStatus.COMPLETED)
                elif arg == "failed":
                    statuses_to_clean.append(TaskStatus.FAILED)
                elif arg == "interrupted":
                    statuses_to_clean.append(TaskStatus.INTERRUPTED)
            else:
                self._print(f"Invalid status: {arg}. Valid options: {', '.join(valid_statuses)}", "error")
                return
        
        # If no specific statuses provided, clean all ended/completed/failed/interrupted
        if not statuses_to_clean:
            statuses_to_clean = [TaskStatus.ENDED, TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.INTERRUPTED]
        
        # Use universal confirmation method
        if not self.confirm_multiple_actions(
            f"Clean up {len(statuses_to_clean)} status(es) of tasks? (y/n): ",
            context={"statuses_to_clean": [s.value for s in statuses_to_clean]},
            cancel_message="Clean operation cancelled"
        ):
            return
        
        cleaned_count = self.task_manager.clean_tasks(statuses_to_clean, getattr(self, 'scheduled_manager', None))
        self._print(f"Cleaned up {cleaned_count} task(s)", "success")
