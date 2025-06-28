import base64
import hashlib


def generate_short_id(input_string: str) -> str:
    """
    Generate a 5-character ID from an input string using SHA-256 hashing.

    Args:
        input_string (str): The string to hash

    Returns:
        str: A 5-character ID
    """
    # Create SHA-256 hash of the input string
    hash_object = hashlib.sha256(input_string.encode())

    # Get the hash in bytes and encode to base64
    hash_bytes = hash_object.digest()
    base64_str = base64.urlsafe_b64encode(hash_bytes).decode()

    # Take first 5 characters and remove any non-alphanumeric characters
    short_id = "".join(c for c in base64_str[:5] if c.isalnum())

    # If we somehow got less than 5 characters, pad with '0'
    return short_id.ljust(5, "0")
