# Mailsh

Mailsh is an interactive command-line email client for composing, sending, scheduling, and managing bulk email — with SMTP profiles, templates, contact lists, and a protocol server for automating it from other tools.

## Features

- **Interactive shell** — tab completion, command history, syntax highlighting
- **SMTP profiles** — configure and switch between multiple SMTP accounts
- **Email composition** — attachments, HTML/plain text, custom headers
- **Templates** — reusable email templates with variable substitution
- **Contacts** — import and manage CSV-based contact lists
- **Scheduling** — queue emails to send at a future date/time
- **Bulk sending** — parallel sends with rate limiting and retries
- **Task management** — pause, resume, or cancel background send jobs
- **Safety checks** — email/DNS validation and confirmation prompts before destructive actions
- **History** — full log of sent email with delivery status
- **MCP server** — exposes Mailsh's functionality to external tools programmatically

## Installation

Requires Python 3.8+.

```bash
git clone https://github.com/yemi-sh/Mailsh.git
cd Mailsh
pip install -r requirements.txt
```

## Usage

Run it directly, as a module, or (once installed) as the `mailsh` command:

```bash
python Mailsh.py
# or
python -m mailsh_app
# or, if installed:
mailsh
```

Typical first steps inside the shell:

```
profile add          # set up an SMTP profile
connect <profile>    # connect to it
compose               # draft an email
preview                # review the draft
send                    # send it
```

### Key commands

| Area | Commands |
|---|---|
| Connection | `connect`, `disconnect`, `profile add/list/edit/remove/show` |
| Composition | `compose`, `set`, `unset`, `preview`, `clear` |
| Sending | `send`, `send bulk --contacts`, `task list/watch/show/pause/resume/end` |
| Templates | `template list/show/create/import/edit/delete/test` |
| Contacts | `contacts import/list/preview/validate/update/remove` |
| Scheduling | `schedule send/list/show/cancel/clear` |
| Config & history | `config get/set/show/reset`, `history list/show/stats` |

## MCP (Mailsh Command Protocol)

Mailsh ships an MCP server (`mailsh_app/mcp`) so external tools can drive it programmatically — token-based auth, continuation tokens for multi-step confirmations, and full access to the same functionality as the shell.

## Project layout

```
mailsh_app/
├── core/       # business logic: config, profiles, composing, sending, history
├── cli/        # shell + command handlers
├── features/   # templates, scheduling, contacts, safety checks
├── utils/      # shared helpers
└── mcp/        # MCP server
```

## License

[MIT](LICENSE)
