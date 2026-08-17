"""
Template management commands.

Commands: template (list/show/create/edit/delete/test/import)
"""

import time
from pathlib import Path
from typing import Dict, List, Optional, Any
import re
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
from ...utils.email_parser import extract_body
from ...core.config import Config
from ...core.profile import Profile
from ...core.history import History
from ...features.templates import TemplateEngine
from ...core.composer import EmailComposer
from ...features.scheduler import ScheduleManager
from ...features.contacts import ContactsManager


class TemplateCommands:
    """Mixin class providing template-related commands."""
    
    def cmd_template(self, args: List[str]):
        """Template management"""
        if not args:
            self._print("Usage: template <list|show|create|import|edit|delete|test>", "error")
            self._print("Type 'help template' for more information", "info")
            return
        
        action = args[0]
        
        if action == "list":
            templates = self.templates.list()
            if templates:
                self._print(f"Available templates ({len(templates)}):", "info")
                for t in templates:
                    print(f"  - {t}")
            else:
                self._print("No templates found", "warning")
                self._print("Use 'template create <name>' to create one", "info")
        
        elif action == "show":
            if len(args) < 2:
                self._print("Usage: template show <name>", "error")
                return
            
            name = args[1]
            content = self.templates.load(name)
            if content:
                print("\n" + "="*70)
                self._print(f"Template: {name}", "theme")
                print("="*70)
                print(content)
                print("="*70 + "\n")
            else:
                self._print(f"Template not found: {name}", "error")
        
        elif action == "create":
            if len(args) < 2:
                self._print("Usage: template create <name>", "error")
                return
            
            name = args[1]
            
            if name in self.templates.list():
                self._print(f"Template '{name}' already exists. Use 'template edit {name}' to modify it.", "error")
                return
            
            self._print("Opening editor to create template...", "info")
            self._print("Tip: Use {{variable}} for substitution", "info")
            time.sleep(1)
            content = self._edit_with_nano()
            
            if content.strip():
                self.templates.save(name, content)
                self._print(f"Template '{name}' created", "success")
            else:
                self._print("Template was empty, not saved", "warning")
        
        elif action == "edit":
            if len(args) < 2:
                self._print("Usage: template edit <name>", "error")
                return
            
            name = args[1]
            existing = self.templates.load(name)
            if not existing:
                self._print(f"Template not found: {name}", "error")
                self._print(f"Use 'template create {name}' to create it", "info")
                return
            
            self._print(f"Opening editor for template: {name}", "info")
            time.sleep(0.5)
            content = self._edit_with_nano(existing)
            self.templates.save(name, content)
            self._print(f"Template '{name}' updated", "success")
        
        elif action == "delete":
            if len(args) < 2:
                self._print("Usage: template delete <name>", "error")
                return
            
            name = args[1]
            
            if name not in self.templates.list():
                self._print(f"Template not found: {name}", "error")
                return
            
            # Use universal confirmation method
            template_path = self.templates.template_dir / f"{name}.txt"
            if not self.confirm_action(
                f"Delete template '{name}'? (y/n): ",
                context={"name": name, "template_path": str(template_path)}
            ):
                return
            
            if self.templates.delete(name):
                self._print(f"Template '{name}' deleted", "success")
        
        elif action == "test":
            if len(args) < 2:
                self._print("Usage: template test <name>", "error")
                return
            
            name = args[1]
            content = self.templates.load(name)
            if not content:
                self._print(f"Template not found: {name}", "error")
                return
            
            # Extract variables from template
            variables = set(re.findall(r'\$\{(\w+)\}|\{(\w+)\}', content))
            variables = [v[0] or v[1] for v in variables]
            
            if variables:
                self._print(f"Template variables found: {', '.join(variables)}", "info")
                print()
                test_data = {}
                for var in variables:
                    test_data[var] = input(f"Value for '{var}': ")
                
                rendered = self.templates.render(content, test_data)
                print("\n" + "="*70)
                self._print("Rendered template:", "theme")
                print("="*70)
                print(rendered)
                print("="*70 + "\n")
            else:
                self._print("No variables found in template", "warning")
                print("\nTemplate content:")
                print(content)
        
        elif action == "import":
            if len(args) < 3:
                self._print("Usage: template import <eml_file.eml> --html/--text <template_name>", "error")
                return
            
            eml_file = args[1]
            format_flag = args[2].lower()
            template_name = args[3] if len(args) >= 4 else None
            
            # Validate format flag
            if format_flag not in ['--html', '--text']:
                self._print("Usage: template import <eml_file.eml> --html/--text <template_name>", "error")
                return
            
            # If format flag is the last arg, check if template name exists
            if not template_name:
                if format_flag == '--html' and len(args) == 3:
                    self._print("Usage: template import <eml_file.eml> --html/--text <template_name>", "error")
                    return
                elif format_flag == '--text' and len(args) == 3:
                    self._print("Usage: template import <eml_file.eml> --html/--text <template_name>", "error")
                    return
            
            # Get template name (if not already assigned)
            if not template_name:
                template_name = args[3]
            
            # Validate EML file exists
            if not Path(eml_file).exists():
                self._print(f"Error: EML file not found: {eml_file}", "error")
                return
            
            # Validate template name is not empty
            if not template_name.strip():
                self._print("Template name cannot be empty", "error")
                return
            
            # Determine format type
            format_type = 'html' if format_flag == '--html' else 'text'
            
            # Extract the body from the EML file
            self._print(f"Extracting {format_type.upper()} body from {eml_file}...", "info")
            body_content = extract_body(eml_file, format_type)
            
            if body_content is None:
                self._print("Error: Could not extract email body", "error")
                return
            
            # Check if template already exists
            if template_name in self.templates.list():
                if not self.confirm_action(
                    f"Template '{template_name}' already exists. Overwrite? (y/n): ",
                    context={
                        "action": "template_import_overwrite", 
                        "template_name": template_name,
                        "eml_file": eml_file,
                        "format": format_type
                    },
                    cancel_message="Import cancelled"
                ):
                    return
            
            # Save the extracted body as a template
            self.templates.save(template_name, body_content)
            self._print(f"Template '{template_name}' imported successfully from {eml_file}", "success")
        
        else:
            self._print(f"Unknown action: {action}", "error")
            self._print("Valid actions: list, show, create, edit, delete, test, import", "info")
