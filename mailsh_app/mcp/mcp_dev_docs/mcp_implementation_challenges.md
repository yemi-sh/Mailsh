# MCP Server Requirements and Architecture Document

## Objective

We need to create an MCP (Model Context Protocol) server for Mailsh that provides AI agents with access to email functionality while maintaining persistent session state and preserving existing confirmation prompts.

## What We Want to Achieve

1. **Persistent Session State**: Maintain state between multiple tool calls (current email draft, connection status, etc.) so that commands can build upon each other's context.

2. **Structured Output**: Return properly structured, API-level return values rather than parsing text output from CLI operations.

3. **Preserve Confirmation Prompts**: Maintain existing confirmation prompts (like "Delete template 'name'? (y/n):") without bypassing or modifying them.

4. **Async Compatibility**: Ensure the MCP server doesn't block when handling interactive commands with confirmation prompts.

5. **Full Command Access**: Support all Mailsh commands including interactive ones that require user input.

## What We Want to Avoid

1. **Text Output Parsing**: Avoid capturing and parsing text output from CLI operations; prefer direct API return values.

2. **Confirmation Bypass**: Do not add flags like `--force` to bypass existing confirmation prompts.

3. **Major Application Refactoring**: Avoid requiring significant changes to the core Mailsh application architecture.

4. **Sync-blocking Operations**: Avoid blocking the MCP async event loop during interactive operations.

## Explored Approaches

### 1. Direct Object Reference (Current State)
- **Implementation**: Single Mailsh instance shared across all tool calls
- **Pros**: Direct API access, structured output, maintains state between calls
- **Cons**: Blocks async event loop on confirmation prompts, causing "asyncio.run() cannot be called from a running event loop" error

### 2. PTY (Pseudo-terminal) Approach
- **Implementation**: Run Mailsh as separate process with PTY for terminal emulation
- **Pros**: Preserves all interactive behavior, doesn't block main event loop, maintains confirmation prompts
- **Cons**: Requires parsing text output, more complex process management

### 3. Thread-based Approach
- **Implementation**: Run blocking operations in separate threads using `asyncio.to_thread()`
- **Pros**: Maintains direct API access, structured output
- **Cons**: Still blocks individual threads on confirmation prompts, doesn't solve the core blocking issue

### 4. Subprocess with CLI
- **Implementation**: Run Mailsh CLI as subprocess and capture stdout/stderr
- **Pros**: Isolates blocking operations, doesn't block main event loop
- **Cons**: Requires text output parsing, loses structured return values

### 5. Separate API Server Process
- **Implementation**: Create IPC server that uses Mailsh API directly in separate process
- **Pros**: Maintains structured output, process isolation, preserves confirmations
- **Cons**: Complex IPC implementation required

## Current Limitations

1. **Async/Sync Mismatch**: The core Mailsh application uses synchronous operations with blocking input calls that are incompatible with async MCP server requirements.

2. **Interactive Prompt Handling**: Confirmation prompts require blocking input operations that conflict with the async nature of MCP servers.

3. **Architecture Constraint**: The existing Mailsh application was designed as an interactive CLI, not for programmatic API access with preserved interactive elements.

4. **State Management**: The application maintains state internally, making it challenging to separate interactive elements from stateful operations.

## Key Challenge

We need to simultaneously maintain:
- Direct API access with structured output
- Persistent session state between commands
- All existing confirmation prompts
- Async event loop compatibility

This creates a technical paradox since confirmation prompts require blocking operations that conflict with async server requirements.

## Request for Recommendations

We need your expertise to suggest an approach that best balances these requirements, or identify a solution we may have missed that addresses all our objectives while working within the existing architecture constraints.