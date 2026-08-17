"""
Centralized color formatting helpers for CLI status displays.

Provide small helper functions to consistently color task and schedule statuses.
"""
from typing import Optional

# ANSI color codes used across the app
_GREEN = "\033[92m"
_YELLOW = "\033[93m"
# Use a sharp, pure red (truecolor #ff0000) and include an ANSI italic code so
# error messages appear italicized where the terminal supports it. Terminals
# that don't support italic or truecolor will gracefully ignore those parts.
# Sequence: italic (3) then truecolor foreground (38;2;R;G;B)
_RED = "\033[3m\033[38;2;255;0;0m"
_ORANGE = "\033[38;5;208m"  # distinct orange for interrupted
_PURPLE = "\033[38;2;170;0;255m"
_RESET = "\033[0m"


def _wrap(color: str, text: str) -> str:
    return f"{color}{text}{_RESET}"

# Public mapping for common named colors used across the app
COLORS = {
    'success': _GREEN,
    'warning': _YELLOW,
    'error': _RED,        # keep truecolor/error style separate if needed
    'info': '\033[94m',
    'cyan': '\033[38;2;0;215;255m',  # #00d7ff in truecolor format (kept for backward compatibility)
    'theme': _PURPLE,                 # New theme color using purple
    'orange': _ORANGE,
    'reset': _RESET,
}


def color_text(name: str, text: str) -> str:
    """Wrap text with a named color from COLORS. If name unknown, return text unchanged."""
    if name in COLORS:
        return f"{COLORS[name]}{text}{_RESET}"
    return text


def color_for_task_status(status) -> str:
    """Return a colored display string for a task status.

    "status" may be a string or an enum-like object with a ``value`` attribute.
    This function normalizes the visible label (e.g. map 'ended' -> 'canceled')
    and returns a string containing ANSI color codes.
    """
    if hasattr(status, "value"):
        s = status.value
    else:
        s = str(status)

    # Normalize ended -> canceled for display consistency
    display = "canceled" if s == "ended" else s

    if display in ["running", "completed"]:
        return _wrap(_GREEN, display)
    if display == "paused":
        return _wrap(_YELLOW, display)
    if display == "interrupted":
        return _wrap(_ORANGE, display)
    if display in ["failed", "canceled", "cancelled"]:
        return _wrap(_RED, display)

    # Fallback: green
    return _wrap(_GREEN, display)


def color_for_schedule_status(status_str: str, task_info: Optional[object] = None) -> str:
    """Return a colored display string for schedule-related statuses.

    Handles simple labels like 'sent', 'scheduled', 'failed', and compound
    labels like 'started(paused)' and 'started(interrupted)'.

    If ``task_info`` is provided (optional), callers can still pass it for
    future enhancements; currently it's unused.
    """
    s = status_str or ""

    if s == 'sent':
        return _wrap(_GREEN, s)
    if s == 'scheduled':
        return _wrap(_YELLOW, s)
    if s in ('cancelled', 'cancelled', 'cancelled') or s == 'cancelled':
        return _wrap(_RED, s)
    if s == 'failed':
        return _wrap(_RED, s)
    if s == 'started':
        return _wrap(_GREEN, s)
    if s == 'completed':
        return _wrap(_GREEN, s)
    if s == 'paused':
        return _wrap(_YELLOW, s)

    # Compound states: e.g. started(paused), started(interrupted)
    if s.startswith('started(') and s.endswith(')'):
        inner = s[len('started('):-1]
        if inner == 'paused':
            return f"{_wrap(_GREEN, 'started')}({_wrap(_YELLOW, 'paused')})"
        if inner == 'interrupted':
            return f"{_wrap(_GREEN, 'started')}({_wrap(_ORANGE, 'interrupted')})"
        # Unknown inner state: color started green and inner as red
        return f"{_wrap(_GREEN, 'started')}({_wrap(_RED, inner)})"

    # Default: no color
    return s
