# Completers.py Development Guidelines

## ⚠️ CRITICAL: READ THIS BEFORE MODIFYING COMPLETERS.PY

This document outlines the **strict architectural philosophy** that MUST be followed when modifying the `completers.py` file. Violating these principles will break the completion system's design and introduce bugs.

## Architecture Decision: Subcommand vs Flag_spec

### When to Use Subcommand Pattern

Use `type: "subcommand"` when:
- The second argument is a **command-like action** (e.g., `send bulk`, `profile remove`)
- It changes the behavior fundamentally
- It has its own set of options/flags distinct from the parent
- Users think of it as "doing something different"

**Examples**:
- `send bulk` - bulk sending is a distinct action
- `profile remove` - removing is an action
- `config set` - setting is an action

### When to Use Flag_spec Pattern

Use `flag_spec` when:
- The second argument is a **field or data type** (e.g., `set attachment`, `set html`)
- It's selecting what to operate on, not what action to perform
- The behavior is still "setting", just on different types of data
- Users think of it as "setting different things"

**Examples**:
- `set attachment <path>` - "attachment" is a field type
- `set html <bool>` - "html" is a field type
- `unset header <name>` - "header" is a field type

### Quick Decision Rule

Ask: "Is this a verb or a noun?"
- **Verb** (action) → Subcommand pattern
- **Noun** (data/field) → Flag_spec pattern

---

## Core Philosophy: Position-Based, Strict, Coercive Completions

The completion system is designed to be **position-aware, strictly terminal-enforced, and coercive**. This means:

1. **Every command has predetermined, exact position counts** (min = max in most cases)
2. **Each position accepts ONLY specific types of values** (no cross-contamination)
3. **Terminal positions are strictly enforced** - once reached, NO completions appear
4. **Positions are completed sequentially** - you cannot skip to later positions
5. **Flags have designated positions** - they don't float arbitrarily

---

## Position Counting System

### How Positions Are Counted

Positions are **zero-indexed** starting from the command itself:

```
Position:    0      1     2      3       4        5         6
Command:  command  sub  arg1   arg2   --flag  flag_val  --flag2
           ^                                              ^
       Position 0                                    Position 6
```

### Terminal Position Semantics

**Terminal position N** means: "Stop all completions when `tracker.current_position() > N`"

Examples:
- `terminal: 1` = allows positions 0 and 1 (2 total positions)
- `terminal: 3` = allows positions 0, 1, 2, 3 (4 total positions)  
- `terminal: -1` = no arguments allowed (command only)

**CRITICAL**: Count positions from the command level, not relative. For subcommands, count from the main command:
- `config set <key> <value>` = positions 0, 1, 2, 3 → `terminal: 4`
- `profile remove <name>` = positions 0, 1, 2 → `terminal: 3`

---

## Command Type Architecture

### 1. Simple Commands (`type: "simple"`)

Commands with fixed positional arguments, no subcommands.

**When to use**: 
- Single-level commands like `connect <profile>`
- Commands with positions + flags like `send [bulk|--template]`

**Spec Structure**:
```python
"command_name": {
    "type": "simple",
    "positions": [
        # Position 1 (after command)
        lambda self: self.mailsh.some_data.list(),  # Dynamic
        # OR
        ["option1", "option2"],  # Static
        # OR
        "_path",  # File path
        # OR
        None  # User must type manually, no completions
    ],
    "terminal": 2  # Total positions: command + 1 arg = 2
}
```

**Examples**:
```python
"connect": {
    "type": "simple",
    "positions": [lambda self: self.mailsh.profiles.list()],
    "terminal": 1  # connect <profile> = 2 positions total (0, 1)
}
```

---

### 2. Subcommand-Based Commands (`type: "subcommand"`)

Commands with subcommands, each having their own position specs.

**When to use**: 
- Multi-level commands like `profile {add|list|remove|show}`, `config {get|set}`, etc.

**Spec Structure**:
```python
"command_name": {
    "type": "subcommand",
    "subcommands": {
        "subcommand1": {
            "positions": [...],
            "terminal": N  # Count from main command!
        },
        "subcommand2": {
            "positions": [...],
            "flags": {...},  # Optional
            "terminal": M
        }
    }
}
```

**Examples**:
```python
"config": {
    "type": "subcommand",
    "subcommands": {
        "get": {
            "positions": [all_config_keys],
            "terminal": 3  # config get <key> = 3 positions (0,1,2)
        },
        "set": {
            "positions": [
                all_config_keys,
                "_context_dependent_values"
            ],
            "terminal": 4  # config set <key> <value> = 4 positions (0,1,2,3)
        }
    }
}
```

---

### 3. Commands with Flags

Commands that accept flags with values.

**CRITICAL RULES FOR FLAGS**:

#### Rule 1: Use Positions First, Then Flags

If a command has BOTH positional arguments AND flags, **positions must complete BEFORE flags appear**.

**Correct Pattern**:
```python
"contacts": {
    "type": "subcommand",
    "subcommands": {
        "preview": {
            "positions": [
                lambda self: self.mailsh.contacts_manager.list_contacts()  # Position 1
            ],
            "flags": {
                "--limit": {...}  # Only appears AFTER position 1
            },
            "terminal": 5
        }
    }
}
```

**WRONG Pattern** (DO NOT DO THIS):
```python
"preview": {
    "type": "flags",  # ❌ This makes flags appear BEFORE positions!
    "positions": [lambda self: ...],
    "flags": {...}
}
```

#### Rule 2: Flag Specification Format

```python
"flags": {
    "--flag-name": {
        "value_provider": lambda self: [...],  # OR static list
        "multi_value": False  # True only if flag accepts multiple values
    },
    "--boolean-flag": {
        "value_provider": None,  # No value needed
        "multi_value": False
    }
}
```

#### Rule 3: Flag Contexts (flag_spec)

Some commands have context-specific flags (like `send bulk` vs plain `send`).

**Pattern**:
```python
"send": {
    "type": "simple",
    "positions": [["bulk", "--template"]],  # Position 1 options
    "flags": {
        "--template": {...}  # Default flag (for 'send --template')
    },
    "flag_spec": {
        "bulk": {  # Context: when user types 'send bulk'
            "flags": {
                "--contacts": {...},
                "--template": {...},
                "--dry-run": {...}
            },
            "terminal": 6
        }
    },
    "terminal": 3  # For non-bulk send
}
```

#### Rule 4: Positional Args Within Flag Contexts

Some flag contexts need positional arguments (like `set attachment <path>`).

**Pattern**:
```python
"set": {
    "type": "simple",
    "positions": [FIELD_SUGGESTIONS],  # Position 1: field name
    "flag_spec": {
        "attachment": {
            "positions": ["_path"],  # Position 2: file path
            "terminal": 3
        },
        "html": {
            "positions": [["true", "false"]],  # Position 2: boolean
            "terminal": 3
        }
    }
}
```

---

## Position Handler Types

### 1. Static List
```python
"positions": [
    ["option1", "option2", "option3"]
]
```

### 2. Dynamic Provider (Lambda)
```python
"positions": [
    lambda self: self.mailsh.profiles.list()
]
```

### 3. File Path
```python
"positions": [
    "_path"
]
```

### 4. Context-Dependent Values
```python
"positions": [
    all_config_keys,
    "_context_dependent_values"  # Values depend on previous position
]
```

Add logic in `_complete_context_dependent()` to handle the context.

### 5. None (No Completions)
```python
"positions": [
    None  # User must type manually
]
```

**CRITICAL**: When a position is `None`, NO completions appear (not even flags) until the user types something and moves past that position.

**Example**: `schedule send <time_spec>` - time_spec has no completions, user must type it manually.

---

## Strict Rules to Follow

### ✅ DO:

1. **Always count terminal from position 0** (the command itself)
2. **Always specify terminal explicitly** - don't rely on defaults
3. **Use "simple" type for commands with positions + flags** - NOT "flags" type
4. **Put positions before flags in specs** - positions complete first
5. **Check for None positions explicitly** in handlers
6. **Preserve original tracker** for context-dependent values
7. **Test terminal enforcement** - verify no completions after terminal
8. **Document position counts** in comments

### ❌ DON'T:

1. **DON'T use `type: "flags"` for commands with positions** - use "simple" instead
2. **DON'T let flags appear before positions** - positions MUST complete first
3. **DON'T allow cross-contamination** - position 3 values must never appear in position 4
4. **DON'T forget terminal positions** - every command needs one
5. **DON'T use relative position counting** - always count from command (position 0)
6. **DON'T modify core handler logic** without understanding the position priority system
7. **DON'T add fallback completions** - completions must be deterministic and position-aware
8. **DON'T skip None position checks** - None means "no completions, period"

---

## Handler Priority System

### For "simple" Commands:

```
1. Flag_spec context check (e.g., 'send bulk')
   ↓ (if not in context)
2. Positional completions (e.g., 'send ' → ['bulk', '--template'])
   ↓ (if past positions)
3. Regular flags (e.g., 'send --template')
```

**Code Pattern**:
```python
# 1. Check flag_spec context FIRST
if "flag_spec" in spec and len(tracker.parts) >= 2 and not tracker.has_trailing_space:
    context_key = tracker.parts[1]
    if context_key in spec["flag_spec"]:
        # Handle context flags
        return

# 2. Check positions
if current_pos < len(positions):
    if not tracker.current_token().startswith("-"):
        # Handle positions
        return

# 3. Handle regular flags
if "flags" in spec:
    # Handle flags
```

### For "subcommand" Commands:

```
1. Subcommand selection (position 1)
   ↓
2. Positional arguments (positions within subcommand)
   ↓ (if past positions OR user types '-')
3. Flags (if subcommand has flags)
```

**Code Pattern**:
```python
# Subcommand selection
if tracker.current_position() == 1:
    # Show subcommands
    return

# Get subcommand spec
subcommand_spec = spec["subcommands"][subcommand]

# Check positions first
if current_pos < len(positions) and not current_token.startswith("-"):
    position_handler = positions[current_pos]
    
    # Handle None positions
    if position_handler is None:
        return  # No completions!
    
    # Handle position
    return

# Then handle flags
if "flags" in subcommand_spec:
    # Handle flags
```

---

## Common Patterns and Examples

### Pattern 1: Simple Command with One Argument

```python
"connect": {
    "type": "simple",
    "positions": [lambda self: self.mailsh.profiles.list()],
    "terminal": 1  # connect <profile> = positions 0, 1
}
```

**Behavior**:
- `connect ` → shows profile names
- `connect profile_name ` → no completions (terminal reached)

---

### Pattern 2: Subcommand with Positions

```python
"profile": {
    "type": "subcommand",
    "subcommands": {
        "remove": {
            "positions": [lambda self: self.mailsh.profiles.list()],
            "terminal": 3  # profile remove <name> = positions 0, 1, 2
        }
    }
}
```

**Behavior**:
- `profile ` → shows subcommands
- `profile remove ` → shows profile names
- `profile remove name ` → no completions (terminal)

---

### Pattern 3: Command with Positions + Flags

```python
"contacts": {
    "type": "subcommand",
    "subcommands": {
        "preview": {
            "positions": [
                lambda self: self.mailsh.contacts_manager.list_contacts()
            ],
            "flags": {
                "--limit": {
                    "value_provider": ["5", "10", "20"],
                    "multi_value": False
                }
            },
            "terminal": 5  # contacts preview <name> --limit <n>
        }
    }
}
```

**Behavior**:
- `contacts preview ` → shows contact names (position 1)
- `contacts preview name ` → shows `--limit` flag
- `contacts preview name --limit ` → shows `[5, 10, 20]`
- `contacts preview name --limit 10 ` → no completions (terminal)

---

### Pattern 4: None Position (Manual Entry Required)

```python
"schedule": {
    "type": "subcommand",
    "subcommands": {
        "send": {
            "positions": [None],  # time_spec - no completions
            "flags": {
                "--template": {...},
                "--contacts": {...}
            },
            "terminal": 7
        }
    }
}
```

**Behavior**:
- `schedule send ` → no completions (position 1 is None)
- `schedule send "10min" ` → shows flags (past None position)
- `schedule send "10min" --template ` → shows template names

---

### Pattern 5: Context-Dependent Values

```python
"config": {
    "type": "subcommand",
    "subcommands": {
        "set": {
            "positions": [
                all_config_keys,
                "_context_dependent_values"
            ],
            "terminal": 4
        }
    }
}
```

**Handler Logic**:
```python
async def _complete_context_dependent(self, tracker, ...):
    # Get full command parts
    actual_parts = tracker.parts
    
    if actual_parts[0] == "config" and actual_parts[1] == "set":
        key = actual_parts[2]
        
        # Determine values based on key
        if key in BOOL_KEYS:
            suggestions = ["true", "false"]
        elif key == "logging.level":
            suggestions = LOG_LEVELS
        # ... etc
```

**Behavior**:
- `config set ` → shows all config keys
- `config set safety_features.enabled ` → shows `[true, false]`
- `config set logging.level ` → shows `[DEBUG, INFO]`

---

### Pattern 6: Flag Context (flag_spec)

```python
"send": {
    "type": "simple",
    "positions": [["bulk", "--template"]],
    "flags": {
        "--template": {
            "value_provider": lambda self: self.mailsh.templates.list(),
            "multi_value": False
        }
    },
    "flag_spec": {
        "bulk": {
            "flags": {
                "--contacts": {...},
                "--template": {...},
                "--dry-run": {...}
            },
            "terminal": 6
        }
    },
    "terminal": 3
}
```

**Behavior**:
- `send ` → shows `[bulk, --template]`
- `send --template ` → shows template names (using regular flags)
- `send bulk ` → shows bulk flags `[--contacts, --template, --dry-run]`
- `send bulk --contacts ` → shows contact names

---

### Pattern 7: Positional Args in Flag Context

```python
"set": {
    "type": "simple",
    "positions": [FIELD_SUGGESTIONS],
    "flag_spec": {
        "attachment": {
            "positions": ["_path"],
            "terminal": 3
        },
        "send": {
            "flags": {
                "--template": {...},
                "--contacts": {...}
            },
            "terminal": 7
        }
    }
}
```

**Behavior**:
- `set ` → shows field suggestions
- `set attachment ` → shows file paths (positional in "attachment" context)
- `set send ` → shows flags (flag context for "send")
- `set send --template ` → shows template names

---

## Testing Requirements

When adding or modifying commands, you MUST test:

### 1. Position Completions
- [ ] Correct suggestions at each position
- [ ] Suggestions match position spec exactly
- [ ] No suggestions from other positions appear

### 2. Terminal Enforcement
- [ ] No completions after terminal position
- [ ] Terminal counted correctly from position 0
- [ ] Works with trailing space

### 3. Flag Behavior
- [ ] Flags appear only after positions (if positions exist)
- [ ] Flag values complete correctly
- [ ] Boolean flags don't prompt for values

### 4. Context Handling
- [ ] Flag_spec contexts trigger correctly
- [ ] Context-dependent values resolve correctly
- [ ] None positions block all completions

### 5. Edge Cases
- [ ] Empty input (just command)
- [ ] Partial token (typing first letters)
- [ ] Trailing spaces
- [ ] Flag at wrong position
- [ ] Past terminal position

---

## Modification Checklist

Before committing changes to `completers.py`, verify:

- [ ] Terminal positions counted from position 0 (command)
- [ ] No `type: "flags"` used with positional arguments
- [ ] Positions complete before flags (if both exist)
- [ ] None positions explicitly checked
- [ ] Context-dependent handlers use original tracker
- [ ] All terminals explicitly specified
- [ ] No fallback completions added
- [ ] No cross-contamination between positions
- [ ] Handler priority system respected
- [ ] All test cases pass

---

## Common Mistakes and How to Avoid Them

### Mistake 1: Wrong Terminal Position
```python
# ❌ WRONG - terminal too early
"config set": {"terminal": 1}  # Blocks value completion!

# ✅ CORRECT - count all positions
"config set": {"terminal": 4}  # config=0, set=1, key=2, value=3
```

### Mistake 2: Using "flags" Type with Positions
```python
# ❌ WRONG - flags appear before positions
"contacts preview": {
    "type": "flags",
    "positions": [contact_names],
    "flags": {"--limit": {...}}
}

# ✅ CORRECT - no type, or type: "simple"
"contacts preview": {
    "positions": [contact_names],
    "flags": {"--limit": {...}}
}
```

### Mistake 3: Forgetting None Position Check
```python
# ❌ WRONG - shows flags even at None position
if current_pos < len(positions):
    complete_position()
    return
show_flags()

# ✅ CORRECT - check for None first
if current_pos < len(positions):
    if positions[current_pos] is None:
        return  # No completions!
    complete_position()
    return
show_flags()
```

### Mistake 4: Relative Position Counting
```python
# ❌ WRONG - terminal relative to subcommand
"profile remove": {"terminal": 1}  # Off by 2!

# ✅ CORRECT - terminal from main command
"profile remove": {"terminal": 3}  # profile=0, remove=1, name=2
```

### Mistake 5: Not Preserving Original Tracker
```python
# ❌ WRONG - loses command context
async def _complete_by_position(self, spec, tracker, ...):
    if handler == "_context_dependent_values":
        complete_context_dependent(tracker)  # Wrong tracker!

# ✅ CORRECT - preserve original
async def _complete_by_position(self, spec, tracker, ..., original_tracker=None):
    if original_tracker is None:
        original_tracker = tracker
    if handler == "_context_dependent_values":
        complete_context_dependent(original_tracker)  # Correct!
```

---

## Summary: The Golden Rules

1. **Positions are sacred** - strictly enforced, never crossed
2. **Terminal is absolute** - once reached, nothing appears
3. **Positions before flags** - always complete sequentially
4. **None means nothing** - no completions, no exceptions
5. **Count from zero** - command is position 0
6. **Context is preserved** - original tracker for dependencies
7. **Test everything** - positions, terminals, flags, edges
8. **No fallbacks** - completions are deterministic

---

## Questions? Debugging?

If completions aren't working as expected, check:

1. **Is the terminal position correct?** (Count from 0)
2. **Are positions completing before flags?** (Check type and order)
3. **Is there a None position blocking completions?** (Check position handler)
4. **Is the flag_spec context triggering correctly?** (Check has_trailing_space)
5. **Is the handler priority system respected?** (Check router logic)

When in doubt, **follow the patterns in this document exactly**. The completion system is designed to be predictable and strict - deviation from these patterns will break it.

---

**This is not a suggestion - this is the architecture. Follow it strictly.**