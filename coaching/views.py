"""
Legacy import surface for coaching views.

The URLConf still imports `coaching.views`, so this module re-exports the
single maintained implementation from `views_v2`.
"""

from .views_v2 import (  # noqa: F401
    assign_member,
    coach_create,
    coach_delete,
    coach_detail,
    coach_member_detail,
    coach_member_weight_measurement_create,
    coach_list,
    coach_portal,
    coach_update,
    group_program_create,
    group_program_delete,
    group_program_detail,
    group_program_list,
    group_program_update,
    remove_member,
)
