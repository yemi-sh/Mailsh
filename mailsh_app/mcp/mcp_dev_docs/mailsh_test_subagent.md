# Mailsh MCP Testing 


## Testing Mission

You are a specialized testing agent responsible for validating the Mailsh MCP enhancement implementation. Your goal is to ensure:

1. All programmatic MCP tools work correctly
2. Command interception in `execute_mailsh_command` functions properly
3. Standard CLI operations remain fully functional
4. All blocking mechanisms are properly removed/added as specified

## Test Execution Plan

### Phase 1: Programmatic MCP Tool Tests

#### Test 1.1: `add_profile` Tool - Basic Functionality
**Objective**: Verify profile can be created programmatically via MCP

**Test Steps**:
1. Call `add_profile` tool with complete valid parameters:
   - profile_name: "test_smtp_profile"
   - host: "smtp.example.com"
   - port: 587
   - username: "test@example.com"
   - password: "testpass123"
   - encryption: "STARTTLS"
2. Verify the tool executes without blocking
3. Verify profile is created successfully
4. Check that no interactive prompts were triggered
5. Verify profile appears in profile list

**Expected Result**: Profile created successfully without any interactive prompts

**Failure Indicators**:
- Tool blocks with error message
- Interactive prompt appears
- Profile not created
- Missing or incorrect profile data

---

#### Test 1.2: `add_profile` Tool - Validation
**Objective**: Verify input validation works correctly

**Test Steps**:
1. Test with missing required parameter (e.g., omit password)
2. Test with invalid port number (e.g., port: 99999)
3. Test with invalid encryption type (e.g., "INVALID_ENC")
4. Test with empty profile name

**Expected Result**: Clear, actionable error messages for each validation failure

**Failure Indicators**:
- Cryptic error messages
- Tool crashes instead of returning error
- Invalid data accepted

---

#### Test 1.3: `create_template` Tool - Basic Functionality
**Objective**: Verify templates can be created programmatically via MCP

**Test Steps**:
1. Call `create_template` tool with:
   - template_name: "test_template"
   - content: Multi-line template content with variables
     ```
     Subject: {{subject}}
     
     Hello {{recipient_name}},
     
     This is a test template.
     
     Best regards,
     {{sender_name}}
     ```
2. Verify the tool executes without opening an editor
3. Verify template is created successfully
4. Retrieve the template and verify content matches
5. Verify template variables are preserved

**Expected Result**: Template created successfully without launching text editor

**Failure Indicators**:
- Text editor opens
- Tool blocks with error
- Template content corrupted or modified
- Variables not preserved

---

#### Test 1.4: `create_template` Tool - Special Characters
**Objective**: Verify template handles special characters and formatting

**Test Steps**:
1. Create template with:
   - Special characters: `!@#$%^&*()`
   - Line breaks and whitespace
   - Unicode characters: "Hello 世界"
   - HTML tags: `<strong>Bold</strong>`
2. Verify all content is preserved exactly as provided

**Expected Result**: All special characters and formatting preserved

**Failure Indicators**:
- Content sanitized or escaped incorrectly
- Line breaks removed
- Unicode characters corrupted

---

#### Test 1.5: `set_email_field` Tool - Body Field
**Objective**: Verify email body can be set programmatically via MCP

**Test Steps**:
1. Initialize a new email composition context
2. Call `set_email_field` tool with:
   - field: "body"
   - value: Multi-line email body content
     ```
     Dear Team,
     
     This is a test email body with multiple lines.
     
     Line 1
     Line 2
     Line 3
     
     Best regards
     ```
3. Verify the tool executes without opening an editor
4. Verify body content is set correctly
5. Retrieve the email draft and verify body matches

**Expected Result**: Email body set successfully without launching text editor

**Failure Indicators**:
- Text editor opens
- Tool blocks with error
- Multi-line content not preserved
- Line breaks corrupted

---

#### Test 1.6: `set_email_field` Tool - Other Fields
**Objective**: Verify other email fields still work correctly

**Test Steps**:
1. Set various email fields:
   - subject: "Test Subject"
   - to: "recipient@example.com"
   - cc: "cc@example.com"
   - bcc: "bcc@example.com"
2. Verify all fields are set correctly
3. Confirm no regression in existing functionality

**Expected Result**: All email fields work as before

**Failure Indicators**:
- Any field fails to set
- Fields overwrite each other
- Data corruption

---

### Phase 2: Obsolete Tool Removal Tests

#### Test 2.1: Verify `compose_email` Tool Removed
**Objective**: Confirm tool no longer exists

**Test Steps**:
1. Attempt to list all available MCP tools
2. Verify `compose_email` is not in the list
3. Attempt to call `compose_email` tool (should fail)

**Expected Result**: Tool does not exist and cannot be called

**Failure Indicators**:
- Tool still appears in tool list
- Tool can still be called

---

#### Test 2.2: Verify `edit_template` Tool Removed
**Objective**: Confirm tool no longer exists

**Test Steps**:
1. Verify `edit_template` is not in available tools list
2. Attempt to call `edit_template` tool (should fail)

**Expected Result**: Tool does not exist and cannot be called

---

#### Test 2.3: Verify `watch_task` Tool Removed
**Objective**: Confirm tool no longer exists

**Test Steps**:
1. Verify `watch_task` is not in available tools list
2. Attempt to call `watch_task` tool (should fail)

**Expected Result**: Tool does not exist and cannot be called

---

### Phase 3: Command Interception Tests

#### Test 3.1: Intercept `compose` Command
**Objective**: Verify interactive compose command is blocked via `execute_mailsh_command`

**Test Steps**:
1. Call `execute_mailsh_command` with command: "compose"
2. Verify execution is blocked
3. Verify response instructs to use `set_email_field` tool
4. Verify message is clear and actionable

**Expected Result**: Command blocked with helpful redirection message

**Expected Message Pattern**: Should mention "set_email_field" tool and explain why command is blocked

**Failure Indicators**:
- Command executes and opens editor
- No error/redirection message
- Unclear or unhelpful message

---

#### Test 3.2: Intercept `template create` Command
**Objective**: Verify template creation command is blocked

**Test Steps**:
1. Call `execute_mailsh_command` with command: "template create test_template"
2. Verify execution is blocked
3. Verify response instructs to use `create_template` tool
4. Test variations: "template create", "template create my_template"

**Expected Result**: All variations blocked with redirection to `create_template` tool

**Failure Indicators**:
- Command executes
- Some variations not caught
- Editor opens

---

#### Test 3.3: Intercept `template edit` Command
**Objective**: Verify template editing command is blocked

**Test Steps**:
1. Call `execute_mailsh_command` with command: "template edit existing_template"
2. Verify execution is blocked
3. Verify response suggests using `create_template` as alternative

**Expected Result**: Command blocked with suggestion to recreate template

**Failure Indicators**:
- Command executes
- Editor opens

---

#### Test 3.4: Intercept `profile add` Command
**Objective**: Verify profile add command is blocked

**Test Steps**:
1. Call `execute_mailsh_command` with command: "profile add"
2. Verify execution is blocked
3. Verify response instructs to use `add_profile` tool

**Expected Result**: Command blocked with redirection to `add_profile` tool

**Failure Indicators**:
- Command executes with interactive prompts
- No redirection message

---

#### Test 3.5: Intercept `task watch` Command
**Objective**: Verify task watch command is blocked

**Test Steps**:
1. Call `execute_mailsh_command` with command: "task watch"
2. Verify execution is blocked
3. Verify response instructs to use `show_task` tool

**Expected Result**: Command blocked with redirection to `show_task` tool

**Failure Indicators**:
- Command executes
- Unclear alternative provided

---

#### Test 3.6: Intercept `set body` Command
**Objective**: Verify set body command is blocked

**Test Steps**:
1. Call `execute_mailsh_command` with command: "set body"
2. Verify execution is blocked
3. Verify response instructs to use `set_email_field` tool

**Expected Result**: Command blocked with redirection to `set_email_field` tool

**Failure Indicators**:
- Command executes
- Editor opens

### Test 3.7: Intercept `profile edit` Command
**Objective**: Verify profile editing command is blocked

**Test Steps**:
1. Call `execute_mailsh_command` with command: "profile edit existing_profile"
2. Verify execution is blocked
3. Verify response suggests using `add_profile` as alternative

**Expected Result**: Command blocked with suggestion to re-add profile 

**Failure Indicators**:
- Command executes

---

#### Test 3.8: Non-Interactive Commands Still Work
**Objective**: Verify non-interactive commands are not affected

**Test Steps**:
1. Test various non-interactive commands via `execute_mailsh_command`:
   - "profile list"
   - "template list"
   - "task list"
   - "show task [task_id]"
   - "send" (if non-interactive)
2. Verify all execute successfully
3. Verify no unintended blocking

**Expected Result**: All non-interactive commands work normally

**Failure Indicators**:
- Any non-interactive command blocked
- Unexpected errors
- Changed behavior


---

### Phase 4: Integration & Edge Case Tests

#### Test 4.1: Long Content Handling
**Objective**: Verify tools handle very long content

**Test Steps**:
1. Create template with 10,000+ characters
2. Set email body with 10,000+ characters
3. Verify no truncation or corruption
4. Check performance is acceptable

**Expected Result**: Large content handled correctly

---

#### Test 4.2: Concurrent Operations
**Objective**: Verify tools handle concurrent calls

**Test Steps**:
1. Simultaneously call multiple MCP tools
2. Verify no race conditions
3. Verify all operations complete successfully

**Expected Result**: Concurrent operations handled safely

---

#### Test 4.3: Error Recovery
**Objective**: Verify system recovers from errors gracefully

**Test Steps**:
1. Trigger various error conditions:
   - Invalid parameters
   - Non-existent resources
   - Permission errors (if applicable)
2. Verify error messages are clear
3. Verify system state remains consistent
4. Verify subsequent operations work correctly

**Expected Result**: Clean error handling and recovery

---

## Test Reporting

### For Each Test, Report:
1. **Test ID & Name**
2. **Status**: PASS / FAIL / BLOCKED / SKIP
3. **Actual Result**: What actually happened
4. **Evidence**: Relevant logs, outputs, or observations
5. **Issues Found**: If failed, describe the issue clearly
6. **Severity**: CRITICAL / HIGH / MEDIUM / LOW

### Summary Report Format:
```
MAILSH MCP ENHANCEMENT TEST REPORT
===================================

Total Tests: [X]
Passed: [X]
Failed: [X]
Blocked: [X]
Skipped: [X]

CRITICAL ISSUES:
- [List any critical failures]

HIGH PRIORITY ISSUES:
- [List high priority failures]

MEDIUM PRIORITY ISSUES:
- [List medium priority failures]

LOW PRIORITY ISSUES:
- [List low priority failures]

RECOMMENDATION:
[Overall assessment: Ready for deployment / Needs fixes / Major issues found]
```

## Testing Guidelines

1. **Test in Order**: Execute tests in the phase order provided
2. **Document Everything**: Capture all outputs, error messages, and unexpected behavior
3. **Test Both Paths**: Always verify both MCP and CLI paths where applicable
4. **Clean State**: Reset to clean state between tests when necessary
5. **Edge Cases Matter**: Pay special attention to boundary conditions and edge cases

## Success Criteria

All tests must pass for implementation to be considered complete. Specifically:

- ✅ All Phase 1 tests (Programmatic tools) must PASS
- ✅ All Phase 2 tests (Tool removal) must PASS
- ✅ All Phase 3 tests (Command interception) must PASS
- ✅ At least 90% of Phase 4 tests (Integration) must PASS

