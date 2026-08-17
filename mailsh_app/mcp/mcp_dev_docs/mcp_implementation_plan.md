# MCP Server Implementation Plan: Command State Manager with Continuation Tokens

## Overview

This implementation adds an MCP server to Mailsh that enables AI agents to interact with email functionality while preserving all existing confirmation prompts through a two-step interaction pattern. The solution uses a continuation token system that intercepts confirmation requests and converts them into structured responses.

---

## 1. Architecture & Design

### 1.1 Class Structure

#### CommandStateManager

```python
class CommandStateManager:
    """
    Manages pending command states that require user confirmation.
    Thread-safe singleton that stores continuation tokens and their associated command contexts.
    """
    
    # Attributes:
    # - _states: Dict[str, CommandState] - Maps continuation tokens to command states
    # - _lock: threading.Lock - Ensures thread-safe operations
    # - _timeout_seconds: int - How long states remain valid (default: 300)
    
    # Methods:
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
    
    def get_state(self, token: str) -> Optional[CommandState]:
        """
        Retrieves a command state by its continuation token.
        Returns None if token is invalid or expired.
        """
    
    def resolve_state(self, token: str, response: str) -> CommandState:
        """
        Marks a state as resolved with the given response and removes it.
        Raises InvalidTokenError if token doesn't exist or is expired.
        """
    
    def cleanup_expired(self) -> int:
        """
        Removes expired states. Returns count of removed states.
        Called periodically by a background thread.
        """
    
    def clear_all(self) -> None:
        """Clears all pending states. Used for testing and cleanup."""
```

#### CommandState

```python
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
```

#### ConfirmationRequest Exception

```python
class ConfirmationRequest(Exception):
    """
    Special exception raised when a command needs user confirmation.
    Used to interrupt normal command flow and convert to MCP response.
    """
    def __init__(self, prompt_message: str, context: Any = None):
        self.prompt_message = prompt_message
        self.context = context
        super().__init__(prompt_message)
```

#### ExecutionMode Context Manager

```python
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
    
    @staticmethod
    def get_mode() -> str:
        """Returns current execution mode, defaults to 'cli'"""
    
    @staticmethod
    def is_mcp_mode() -> bool:
        """Returns True if currently in MCP mode"""
    
    @classmethod
    @contextmanager
    def mcp_mode(cls):
        """Context manager to temporarily set MCP mode"""
        # Sets mode to 'mcp', yields, then restores previous mode
```

### 1.2 Data Models

#### MCP Response Formats

```python
# Success response
{
    "status": "success",
    "data": Any,  # Command-specific return value
    "message": Optional[str]
}

# Confirmation required response
{
    "status": "confirmation_required",
    "prompt": str,  # The confirmation message
    "continuation_token": str,  # Token to use for responding
    "command": str,  # Name of the command
    "expires_at": float  # Unix timestamp
}

# Error response
{
    "status": "error",
    "error_type": str,  # "InvalidTokenError", "CommandError", etc.
    "message": str,
    "details": Optional[dict]
}
```

#### State Storage Schema

```python
# In-memory storage structure
{
    "cmd_abc123": CommandState(
        token="cmd_abc123",
        command_name="delete_template",
        command_args={"name": "welcome"},
        prompt_message="Delete template 'welcome'? (y/n):",
        context={"template_path": "/path/to/template.txt"},
        created_at=1699123456.789,
        expires_at=1699123756.789,
        response=None,
        resolved=False
    ),
    # ... more states
}
```

### 1.3 Integration Points

#### Location 1: `mailsh_app/core/state_manager.py` (NEW FILE)
Create this new module to house the CommandStateManager and related classes.

#### Location 2: `mailsh_app/cli/shell.py`
Modify the main shell loop to:
- Initialize ExecutionMode for CLI sessions (stays in 'cli' mode)
- No other changes needed - existing behavior preserved

#### Location 3: `mailsh_app/cli/commands/*.py`
Modify each command handler that uses confirmation prompts:
- Wrap confirmation logic with ExecutionMode check
- If MCP mode, raise ConfirmationRequest instead of blocking input
- If CLI mode, use existing input() behavior

**Example locations:**
- `mailsh_app/cli/commands/templates.py` - delete_template, edit_template
- `mailsh_app/cli/commands/composition.py`
- `mailsh_app/cli/commands/tasks.py`
- `mailsh_app/cli/commands/contacts.py`
- Any other commands with confirmation prompts

#### Location 4: `mailsh_app/mcp/server.py` (NEW FILE) (our mcp_no_session/mailsh_mcp_server.py now goes here)
Create the MCP server that:
- Initializes CommandStateManager
- Wraps command calls in ExecutionMode.mcp_mode() context
- Catches ConfirmationRequest exceptions
- Provides the confirmation tool endpoint

#### Location 5: `mailsh_app/mcp/__init__.py` (NEW FILE)
Package initialization for MCP components.

### 1.4 State Lifecycle

```
1. CREATION
   ├─ Command executed in MCP mode
   ├─ Command logic reaches confirmation point
   ├─ ExecutionMode.is_mcp_mode() returns True
   ├─ Command raises ConfirmationRequest(prompt, context)
   ├─ MCP server catches exception
   ├─ Server calls state_manager.create_state(...)
   └─ Returns continuation_token to AI agent

2. STORAGE
   ├─ State stored in memory with unique token
   ├─ Expiration timestamp calculated (created_at + timeout)
   └─ State marked as resolved=False

3. RETRIEVAL
   ├─ AI agent calls confirm tool with token
   ├─ Server calls state_manager.get_state(token)
   ├─ Validation checks:
   │  ├─ Token exists in storage
   │  ├─ State not already resolved
   │  └─ State not expired (current_time < expires_at)
   └─ Returns CommandState or raises InvalidTokenError

4. RESOLUTION
   ├─ Server calls state_manager.resolve_state(token, response)
   ├─ State marked as resolved=True
   ├─ Response stored in state
   ├─ Command resumed with response
   ├─ State removed from storage
   └─ Result returned to AI agent

5. CLEANUP (Background)
   ├─ Periodic timer (every 60 seconds)
   ├─ state_manager.cleanup_expired() called
   ├─ Iterates through all states
   ├─ Removes states where current_time > expires_at
   └─ Logs cleanup statistics
```

---

## 2. Implementation Details

### 2.1 Token Generation

**Algorithm:**
```python
import secrets
import hashlib
from datetime import datetime

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
```

**Security considerations:**
- Uses `secrets` module for cryptographic randomness
- Tokens are unpredictable and cannot be forged
- Short enough to be manageable but long enough to prevent collisions
- Include timestamp hash to prevent replay attacks

### 2.2 Thread Safety

**Strategy: Lock-based synchronization**

```python
class CommandStateManager:
    def __init__(self):
        self._states: Dict[str, CommandState] = {}
        self._lock = threading.Lock()
    
    def create_state(self, ...) -> str:
        with self._lock:
            token = self._generate_token(...)
            state = CommandState(...)
            self._states[token] = state
            return token
    
    def get_state(self, token: str) -> Optional[CommandState]:
        with self._lock:
            state = self._states.get(token)
            if state and not self._is_expired(state):
                return state
            return None
    
    def resolve_state(self, token: str, response: str) -> CommandState:
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
            del self._states[token]
            return state
```

**Concurrent access handling:**
- All public methods acquire lock before accessing shared state
- Lock is released automatically via context manager
- Operations are atomic - either complete fully or not at all
- No race conditions between check and modify operations

**ExecutionMode thread safety:**
- Uses `threading.local()` for thread-local storage
- Each thread has its own execution mode
- Allows concurrent CLI and MCP operations
- No locks needed since storage is per-thread

### 2.3 Storage Mechanism

**Primary storage: In-memory dictionary**

```python
# In CommandStateManager
self._states: Dict[str, CommandState] = {}
```

**Rationale:**
- Fast access (O(1) lookups)
- No external dependencies
- States are transient by nature
- Automatic cleanup on server restart
- Sufficient for session-scoped persistence

**Alternative for production (optional future enhancement):**
- Redis for distributed deployments
- SQLite for persistent audit logs
- But in-memory is recommended for initial implementation

**Memory management:**
- States are small (< 1KB each)
- Automatic expiration prevents unbounded growth
- Background cleanup removes stale states
- Expected max concurrent states: ~100 (reasonable for single-user tool)

### 2.4 Timeout Handling

**Default timeout: 5 minutes (300 seconds)**

```python
class CommandStateManager:
    DEFAULT_TIMEOUT = 300  # seconds
    CLEANUP_INTERVAL = 60  # seconds
    
    def __init__(self, timeout_seconds: int = DEFAULT_TIMEOUT):
        self._timeout_seconds = timeout_seconds
        self._cleanup_timer = None
        self._start_cleanup_timer()
    
    def _start_cleanup_timer(self):
        """Starts background thread for periodic cleanup"""
        def cleanup_loop():
            while True:
                time.sleep(self.CLEANUP_INTERVAL)
                try:
                    removed = self.cleanup_expired()
                    if removed > 0:
                        logger.debug(f"Cleaned up {removed} expired states")
                except Exception as e:
                    logger.error(f"Cleanup error: {e}")
        
        self._cleanup_timer = threading.Thread(
            target=cleanup_loop, 
            daemon=True,
            name="StateCleanup"
        )
        self._cleanup_timer.start()
    
    def _is_expired(self, state: CommandState) -> bool:
        """Checks if a state has expired"""
        return time.time() > state.expires_at
    
    def cleanup_expired(self) -> int:
        """Removes expired states and returns count"""
        with self._lock:
            expired_tokens = [
                token for token, state in self._states.items()
                if self._is_expired(state)
            ]
            for token in expired_tokens:
                del self._states[token]
            return len(expired_tokens)
```

**Expiration flow:**
1. When state created, `expires_at = created_at + timeout_seconds`
2. Every operation checks expiration before processing
3. Background thread runs every 60 seconds to cleanup
4. Expired states return "token expired" error to client

**Configurable timeout:**
- Can be adjusted via constructor parameter
- Allows different timeouts for different deployments
- Testing can use shorter timeouts (e.g., 10 seconds)

### 2.5 Error Handling

**Custom exception hierarchy:**

```python
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
```

**Error handling patterns:**

```python
# In MCP server tool handlers
def execute_command_tool(name: str, arguments: dict) -> dict:
    try:
        with ExecutionMode.mcp_mode():
            result = execute_command(name, arguments)
            return {
                "status": "success",
                "data": result
            }
    except ConfirmationRequest as e:
        token = state_manager.create_state(
            command_name=name,
            command_args=arguments,
            prompt_message=e.prompt_message,
            context=e.context
        )
        return {
            "status": "confirmation_required",
            "prompt": e.prompt_message,
            "continuation_token": token,
            "command": name,
            "expires_at": time.time() + state_manager._timeout_seconds
        }
    except InvalidTokenError as e:
        return {
            "status": "error",
            "error_type": "InvalidTokenError",
            "message": str(e)
        }
    except CommandExecutionError as e:
        return {
            "status": "error",
            "error_type": "CommandExecutionError",
            "message": str(e),
            "details": getattr(e, 'details', None)
        }
    except Exception as e:
        logger.exception("Unexpected error in command execution")
        return {
            "status": "error",
            "error_type": type(e).__name__,
            "message": str(e)
        }

def confirm_continuation_tool(token: str, response: str) -> dict:
    try:
        state = state_manager.resolve_state(token, response)
        # Resume command with the response
        result = resume_command(state, response)
        return {
            "status": "success",
            "data": result
        }
    except InvalidTokenError as e:
        return {
            "status": "error",
            "error_type": "InvalidTokenError",
            "message": str(e)
        }
```

**Validation:**
- Token format validation before lookup
- Response validation (e.g., must be "y" or "n" for yes/no prompts)
- Command argument validation before execution
- Context validation when resuming commands

---

## 3. MCP Server Integration

### 3.1 New Tool Endpoints

**Tool 1: confirm_continuation**

```python
{
    "name": "confirm_continuation",
    "description": "Responds to a confirmation prompt from a previous command. Use this when a command returns status='confirmation_required'.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "continuation_token": {
                "type": "string",
                "description": "The continuation token received from the command requiring confirmation"
            },
            "response": {
                "type": "string",
                "description": "Your response to the confirmation prompt (typically 'y' for yes or 'n' for no)",
                "enum": ["y", "n", "yes", "no"]
            }
        },
        "required": ["continuation_token", "response"]
    }
}
```

**Existing tools modified:**
All existing command tools (compose_email, delete_template, etc.) will now potentially return confirmation_required status instead of immediately executing. No schema changes needed, but documentation should note the two-step flow.

### 3.2 Response Formats

**Standard Success Response:**
```json
{
    "status": "success",
    "data": {
        "message": "Template deleted successfully",
        "template_name": "welcome"
    }
}
```

**Confirmation Required Response:**
```json
{
    "status": "confirmation_required",
    "prompt": "Delete template 'welcome'? (y/n):",
    "continuation_token": "cmd_7a3f_k9x2m4p8_9b2e",
    "command": "delete_template",
    "expires_at": 1699123756.789
}
```

**Error Response:**
```json
{
    "status": "error",
    "error_type": "InvalidTokenError",
    "message": "Token expired: cmd_7a3f_k9x2m4p8_9b2e"
}
```

**Schema validation:**
- All responses include "status" field
- Status values: "success", "confirmation_required", "error"
- Additional fields depend on status
- AI agents can reliably check status to determine next action

### 3.3 Session Management

**MCP Server Session Lifecycle:**

```python
class MailshMCPServer:
    def __init__(self):
        self.state_manager = CommandStateManager()
        self.mailsh_instance = None  # Lazy initialization
        self._session_lock = threading.Lock()
    
    def _get_mailsh_instance(self):
        """
        Returns the singleton Mailsh instance for this server session.
        Creates it on first access.
        """
        if self.mailsh_instance is None:
            with self._session_lock:
                if self.mailsh_instance is None:
                    self.mailsh_instance = Mailsh()  # Or however it's initialized
        return self.mailsh_instance
    
    async def handle_tool_call(self, tool_name: str, arguments: dict):
        """Routes tool calls to appropriate handlers"""
        mailsh = self._get_mailsh_instance()
        
        if tool_name == "confirm_continuation":
            return await self._handle_confirmation(arguments)
        else:
            return await self._handle_command(mailsh, tool_name, arguments)
```

**Integration with existing session:**
- Single Mailsh instance per MCP server process
- Maintains all existing session state (current draft, connection, etc.)
- State persists across multiple tool calls
- CommandStateManager is separate - only tracks pending confirmations
- When server shuts down, both Mailsh state and pending confirmations are lost (acceptable per requirements)

**Concurrency model:**
- Single Mailsh instance shared across all tool calls
- ExecutionMode in thread-local storage allows concurrent calls
- State manager lock protects confirmation state
- Mailsh internal state should be thread-safe or protected as needed

---

## 4. Preservation of Existing Behavior

### 4.1 CLI Mode Preservation

**No changes to human user experience:**

```python
# In command handler (e.g., templates.py)
def delete_template(name: str, mailsh_instance):
    """Delete a template"""
    template_path = get_template_path(name)
    
    if not template_path.exists():
        print(f"Template '{name}' not found")
        return
    
    # THE KEY MODIFICATION: Check execution mode
    if ExecutionMode.is_mcp_mode():
        # MCP mode: Raise exception to interrupt and request confirmation
        raise ConfirmationRequest(
            prompt_message=f"Delete template '{name}'? (y/n):",
            context={"template_path": str(template_path), "name": name}
        )
    else:
        # CLI mode: Use existing blocking input (unchanged behavior)
        response = input(f"Delete template '{name}'? (y/n): ").strip().lower()
        if response not in ['y', 'yes']:
            print("Deletion cancelled")
            return
    
    # Continue with deletion (both modes reach here eventually)
    template_path.unlink()
    print(f"Template '{name}' deleted successfully")
```

**Key principle:**
- ExecutionMode defaults to 'cli'
- CLI users never trigger MCP-specific code paths
- All existing behavior preserved exactly
- Only MCP server sets ExecutionMode to 'mcp'

### 4.2 Backward Compatibility

**Compatibility checklist:**

1. **Existing CLI functionality:** ✓ Unchanged
   - All commands work identically for human users
   - No new required arguments
   - No removed features

2. **Direct Mailsh API usage:** ✓ Compatible
   - Core modules (core/, features/) unchanged
   - Direct API calls continue to work
   - No breaking changes to public interfaces

3. **Third-party integrations:** ✓ Safe
   - MCP server is additive, not replacing anything
   - Existing scripts/integrations unaffected
   - New functionality is opt-in

4. **Configuration files:** ✓ No migration needed
   - Existing config format unchanged
   - No new required config values
   - MCP settings are optional additions

**Testing backward compatibility:**
- Run existing test suite without modifications
- All tests should pass without changes
- Manual testing of CLI commands
- Verify no performance degradation

### 4.3 Configuration Options

**New configuration file: `mailsh_app/mcp/config.py`**

```python
@dataclass
class MCPConfig:
    """Configuration for MCP server behavior"""
    
    # Enable/disable MCP server
    enabled: bool = False
    
    # Server binding
    host: str = "localhost"
    port: int = 3000
    
    # State management
    confirmation_timeout_seconds: int = 300
    cleanup_interval_seconds: int = 60
    max_pending_states: int = 100
    
    # Logging
    log_level: str = "INFO"
    log_file: Optional[str] = None
    
    @classmethod
    def from_file(cls, config_path: Path) -> 'MCPConfig':
        """Load configuration from YAML/JSON file"""
        # Implementation for loading from file
        pass
    
    @classmethod
    def from_env(cls) -> 'MCPConfig':
        """Load configuration from environment variables"""
        return cls(
            enabled=os.getenv('MAILSH_MCP_ENABLED', 'false').lower() == 'true',
            host=os.getenv('MAILSH_MCP_HOST', 'localhost'),
            port=int(os.getenv('MAILSH_MCP_PORT', '3000')),
            confirmation_timeout_seconds=int(os.getenv('MAILSH_MCP_TIMEOUT', '300')),
            # ... other env vars
        )
```

**Environment variables:**
```bash
# Enable MCP server
export MAILSH_MCP_ENABLED=true

# Server configuration
export MAILSH_MCP_HOST=localhost
export MAILSH_MCP_PORT=3000

# State management
export MAILSH_MCP_TIMEOUT=300
export MAILSH_MCP_CLEANUP_INTERVAL=60
export MAILSH_MCP_MAX_STATES=100

# Logging
export MAILSH_MCP_LOG_LEVEL=INFO
export MAILSH_MCP_LOG_FILE=/var/log/mailsh-mcp.log
```

**Runtime control:**
```python
# In main entry point
def main():
    config = MCPConfig.from_env()
    
    if config.enabled:
        # Start MCP server
        mcp_server = MailshMCPServer(config)
        mcp_server.start()
    else:
        # Normal CLI mode only
        start_cli()
```

---

## 5. Testing Strategy

### 5.1 Unit Tests

**Test file: `tests/test_state_manager.py`**

```python
class TestCommandStateManager:
    def test_create_state_generates_unique_token(self):
        """Verify token generation is unique"""
        manager = CommandStateManager()
        token1 = manager.create_state("cmd1", {}, "Confirm?", None)
        token2 = manager.create_state("cmd1", {}, "Confirm?", None)
        assert token1 != token2
    
    def test_get_state_returns_valid_state(self):
        """Verify state retrieval works"""
        manager = CommandStateManager()
        token = manager.create_state("cmd1", {"arg": "value"}, "Confirm?", {"key": "data"})
        state = manager.get_state(token)
        assert state is not None
        assert state.command_name == "cmd1"
        assert state.command_args == {"arg": "value"}
    
    def test_get_state_returns_none_for_invalid_token(self):
        """Verify invalid tokens return None"""
        manager = CommandStateManager()
        state = manager.get_state("invalid_token")
        assert state is None
    
    def test_resolve_state_marks_resolved(self):
        """Verify state resolution"""
        manager = CommandStateManager()
        token = manager.create_state("cmd1", {}, "Confirm?", None)
        state = manager.resolve_state(token, "y")
        assert state.resolved == True
        assert state.response == "y"
        # Verify state is removed after resolution
        assert manager.get_state(token) is None
    
    def test_resolve_invalid_token_raises_error(self):
        """Verify error on invalid token resolution"""
        manager = CommandStateManager()
        with pytest.raises(InvalidTokenError):
            manager.resolve_state("invalid_token", "y")
    
    def test_expired_state_returns_none(self):
        """Verify expired states are not retrievable"""
        manager = CommandStateManager(timeout_seconds=1)
        token = manager.create_state("cmd1", {}, "Confirm?", None)
        time.sleep(2)  # Wait for expiration
        state = manager.get_state(token)
        assert state is None
    
    def test_cleanup_expired_removes_old_states(self):
        """Verify cleanup removes expired states"""
        manager = CommandStateManager(timeout_seconds=1)
        token1 = manager.create_state("cmd1", {}, "Confirm?", None)
        time.sleep(2)
        token2 = manager.create_state("cmd2", {}, "Confirm?", None)
        
        removed = manager.cleanup_expired()
        assert removed == 1
        assert manager.get_state(token1) is None
        assert manager.get_state(token2) is not None
    
    def test_thread_safety(self):
        """Verify thread-safe operations"""
        manager = CommandStateManager()
        tokens = []
        
        def create_states():
            for i in range(100):
                token = manager.create_state(f"cmd{i}", {}, "Confirm?", None)
                tokens.append(token)
        
        threads = [threading.Thread(target=create_states) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # Verify all tokens are unique
        assert len(tokens) == len(set(tokens))
```

**Test file: `tests/test_execution_mode.py`**

```python
class TestExecutionMode:
    def test_default_mode_is_cli(self):
        """Verify default execution mode"""
        assert ExecutionMode.get_mode() == "cli"
        assert not ExecutionMode.is_mcp_mode()
    
    def test_set_mode_changes_mode(self):
        """Verify mode setting"""
        ExecutionMode.set_mode("mcp")
        assert ExecutionMode.get_mode() == "mcp"
        assert ExecutionMode.is_mcp_mode()
        ExecutionMode.set_mode("cli")  # Reset
    
    def test_mcp_mode_context_manager(self):
        """Verify context manager sets and resets mode"""
        assert ExecutionMode.get_mode() == "cli"
        with ExecutionMode.mcp_mode():
            assert ExecutionMode.is_mcp_mode()
        assert ExecutionMode.get_mode() == "cli"
    
    def test_thread_local_isolation(self):
        """Verify each thread has independent mode"""
        results = []
        
        def thread_func(mode):
            ExecutionMode.set_mode(mode)
            time.sleep(0.1)
            results.append(ExecutionMode.get_mode())
        
        t1 = threading.Thread(target=thread_func, args=("mcp",))
        t2 = threading.Thread(target=thread_func, args=("cli",))
        
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        
        # Both threads should report their own mode
        assert "mcp" in results
        assert "cli" in results
```

**Test file: `tests/test_confirmation_request.py`**

```python
class TestConfirmationRequest:
    def test_exception_carries_message_and_context(self):
        """Verify ConfirmationRequest exception structure"""
        context = {"key": "value"}
        exc = ConfirmationRequest("Confirm action?", context)
        assert exc.prompt_message == "Confirm action?"
        assert exc.context == context
```

### 5.2 Integration Tests

**Test file: `tests/integration/test_mcp_command_flow.py`**

```python
class TestMCPCommandFlow:
    def test_delete_template_confirmation_flow(self):
        """Test complete delete template flow with confirmation"""
        # Setup
        server = MailshMCPServer()
        create_test_template("test_template", "content")
        
        # Step 1: Initial delete command
        response1 = server.handle_tool_call("delete_template", {"name": "test_template"})
        assert response1["status"] == "confirmation_required"
        assert "continuation_token" in response1
        assert "Delete template 'test_template'?" in response1["prompt"]
        
        token = response1["continuation_token"]
        
        # Step 2: Confirm deletion
        response2 = server.handle_tool_call("confirm_continuation", {
            "continuation_token": token,
            "response": "y"
        })
        assert response2["status"] == "success"
        assert not template_exists("test_template")
    
    def test_delete_template_cancellation_flow(self):
        """Test cancelling a delete template operation"""
        server = MailshMCPServer()
        create_test_template("test_template", "content")
        
        # Step 1: Initial delete command
        response1 = server.handle_tool_call("delete_template", {"name": "test_template"})
        token = response1["continuation_token"]
        
        # Step 2: Cancel deletion
        response2 = server.handle_tool_call("confirm_continuation", {
            "continuation_token": token,
            "response": "n"
        })
        assert response2["status"] == "success"
        assert template_exists("test_template")  # Template should still exist
    
    def test_expired_token_error(self):
        """Test that expired tokens return error"""
        server = MailshMCPServer(timeout_seconds=1)
        create_test_template("test_template", "content")
        
        # Get token
        response1 = server.handle_tool_call("delete_template", {"name": "test_template"})
        token = response1["continuation_token"]
        
        # Wait for expiration
        time.sleep(2)
        
        # Try to use expired token
        response2 = server.handle_tool_call("confirm_continuation", {
            "continuation_token": token,
            "response": "y"
        })
        assert response2["status"] == "error"
        assert response2["error_type"] == "InvalidTokenError"
        assert "expired" in response2["message"].lower()
    
    def test_multiple_concurrent_confirmations(self):
        """Test handling multiple pending confirmations"""
        server = MailshMCPServer()
        create_test_template("template1", "content1")
        create_test_template("template2", "content2")
        create_test_template("template3", "content3")
        
        # Create multiple pending confirmations
        response1 = server.handle_tool_call("delete_template", {"name": "template1"})
        response2 = server.handle_tool_call("delete_template", {"name": "template2"})
        response3 = server.handle_tool_call("delete_template", {"name": "template3"})
        
        token1 = response1["continuation_token"]
        token2 = response2["continuation_token"]
        token3 = response3["continuation_token"]
        
        # Resolve in different order
        server.handle_tool_call("confirm_continuation", {"continuation_token": token2, "response": "y"})
        server.handle_tool_call("confirm_continuation", {"continuation_token": token1, "response": "n"})
        server.handle_tool_call("confirm_continuation", {"continuation_token": token3, "response": "y"})
        
        # Verify correct templates were deleted
        assert template_exists("template1")  # Cancelled
        assert not template_exists("template2")  # Confirmed
        assert not template_exists("template3")  # Confirmed
    
    def test_compose_email_with_send_confirmation(self):
        """Test email composition and send confirmation flow"""
        server = MailshMCPServer()
        
        # Compose email
        compose_response = server.handle_tool_call("compose_email", {
            "to": "test@example.com",
            "subject": "Test Email",
            "body": "This is a test"
        })
        assert compose_response["status"] == "success"
        
        # Send email (triggers confirmation)
        send_response = server.handle_tool_call("send_email", {})
        assert send_response["status"] == "confirmation_required"
        assert "Send email?" in send_response["prompt"]
        
        token = send_response["continuation_token"]
        
        # Confirm send
        confirm_response = server.handle_tool_call("confirm_continuation", {
            "continuation_token": token,
            "response": "y"
        })
        assert confirm_response["status"] == "success"
    
    def test_invalid_token_error(self):
        """Test using completely invalid token"""
        server = MailshMCPServer()
        
        response = server.handle_tool_call("confirm_continuation", {
            "continuation_token": "completely_invalid_token_12345",
            "response": "y"
        })
        assert response["status"] == "error"
        assert response["error_type"] == "InvalidTokenError"
    
    def test_reusing_resolved_token_fails(self):
        """Test that tokens cannot be reused after resolution"""
        server = MailshMCPServer()
        create_test_template("test_template", "content")
        
        # Get and resolve token
        response1 = server.handle_tool_call("delete_template", {"name": "test_template"})
        token = response1["continuation_token"]
        response2 = server.handle_tool_call("confirm_continuation", {
            "continuation_token": token,
            "response": "y"
        })
        assert response2["status"] == "success"
        
        # Try to reuse the same token
        response3 = server.handle_tool_call("confirm_continuation", {
            "continuation_token": token,
            "response": "y"
        })
        assert response3["status"] == "error"
        assert response3["error_type"] == "InvalidTokenError"
```

### 5.3 Edge Cases

**Test file: `tests/test_edge_cases.py`**

```python
class TestEdgeCases:
    def test_server_restart_clears_pending_states(self):
        """Verify pending states don't persist across server restart"""
        server1 = MailshMCPServer()
        create_test_template("test_template", "content")
        
        # Create pending confirmation
        response = server1.handle_tool_call("delete_template", {"name": "test_template"})
        token = response["continuation_token"]
        
        # Simulate server restart
        server1.shutdown()
        server2 = MailshMCPServer()
        
        # Token should be invalid
        response = server2.handle_tool_call("confirm_continuation", {
            "continuation_token": token,
            "response": "y"
        })
        assert response["status"] == "error"
    
    def test_max_pending_states_limit(self):
        """Test behavior when max pending states is reached"""
        server = MailshMCPServer(max_pending_states=5)
        
        # Create max number of pending states
        tokens = []
        for i in range(5):
            create_test_template(f"template{i}", "content")
            response = server.handle_tool_call("delete_template", {"name": f"template{i}"})
            tokens.append(response["continuation_token"])
        
        # Try to create one more
        create_test_template("template6", "content")
        response = server.handle_tool_call("delete_template", {"name": "template6"})
        
        # Should either error or remove oldest state
        # Implementation choice - document behavior
        assert response["status"] in ["error", "confirmation_required"]
    
    def test_special_characters_in_prompt(self):
        """Test handling of special characters in prompts"""
        server = MailshMCPServer()
        # Create template with special chars in name
        special_name = "template's \"test\" <name>"
        create_test_template(special_name, "content")
        
        response = server.handle_tool_call("delete_template", {"name": special_name})
        assert response["status"] == "confirmation_required"
        assert special_name in response["prompt"]
        
        # Verify token works
        token = response["continuation_token"]
        confirm_response = server.handle_tool_call("confirm_continuation", {
            "continuation_token": token,
            "response": "y"
        })
        assert confirm_response["status"] == "success"
    
    def test_empty_context_handling(self):
        """Test commands that don't need context data"""
        manager = CommandStateManager()
        token = manager.create_state("simple_command", {}, "Confirm?", context=None)
        state = manager.get_state(token)
        assert state.context is None
        
        # Should still work fine
        resolved = manager.resolve_state(token, "y")
        assert resolved.response == "y"
    
    def test_large_context_data(self):
        """Test handling of large context objects"""
        manager = CommandStateManager()
        large_context = {
            "data": "x" * 10000,  # 10KB of data
            "nested": {"more": "data" * 1000}
        }
        token = manager.create_state("cmd", {}, "Confirm?", large_context)
        state = manager.get_state(token)
        assert state.context == large_context
    
    def test_rapid_create_and_resolve(self):
        """Test rapid creation and resolution of states"""
        server = MailshMCPServer()
        
        for i in range(50):
            create_test_template(f"template{i}", "content")
            response1 = server.handle_tool_call("delete_template", {"name": f"template{i}"})
            token = response1["continuation_token"]
            response2 = server.handle_tool_call("confirm_continuation", {
                "continuation_token": token,
                "response": "y"
            })
            assert response2["status"] == "success"
    
    def test_unicode_in_prompts_and_responses(self):
        """Test Unicode handling"""
        server = MailshMCPServer()
        unicode_name = "template_émojis_🎉_中文"
        create_test_template(unicode_name, "content")
        
        response = server.handle_tool_call("delete_template", {"name": unicode_name})
        assert response["status"] == "confirmation_required"
        assert unicode_name in response["prompt"]
```

---

## 6. Migration Plan

### 6.1 Phase 1: Core Infrastructure (No Breaking Changes)

**Step 1: Create new modules**

Create `mailsh_app/core/state_manager.py`:
- Implement `CommandStateManager` class
- Implement `CommandState` dataclass
- Implement `ConfirmationRequest` exception
- Implement `ExecutionMode` class with thread-local storage
- Add all error classes (InvalidTokenError, etc.)
- Add comprehensive docstrings

Create `mailsh_app/mcp/__init__.py`:
- Empty or basic package initialization

Create `mailsh_app/mcp/config.py`:
- Implement `MCPConfig` dataclass
- Add environment variable parsing
- Add file-based config loading

**Step 2: Add tests for core infrastructure**

Create test files:
- `tests/test_state_manager.py`
- `tests/test_execution_mode.py`
- `tests/test_confirmation_request.py`

Run tests to verify core functionality works in isolation.

**Step 3: Verify no impact on existing functionality**

- Run existing test suite
- All tests should pass
- New modules are not imported anywhere yet
- Zero impact on CLI users

### 6.2 Phase 2: Command Handler Modifications

**Step 4: Identify all commands with confirmations**

Search codebase for `input(` calls in command handlers:
```bash
grep -r "input(" mailsh_app/cli/commands/
```

Create a list of all commands that need modification:
- `delete_template` in `templates.py`
- `delete_contact` in `contacts.py`
- `delete_task` in `tasks.py`
- `discard_draft` in `composition.py`
- Any others found

**Step 5: Modify command handlers one at a time**

For each command identified above, apply this pattern:

**Before:**
```python
def delete_template(name: str):
    if not template_exists(name):
        print(f"Template '{name}' not found")
        return
    
    response = input(f"Delete template '{name}'? (y/n): ").strip().lower()
    if response not in ['y', 'yes']:
        print("Deletion cancelled")
        return
    
    perform_deletion(name)
    print("Template deleted")
```

**After:**
```python
from mailsh_app.core.state_manager import ExecutionMode, ConfirmationRequest

def delete_template(name: str):
    if not template_exists(name):
        print(f"Template '{name}' not found")
        return
    
    # Check execution mode
    if ExecutionMode.is_mcp_mode():
        # MCP mode: raise exception with context
        raise ConfirmationRequest(
            prompt_message=f"Delete template '{name}'? (y/n):",
            context={"name": name, "template_path": get_template_path(name)}
        )
    else:
        # CLI mode: existing behavior unchanged
        response = input(f"Delete template '{name}'? (y/n): ").strip().lower()
        if response not in ['y', 'yes']:
            print("Deletion cancelled")
            return
    
    # Both modes reach here (MCP mode after confirmation resolved)
    perform_deletion(name)
    print("Template deleted")
```

**Step 6: Add integration tests for modified commands**

For each modified command, add test in `tests/integration/test_mcp_command_flow.py`:
- Test confirmation required response
- Test confirmation acceptance
- Test confirmation rejection
- Test expired token handling

**Step 7: Verify CLI behavior unchanged**

After each command modification:
- Manually test the command in CLI mode
- Verify prompt appears correctly
- Verify y/n responses work
- Verify cancellation works
- Run existing test suite

### 6.3 Phase 3: MCP Server Implementation

**Step 8: Create command resumption logic**

In `mailsh_app/mcp/command_executor.py` (new file):

```python
from mailsh_app.core.state_manager import CommandState

def resume_command(state: CommandState, response: str):
    """
    Resumes a command after confirmation response.
    
    This function recreates the command execution context and continues
    from where the ConfirmationRequest was raised.
    """
    command_name = state.command_name
    command_args = state.command_args
    context = state.context
    
    # Map response to standardized form
    confirmed = response.lower() in ['y', 'yes']
    
    # Route to appropriate command handler
    if command_name == "delete_template":
        return resume_delete_template(confirmed, context)
    elif command_name == "delete_contact":
        return resume_delete_contact(confirmed, context)
    elif command_name == "delete_task":
        return resume_delete_task(confirmed, context)
    # ... other commands
    else:
        raise ValueError(f"Unknown command: {command_name}")

def resume_delete_template(confirmed: bool, context: dict):
    """Resume delete_template after confirmation"""
    if not confirmed:
        return {"message": "Deletion cancelled", "cancelled": True}
    
    name = context["name"]
    template_path = context["template_path"]
    
    # Perform the deletion
    Path(template_path).unlink()
    return {"message": f"Template '{name}' deleted successfully", "deleted": True}

# Similar resume functions for other commands...
```

**Step 9: Implement MCP server**

Create `mailsh_app/mcp/server.py`:

```python
import asyncio
from typing import Any, Dict
from mailsh_app.core.state_manager import (
    CommandStateManager, 
    ExecutionMode, 
    ConfirmationRequest,
    InvalidTokenError
)
from mailsh_app.mcp.command_executor import resume_command
from mailsh_app import Mailsh

class MailshMCPServer:
    def __init__(self, config=None):
        self.config = config or MCPConfig.from_env()
        self.state_manager = CommandStateManager(
            timeout_seconds=self.config.confirmation_timeout_seconds
        )
        self.mailsh_instance = None
    
    def _get_mailsh_instance(self):
        """Lazy initialization of Mailsh instance"""
        if self.mailsh_instance is None:
            self.mailsh_instance = Mailsh()
        return self.mailsh_instance
    
    async def handle_tool_call(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Main entry point for tool calls"""
        if tool_name == "confirm_continuation":
            return await self._handle_confirmation(arguments)
        else:
            return await self._handle_command(tool_name, arguments)
    
    async def _handle_command(self, command_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a command in MCP mode"""
        mailsh = self._get_mailsh_instance()
        
        try:
            # Execute in MCP mode context
            with ExecutionMode.mcp_mode():
                # Route to appropriate command handler
                result = await self._execute_command(mailsh, command_name, arguments)
                return {
                    "status": "success",
                    "data": result
                }
        
        except ConfirmationRequest as e:
            # Command needs confirmation
            token = self.state_manager.create_state(
                command_name=command_name,
                command_args=arguments,
                prompt_message=e.prompt_message,
                context=e.context
            )
            return {
                "status": "confirmation_required",
                "prompt": e.prompt_message,
                "continuation_token": token,
                "command": command_name,
                "expires_at": time.time() + self.state_manager._timeout_seconds
            }
        
        except Exception as e:
            logger.exception(f"Error executing command {command_name}")
            return {
                "status": "error",
                "error_type": type(e).__name__,
                "message": str(e)
            }
    
    async def _handle_confirmation(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handle confirmation response"""
        token = arguments["continuation_token"]
        response = arguments["response"]
        
        try:
            # Resolve the state
            state = self.state_manager.resolve_state(token, response)
            
            # Resume the command
            result = resume_command(state, response)
            
            return {
                "status": "success",
                "data": result
            }
        
        except InvalidTokenError as e:
            return {
                "status": "error",
                "error_type": "InvalidTokenError",
                "message": str(e)
            }
        except Exception as e:
            logger.exception("Error handling confirmation")
            return {
                "status": "error",
                "error_type": type(e).__name__,
                "message": str(e)
            }
    
    async def _execute_command(self, mailsh, command_name: str, arguments: Dict[str, Any]):
        """Route command to appropriate handler"""
        # This is a simplified routing - actual implementation needs
        # to map MCP tool names to Mailsh command handlers
        
        if command_name == "delete_template":
            from mailsh_app.cli.commands.templates import delete_template
            return delete_template(**arguments)
        elif command_name == "compose_email":
            from mailsh_app.cli.commands.composition import compose_email
            return compose_email(**arguments)
        # ... other commands
        else:
            raise ValueError(f"Unknown command: {command_name}")
    
    def shutdown(self):
        """Cleanup on server shutdown"""
        self.state_manager.clear_all()
        if self.mailsh_instance:
            # Perform any necessary cleanup
            pass
```

**Step 10: Define MCP tool schemas**

Create `mailsh_app/mcp/tools.py`:

```python
TOOL_DEFINITIONS = {
    "confirm_continuation": {
        "name": "confirm_continuation",
        "description": "Responds to a confirmation prompt from a previous command",
        "inputSchema": {
            "type": "object",
            "properties": {
                "continuation_token": {
                    "type": "string",
                    "description": "The continuation token from the confirmation request"
                },
                "response": {
                    "type": "string",
                    "description": "Your response: 'y' or 'n'",
                    "enum": ["y", "n", "yes", "no"]
                }
            },
            "required": ["continuation_token", "response"]
        }
    },
    # ... existing tool definitions with updated descriptions noting
    # that they may return confirmation_required status
}
```

**Step 11: Add integration tests**

Create comprehensive integration tests in `tests/integration/`:
- Test all modified commands end-to-end
- Test concurrent operations
- Test error conditions
- Test session state persistence

### 6.4 Phase 4: Documentation and Deployment

**Step 12: Update documentation**

Create `docs/MCP_INTEGRATION.md`:
- How the MCP server works
- How to enable/configure it
- Example AI agent interaction flows
- Troubleshooting guide

Update `README.md`:
- Add section on MCP server
- Link to detailed documentation
- Add configuration examples

**Step 13: Add logging and monitoring**

Add comprehensive logging throughout:
- State creation/resolution
- Command execution
- Errors and exceptions
- Performance metrics

**Step 14: Production readiness**

- Add health check endpoint
- Add metrics endpoint (pending states count, etc.)
- Add graceful shutdown handling
- Add rate limiting if needed
- Security review of token generation

**Step 15: Deployment**

- Deploy to staging environment
- Run integration tests against staging
- Monitor for issues
- Deploy to production
- Monitor metrics and logs

---

## 7. Implementation Checklist

Use this checklist to track progress:

### Phase 1: Core Infrastructure
- [ ] Create `mailsh_app/core/state_manager.py`
- [ ] Implement `CommandStateManager` class
- [ ] Implement `CommandState` dataclass
- [ ] Implement `ConfirmationRequest` exception
- [ ] Implement `ExecutionMode` class
- [ ] Implement custom error classes
- [ ] Create `mailsh_app/mcp/__init__.py`
- [ ] Create `mailsh_app/mcp/config.py`
- [ ] Implement `MCPConfig` class
- [ ] Create `tests/test_state_manager.py`
- [ ] Create `tests/test_execution_mode.py`
- [ ] Run tests - all passing
- [ ] Run existing test suite - all passing

### Phase 2: Command Handler Modifications
- [ ] Identify all commands with confirmations
- [ ] Modify `delete_template` in `templates.py`
- [ ] Test `delete_template` in CLI mode
- [ ] Add integration test for `delete_template`
- [ ] Modify `delete_contact` in `contacts.py`
- [ ] Test `delete_contact` in CLI mode
- [ ] Add integration test for `delete_contact`
- [ ] Modify `delete_task` in `tasks.py`
- [ ] Test `delete_task` in CLI mode
- [ ] Add integration test for `delete_task`
- [ ] Modify `discard_draft` in `composition.py`
- [ ] Test `discard_draft` in CLI mode
- [ ] Add integration test for `discard_draft`
- [ ] Modify any other commands with confirmations
- [ ] Run all tests - all passing
- [ ] Manual CLI testing - all commands work unchanged

### Phase 3: MCP Server Implementation
- [ ] Create `mailsh_app/mcp/command_executor.py`
- [ ] Implement `resume_command` function
- [ ] Implement resume functions for each command
- [ ] Create `mailsh_app/mcp/server.py`
- [ ] Implement `MailshMCPServer` class
- [ ] Implement `_handle_command` method
- [ ] Implement `_handle_confirmation` method
- [ ] Implement `_execute_command` routing
- [ ] Create `mailsh_app/mcp/tools.py`
- [ ] Define all tool schemas
- [ ] Create `tests/integration/test_mcp_command_flow.py`
- [ ] Add end-to-end integration tests
- [ ] Create `tests/test_edge_cases.py`
- [ ] Run all tests - all passing

### Phase 4: Documentation and Deployment
- [ ] Create `docs/MCP_INTEGRATION.md`
- [ ] Update `README.md`
- [ ] Add logging throughout
- [ ] Add health check endpoint
- [ ] Add metrics endpoint
- [ ] Implement graceful shutdown
- [ ] Security review
- [ ] Deploy to staging
- [ ] Run integration tests on staging
- [ ] Deploy to production
- [ ] Monitor metrics and logs

---

## 8. Key Design Decisions Summary

1. **In-memory state storage**: Simple, fast, sufficient for session-scoped persistence
2. **Thread-local ExecutionMode**: Enables concurrent CLI and MCP operations
3. **Exception-based flow control**: Clean way to interrupt command execution
4. **Continuation tokens**: Secure, unpredictable, time-limited
5. **Dual-mode operation**: Commands work identically in CLI, differently in MCP
6. **Explicit confirmation tool**: Separate tool for responding to confirmations
7. **Command resumption pattern**: Commands resume from interruption point
8. **No CLI changes**: Human users see zero difference

## 9. Success Criteria

The implementation will be considered successful when:

1. ✅ All existing CLI functionality works identically to before
2. ✅ All existing tests pass without modification
3. ✅ AI agents can execute all commands via MCP server
4. ✅ AI agents receive and respond to all confirmation prompts
5. ✅ Session state persists across multiple tool calls
6. ✅ Async event loop never blocks on confirmations
7. ✅ Expired tokens are handled gracefully
8. ✅ Concurrent operations don't interfere with each other
9. ✅ Error handling is comprehensive and informative
10. ✅ Documentation is complete and accurate

## 10. Potential Challenges and Solutions

### Challenge 1: Command handlers tightly coupled with CLI

**Solution**: The ExecutionMode abstraction allows commands to detect their context and behave appropriately without requiring major refactoring.

### Challenge 2: Resume logic duplication

**Solution**: Extract common deletion/confirmation logic into reusable functions that both CLI and MCP modes can call.

### Challenge 3: State synchronization complexity

**Solution**: Single Mailsh instance with thread-safe state manager keeps synchronization simple.

### Challenge 4: Testing asynchronous flows

**Solution**: Use pytest-asyncio and create comprehensive integration tests that simulate full AI agent interactions.

### Challenge 5: Token security

**Solution**: Cryptographically secure random generation, short expiration times, single-use tokens.

---

## End of Implementation Plan

This plan provides comprehensive guidance for implementing the MCP server with continuation token-based confirmation handling. Follow the phases in order, run tests frequently, and maintain backward compatibility throughout.
