# Mailsh - Robust Command-Line Email Client

## Project Overview

Mailsh is a sophisticated command-line email sending client written in Python. It provides an interactive shell interface for composing, sending, scheduling, and managing email communications with support for bulk operations, templates, and contacts management.

### Key Features

- **Interactive Shell**: Rich command-line interface with tab completion, history, and syntax highlighting
- **SMTP Profiles**: Multiple SMTP connection profiles with easy switching
- **Email Composition**: Interactive email creation with support for attachments, HTML/Plain text, and custom headers
- **Templates System**: Template-based email composition with variable substitution
- **Contacts Management**: CSV-based contact lists with validation and bulk operations
- **Scheduling**: Schedule emails for future sending with flexible date/time formats
- **Bulk Sending**: Parallel email sending with rate limiting and retry mechanisms
- **Task Management**: Background task execution with pause/resume/cancel operations
- **Safety Features**: Built-in safety checks and confirmation prompts
- **History Tracking**: Comprehensive logging of sent emails with status tracking
- **MCP Protocol**: Mailsh Command Protocol server for programmatic access

### Architecture

The project is organized into several key modules:

- **core/**: Core business logic including configuration, profiles, email composition, sending, and history
- **cli/**: Command-line interface and shell implementation with command handlers
- **features/**: Optional feature modules for templates, scheduling, and contacts
- **utils/**: Shared utilities and helper functions
- **mcp/**: Mailsh Command Protocol server for external applications
- **features/safety/**: Safety and confirmation management system

## Building and Running

### Prerequisites

- Python 3.8 or higher
- pip package manager

### Installation

1. **Clone or download the project**
2. **Install dependencies**:

```bash
pip install -r requirements.txt
```

The project requires `mcp-server==0.1.4` for MCP functionality.

### Running Mailsh

The application can be run in several ways:

1. **Direct execution**:
```bash
python Mailsh.py
```

2. **As a module**:
```bash
python -m mailsh_app
```

3. **Using the installed package** (if installed):
```bash
mailsh
```

### Basic Usage

1. **Setup profiles**: Create SMTP profiles using `profile add`
2. **Connect**: Use `connect <profile_name>` to connect to an SMTP server
3. **Compose**: Create emails using `compose` or `set` commands
4. **Preview**: Use `preview` to see your draft
5. **Send**: Use `send` to dispatch the email

## Development Conventions

### Code Structure

- Core functionality is placed in the `core/` directory
- Optional features are added to the `features/` directory  
- New commands are created in `cli/` directory
- Utility functions go in the `utils/` directory
- Self-contained utility modules should avoid importing from other directories

### Module Dependencies

- Core modules can import from `utils`
- Feature modules can import from `utils` and `core`
- CLI modules can import from everywhere (`utils`, `core`, `features`)
- Utility modules should be self-contained and avoid importing from other directories

### Safety and Security

- Email validation and DNS checks
- Rate limiting to prevent spam
- Confirmation prompts for destructive operations
- MCP safety features with continuation tokens
- Session state persistence

## Key Commands

### Connection & Profiles
- `connect <profile>` - Connect to SMTP profile
- `disconnect` - Disconnect from current profile
- `profile add/list/edit/remove/show/connect` - Manage SMTP profiles

### Email Composition
- `compose` - Interactive email composition
- `set <field> <value>` - Set email field (including attachments)
- `unset <field> [index]` - Unset email field
- `preview` - Preview current draft
- `clear` - Clear current draft

### Sending
- `send` - Send current email
- `send bulk --contacts` - Bulk send using contact lists
- `task list/watch/show/pause/resume/end/clean` - Manage bulk send tasks

### Templates & Contacts
- `template list/show/create/import/edit/delete/test` - Manage email templates
- `contacts import/list/preview/validate/update/remove` - Manage contact lists

### Configuration & History
- `config get/set/show/reset` - Manage configuration
- `history [list]/show/stats` - View email history

### Scheduling
- `schedule send/list/show/cancel/clear` - Manage scheduled emails

## MCP (Mailsh Command Protocol)

The project includes an MCP server implementation that allows external applications to control Mailsh programmatically. This is particularly useful for integration with other tools or for automation purposes.

### MCP Features
- Token-based authentication and secure command execution
- Continuation tokens for multi-step operations requiring confirmation
- Programmatic access to all Mailsh functionality
- Session state management for external clients

## Configuration Options

Mailsh supports extensive configuration options including:
- Rate limiting (emails per minute/hour)
- Bulk send settings (parallel connections, retry attempts)
- Email validation settings
- Template engine configuration
- Tracking options (read receipts, SMTP response logging)
- Logging levels and settings
- Editor preferences
- Syntax highlighting customization
- Safety features enable/disable





# Instructions for Coding Agents

## Problem Understanding Protocol

When you receive a problem description, bug report, or feature request from the human developer, you **MUST** follow this protocol before making any changes to the codebase:

### 1. Demonstrate Understanding First

Before proceeding with any code modifications, you must:

- Restate the problem or request in your own words
- Identify the specific components, files, or systems involved
- Clarify the expected behavior vs. current behavior (for bugs)
- Outline your proposed approach to solving the problem
- Highlight any assumptions you're making

### 2. Wait for Confirmation

After demonstrating your understanding:

- Wait for explicit approval from the human developer
- Address any clarifications or corrections they provide
- Refine your understanding if needed

### 3. Proceed Only After Approval

Only begin implementing changes after receiving clear confirmation that your understanding is correct.

## Why This Matters

This protocol ensures:

- Alignment between your interpretation and the developer's intent
- Reduced wasted effort on incorrect solutions
- Better documentation of the problem-solving process
- Opportunity to catch misunderstandings early

---

**Remember:** Taking time to confirm understanding upfront saves significant time in the long run.
