| Command | Scenario | Prompt |
|---------|----------|--------|
| `template delete <name>` | Delete template | `"Delete template '{name}'? (y/n): "` |
| `template import <eml_file.eml> --html/--text <template_name>` | Overwrite existing template | `"Template '{template_name}' already exists. Overwrite? (y/n): "` |
| `config reset` | Reset configuration to defaults | `"This will reset ALL configuration to defaults! Are you sure? (y/n): "` |
| `contacts remove <contact_name>` | Remove contact list | `"Remove contact list '{contact_name}'? (y/n):"` |
| `task pause --all` | Pause all running tasks | `"This will pause all {len(running_tasks)} running tasks. Are you sure? (y/n): "` |
| `task resume --all` | Resume all paused/interrupted tasks | `"This will resume all {len(resumable_tasks)} paused/interrupted tasks. Are you sure? (y/n): "` |
| `task end --all` | Cancel all active tasks | `"This will cancel all {len(active_tasks)} active tasks. Are you sure? (y/n): "` |
| `task end <task_id>` | Cancel single task | `"This will cancel task {task.id} 'contacts: {contact_info}'. Are you sure? (y/n): "` |
| `task clean` | Clean up tasks | `"Clean up {len(statuses_to_clean)} status(es) of tasks? (y/n): "` |
| `send` | Send email | `"\nConfirm send? (y/n): "` |
| `send bulk --contacts <contact_name>` | Bulk send emails | `"Send {len(rows)} emails using profile '{self.current_profile}'? (y/n): "` |
| `schedule cancel --all` | Cancel all scheduled emails | `"Cancel all {len(scheduled_emails)} upcoming scheduled emails? (y/n): "` |
| `schedule cancel <id>` | Cancel scheduled email | `"Cancel scheduled email '{schedule_id}'? (y/n): "` |
| `schedule clear` or `schedule clear --status <status>` | Remove scheduled emails | Dynamic message based on status filter |
| `clear` | Clear current draft | `"Clear current draft? (y/n): "` |
| `profile remove <name>` | Remove SMTP profile | `"Delete profile '{name}'? (y/n): "` |