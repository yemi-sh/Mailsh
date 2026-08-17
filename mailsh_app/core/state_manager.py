"""
State management for MCP server with continuation tokens.

This module provides infrastructure for managing pending command states
that require user confirmation, allowing AI agents to respond to prompts
programmatically while preserving the original CLI experience for humans.
"""

import secrets
import hashlib
import threading
import time
from dataclasses import dataclass
from typing import Optional, Dict, Any
from contextlib import contextmanager


@dataclass
class CommandState:
    """
    Represents a pending command waiting for confirmation.
    """
    token: str                    # Unique continuation token
    command_name: str             # Name of the command (e.g., "delete_template")
    command_args: Dict[str, Any]  # Original command arguments
    prompt_message: str           # The confirmation prompt text
    context: Any                  # Command-specific context needed to resume
    created_at: float             # Unix timestamp of creation
    expires_at: float             # Unix timestamp when this state expires
    response: Optional[str]       # User's response ("y", "n", etc.) once resolved
    resolved: bool                # Whether this state has been resolved


class MCPError(Exception):
    """Base exception for MCP-related errors"""
    pass


class InvalidTokenError(MCPError):
    """Raised when a continuation token is invalid, expired, or already used"""
    pass


class CommandExecutionError(MCPError):
    """Raised when a command fails during execution"""
    pass


class StateManagerError(MCPError):
    """Raised for state management issues"""
    pass


class ConfirmationRequest(Exception):
    """
    Special exception raised when a command needs user confirmation.
    Used to interrupt normal command flow and convert to MCP response.
    """
    def __init__(self, prompt_message: str, context: Any = None):
        self.prompt_message = prompt_message
        self.context = context
        super().__init__(prompt_message)


class ExecutionMode:
    """
    Context manager that controls whether commands run in CLI or MCP mode.
    Stored in thread-local storage to allow concurrent operations.
    """
    
    # Thread-local storage for execution mode
    _local = threading.local()
    
    @staticmethod
    def set_mode(mode: str) -> None:
        """Sets execution mode for current thread: 'cli' or 'mcp'"""
        ExecutionMode._local.mode = mode
    
    @staticmethod
    def get_mode() -> str:
        """Returns current execution mode, defaults to 'cli'"""
        return getattr(ExecutionMode._local, 'mode', 'cli')
    
    @staticmethod
    def is_mcp_mode() -> bool:
        """Returns True if currently in MCP mode"""
        return ExecutionMode.get_mode() == 'mcp'
    
    @classmethod
    @contextmanager
    def mcp_mode(cls):
        """Context manager to temporarily set MCP mode"""
        old_mode = getattr(ExecutionMode._local, 'mode', 'cli')
        try:
            ExecutionMode.set_mode('mcp')
            yield
        finally:
            ExecutionMode.set_mode(old_mode)


def generate_token(command_name: str, timestamp: float) -> str:
    """
    Generates a cryptographically secure continuation token.
    
    Format: cmd_{command_name_hash}_{random}_{timestamp_hash}
    Example: cmd_7a3f_k9x2m4p8_9b2e
    """
    # Hash command name for privacy (6 chars)
    cmd_hash = hashlib.sha256(command_name.encode()).hexdigest()[:4]
    
    # Generate random component (8 chars)
    random_part = secrets.token_urlsafe(6)[:8]
    
    # Hash timestamp (4 chars)
    ts_hash = hashlib.sha256(str(timestamp).encode()).hexdigest()[:4]
    
    return f"cmd_{cmd_hash}_{random_part}_{ts_hash}"


class CommandStateManager:
    """
    Manages pending command states that require user confirmation.
    Thread-safe singleton that stores continuation tokens and their associated command contexts.
    """
    
    def __init__(self, timeout_seconds: int = 300):  # 5 minutes default
        self._states: Dict[str, CommandState] = {}
        self._lock = threading.Lock()
        self._timeout_seconds = timeout_seconds
        self._cleanup_timer = None
        self._start_cleanup_timer()
    
    def _start_cleanup_timer(self):
        """Starts background thread for periodic cleanup"""
        def cleanup_loop():
            while True:
                time.sleep(60)  # Clean up every minute
                try:
                    removed = self.cleanup_expired()
                    if removed > 0:
                        # Note: In a real implementation, you'd want to use proper logging
                        # For now, using print for visibility
                        print(f"INFO: Cleaned up {removed} expired states", flush=True)
                except Exception as e:
                    print(f"ERROR: Cleanup error: {e}", flush=True)
        
        self._cleanup_timer = threading.Thread(
            target=cleanup_loop, 
            daemon=True,
            name="StateCleanup"
        )
        self._cleanup_timer.start()
    
    def _is_expired(self, state: CommandState) -> bool:
        """Checks if a state has expired"""
        return time.time() > state.expires_at
    
    def create_state(self, command_name: str, command_args: dict, 
                     prompt_message: str, context: Any) -> str:
        """
        Creates a new pending command state and returns a continuation token.
        
        Args:
            command_name: Name of the command awaiting confirmation
            command_args: Original arguments passed to the command
            prompt_message: The confirmation message to show
            context: Any contextual data needed to resume the command
            
        Returns:
            A unique continuation token string
        """
        with self._lock:
            token = generate_token(command_name, time.time())
            state = CommandState(
                token=token,
                command_name=command_name,
                command_args=command_args,
                prompt_message=prompt_message,
                context=context,
                created_at=time.time(),
                expires_at=time.time() + self._timeout_seconds,
                response=None,
                resolved=False
            )
            self._states[token] = state
            return token
    
    def get_state(self, token: str) -> Optional[CommandState]:
        """
        Retrieves a command state by its continuation token.
        Returns None if token is invalid or expired.
        """
        with self._lock:
            state = self._states.get(token)
            if state and not self._is_expired(state):
                return state
            return None
    
    def resolve_state(self, token: str, response: str) -> CommandState:
        """
        Marks a state as resolved with the given response and removes it.
        Raises InvalidTokenError if token doesn't exist or is expired.
        """
        with self._lock:
            state = self._states.get(token)
            if not state:
                raise InvalidTokenError(f"Token not found: {token}")
            if self._is_expired(state):
                del self._states[token]
                raise InvalidTokenError(f"Token expired: {token}")
            if state.resolved:
                raise InvalidTokenError(f"Token already resolved: {token}")
            
            state.response = response
            state.resolved = True
            # Remove the state after resolution (one-time use)
            del self._states[token]
            return state
    
    def cleanup_expired(self) -> int:
        """
        Removes expired states. Returns count of removed states.
        Called periodically by a background thread.
        """
        with self._lock:
            current_time = time.time()
            expired_tokens = [
                token for token, state in self._states.items()
                if current_time > state.expires_at
            ]
            for token in expired_tokens:
                del self._states[token]
            return len(expired_tokens)
    
    def clear_all(self) -> None:
        """Clears all pending states. Used for testing and cleanup."""
        with self._lock:
            self._states.clear()