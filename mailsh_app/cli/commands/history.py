"""
Email history and statistics commands.

Commands: history (list/show/stats)
"""

from typing import Dict, List, Optional, Any
import json
from datetime import datetime
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
from ...core.config import Config
from ...core.profile import Profile
from ...core.history import History
from ...features.templates import TemplateEngine
from ...core.composer import EmailComposer
from ...features.scheduler import ScheduleManager
from ...features.contacts import ContactsManager


class HistoryCommands:
    """Mixin class providing history-related commands."""
    
    def _parse_date_arg(self, date_str: str):
        """Parse date argument which can be YYYY-MM-DD, YYYY-MM-DDTHH:MM:SS, or relative terms"""
        from datetime import datetime, timedelta
        
        if not date_str:
            return None
            
        # Handle relative terms
        if date_str.lower() == 'today':
            today = datetime.now().date()
            return datetime.combine(today, datetime.min.time())
        elif date_str.lower() == 'yesterday':
            yesterday = datetime.now().date() - timedelta(days=1)
            return datetime.combine(yesterday, datetime.min.time())
        
        # Try to parse as ISO format first
        try:
            # Handle ISO format with or without time
            if 'T' in date_str:
                return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            else:
                # If it's just YYYY-MM-DD, create a datetime at start of day
                date_part = datetime.fromisoformat(date_str)
                return datetime.combine(date_part.date(), datetime.min.time())
        except ValueError:
            pass
        
        # Try common date formats
        for fmt in ['%Y-%m-%d', '%Y-%m-%d %H:%M:%S', '%m/%d/%Y', '%d/%m/%Y']:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue
        
        return None

    def cmd_history(self, args: List[str]):
        """View email history"""
        if not args or args[0] == "list":
            history = self.history.get_all()
            
            if not history:
                self._print("No email history", "warning")
                self._print("Send some emails to see history here", "info")
                return
            
            # Parse flags for filtering and pagination
            top_count = None
            bottom_count = None
            show_all = False
            status_filter = None
            profile_filter = None
            recipient_filter = None
            subject_filter = None
            from_date_filter = None
            to_date_filter = None
            
            i = 1
            while i < len(args):
                arg = args[i]
                
                if arg == "--top" and i + 1 < len(args):
                    try:
                        top_count = int(args[i + 1])
                        if top_count <= 0:
                            self._print("Error: Count must be positive", "error")
                            return
                        i += 2
                    except ValueError:
                        self._print("Usage: history list --top <count>", "error")
                        return
                elif arg == "--bottom" and i + 1 < len(args):
                    try:
                        bottom_count = int(args[i + 1])
                        if bottom_count <= 0:
                            self._print("Error: Count must be positive", "error")
                            return
                        i += 2
                    except ValueError:
                        self._print("Usage: history list --bottom <count>", "error")
                        return
                elif arg == "--all":
                    show_all = True
                    i += 1
                elif arg == "--status" and i + 1 < len(args):
                    status_filter = args[i + 1].lower()
                    if status_filter not in ['sent', 'failed']:
                        self._print("Error: Status must be 'sent' or 'failed'", "error")
                        return
                    i += 2
                elif arg == "--profile" and i + 1 < len(args):
                    profile_filter = args[i + 1]
                    i += 2
                elif arg == "--recipient" and i + 1 < len(args):
                    recipient_filter = args[i + 1].lower()
                    i += 2
                elif arg == "--subject" and i + 1 < len(args):
                    subject_filter = args[i + 1].lower()
                    i += 2
                elif arg == "--from" and i + 1 < len(args):
                    from_date_filter = args[i + 1]
                    i += 2
                elif arg == "--to" and i + 1 < len(args):
                    to_date_filter = args[i + 1]
                    i += 2
                else:
                    self._print("Usage: history list [filters and options]", "error")
                    self._print("Filters: --status <status> --profile <name> --recipient <email> --subject <pattern> --from <date> --to <date>", "error")
                    self._print("Options: --top <count> --bottom <count> --all", "error")
                    return
            
            # Apply filters to history
            filtered_history = []
            for entry in history:
                include = True
                
                # Status filter
                if status_filter and entry.get('status', '').lower() != status_filter:
                    include = False
                
                # Profile filter
                if profile_filter and entry.get('profile', '').lower() != profile_filter.lower():
                    include = False
                
                # Recipient filter (check to, cc, bcc)
                if recipient_filter:
                    recipient_match = False
                    for field in ['to', 'cc', 'bcc']:
                        recipients = entry.get(field, [])
                        if isinstance(recipients, list):
                            for recipient in recipients:
                                if recipient_filter in recipient.lower():
                                    recipient_match = True
                                    break
                        elif isinstance(recipients, str) and recipient_filter in recipients.lower():
                            recipient_match = True
                    if not recipient_match:
                        include = False
                
                # Subject filter
                if subject_filter and subject_filter not in entry.get('subject', '').lower():
                    include = False
                
                # Date filters
                if from_date_filter or to_date_filter:
                    timestamp = entry.get('timestamp', '')
                    if timestamp:
                        try:
                            entry_time = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                            
                            if from_date_filter:
                                from_time = self._parse_date_arg(from_date_filter)
                                if from_time and entry_time < from_time:
                                    include = False
                            
                            if to_date_filter:
                                to_time = self._parse_date_arg(to_date_filter)
                                if to_time and entry_time > to_time:
                                    include = False
                        except ValueError:
                            # If timestamp parsing fails, include by default
                            pass

                
                if include:
                    filtered_history.append(entry)
            
            # Determine which entries to display after filtering
            if show_all:
                display_history = filtered_history
            elif top_count:
                display_history = filtered_history[:top_count]
            elif bottom_count:
                display_history = filtered_history[-bottom_count:]
            else:
                # Default: show last 20
                display_history = filtered_history[-20:] if len(filtered_history) > 20 else filtered_history
            
            print("\n" + "="*110)
            self._print("EMAIL HISTORY", "theme")
            print("="*110)
            print(f"{'#':<4} {'Profile':<15} {'To':<30} {'Subject':<25} {'Status':<8} {'Date':<20}")
            print("-"*110)
            
            # Calculate starting index for numbering
            start_idx = len(history) - len(display_history) + 1 if not top_count and not show_all else 1
            
            enum_start = start_idx
            for i, entry in enumerate(display_history, enum_start):
                profile = entry.get('profile', 'N/A')
                
                # Handle 'to' field safely - it might be missing, a list, or a string
                to_field = entry.get('to', [])
                if isinstance(to_field, list):
                    to_str = ', '.join(to_field)
                elif isinstance(to_field, str):
                    to_str = to_field
                else:
                    to_str = str(to_field) if to_field else 'N/A'
                
                if len(to_str) > 29:
                    to_str = to_str[:26] + "..."
                
                subject = entry.get('subject', 'N/A')
                if len(subject) > 24:
                    subject = subject[:21] + "..."
                
                status = entry.get('status', 'unknown')
                timestamp = entry.get('timestamp', '')[:19].replace('T', ' ') if entry.get('timestamp') else 'N/A'
                
                from ...utils.colors import color_text

                status_colored = status
                if status == 'sent':
                    status_colored = color_text('success', status)
                elif status == 'failed':
                    status_colored = color_text('error', status)
                
                print(f"{i:<4} {profile:<15} {to_str:<30} {subject:<25} {status_colored:<8} {timestamp:<20}")
            
            print("="*110 + "\n")
            
            # Print summary if not showing all
            if not show_all and len(history) > len(display_history):
                self._print(f"Showing {len(display_history)} of {len(history)} emails", "info")
                self._print("Use 'history show <#>' for details", "info")
                self._print(f"Use 'history list --all' to see all emails", "info")
        
        elif args[0] == "show":
            if len(args) < 2:
                self._print("Usage: history show <#>", "error")
                return
            
            try:
                idx = int(args[1]) - 1
                history = self.history.get_all()
                
                if 0 <= idx < len(history):
                    entry = history[idx]
                    print("\n" + "="*70)
                    self._print(f"Email Details (#{idx+1})", "theme")
                    print("="*70)
                    import json
                    print(json.dumps(entry, indent=2))
                    print("="*70 + "\n")
                else:
                    self._print(f"Invalid ID. Valid range: 1-{len(history)}", "error")
            except ValueError:
                self._print("Invalid ID. Must be a number.", "error")
        
        elif args[0] == "stats":
            stats = self.history.get_stats()
            print("\n" + "="*50)
            self._print("EMAIL STATISTICS", "theme")
            print("="*50)
            print(f"Total emails sent: {stats['total']}")
            print(f"Successful: {stats['sent']}")
            print(f"Failed: {stats['failed']}")
            if stats['total'] > 0:
                print(f"Success rate: {stats['success_rate']:.2f}%")
            print("="*50 + "\n")
        
        else:
            self._print(f"Unknown action: {args[0]}", "error")
            self._print("Valid actions: list, show, stats", "info")