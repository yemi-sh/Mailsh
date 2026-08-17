"""
SMTP email sending functionality.

This module handles the actual sending of emails via SMTP, including
message construction, attachment handling, and SMTP connection management.
"""

import smtplib
from datetime import datetime
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from email.utils import formataddr, make_msgid
from datetime import datetime
import io
import sys
from contextlib import redirect_stderr
from typing import Dict, Optional, Tuple

from .composer import EmailComposer
from .config import Config


class EmailSender:
    """SMTP email sender"""
    
    def __init__(self, profile_data: Dict, config: Config, task_log_file: str = None):
        self.profile = profile_data
        self.config = config
        self.task_log_file = task_log_file
    
    def send(self, composer: EmailComposer, tracking_id: Optional[str] = None) -> tuple:
        """Send email and return (success: bool, message: str, smtp_response: str)"""
        
        try:
            # Create message
            msg = MIMEMultipart('alternative') if composer.html else MIMEMultipart()
            
            # Set headers
            default_headers = self.profile.get('default_headers', {})
            
            # From header (support case-insensitive and dash/underscore variants)
            def _lookup_header(hdr_name, fallback_key):
                # hdr_name: e.g. 'From-Name'; fallback_key: e.g. 'from_name'
                # Check composer.headers with variants
                for key in composer.headers.keys():
                    norm = key.replace('_', '-').lower()
                    if norm == hdr_name.replace('_', '-').lower():
                        return composer.headers[key]
                return default_headers.get(fallback_key, '')

            from_name = _lookup_header('From-Name', 'from_name')
            from_address = _lookup_header('From-Address', 'from_address') or self.profile['smtp']['username']
            
            if from_name:
                msg['From'] = formataddr((from_name, from_address))
            else:
                msg['From'] = from_address
            
            # Other headers
            msg['To'] = ', '.join(composer.to)
            if composer.cc:
                msg['Cc'] = ', '.join(composer.cc)
            msg['Subject'] = composer.subject
            msg['Date'] = datetime.now().strftime('%a, %d %b %Y %H:%M:%S %z')
            msg['Message-ID'] = make_msgid()
            
            # Reply-To (support case-insensitive variants and underscores)
            def _get_reply_to():
                # Look in composer.headers first
                for key, val in composer.headers.items():
                    if key.replace('_', '-').lower() == 'reply-to':
                        return val
                # Then profile defaults
                if 'reply_to' in default_headers:
                    return default_headers['reply_to']
                if 'reply-to' in default_headers:
                    return default_headers['reply-to']
                return None

            reply_to_val = _get_reply_to()
            if reply_to_val:
                msg['Reply-To'] = reply_to_val
            
            # Read receipt
            if self.config.get('tracking.request_read_receipt'):
                msg['Disposition-Notification-To'] = from_address
            
            # Custom headers
            # Merge custom headers with composer.headers, normalizing keys.
            custom_headers = default_headers.get('custom', {})
            merged = {}
            # Start with custom headers
            for k, v in custom_headers.items():
                merged[k] = v
            # Composer headers override defaults; normalize keys to preserve original casing where possible
            for k, v in composer.headers.items():
                # Normalize header name to use hyphens
                norm = k.replace('_', '-').strip()
                merged[norm] = v

            # Remove From-Name/From-Address/Reply-To from merged output (they are handled separately)
            for forbidden in ['From-Name', 'From-Address', 'Reply-To']:
                # Remove any case-variant
                for mk in list(merged.keys()):
                    if mk.replace('_', '-').lower() == forbidden.replace('_', '-').lower():
                        merged.pop(mk, None)

            for key, value in merged.items():
                msg[key] = value
            
            # Body
            if composer.html:
                msg.attach(MIMEText(composer.body, 'html', self.config.get('encoding')))
            else:
                msg.attach(MIMEText(composer.body, 'plain', self.config.get('encoding')))
            
            # Attachments
            for filepath in composer.attachments:
                self._attach_file(msg, filepath)
            
            # Connect and send
            smtp_config = self.profile['smtp']
            security = smtp_config.get('security', 'starttls')
            
            if security == 'ssl':
                server = smtplib.SMTP_SSL(smtp_config['host'], smtp_config['port'])
            else:
                server = smtplib.SMTP(smtp_config['host'], smtp_config['port'])
                if security == 'starttls':
                    server.starttls()
            
            if self.config.get('logging.level') == 'DEBUG':
                if self.task_log_file:
                    # When in a task context, we need to redirect stderr to capture SMTP debug output
                    import sys

                    # Create a custom class that writes to our task log file instead of stderr
                    class TaskLogStream:
                        def __init__(self, log_file):
                            self.log_file = log_file

                        def write(self, text):
                            if text.strip():  # Only write non-empty lines
                                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                                with open(self.log_file, 'a', encoding='utf-8') as f:
                                    f.write(f"[{timestamp}] SMTP DEBUG: {text}")

                        def flush(self):
                            pass  # No-op for compatibility

                    # Create a custom stream that will write to the task log file
                    task_log_stream = TaskLogStream(self.task_log_file)

                    # Temporarily redirect stderr to our custom stream
                    original_stderr = sys.stderr
                    sys.stderr = task_log_stream

                    try:
                        # Enable debug level to generate output to our redirected stderr
                        server.set_debuglevel(1)
                        server.login(smtp_config['username'], smtp_config['password'])

                        # Send mail with redirected stderr to capture all debug info
                        all_recipients = composer.to + composer.cc + composer.bcc
                        response = server.sendmail(from_address, all_recipients, msg.as_string())
                    finally:
                        # Close the connection with debug output still redirected, then restore stderr
                        server.quit()
                        # Restore original stderr after closing connection, even if there's an error
                        sys.stderr = original_stderr
                    
                    # Return the result
                    return (True, "Email sent successfully", str(response))
                else:
                    # Original behavior - print to stderr (terminal)
                    server.set_debuglevel(1)
                    server.login(smtp_config['username'], smtp_config['password'])
                    all_recipients = composer.to + composer.cc + composer.bcc
                    response = server.sendmail(from_address, all_recipients, msg.as_string())
                    server.quit()
                    
                    # Return the result
                    return (True, "Email sent successfully", str(response))
            else:
                # No debug level - standard operation
                server.login(smtp_config['username'], smtp_config['password'])
                all_recipients = composer.to + composer.cc + composer.bcc
                response = server.sendmail(from_address, all_recipients, msg.as_string())
                server.quit()

                # Return the result
                return (True, "Email sent successfully", str(response))
            
        except Exception as e:
            return (False, f"Failed to send email: {str(e)}", "")
    
    def _attach_file(self, msg: MIMEMultipart, filepath: str):
        """Attach file to message"""
        with open(filepath, 'rb') as f:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(f.read())
        
        encoders.encode_base64(part)
        # Extract the original filename from the temporary filename if it follows the pattern
        # "attachment_{original_name}_{hash}" to preserve the original attachment name for recipients
        original_filename = Path(filepath).name
        temp_filename = Path(filepath).name
        if temp_filename.startswith('attachment_'):
            # Extract original name by removing prefix and hash suffix (32-char MD5 hash)
            if '_' in temp_filename:
                # Remove the "attachment_" prefix
                suffix = temp_filename[11:]  # len('attachment_') = 11
                
                # Find the last underscore which should separate the original name from the hash
                last_underscore = suffix.rfind('_')
                if last_underscore != -1:
                    potential_hash = suffix[last_underscore + 1:]
                    # Check if the part after the last underscore looks like an MD5 hash (32 hex chars)
                    if len(potential_hash) == 32 and all(c in '0123456789abcdef' for c in potential_hash.lower()):
                        original_filename = suffix[:last_underscore]
        
        part.add_header('Content-Disposition', f'attachment; filename={original_filename}')
        msg.attach(part)