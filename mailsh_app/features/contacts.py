"""
Contact list management for bulk email operations.

This module handles importing, validating, and managing contact lists
stored as CSV files for bulk email sending.
"""

import csv
from pathlib import Path
from typing import List, Tuple
from ..utils.validators import is_email


class ContactsManager:
    """Manages contact lists stored in CSV files"""
    
    def __init__(self, config_dir: Path):
        self.config_dir = config_dir
        self.contacts_dir = config_dir / "contacts"
        self.contacts_dir.mkdir(exist_ok=True)  # Create contacts directory if it doesn't exist
    
    def _get_contact_path(self, name: str) -> Path:
        """Get the file path for a contact list"""
        return self.contacts_dir / f"{name}.csv"
    
    def list_contacts(self) -> List[str]:
        """List all available contact names"""
        contacts = []
        for file_path in self.contacts_dir.glob("*.csv"):
            contacts.append(file_path.stem)  # Get filename without extension
        return sorted(contacts)
    
    def contact_exists(self, name: str) -> bool:
        """Check if a contact list exists"""
        return self._get_contact_path(name).exists()
    
    def import_contacts(self, name: str, csv_file: str, append: bool = False) -> tuple:
        """Import contacts from a CSV file to create or update a contact list"""
        source_path = Path(csv_file).resolve()
        
        if not source_path.exists():
            return (False, [], f"Source CSV file not found: {csv_file}")
        
        try:
            # Read source CSV
            with open(source_path, 'r', newline='', encoding='utf-8') as source_file:
                reader = csv.DictReader(source_file)
                rows = list(reader)
            
            if 'email' not in rows[0]:
                return (False, [], "CSV must have 'email' column")
            
            # Validate emails
            invalid_emails = []
            for i, row in enumerate(rows, 1):
                email = row.get('email', '').strip()
                if not email:
                    invalid_emails.append(f"Row {i}: Empty email")
                elif not is_email(email):
                    invalid_emails.append(f"Row {i}: Invalid email format - {email}")
            
            if invalid_emails:
                return (False, invalid_emails, f"Found {len(invalid_emails)} invalid emails")
            
            # Get destination path
            dest_path = self._get_contact_path(name)
            
            # If append mode and file exists, read existing contacts
            if append and dest_path.exists():
                with open(dest_path, 'r', newline='', encoding='utf-8') as dest_file:
                    existing_reader = csv.DictReader(dest_file)
                    existing_rows = list(existing_reader)
                
                # Create a set of existing emails for fast lookup
                existing_emails = {row['email'].lower() for row in existing_rows if row.get('email')}
                
                # Filter new rows to only include those not already in existing contacts
                new_rows = []
                for row in rows:
                    if row.get('email', '').lower() not in existing_emails:
                        new_rows.append(row)
                
                # Combine existing and new rows
                all_rows = existing_rows + new_rows
            else:
                all_rows = rows
                # Create directory if it doesn't exist
                dest_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Write to destination file
            with open(dest_path, 'w', newline='', encoding='utf-8') as dest_file:
                if all_rows:
                    fieldnames = all_rows[0].keys()
                    writer = csv.DictWriter(dest_file, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(all_rows)
            
            action = "updated" if append else "created"
            return (True, f"Contact list '{name}' {action} with {len(all_rows)} contacts")
            
        except Exception as e:
            return (False, f"Error importing contacts: {str(e)}")
    
    def get_contacts(self, name: str) -> tuple:
        """Get contact data for a named contact list"""
        if not self.contact_exists(name):
            return (False, [], f"Contact list '{name}' does not exist")
        
        try:
            with open(self._get_contact_path(name), 'r', newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            return (True, rows, "")
        except Exception as e:
            return (False, [], f"Error reading contact list: {str(e)}")
    
    def validate_contacts(self, name: str, validate_mx: bool = False) -> tuple:
        """Validate emails in a contact list"""
        success, rows, error = self.get_contacts(name)
        if not success:
            return (False, [], error)
        
        invalid = []
        for i, row in enumerate(rows, 1):
            email = row.get('email', '').strip()
            if not email:
                invalid.append((i, "Empty email"))
            elif not is_email(email):
                invalid.append((i, f"Invalid format: {email}"))
            elif validate_mx:
                # Import dns.resolver only when needed for MX validation
                try:
                    import dns.resolver
                    # Try to perform MX record lookup
                    domain = email.split('@')[1]
                    dns.resolver.resolve(domain, 'MX')
                except ImportError:
                    # dns.resolver not available
                    return (False, [], "dns.resolver module not available for MX validation. Install dnspython package.")
                except Exception:
                    invalid.append((i, f"No MX record for domain: {domain}"))
        
        return (True, invalid, f"Found {len(invalid)} invalid entries")
    
    def generate_random_name(self) -> str:
        """Generate a random name for a contact list"""
        import random
        import string
        # Generate a random name with 8 characters
        return 'contact_' + ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
    
    def remove_contact(self, name: str) -> tuple:
        """Remove a contact list"""
        contact_path = self._get_contact_path(name)
        if not contact_path.exists():
            return (False, f"Contact list '{name}' does not exist")
        
        try:
            contact_path.unlink()  # Remove the file
            return (True, f"Contact list '{name}' removed")
        except Exception as e:
            return (False, f"Error removing contact list: {str(e)}")