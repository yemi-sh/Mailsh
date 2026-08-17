"""
Help system and documentation for Mailsh commands.

This module contains all help text and documentation for Mailsh commands,
organized by command name.
"""

from typing import List


class CommandHelp:
    """Help system for all commands"""

    HELP_TEXT = {


        "profile": """
COMMAND: profile

DESCRIPTION:
    Manage SMTP profiles. Profiles store connection settings, credentials,
    and default headers for different email accounts.

USAGE:
    profile add                     Add a new profile interactively
    profile list                    List all configured profiles
    profile remove <name>           Remove a profile
    profile show [<name>]           Show profile details (current if no name provided)
    profile connect <name>          Connect to a profile
    profile disconnect              Disconnect from current profile
    profile edit <name>		    Edit a profile

OPTIONS:
    add      	 Create a new SMTP profile with interactive prompts
    list     	 Display all available profiles
    remove   	 Delete a profile permanently
    show     	 Display full configuration of a profile (or current profile if no name provided)
    connect 	 Connect to a profile
    disconnect   Disconnect from current profile
    edit         Edit an existing profile

EXAMPLES:
    profile add
    profile list
    profile remove old_account
    profile show               # shows current connected profile
    profile show gmail         # shows specific profile
    profile connect work
    profile disconnect
    profile edit work

SEE ALSO:
    profile
""",

        "draft": """
COMMAND: draft

DESCRIPTION:
    Manage email drafts with compose, preview, and clear operations.

USAGE:
    draft compose                   Interactively compose a new email
    draft preview                   Display a preview of the current email draft
    draft clear                     Clear the current email draft

SUBCOMMANDS:
    compose      Interactively compose a new email including recipients, subject, body and attachments
    preview      Display a preview of the current email draft including all headers, recipients, subject, body, and attachments
    clear        Clear the current email draft, removing all recipients, subject, body, attachments, and custom headers

EXAMPLES:
    draft compose
    draft preview
    draft clear

SEE ALSO:
    set, send
""",



        "set": """
COMMAND: set

DESCRIPTION:
    Set or modify individual email fields without full composition.

USAGE:
    set to <emails>                 Set To recipients (comma-separated)
    set cc <emails>                 Set Cc recipients (comma-separated)
    set bcc <emails>                Set Bcc recipients (comma-separated)
    set subject <text>              Set email subject
    set body                        Open nano to edit email body
    set header <name> <value>       Set custom email header
    set html <true|false>           Enable/disable HTML mode
    set attachment <filepath>       Attach file to email draft

ARGUMENTS:
    to/cc/bcc    Comma-separated list of email addresses
    subject      Subject line text (can include spaces)
    body         Opens nano editor for body content
    header       Custom header name and value
    html         Boolean for HTML email format
    attachment   Path to file to attach (supports absolute and relative paths)

EXAMPLES:
    set to john@example.com, jane@example.com
    set subject Important: Meeting Tomorrow
    set body
    set header X-Priority 1
    set header Reply-To support@company.com
    set html true
    set attachment document.pdf

SEE ALSO:
    draft, preview, clear
""",

        "unset": """
COMMAND: unset

DESCRIPTION:
    Unset or clear individual email fields. Resets fields to their default values.

USAGE:
    unset to                      Clear To recipients
    unset cc                      Clear Cc recipients
    unset bcc                     Clear Bcc recipients
    unset subject                 Clear email subject
    unset body                    Clear email body
    unset header <name>           Remove specific custom email header
    unset html                    Disable HTML mode
    unset attachment <index>      Remove attachment at specified index

ARGUMENTS:
    to/cc/bcc    Clears recipient lists to empty
    subject      Clears subject to empty string
    body         Clears body to empty string
    header       Removes specific header by name
    html         Sets HTML mode to false
    attachment   Numeric index of attachment to remove (optional)

EXAMPLES:
    unset to
    unset cc
    unset subject
    unset header X-Priority
    unset html
    unset attachment          # List attachments
    unset attachment 0        # Remove first attachment

SEE ALSO:
    set, draft, preview, clear
""",





        "send": """
COMMAND: send

DESCRIPTION:
    Send the current email draft. Validates recipients, confirms send,
    and logs the result to history. Can optionally use a template to
    override the draft body content.

USAGE:
    send [--template <template_name>]
    send bulk --contacts <contact_name> [--template <name>] [--dry-run]

OPTIONS:
    --template <name>    Use specified template for email body instead of draft
    bulk --contacts      Send emails to recipients from named contact list
    --dry-run            Run bulk operation without actually sending emails

REQUIREMENTS:
    - Must be connected to a profile (use 'profile connect')
    - Must have at least one recipient in 'To' field (for regular send)
    - Contact list must exist (for bulk send)
    - Will prompt for confirmation before sending

EXAMPLES:
    send
    send --template welcome
    send --template newsletter
    send bulk --contacts friends
    send bulk --contacts friends --template welcome
    send bulk --contacts friends --dry-run

SEE ALSO:
    draft, preview, contacts, history, template
""",

        "template": """
COMMAND: template

DESCRIPTION:
    Manage email templates with variable substitution.

USAGE:
    template list                   List all templates
    template show <name>            Display template content
    template create <name>          Create new template (opens nano)
    template edit <name>            Edit existing template (opens nano)
    template delete <name>          Delete template
    template test <name>            Test template with sample data
    template import <eml_file>      Import email body from .eml file as template

TEMPLATE SYNTAX:
    Use {{variable}} for substitution.

    Example:
        Hello {{name}},

        Welcome to {{company}}!

ARGUMENTS:
    name        Template name (without extension)
    eml_file    Path to .eml file to import

EXAMPLES:
    template list
    template create welcome
    template show welcome
    template edit welcome
    template test welcome
    template import email.eml --html newsletter
    template import email.eml --text plain_email
    template delete old_template

SEE ALSO:
    draft, set
""",

        "config": """
COMMAND: config

DESCRIPTION:
    View and modify Mailsh configuration settings.

USAGE:
    config show                     Display all configuration
    config get <key>                Get specific config value
    config set <key> <value>        Set config value
    config reset                    Reset all configuration to defaults
    config reset <key> [key...]     Reset specific keys to defaults

CONFIGURATION KEYS:
    rate_limiting.delay_between_emails_ms
    bulk_send.parallel_connections
    bulk_send.retry_attempts
    bulk_send.retry_delay_seconds
    bulk_send.continue_on_error
    validation.check_email_format
    validation.check_dns_mx
    validation.max_attachment_size_mb
    tracking.request_read_receipt
    editor
    encoding

EXAMPLES:
    config show
    config get rate_limiting
    config set bulk_send.retry_attempts 5
    config set editor vim
    config set editor default            # Reset editor to default (nano)
    config reset

SEE ALSO:
    profile
""",

        "history": """
COMMAND: history

DESCRIPTION:
    View email sending history, detailed logs, and statistics.

USAGE:
    history [list] [--status <status>] [--profile <name>] [--recipient <email>]
               [--subject <pattern>] [--from <date>] [--to <date>]
               [--top <count>] [--bottom <count>] [--all]
    history show <id>               Show detailed email info
    history stats                   Show sending statistics

FILTERS:
    --status <status>      Filter by sending status ('sent' or 'failed')
    --profile <name>       Filter by SMTP profile name
    --recipient <email>    Filter by recipient email address (in to, cc, bcc)
    --subject <pattern>    Filter by subject text (case-insensitive)
    --from <date>          Filter entries from specific date (YYYY-MM-DD)
    --to <date>            Filter entries up to specific date (YYYY-MM-DD)

OPTIONS:
    --top <count>          Show first N entries
    --bottom <count>       Show last N entries
    --all                  Show all entries (no pagination)

ARGUMENTS:
    id      Numeric ID from history list

EXAMPLES:
    history
    history list
    history list --status sent
    history list --profile work
    history list --recipient @gmail.com
    history list --subject meeting
    history list --from 2025-10-01
    history list --to 2025-10-31
    history list --from 2025-10-01 --to 2025-10-31
    history list --profile work --status sent
    history show 5
    history stats

SEE ALSO:
    send, schedule
""",

        "schedule": """
COMMAND: schedule

DESCRIPTION:
    Schedule emails for later sending. Manage scheduled emails with various
    time specifications including offsets, specific dates, and natural language.
    Bulk sends are handled as scheduled tasks with full management capabilities.

USAGE:
    schedule send <time_spec> [--template <name>]              Schedule current draft
    schedule send <time_spec> --contacts <contact_name>        Schedule bulk send as single task
    schedule list                                               List all scheduled emails
    schedule show <id>                                          Show details of scheduled email
    schedule cancel <id>                                        Cancel specific scheduled email
    schedule clear                                              Cancel all scheduled emails

TIME SPECIFICATIONS:
    - Relative: '30m', '2h', '1d', '3d5h30m'
    - Natural: 'tomorrow', 'in 2 hours', 'next Friday'
    - Specific: '2025-12-25 14:30', '2025-12-25', '12/25/2025 2:30 PM'

EXAMPLES:
    schedule send 30m                            # Send in 30 minutes
    schedule send tomorrow                       # Send tomorrow at 9 AM
    schedule send "2025-12-25 14:30"            # Send at specific date/time
    schedule send 2h --template newsletter      # Use template and send in 2 hours
    schedule send 2h --contacts marketing_list   # Schedule bulk send for 2 hours from now
    schedule list                                # Show all scheduled emails
    schedule show abc123...                      # Show details for specific scheduled email
    schedule cancel abc123...                    # Cancel specific scheduled email

SEE ALSO:
    send, template, history
""",

        "help": """
COMMAND: help

DESCRIPTION:
    Display help information for commands.

USAGE:
    help                Display general help and command list
    help <command>      Display detailed help for specific command

ARGUMENTS:
    command     Name of command to get help for

EXAMPLES:
    help
    help send
    help bulk
    help template

AVAILABLE COMMANDS:
    Connection:     profile
    Composition:    draft (compose/preview/clear), set, unset
    Sending:        send, bulk
    Templates:      template
    Configuration:  config
    History:        history
    System:         .<command> (run system commands)
    Other:          help, exit, quit
""",

        "system": """
SYSTEM COMMANDS:

DESCRIPTION:
    Execute system commands and interact with your filesystem by
    prepending commands with a dot (.)

USAGE:
    .<command> [args...]

FEATURES:
    - Run any system command
    - Change directories (persists in shell)
    - Full filesystem access
    - Command output displayed directly

EXAMPLES:
    .ls                     List files in current directory
    .ls -la                 List with details
    .cd /home/user         Change directory
    .pwd                   Print working directory
    .cat file.txt          Display file contents
    .mkdir newfolder       Create directory
    .nano myfile.txt       Edit file with nano
    .python script.py      Run Python script
    .grep "search" *.txt   Search in files

SPECIAL HANDLING:
    The 'cd' command changes Mailsh's working directory, so subsequent
    commands will use the new directory.

NOTE:
    You can use relative and absolute paths with all commands.
""",

        "contacts": """
COMMAND: contacts

DESCRIPTION:
    Manage contact lists stored within Mailsh. Import, update, validate,
    and preview contacts directly from the Mailsh shell instead of using
    external CSV files.

USAGE:
    contacts import <csv_file> [--name <contact_name>]      Import contacts from CSV
    contacts update <contact_name> <csv_file>              Update existing contacts
    contacts preview <contact_name> [--limit <n>]          Preview contact list
    contacts validate <contact_name>                       Validate contact emails
    contacts list                                          List all contact lists
    contacts remove <contact_name>                         Remove a contact list

SUBCOMMANDS:
    import      Import CSV file to create a new contact list
    update      Import CSV file to append new contacts to existing list
    preview     Show contact list preview (like bulk preview)
    validate    Validate emails in contact list (with optional MX validation)
    list        List all available contact lists
    remove      Remove a contact list

OPTIONS:
    --name <name>     Specify contact list name (random name if omitted during import)
    --limit <n>       Limit preview to first n entries (default: 5)
    --mx              For validate: perform MX record checks (requires dnspython)

EXAMPLES:
    contacts import my_contacts.csv --name friends
    contacts import my_contacts.csv             # Uses random name
    contacts update friends new_emails.csv      # Add to existing 'friends' list
    contacts preview friends --limit 10
    contacts validate friends --mx
    contacts validate friends                   # Basic validation only
    contacts list                               # List all contact lists
    contacts remove friends                     # Remove 'friends' contact list

SEE ALSO:
    send, template
""",

        "task": """
COMMAND: task

DESCRIPTION:
    Manage background bulk email sending tasks. Bulk sends run as background
    tasks with output redirected to log files instead of stdout, allowing
    you to continue using the Mailsh prompt for other operations.

USAGE:
    task list                          List all active tasks
    task show [<task_id>]              Show details of specific task (or current if only one active)
    task watch [<task_id>]             Watch task log in real-time (like tail -f) - press Ctrl+C to exit
    task pause <task_id>               Pause a running task
    task resume <task_id>              Resume a paused task
    task end <task_id>                 Cancel/stop a running task
    task clean [ended|completed|failed] Clean up old tasks (interactive confirmation)

SUBCOMMANDS:
    list      Display all active tasks with status, progress, and IDs
    show      Show detailed information about a task including progress, status, and log file
    watch     Continuously monitor task log output in real-time (press Ctrl+C to exit)
    pause     Pause a currently running task (can be resumed later)
    resume    Resume a previously paused task
    end       Cancel and stop a running or paused task
    clean     Remove completed/failed/cancelled task files to free up space

ARGUMENTS:
    task_id         Unique identifier for a specific task (shown when task starts)
    status_filter   Optional status to clean: ended, completed, failed (defaults to all)

EXAMPLES:
    task list                           # List all active tasks
    task show                           # Show details for single active task
    task show abc123def               # Show details for specific task
    task watch                          # Watch single active task log
    task watch abc123def              # Watch specific task log
    task pause abc123def              # Pause task with ID abc123def
    task resume abc123def             # Resume paused task
    task end abc123def                # Stop/cancel task
    task clean                        # Clean up all completed/failed/cancelled tasks
    task clean ended                  # Clean up only ended tasks
    task clean completed failed       # Clean up completed and failed tasks

NOTES:
    - Only bulk sends create tasks, regular sends do not
    - All task logs and metadata are stored in ~/.config/mailsh/.tasks/
    - Task logs are persistent and can be accessed even after Mailsh restarts
    - Use 'send bulk --contacts' to create new tasks
    - When watching logs with 'task watch', press Ctrl+C to exit watching (does not affect the task)

SEE ALSO:
    send, contacts, history
"""}

    @classmethod
    def get(cls, command: str) -> str:
        """Get help text for command"""
        return cls.HELP_TEXT.get(command, f"No help available for '{command}'")

    @classmethod
    def list_commands(cls) -> List[str]:
        """List all commands with help"""
        return list(cls.HELP_TEXT.keys())
