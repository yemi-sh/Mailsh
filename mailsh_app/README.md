# Mailsh Code Organization

## Directory Structure
- core/: Core business logic and data models
- features/: Optional feature modules
- cli/: Command-line interface and commands
- utils/: Shared utilities and helpers

## Adding New Features
- Place core functionality in the `core/` directory
- Add new features to the `features/` directory
- Create new command modules in `cli/commands/` directory
- Add utility functions to the `utils/` directory

## Module Dependencies
- Core modules can import from `utils`
- Feature modules can import from `utils` and `core`
- CLI modules can import from everywhere (`utils`, `core`, `features`)
- Utility modules should be self-contained and avoid importing from other directories