"""
Template engine for email body rendering with variable substitution.

This module provides simple template functionality with {{variable}} 
syntax for dynamic email content generation.
"""

from pathlib import Path
from typing import List, Optional, Dict
import re


class TemplateEngine:
    """Simple template engine with variable substitution"""
    
    def __init__(self, config_dir: Path, syntax: str = "{{var}}"):
        self.template_dir = config_dir / "templates"
        self.template_dir.mkdir(exist_ok=True)
        self.syntax = syntax
    
    def render(self, text: str, variables: Dict[str, str]) -> str:
        """Render template with variables using {{variable}} format only"""
        result = text
        for key, value in variables.items():
            # Support only {{var}} syntax for consistency
            result = result.replace(f"{{{{{key}}}}}", str(value))
        return result
    
    def save(self, name: str, content: str):
        """Save template"""
        filepath = self.template_dir / f"{name}.txt"
        with open(filepath, 'w') as f:
            f.write(content)
    
    def load(self, name: str) -> Optional[str]:
        """Load template"""
        filepath = self.template_dir / f"{name}.txt"
        if filepath.exists():
            with open(filepath, 'r') as f:
                return f.read()
        return None
    
    def list(self) -> List[str]:
        """List all templates"""
        return [f.stem for f in self.template_dir.glob("*.txt")]
    
    def delete(self, name: str) -> bool:
        """Delete template"""
        filepath = self.template_dir / f"{name}.txt"
        if filepath.exists():
            filepath.unlink()
            return True
        return False