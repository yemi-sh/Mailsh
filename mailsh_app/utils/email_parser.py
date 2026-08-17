"""
Email parsing utilities for extracting content from .eml files.

This module provides functions to parse email files and extract body content
in various formats (HTML, plain text).
"""

import email
from email import policy


def extract_body(eml_path, format_type):
    """
    Extract email body from .eml file using Python's built-in email module.
    
    Args:
        eml_path: Path to .eml file
        format_type: 'html' or 'text'
    
    Returns:
        Extracted body content as string, or None if not found
    """
    try:
        # Parse the email file
        with open(eml_path, 'rb') as f:
            msg = email.message_from_binary_file(f, policy=policy.default)
        
        html_body = None
        text_body = None
        
        # Handle multipart emails
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition", "")).lower()
                
                # Skip attachments
                if "attachment" in content_disposition:
                    continue
                
                # Extract HTML body
                if content_type == "text/html" and html_body is None:
                    try:
                        html_body = part.get_payload(decode=True).decode(
                            part.get_content_charset() or 'utf-8', errors='replace'
                        )
                    except Exception:
                        pass
                
                # Extract plain text body
                elif content_type == "text/plain" and text_body is None:
                    try:
                        text_body = part.get_payload(decode=True).decode(
                            part.get_content_charset() or 'utf-8', errors='replace'
                        )
                    except Exception:
                        pass
        
        # Handle simple (non-multipart) emails
        else:
            content_type = msg.get_content_type()
            try:
                body = msg.get_payload(decode=True).decode(
                    msg.get_content_charset() or 'utf-8', errors='replace'
                )
                if content_type == "text/html":
                    html_body = body
                else:
                    text_body = body
            except Exception:
                pass
        
        # Return requested format with fallback
        if format_type == 'html':
            if html_body:
                return html_body
            else:
                print("Warning: No HTML body found, using plain text instead...")
                return text_body
        else:  # text
            if text_body:
                return text_body
            else:
                print("Warning: No plain text body found, using HTML instead...")
                return html_body
        
    except Exception as e:
        print(f"Error parsing email: {e}")
        return None