# Mailsh MCP Enhancement: Programmatic Access Implementation

## Overview
Enhance Mailsh to provide programmatic alternatives for operations that currently require interactive user input, while maintaining backward compatibility with the standard Mailsh CLI experience.

## Current Problem
Several MCP tools are currently non-functional because they map to commands requiring interactive operations (multi-step prompts, text editor launches, etc.):
- `profile_add`
- `set_email_field` (for email body)
- `create_template`
- `compose_email`
- `edit_template`
- `watch_task`

These operations have blocking mechanisms that prevent MCP clients from using them effectively.

## Implementation Objectives

### Phase 1: Enable Programmatic Access
Add programmatic versions of interactive operations for the following MCP tools:

#### 1. **`add_profile` Tool**
- Implement functionality to programmatically add SMTP profiles without interactive prompts
- Accept all required profile parameters (host, port, username, password, encryption, etc.) as direct inputs
- Bypass any interactive field collection mechanisms
- Validate inputs and provide clear error messages for missing/invalid parameters

#### 2. **`create_template` Tool**
- Implement functionality to programmatically create email templates without launching a text editor
- Accept template name and complete template content as direct inputs
- Support all template formatting and variable substitution features
- Validate template syntax and provide meaningful error feedback

#### 3. **`set_email_field` Tool**
- Implement functionality to programmatically set email body content without launching a text editor
- Accept body content as a direct input parameter (supporting multi-line text)
- Preserve existing functionality for other email fields (subject, to, cc, bcc, etc.)

### Phase 2: Remove Obsolete Tools
Remove the following MCP tools entirely as they are redundant or unsuitable for MCP usage:
- `compose_email` (functionality covered by `set_email_field`)
- `edit_template` (editing via MCP should use `create_template` to replace)
- `watch_task` (use existing `show_task` tool instead)

### Phase 3: Remove Old Blocking Mechanisms
After implementing programmatic access in Phase 1:
- Locate and remove blocking mechanisms currently preventing `add_profile`, `create_template`, and `set_email_field` from functioning over MCP
- Ensure these tools now execute successfully when called by MCP clients

### Phase 4: Implement Command Interception in `execute_mailsh_command`
Add blocking/coercion mechanisms within the `execute_mailsh_command` tool to intercept interactive commands and redirect MCP clients to use appropriate programmatic tools instead.

Implement interception for the following commands:

#### **`compose` command**
- **Action**: Block execution
- **Response**: Return clear message instructing the client to use the `set_email_field` tool instead
- **Message Example**: "The 'compose' command requires interactive input. Please use the 'set_email_field' tool to set the email body programmatically."

#### **`template create` command**
- **Action**: Block execution
- **Response**: Instruct client to use the `create_template` tool
- **Message Example**: "The 'template create' command requires a text editor. Please use the 'create_template' tool to create templates programmatically with all content provided as parameters."

#### **`template edit` command**
- **Action**: Block execution
- **Response**: Suggest using `create_template` to recreate/replace the template
- **Message Example**: "The 'template edit' command requires a text editor and is not supported over MCP. To modify a template, use the 'create_template' tool to create a new version."

#### **`profile add` command**
- **Action**: Block execution
- **Response**: Instruct client to use the `add_profile` tool
- **Message Example**: "The 'profile add' command requires interactive input. Please use the 'add_profile' tool to add profiles programmatically with all parameters provided directly."

#### **`task watch` command**
- **Action**: Block execution
- **Response**: Instruct client to use the `show_task` tool
- **Message Example**: "The 'task watch' command is not supported over MCP. Please use the 'show_task' tool to retrieve task information."

#### **`set body` command**
- **Action**: Block execution
- **Response**: Instruct client to use the `set_email_field` tool
- **Message Example**: "The 'set body' command requires a text editor. Please use the 'set_email_field' tool to set the email body programmatically."

## Implementation Notes

### Detection Strategy
- Parse the command string in `execute_mailsh_command` before execution
- Match against the list of interactive commands above
- Return helpful error/redirection messages before attempting to execute
- Ensure detection is robust to variations in command formatting (extra spaces, flags, etc.)

### Backward Compatibility
- **Critical**: All changes must preserve normal CLI functionality
- Interactive prompts and editor launches should continue to work when Mailsh is used directly from the command line
- Only MCP-specific code paths should implement the new programmatic access
- Consider using context/environment detection to distinguish between CLI and MCP usage

### Error Handling
- All programmatic implementations should validate inputs thoroughly
- Provide clear, actionable error messages for validation failures
- Maintain consistent error response format across all tools

### Testing Considerations
- Test all modified tools via MCP client to ensure programmatic access works
- Test all commands via standard CLI to ensure interactive functionality remains intact
- Verify command interception in `execute_mailsh_command` catches all specified commands
- Test edge cases: empty inputs, special characters, very long content, etc.

## Success Criteria
1. MCP clients can successfully create profiles using `add_profile` with all parameters
2. MCP clients can create templates using `create_template` with name and full content
3. MCP clients can set email body using `set_email_field` with multi-line content
4. Obsolete tools (`compose_email`, `edit_template`, `watch_task`) are removed
5. Interactive commands executed via `execute_mailsh_command` are properly intercepted with helpful messages
6. Standard Mailsh CLI usage remains completely unchanged and fully functional
7. All blocking mechanisms for now-functional tools are removed

## Files/Areas Likely Requiring Modification
- MCP server tool definitions and handlers
- Core Mailsh modules handling profile management
- Core Mailsh modules handling template operations
- Core Mailsh modules handling email composition
- Command parsing/routing logic in `execute_mailsh_command`
- Any existing blocking/validation mechanisms in MCP tool layer
