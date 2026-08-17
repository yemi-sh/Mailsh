"""
Email scheduling functionality.

This module provides the ability to schedule emails for future sending,
including storage, retrieval, and status management of scheduled emails.
"""

import json
import string
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Union


class ScheduledEmail:
    """Represents a scheduled email"""
    
    def __init__(self, id: str, composer_data: Dict, send_time: datetime, profile_name: str, status: str = "scheduled", is_bulk_operation: bool = False):
        self.id = id
        self.composer_data = composer_data  # Dictionary representation of EmailComposer
        self.send_time = send_time
        self.profile_name = profile_name
        self.status = status  # "scheduled", "sent", "failed", "cancelled", "converted_to_task"
        self.failure_reason = None  # Optional human-readable failure reason when status == 'failed'
        self.created_at = datetime.now()
        self.is_bulk_operation = is_bulk_operation  # Flag to identify bulk operations
        self.converted_at = None  # When a scheduled task was converted to a regular task
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization"""
        data = {
            "id": self.id,
            "composer_data": self.composer_data,
            "send_time": self.send_time.isoformat(),
            "profile_name": self.profile_name,
            "status": self.status,
            "failure_reason": self.failure_reason,
            "created_at": self.created_at.isoformat(),
            "is_bulk_operation": self.is_bulk_operation
        }
        if self.converted_at:
            data["converted_at"] = self.converted_at.isoformat()
        return data
    
    @classmethod
    def from_dict(cls, data: Dict):
        """Create from dictionary (for JSON deserialization)"""
        scheduled_email = cls(
            id=data["id"],
            composer_data=data["composer_data"],
            send_time=datetime.fromisoformat(data["send_time"]),
            profile_name=data["profile_name"],
            status=data.get("status", "scheduled"),
            is_bulk_operation=data.get("is_bulk_operation", False)
        )
        # restore optional failure reason if present
        if "failure_reason" in data:
            scheduled_email.failure_reason = data.get("failure_reason")
        if "converted_at" in data:
            scheduled_email.converted_at = datetime.fromisoformat(data["converted_at"])
        return scheduled_email


class ScheduleManager:
    """Manages scheduled emails"""
    
    def __init__(self, config_dir: Path):
        self.config_dir = config_dir
        self.scheduled_file = config_dir / "scheduled.json"
        self.scheduled_emails = self.load()
    
    def load(self) -> Dict[str, ScheduledEmail]:
        """Load scheduled emails from file"""
        if not self.scheduled_file.exists():
            return {}
        
        try:
            with open(self.scheduled_file, 'r') as f:
                data = json.load(f)
            
            scheduled = {}
            for id, email_data in data.items():
                scheduled[id] = ScheduledEmail.from_dict(email_data)
            
            return scheduled
        except Exception:
            # If there's an error loading, return empty dict
            return {}
    
    def save(self):
        """Save scheduled emails to file"""
        data = {id: email.to_dict() for id, email in self.scheduled_emails.items()}
        with open(self.scheduled_file, 'w') as f:
            json.dump(data, f, indent=2)
    
    def add(self, scheduled_email: ScheduledEmail):
        """Add a scheduled email"""
        self.scheduled_emails[scheduled_email.id] = scheduled_email
        self.save()
    
    def get(self, id: str) -> Optional[ScheduledEmail]:
        """Get a scheduled email by ID"""
        return self.scheduled_emails.get(id)
    
    def remove(self, id: str):
        """Remove a scheduled email by ID"""
        if id in self.scheduled_emails:
            del self.scheduled_emails[id]
            self.save()
    
    def get_all(self) -> List[ScheduledEmail]:
        """Get all scheduled emails"""
        return list(self.scheduled_emails.values())
    
    def get_upcoming(self) -> List[ScheduledEmail]:
        """Get all scheduled emails that are still pending"""
        now = datetime.now()
        return [email for email in self.scheduled_emails.values() 
                if email.status == "scheduled" and email.send_time > now]
    
    def get_past_due(self) -> List[ScheduledEmail]:
        """Get all scheduled emails that are past their send time"""
        now = datetime.now()
        return [email for email in self.scheduled_emails.values() 
                if email.status == "scheduled" and email.send_time <= now]
    
    def get_past_due_tasks(self) -> List[ScheduledEmail]:
        """Get all scheduled bulk tasks that are past their send time"""
        now = datetime.now()
        return [email for email in self.scheduled_emails.values() 
                if email.status == "scheduled" and email.is_bulk_operation and email.send_time <= now]
    
    def get_past_due_emails(self) -> List[ScheduledEmail]:
        """Get all scheduled individual emails that are past their send time (not bulk tasks)"""
        now = datetime.now()
        return [email for email in self.scheduled_emails.values() 
                if email.status == "scheduled" and not email.is_bulk_operation and email.send_time <= now]