"""
Legacy import surface for machine views.

The URLConf still imports `machines.views`, so this module re-exports the
single maintained implementation from `views_v2`.
"""

from .views_v2 import (  # noqa: F401
    machine_create,
    machine_declass,
    machine_delete,
    machine_detail,
    machine_list,
    machine_return_to_service,
    machine_update,
    maintenance_dashboard,
    maintenance_delete,
    maintenance_list,
    maintenance_log_create,
)
