"""common enums definition"""

from enum import Enum


class ORMStatusEnum(int, Enum):
    """ORM Status Enums - commonly used for soft delete and active/inactive status"""

    ACTIVATE = 1
    INACTIVATE = 0


# Add your business enums below
# Example:
# class YourBusinessEnum(str, Enum):
#     """Your Business Enums"""
#     VALUE_1 = "value_1"
#     VALUE_2 = "value_2"
