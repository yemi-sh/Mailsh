"""
SMTP profile management for Mailsh.

This module handles storing and retrieving SMTP connection profiles including
credentials, server settings, and default headers.
"""

import json
from pathlib import Path
from typing import Dict, List, Optional


class Profile:
    """SMTP Profile manager"""
    
    def __init__(self, config_dir: Path):
        self.profiles_file = config_dir / "profiles.json"
        self.profiles = self.load()
    
    def load(self) -> Dict:
        if self.profiles_file.exists():
            with open(self.profiles_file, 'r') as f:
                return json.load(f)
        return {}
    
    def save(self):
        with open(self.profiles_file, 'w') as f:
            json.dump(self.profiles, f, indent=2)
    
    def add(self, name: str, smtp_host: str, smtp_port: int, 
            username: str, password: str, security: str = "starttls",
            default_headers: Optional[Dict] = None):
        self.profiles[name] = {
            "smtp": {
                "host": smtp_host,
                "port": smtp_port,
                "username": username,
                "password": password,
                "security": security
            },
            "default_headers": default_headers or {}
        }
        self.save()
    
    def edit(self, name: str, smtp_host: str, smtp_port: int, 
             username: str, password: str, security: str = "starttls",
             default_headers: Optional[Dict] = None):
        if name in self.profiles:
            self.profiles[name] = {
                "smtp": {
                    "host": smtp_host,
                    "port": smtp_port,
                    "username": username,
                    "password": password,
                    "security": security
                },
                "default_headers": default_headers or {}
            }
            self.save()
            return True
        return False  # Profile doesn't exist
    
    def remove(self, name: str):
        if name in self.profiles:
            del self.profiles[name]
            self.save()
            return True
        return False
    
    def get(self, name: str) -> Optional[Dict]:
        return self.profiles.get(name)
    
    def list(self) -> List[str]:
        return list(self.profiles.keys())