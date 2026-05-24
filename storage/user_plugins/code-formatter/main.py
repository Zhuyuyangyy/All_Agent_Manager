"""
Code Formatter Plugin
A simple code formatting demonstration plugin
"""

def format_code(code: str, language: str = "python", style: str = "default") -> str:
    """
    Format code according to style guidelines
    
    Args:
        code: Code to format
        language: Programming language
        style: Code style
        
    Returns:
        Formatted code
    """
    # Simple formatting demonstration
    if language.lower() == "python":
        # Basic Python formatting
        lines = code.strip().split('\n')
        formatted_lines = []
        indent_level = 0
        
        for line in lines:
            stripped = line.strip()
            if stripped:
                # Adjust indentation
                if stripped.startswith(('def ', 'class ', 'if ', 'for ', 'while ', 'try:', 'except ')):
                    if formatted_lines and formatted_lines[-1].endswith(':'):
                        indent_level += 1
                elif stripped.startswith(('return', 'break', 'continue', 'pass')):
                    if indent_level > 0:
                        indent_level -= 1
                elif stripped.endswith(':'):
                    pass
                
                formatted_line = ' ' * (indent_level * 4) + stripped
                formatted_lines.append(formatted_line)
            else:
                formatted_lines.append('')
        
        return '\n'.join(formatted_lines)
    
    # Default: just return with consistent line endings
    return code.strip()


def get_capabilities():
    """
    Get plugin capabilities
    
    Returns:
        List of capability handlers
    """
    return {
        "format-code": format_code
    }


if __name__ == "__main__":
    sample_code = """
def hello(name):
print(f"Hello, {name}")
if True:
print("Yes!")
    """
    print(format_code(sample_code))
