import re
import os
from pathlib import Path
from typing import Optional, Tuple

# Try to use the external 'email_validator' package if installed for stronger checks
try:
    from email_validator import validate_email as _validate_email_lib, EmailNotValidError
    _HAS_EMAIL_VALIDATOR = True
except Exception:
    _HAS_EMAIL_VALIDATOR = False

# Simple but practical email regex fallback (not full RFC-5322)
EMAIL_RE = re.compile(r'^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$')


def is_email(addr: str, check_mx: bool = False) -> bool:
    """Return True if addr looks like an email address.

    If the optional dependency 'email_validator' is available it will be used
    for a stronger syntactic check. By default we do not perform MX lookups.
    """
    if not addr:
        return False
    addr = addr.strip()
    if _HAS_EMAIL_VALIDATOR:
        try:
            # check_deliverability toggles DNS/MX checks; keep False by default for speed
            _validate_email_lib(addr, check_deliverability=check_mx)
            return True
        except EmailNotValidError:
            return False
    # Fallback to conservative regex
    return bool(EMAIL_RE.match(addr))


def normalize_email(addr: str) -> str:
    addr = addr.strip()
    if '@' not in addr:
        return addr
    local, domain = addr.rsplit('@', 1)
    return f"{local}@{domain.lower()}"


def validate_port(p: int) -> bool:
    return isinstance(p, int) and 1 <= p <= 65535


def validate_security_mode(mode: str) -> bool:
    if not mode:
        return True
    return mode.lower() in ('starttls', 'ssl', 'none')


def is_hostname_or_ip(host: str) -> bool:
    """Basic validation for hostname or IPv4/IPv6 literal.

    This avoids performing DNS lookups. It's conservative but practical.
    """
    if not host:
        return False
    host = host.strip()
    # IPv4
    ipv4_re = re.compile(r'^(?:\d{1,3}\.){3}\d{1,3}$')
    if ipv4_re.match(host):
        parts = host.split('.')
        return all(0 <= int(p) <= 255 for p in parts)

    # IPv6 (very permissive check for presence of ':')
    if ':' in host:
        return True

    # Hostname rules: labels 1-63, overall <=253, allowed chars a-z0-9- (case-insensitive)
    if len(host) > 253:
        return False
    labels = host.split('.')
    label_re = re.compile(r'^[A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?$')
    return all(label_re.match(l) for l in labels if l)


def safe_resolve_path(path: str, must_exist: bool = True) -> Tuple[Optional[str], Optional[str]]:
    try:
        expanded = os.path.expanduser(os.path.expandvars(path))
        p = Path(expanded)
        if must_exist and not p.exists():
            return None, 'not found'
        # Resolve may fail on broken symlinks if strict=True; keep non-strict resolve
        resolved = str(p.resolve(strict=False))
        return resolved, None
    except Exception as e:
        return None, str(e)


def filesize_mb(path: str) -> Optional[float]:
    try:
        return Path(path).stat().st_size / (1024 * 1024)
    except Exception:
        return None


def validate_attachment(path: str, must_exist: bool = True) -> Tuple[Optional[str], Optional[str]]:
    """Resolve a path and validate it's a regular file suitable for attachment.

    Returns (resolved_path, None) on success or (None, error_message) on failure.
    Common error messages: 'not found', 'is a directory', 'not a regular file', or the underlying exception string.
    """
    resolved, err = safe_resolve_path(path, must_exist=must_exist)
    if err:
        return None, err
    try:
        p = Path(resolved)
        if p.is_dir():
            return None, 'is a directory'
        if not p.is_file():
            return None, 'not a regular file'
    except Exception as e:
        return None, str(e)
    return resolved, None
