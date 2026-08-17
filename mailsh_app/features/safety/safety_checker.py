"""
Safety features for Mailsh email sending.

This module provides safety checks to prevent common mistakes when sending emails.
Each safety check returns a tuple of (is_safe: bool, message: str) where
is_safe=False means a safety issue was detected.
"""

import re
from typing import Dict, List, Tuple, Optional
from ...core.composer import EmailComposer
from ...core.profile import Profile
from ...core.config import Config
from ...features.templates import TemplateEngine


class SafetyChecker:
    """Safety checker for email sending operations."""

    def __init__(self, config: Config, profiles: Profile, templates: TemplateEngine):
        self.config = config
        self.profiles = profiles
        self.templates = templates

    def check_html_mismatch(self, composer: EmailComposer) -> Tuple[bool, str]:
        """
        Check if html flag is set but body appears to be plain text, or vice versa.
        Returns (is_safe, message) where is_safe=False means a mismatch was detected.
        """
        body = composer.body or ""

        # Check if body contains common HTML elements/tags
        # This includes opening/closing tags, self-closing tags, and HTML entities
        has_html_tags = bool(re.search(r'<\s*[a-zA-Z][^>]*>', body))  # Any HTML tag
        has_html_entities = bool(re.search(r'&[a-zA-Z]+;', body))    # HTML entities like &nbsp;, &amp;

        has_html_content = has_html_tags or has_html_entities

        if composer.html and not has_html_content:
            return False, (
                "HTML flag is set but body appears to be plain text. "
                "This may render incorrectly for recipients."
            )
        elif not composer.html and has_html_content:
            return False, (
                "HTML flag is not set but body appears to contain HTML. "
                "This may render as raw HTML for recipients."
            )

        return True, "HTML/plain text flags match content"

    def check_unfulfilled_template_variables(self, composer: EmailComposer, template_name: Optional[str] = None, sample_data: Optional[Dict[str, str]] = None) -> Tuple[bool, str]:
        """
        Check if there are unfulfilled variables in the template being used.
        Returns (is_safe, message) where is_safe=False means unfulfilled variables were found.
        """
        if not template_name and not composer.body:
            return True, "No content to check for template variables"

        # Use either template content or composer body
        content = composer.body
        if template_name:
            template_content = self.templates.load(template_name)
            if template_content:
                content = template_content

        # The template engine now supports only {{key}} format for consistency
        # Find all {{key}} patterns
        double_brace_pattern = r'\{\{[^{}]+\}\}'
        all_vars = re.findall(double_brace_pattern, content)

        # If sample data is provided, render the template first and then check what remains
        if sample_data:
            rendered_content = self.templates.render(content, sample_data)
            # Find remaining unfulfilled variables in the rendered content
            unfulfilled_vars = re.findall(double_brace_pattern, rendered_content)
        else:
            # Use the original variables found in the content
            unfulfilled_vars = all_vars

        # Filter to only those that match the {{ }} pattern (still have their delimiters)
        filtered_vars = [var for var in unfulfilled_vars 
                        if var.startswith('{{') and var.endswith('}}') and len(var) > 4]

        if filtered_vars:
            unique_vars = list(set(filtered_vars))
            return False, (
                f"Detected unfulfilled template variables: {', '.join(unique_vars[:5])} "
                f"({'and more...' if len(unique_vars) > 5 else ''}). "
                "These will appear as literal text in the email."
            )

        return True, "No unfulfilled template variables detected"

    def check_rate_limit(self) -> Tuple[bool, str]:
        """
        Check if the current rate limit is lower than the default (might be flagged as spam).
        Returns (is_safe, message) where is_safe=False means rate limit is too low.
        """
        # Get current rate limit configuration
        current_delay = self.config.get('rate_limiting.delay_between_emails_ms')
        # Use the actual default from the config class instead of hardcoding
        default_delay = 3000  # Default 3 second between emails that Mailsh uses

        if current_delay and current_delay < default_delay:
            return False, (
                f"Current rate limit ({current_delay}ms) is lower than Mailsh default "
                f"({default_delay}ms). This may cause emails to be flagged as spam by receivers."
            )

        return True, "Rate limit is at or above Mailsh default"

    def check_empty_subject(self, composer: EmailComposer) -> Tuple[bool, str]:
        """
        Check if the email has no subject set.
        Returns (is_safe, message) where is_safe=False means subject is empty.
        """
        if not composer.subject or not composer.subject.strip():
            return False, "Email has no subject. This may be flagged as spam or ignored by recipients."

        return True, "Subject is set"

    def check_empty_body(self, composer: EmailComposer) -> Tuple[bool, str]:
        """
        Check if the email has no body set.
        Returns (is_safe, message) where is_safe=False means body is empty.
        """
        if not composer.body or not composer.body.strip():
            return False, "Email has no body content. This may be flagged as spam or appear suspicious to recipients."

        return True, "Body is set"

    def check_missing_from_headers(self, composer: EmailComposer, current_profile: str) -> Tuple[bool, str]:
        """
        Check if there is no From headers set AND there is also no default From headers in the profile.
        Returns (is_safe, message) where is_safe=False means From headers are missing.
        """
        if not current_profile:
            return True, "Not connected to any profile, skipping From header check"

        profile = self.profiles.get(current_profile)
        if not profile:
            return True, "Profile not found, skipping From header check"

        # Check if From-Address is set in composer headers
        composer_has_from_address = any(
            key.replace('_', '-').lower() == 'from-address'
            for key in composer.headers.keys()
        )

        # Check if profile has default headers
        profile_default_headers = profile.get('default_headers', {})
        profile_has_from_address = any(
            key in profile_default_headers
            for key in ['from_address', 'from-address', 'from_address', 'from_address']
        )

        # Check if profile's SMTP configuration can provide a from address
        smtp_username = profile.get('smtp', {}).get('username')
        profile_has_smtp_username = smtp_username is not None and smtp_username.strip() != ""

        has_from_address = composer_has_from_address or profile_has_from_address or profile_has_smtp_username

        if not has_from_address:
            return False, (
                "No From header is set in the email and no default From header is configured "
                "in the profile. This may cause delivery issues."
            )

        return True, "From headers are properly configured"
