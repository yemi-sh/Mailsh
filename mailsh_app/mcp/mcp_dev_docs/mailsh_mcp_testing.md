# Mailsh MCP Server Continuation Token Testing

## Overview

Actively use some specific MCP tools offered by the mailsh MCP server. These tools correspond to specific commands in the mailsh app that throw confirmation requests before completing the operation. A continuation token system has been implemented for these tools/commands, and we want to test the MCP server's ability to handle these multistep operations (responding to confirmation requests of a previously sent/called command/tool) without throwing errors.

## Example Flow

```
✓  delete_template (mailsh MCP Server) {"name":"Yinkol"}
   {"status": "confirmation_required", "prompt": "Delete template 'Yinkol'? (y/n): ", "continuation_token": "cmd_02c8_n4ZCWWqh_22ef", "command": "delete_template", "expires_at": 1762208427.4688706}

✓  confirm_continuation (mailsh MCP Server) {"continuation_token":"cmd_02c8_n4ZCWWqh_22ef","response":"y"}
   {"status": "success", "data": {"message": "Template 'Yinkol' deleted successfully", "deleted": true}}
```

## Tools and Command Mapping

List of tools that will return a `confirmation_required` status and their actual corresponding/mapped command in the mailsh app:

| Tool | Command |
|------|---------|
| `cancel_scheduled_email` | `schedule cancel` |
| `clean_tasks` | `task clean` |
| `clear_email_draft` | `clear` |
| `delete_template` | `template delete` |
| `end_task` | `task end` |
| `pause_task` | `task pause` (could potentially return a `confirmation_required` status if used with the `--all` flag) |
| `remove_contact_list` | `contacts remove` |
| `reset_config` | `config reset` |
| `resume_task` | `task resume` (could potentially return a `confirmation_required` status if used with the `--all` flag) |
| `send_bulk_emails` | `send bulk` |
| `send_email` | `send` |

The tools mentioned above will always (potentially) return a `confirmation_required` status, as their corresponding/mapped commands were designed to always request confirmation before completing operation.

## execute_mailsh_command Tool

An additional tool that could potentially return a `confirmation_required` status is the `execute_mailsh_command` tool. This tool is the most powerful and flexible tool for interacting with the mailsh app through MCP as it allows for the direct execution of any mailsh command with full control over arguments and flags. Calling the tool will return a `confirmation_required` status if the tool is used to execute a command that is designed to request confirmation.

### Example Flow

```
✓  execute_mailsh_command (mailsh MCP Server) {"command":"template delete Syoux"}
   {"status": "confirmation_required", "prompt": "Delete template 'Syoux'? (y/n): ", "continuation_token": "cmd_fa2a_nzavPKEP_153d", "command": "execute_mailsh_command", "expires_at": 1762208614.709085}

✓  confirm_continuation (mailsh MCP Server) {"continuation_token":"cmd_fa2a_nzavPKEP_153d","response":"y"}
   {"status": "success", "data": {"message": "Template 'Syoux' deleted successfully", "deleted": true, "executed": true, "success": true}}
```

## Commands Requiring Confirmation

Below is a complete list of commands/scenarios that are designed to request confirmation before completing the operation:

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

## Testing Target

These commands above are the only target of the testing (along with their corresponding/mapped MCP tools mentioned previously), and they all must be tested by being executed through the `execute_mailsh_command` tool. What we are looking for in these tests are anomalies that don't match expected behaviours.

## Expected Behaviour

### For Direct Tool Calls

```
✓  delete_template (mailsh MCP Server) {"name":"Yinkol"}
   (tool that would expectedly return a confirmation prompt is called without errors)
   
   {"status": "confirmation_required", "prompt": "Delete template 'Yinkol'? (y/n): ", "continuation_token": "cmd_02c8_n4ZCWWqh_22ef", "command": "delete_template", "expires_at": 1762208427.4688706}
   (a confirmation_required status is returned without errors)

✓  confirm_continuation (mailsh MCP Server) {"continuation_token":"cmd_02c8_n4ZCWWqh_22ef","response":"y"}
   (the confirmation prompt is responded to, could be a 'y' or 'n' without any errors)
   
   {"status": "success", "data": {"message": "Template 'Yinkol' deleted successfully", "deleted": true}}
   (operation completes without errors)
```

**Final step:** Check to confirm if the operation actually happened and we didn't just get a fake success message (as that will be an anomaly itself too). In this case, the `list_templates` tool or `execute_mailsh_command {"command":"template list"}` tool will be used to confirm that the 'Yinkol' template has actually been successfully deleted.

### For Execution of Direct Commands Through execute_mailsh_command Tool

```
✓  execute_mailsh_command (mailsh MCP Server) {"command":"template delete Syoux"}
   (a command that would expectedly return a confirmation prompt is executed through the tool without errors)
   
   {"status": "confirmation_required", "prompt": "Delete template 'Syoux'? (y/n): ", "continuation_token": "cmd_fa2a_nzavPKEP_153d", "command": "execute_mailsh_command", "expires_at": 1762208614.709085}
   (a confirmation_required status is returned without errors)

✓  confirm_continuation (mailsh MCP Server) {"continuation_token":"cmd_fa2a_nzavPKEP_153d","response":"y"}
   (the confirmation prompt is responded to, could be a 'y' or 'n' without any errors)
   
   {"status": "success", "data": {"message": "Template 'Syoux' deleted successfully", "deleted": true, "executed": true, "success": true}}
   (operation completes without errors)
```

**Final step:** Check to confirm if the operation actually happened and we didn't just get a fake success message (as that will be an anomaly itself too). In this case, the `list_templates` tool or `execute_mailsh_command {"command":"template list"}` tool will be used to confirm that the 'Syoux' template has actually been successfully deleted.

## Anomaly Detection

**Anything that doesn't follow the flow stated above is an anomaly and should be immediately reported/documented for review.**

### Examples of Previously Observed Anomalies

```
Error executing tool 'execute_mailsh_command': asyncio.run() cannot be called from a running event loop

{"status": "success", "data": {"message": "Error executing command 'task pause --all': asyncio.run() cannot be called from a running event loop", "executed": false, "error": "asyncio.run() cannot be called from a running event loop"}}

{"status": "error", "error_type": "ValueError", "message": "Unknown command: send_bulk_emails"}

{"status": "success", "data": {"message": "Unknown command: ", "executed": false, "error": "Unknown command: "}}

{"status": "success", "data": {"message": "Cleaned up 0 tasks", "cleaned": true, "count": 0}}
```