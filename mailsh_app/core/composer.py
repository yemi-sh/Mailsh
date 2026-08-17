"""
Email composition and draft management.

This module provides the EmailComposer class for maintaining email draft state
including recipients, subject, body, attachments, and custom headers.
"""

import copy
from typing import Dict


class EmailComposer:
    """Email composition state manager"""
    
    def __init__(self):
        self.reset()
    
    def reset(self):
        self.to = []
        self.cc = []
        self.bcc = []
        self.subject = ""
        self.body = ""
        self.attachments = []
        self.headers = {}
        self.html = False
    
    def to_dict(self) -> Dict:
        return {
            "to": self.to,
            "cc": self.cc,
            "bcc": self.bcc,
            "subject": self.subject,
            "body": self.body,
            "attachments": self.attachments,
            "headers": self.headers,
            "html": self.html
        }
    
    def from_dict(self, data: Dict):
        self.to = data.get("to", [])
        self.cc = data.get("cc", [])
        self.bcc = data.get("bcc", [])
        self.subject = data.get("subject", "")
        self.body = data.get("body", "")
        self.attachments = data.get("attachments", [])
        self.headers = data.get("headers", {})
        self.html = data.get("html", False)

    def clone(self):
        """Create a deep copy of this composer to capture current state"""
        new_composer = EmailComposer()
        # Use deepcopy to ensure complete independence from the original
        new_composer.to = copy.deepcopy(self.to)
        new_composer.cc = copy.deepcopy(self.cc)
        new_composer.bcc = copy.deepcopy(self.bcc)
        new_composer.subject = self.subject  # strings are immutable
        new_composer.body = self.body  # strings are immutable
        new_composer.attachments = copy.deepcopy(self.attachments)
        new_composer.headers = copy.deepcopy(self.headers)
        new_composer.html = self.html  # bool is immutable
        return new_composer
