"""
Syntax highlighting for Mailsh commands and flags.

This module provides syntax highlighting for the Mailsh CLI,
highlighting valid commands and flags with configurable colors.
"""

from prompt_toolkit.lexers import Lexer
from prompt_toolkit.formatted_text import StyleAndTextTuples
import re
import shlex


class MailshSyntaxHighlighter(Lexer):
    """Syntax highlighter for Mailsh commands."""
    
    def __init__(self, config):
        self.config = config
        # Define valid commands and subcommands
        self.valid_commands = {
            'profile', 'draft', 'set', 'unset',
            'send', 'template', 'config', 'history',
            'schedule', 'contacts', 'task', 'help', 'exit', 'quit'
        }
        
        self.valid_subcommands = {
            'profile': {'add', 'list', 'remove', 'show', 'connect', 'disconnect', 'edit'},
            'draft': {'compose', 'preview', 'clear'},
            'set': {'to', 'cc', 'bcc', 'subject', 'body', 'header', 'html', 'attachment'},
            'unset': {'to', 'cc', 'bcc', 'subject', 'body', 'header', 'html', 'attachment'},
            'template': {'list', 'show', 'create', 'edit', 'delete', 'test', 'import'},
            'config': {'show', 'get', 'set', 'reset'},
            'history': {'list', 'show', 'stats'},
            'schedule': {'send', 'list', 'show', 'cancel', 'clear'},
            'contacts': {'import', 'update', 'preview', 'validate', 'list', 'remove'},
            'task': {'list', 'show', 'watch', 'pause', 'resume', 'end', 'clean'},
            'send': {'bulk'}
        }
        
        self.valid_flags = {
            '--template', '--contacts', '--top', '--bottom', '--all',
            '--html', '--text', '--dry-run', '--limit', '--name', '--mx',
            '--status', '--profile', '--recipient', '--subject', '--from', '--to'
        }
    
    def get_command_color(self) -> str:
        return self.config.get('syntax_highlighting.commands') or '#00d7ff'
    
    def get_flag_color(self) -> str:
        return self.config.get('syntax_highlighting.flags') or '#d700ff'
    
    def get_default_color(self) -> str:
        return self.config.get('syntax_highlighting.default') or '#ffffff'

    def _tokenize_input(self, text):
        """Tokenize input text into tokens and whitespace, preserving positions."""
        tokens = []
        pos = 0
        
        while pos < len(text):
            # Skip whitespace, but record it
            if text[pos].isspace():
                start = pos
                while pos < len(text) and text[pos].isspace():
                    pos += 1
                tokens.append(('whitespace', text[start:pos], start, pos))
                continue
            
            # Find the next non-whitespace sequence (a token)
            start = pos
            if text[pos] == '"':
                # Handle double-quoted strings
                pos += 1
                while pos < len(text) and text[pos] != '"':
                    if pos + 1 < len(text) and text[pos] == '\\':
                        pos += 2  # Skip escaped characters
                    else:
                        pos += 1
                if pos < len(text) and text[pos] == '"':
                    pos += 1  # Include the closing quote
            elif text[pos] == "'":
                # Handle single-quoted strings
                pos += 1
                while pos < len(text) and text[pos] != "'":
                    pos += 1
                if pos < len(text) and text[pos] == "'":
                    pos += 1  # Include the closing quote
            else:
                # Regular token - stop at whitespace
                while pos < len(text) and not text[pos].isspace():
                    pos += 1
            
            token_text = text[start:pos]
            tokens.append(('token', token_text, start, pos))
        
        return tokens

    def lex_document(self, document):
        """Lex the input document and apply syntax highlighting."""
        input_text = document.text
        
        def get_line(line_number):
            if line_number != 0:
                return [('', '')]
            
            if not input_text.strip():
                return [('', input_text)]
            
            # Simple tokenization by whitespace, but we'll process original text carefully
            # Use shlex to properly split while respecting quotes
            try:
                tokens = shlex.split(input_text, posix=False)
            except:
                # If shlex fails, use simple split
                tokens = input_text.split()
            
            # Process original text to identify tokens and apply styles
            result: StyleAndTextTuples = []
            current_pos = 0
            token_idx = 0
            
            while current_pos < len(input_text):
                # Skip whitespace
                while current_pos < len(input_text) and input_text[current_pos].isspace():
                    result.append(('', input_text[current_pos]))
                    current_pos += 1
                
                if current_pos >= len(input_text):
                    break
                
                # Now find the next token
                # Look for the token in the remaining text
                remaining_text = input_text[current_pos:]
                
                # Find the next token to process
                if token_idx < len(tokens):
                    token = tokens[token_idx]
                    
                    # Check if the current position starts with this token
                    if remaining_text.startswith(token):
                        # Apply appropriate styling
                        if token_idx == 0 and token in self.valid_commands:
                            # First token, valid command
                            result.append((f'{self.get_command_color()}', token))
                        elif (token_idx == 1 and 
                              len(tokens) > 0 and 
                              tokens[0] in self.valid_subcommands and 
                              token in self.valid_subcommands[tokens[0]]):
                            # Second token, valid subcommand
                            result.append((f'{self.get_command_color()}', token))
                        elif token.startswith('-') and token in self.valid_flags:
                            # Valid flag
                            result.append((f'{self.get_flag_color()}', token))
                        elif token.startswith('--'):
                            # Potential long flag
                            is_valid = any(token == valid_flag or token.startswith(valid_flag + '=') 
                                         for valid_flag in self.valid_flags if valid_flag.startswith('--'))
                            if is_valid:
                                result.append((f'{self.get_flag_color()}', token))
                            else:
                                result.append(('', token))
                        else:
                            result.append(('', token))
                        
                        current_pos += len(token)
                        token_idx += 1
                    else:
                        # This should not happen with proper tokenization, but just add character
                        result.append(('', input_text[current_pos]))
                        current_pos += 1
                else:
                    # All tokens processed, add remaining text
                    result.append(('', input_text[current_pos:]))
                    break
            
            return result if result else [('', input_text)]
        
        return get_line