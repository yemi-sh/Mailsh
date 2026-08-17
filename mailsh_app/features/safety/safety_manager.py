"""
Safety feature manager to orchestrate all safety checks before email sending.

This module provides a central manager that runs all safety checks and
coordinates with the confirmation prompt system when issues are detected.
"""

from typing import List, Tuple, Optional, Dict, Any
from ...core.composer import EmailComposer
from ...core.profile import Profile
from ...core.config import Config
from ...features.templates import TemplateEngine
from .safety_checker import SafetyChecker


class SafetyFeatureManager:
    """Manages all safety checks before email sending."""

    def __init__(self, config: Config, profiles: Profile, templates: TemplateEngine):
        self.config = config
        self.profiles = profiles
        self.templates = templates
        self.safety_checker = SafetyChecker(config, profiles, templates)

    def run_all_checks(self, composer: EmailComposer, current_profile: str, template_name: Optional[str] = None, sample_data: Optional[Dict[str, str]] = None) -> List[Tuple[bool, str]]:
        """
        Run all safety checks and return a list of (is_safe, message) tuples.

        Args:
            composer: The email composer object containing the email data
            current_profile: The name of the current profile being used
            template_name: Optional template name being used
            sample_data: Optional sample data to validate template variables against

        Returns:
            List of (is_safe, message) tuples from each safety check
        """
        results = []

        # Run each safety check
        results.append(self.safety_checker.check_html_mismatch(composer))
        results.append(self.safety_checker.check_unfulfilled_template_variables(composer, template_name, sample_data))
        results.append(self.safety_checker.check_rate_limit())
        results.append(self.safety_checker.check_empty_subject(composer))
        results.append(self.safety_checker.check_empty_body(composer))
        results.append(self.safety_checker.check_missing_from_headers(composer, current_profile))

        return results

    def get_unsafe_issues(self, results: List[Tuple[bool, str]]) -> List[str]:
        """Extract only the unsafe issues from the results."""
        return [message for is_safe, message in results if not is_safe]

    def has_unsafe_issues(self, results: List[Tuple[bool, str]]) -> bool:
        """Check if there are any unsafe issues detected."""
        return any(not is_safe for is_safe, _ in results)

    def should_run_safety_checks(self) -> bool:
        """Check if safety features are enabled in configuration."""
        value = self.config.get('safety_features.enabled')
        return value if value is not None else True