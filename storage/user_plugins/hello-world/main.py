"""
Hello World Plugin
A simple demonstration plugin
"""

def say_hello(name: str) -> str:
    """
    Say hello to someone
    
    Args:
        name: Name of the person to greet
        
    Returns:
        Greeting message
    """
    return f"Hello, {name}! Welcome to the All-Agent Manager plugin system."


def get_capabilities():
    """
    Get plugin capabilities
    
    Returns:
        List of capability handlers
    """
    return {
        "say-hello": say_hello
    }


if __name__ == "__main__":
    print(say_hello("World"))
