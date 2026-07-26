"""
校验器包
========

v2 架构：拆分单体 itinerary_validator.py 为 7 个独立校验器。

使用方式：
    from backend.validators.hard_constraint_validator import (
        validate_hard_constraints,
        enrich_items_with_places,
    )

    result = validate_hard_constraints(itinerary, requirements)
"""

from backend.validators.hard_constraint_validator import validate_hard_constraints

# 保留向后兼容
from backend.validators.itinerary_validator import validate_itinerary

__all__ = [
    "validate_hard_constraints",
    "validate_itinerary",
]
