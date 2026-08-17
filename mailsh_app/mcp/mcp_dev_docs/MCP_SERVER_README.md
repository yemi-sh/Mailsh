# Mailsh MCP Server with Continuation Token Support

This implementation adds Model Context Protocol (MCP) server functionality to Mailsh that enables AI agents to interact with email functionality while preserving all existing confirmation prompts through a continuation token system.

## Table of Contents
- [Overview](#overview)
- [Architecture](#architecture)
- [How It Works](#how-it-works)
- [Installation](#installation)
- [Usage](#usage)
- [API Reference](#api-reference)
- [Confirmation Flow](#confirmation-flow)
- [State Management](#state-management)
- [Configuration](#configuration)
- [Development](#development)

## Overview

The Mailsh MCP server provides AI agents with access to email functionality while maintaining:
- Persistent session state between multiple tool calls
- All existing confirmation prompts for security
- Structured return values instead of text parsing
- Async compatibility without blocking the event loop
- Full backward compatibility with human CLI users

## Architecture

The system is implemented as a single, self-contained file with minimal dependencies:

### Core Components
- **`CommandStateManager`**: Thread-safe manager for pending confirmation states
- **`ExecutionMode`**: Context manager for CLI/MCP mode switching
- **`ConfirmationRequest`**: Exception for interrupting command flow when confirmation is needed
- **`CommandState`**: Data class for tracking pending confirmations

### Ultra-Simple MCP Server
- **`mailsh_app.mcp.server`**: Single-file implementation containing:
  - MCP server logic and tool definitions
  - Simple configuration via environment variable or hardcoded value
  - Command resumption functions (`resume_command`)
  - All MCP server functionality in one easy-to-understand file

## How It Works

### Two-Step Confirmation Flow
1. AI agent calls a command that requires confirmation (e.g., `delete_template`)
2. Server returns `confirmation_required` status with continuation token
3. AI agent calls `confirm_continuation` with the token and response ('y' or 'n')
4. Server resumes the original command with the response

### Example Flow
```json
// Step 1: Request template deletion
{
  "tool_name": "delete_template",
  "arguments": {"name": "newsletter-template"}
}

// Step 2: Server responds with confirmation request
{
  "status": "confirmation_required",
  "prompt": "Delete template 'newsletter-template'? (y/n):",
  "continuation_token": "cmd_02c8_5oVWUPFx_55eb",
  "command": "delete_template",
  "expires_at": 1762105332.6474156
}

// Step 3: AI agent responds to confirmation
{
  "tool_name": "confirm_continuation", 
  "arguments": {
    "continuation_token": "cmd_02c8_5oVWUPFx_55eb",
    "response": "y"
  }
}

// Step 4: Server confirms deletion
{
  "status": "success",
  "data": {
    "message": "Template 'newsletter-template' deleted successfully",
    "deleted": true
  }
}
```

## Installation

The MCP server is built into Mailsh and requires the following dependencies:

```bash
pip install mcp-server	# or install in a venv
```

## Usage

### Starting the MCP Server

The server can be configured using environment variables:

```bash

export MAILSH_MCP_TIMEOUT=300  # Confirmation timeout in seconds
```

It can be started through your mcp client with `python mailsh_app/mcp/server.py`



### Available Tools

The server exposes all Mailsh functionality through MCP tools:

#### Email Composition
- `set_email_field`: Set email fields (to, cc, bcc, subject, body, etc.)
- `unset_email_field`: Clear email fields
- `preview_email`: Preview current email draft
- `clear_email_draft`: Clear current email draft

#### Template Management
- `list_templates`: List all available templates
- `show_template`: Show template content
- `delete_template`: Delete a template (may return confirmation_required)
- `create_template`: Create a new template (interactive, not supported via MCP)
- `edit_template`: Edit an existing template (interactive, not supported via MCP)

#### Contact Management
- `import_contacts`: Import contacts from CSV
- `list_contacts`: List all contact lists
- `preview_contacts`: Preview a contact list
- `validate_contacts`: Validate email addresses in a contact list
- `remove_contact_list`: Remove a contact list (may return confirmation_required)

#### Configuration
- `show_config`: Show all configuration settings
- `get_config_value`: Get a specific config value
- `set_config_value`: Set a configuration value
- `reset_config`: Reset all configuration to defaults (may return confirmation_required)

#### Task Management
- `list_tasks`: List all background tasks
- `show_task_details`: Show details of a specific task
- `pause_task`: Pause a running task
- `resume_task`: Resume a paused task
- `end_task`: End/cancel a task (may return confirmation_required)
- `clean_tasks`: Clean up old completed/failed tasks (may return confirmation_required)

#### Sending and Scheduling
- `send_email`: Send the current email
- `send_bulk_emails`: Send emails in bulk
- `schedule_email`: Schedule an email to be sent later
- `list_scheduled_emails`: List all scheduled emails
- `show_scheduled_email`: Show details of a scheduled email
- `cancel_scheduled_email`: Cancel a scheduled email

#### Connection Management
- `connect_to_profile`: Connect to an SMTP profile
- `disconnect_from_profile`: Disconnect from the current SMTP profile
- `list_profiles`: List all available SMTP profiles

#### Special Tools
- `confirm_continuation`: Respond to a confirmation prompt from a previous command
- `execute_mailsh_command`: Execute any Mailsh command directly

## API Reference

### Response Formats

#### Success Response
```json
{
  "status": "success",
  "data": { /* command-specific return data */ }
}
```

#### Confirmation Required Response
```json
{
  "status": "confirmation_required",
  "prompt": "The confirmation message to show",
  "continuation_token": "The token to use for responding",
  "command": "The original command name",
  "expires_at": 1762105332.6474156
}
```

#### Error Response
```json
{
  "status": "error",
  "error_type": "ErrorType",
  "message": "Error message",
  "details": { /* optional error details */ }
}
```

### Tool Arguments

Most tools use the same arguments as the corresponding Mailsh commands. See individual command documentation for specific parameters.

## Confirmation Flow

The continuation token system ensures AI agents can respond to confirmation prompts programmatically while preserving security:

1. When a command requires user confirmation, the `ConfirmationRequest` exception is raised
2. The `CommandStateManager` creates a state with a unique continuation token
3. The server returns a structured response with the confirmation prompt and token
4. AI agents store the token and respond with a `confirm_continuation` tool call
5. The server resumes the original command with the provided response

This approach maintains security by requiring explicit confirmation while enabling automation.

## State Management

The `CommandStateManager` provides thread-safe state management:

- Uses an in-memory dictionary to store pending confirmation states
- Implements automatic cleanup of expired states (background thread runs every 60 seconds)
- Generates cryptographically secure continuation tokens
- Provides thread-safe operations using locks
- Stores context needed to resume commands after confirmation

States expire after a configurable timeout (default: 5 minutes) and cannot be reused once resolved.



### Configuration

The server uses a simple, single configuration parameter that can be set in two ways:

1. **Environment Variable**: Set `MAILSH_MCP_TIMEOUT` to specify timeout in seconds
2. **Hardcoded Default**: Edit the `CONFIRMATION_TIMEOUT_SECONDS` variable directly in `server.py`

Example:
```bash
export MAILSH_MCP_TIMEOUT=600  # 10 minute timeout
```

Or edit the value directly in the file:
```python
CONFIRMATION_TIMEOUT_SECONDS = 600  # 10 minutes
```

**Note**: MCP servers communicate via stdio (stdin/stdout) with the client, not over network connections. The timeout controls how long confirmation tokens remain valid.

### Environment Variables (Override Configuration)

Environment variables overrides hardcoded values:

| Variable | Default | Description |
|----------|---------|-------------|
| `MAILSH_MCP_TIMEOUT` | `300` | Confirmation timeout in seconds |






### Architecture Notes

#### Execution Mode System
The system uses `ExecutionMode` context manager to distinguish between CLI and MCP operation:
- CLI mode: Uses existing blocking input behavior
- MCP mode: Raises `ConfirmationRequest` exceptions when confirmations are needed

#### Thread Safety
- `CommandStateManager` uses locks to ensure thread-safe operations
- `ExecutionMode` uses thread-local storage to maintain mode per thread
- The single Mailsh instance is shared across tool calls but should be thread-safe

#### Error Handling
- Proper exception hierarchy with custom MCP-specific errors
- Graceful handling of expired and invalid continuation tokens
- Comprehensive error reporting to AI agents

### Adding New Commands

To add confirmation support to new commands:
1. Check `ExecutionMode.is_mcp_mode()` in the command handler
2. Raise `ConfirmationRequest(prompt_message, context)` instead of blocking input in MCP mode
3. Continue with the confirmation flow in both CLI and MCP modes after receiving response
4. Add corresponding resume logic in `command_executor.py`

## Security Considerations

- Continuation tokens are cryptographically generated and unpredictable
- Tokens expire after a configurable timeout period
- Tokens are single-use and removed after resolution
- The system maintains all original security checks and confirmation prompts

## Troubleshooting

### Common Issues

#### "Token expired" errors
- Increase the confirmation timeout using `MAILSH_MCP_TIMEOUT` environment variable
- Ensure AI agents respond to confirmation prompts promptly

#### "Token not found" errors  
- Check that the correct continuation token is being passed
- Verify that tokens are not being reused after resolution

#### Server not starting
- Verify all required dependencies are installed
- Check environment variable configuration
- Ensure server is being run with a python venv that has all required dependencies:

Example mcp client configuration for the server:

  "mcpServers": {
    "mailsh": {
      "command": "/home/striga/Mailsh/Mailsh/venv/bin/python",
      "args": [
        "/home/striga/Mailsh/Mailsh/tmp/mailsh_app/mcp/server.py"
      ],
      "cwd": "/home/striga/Mailsh/Mailsh/tmp",
      "timeout": 30000


## License

This project is licensed under the same license as the Mailsh application.
