"""
Universal JSON serialization for Home Assistant entity attributes.
Converts datetime, Decimal, Enum and other non-JSON types to safe representations.
"""

from datetime import datetime, date, time
from decimal import Decimal
from enum import Enum


def json_safe(obj):
    """
    Recursively converts Python objects to JSON-serializable types.

    Args:
        obj: Any Python object

    Returns:
        JSON-serializable version of the object
    """
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, (datetime, date, time)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, Enum):
        return obj.name
    if isinstance(obj, dict):
        return {str(k): json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [json_safe(v) for v in obj]
    # poslední záchrana – reprezentace jako text
    return str(obj)
