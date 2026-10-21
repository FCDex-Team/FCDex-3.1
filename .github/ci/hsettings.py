# ruff: noqa
"""CI settings: BallsDex local settings plus sqlite support for its Postgres-only legacy migration guard."""

import importlib
import os
import sys

_upstream = os.environ["FC_UPSTREAM"]
for _extra in (os.path.join(_upstream, "admin_panel"), _upstream):
    if _extra not in sys.path:
        sys.path.insert(0, _extra)

from django.db.migrations.operations.special import RunPython  # noqa: E402

from admin_panel.settings.local import *  # noqa: E402,F401,F403

_mod = importlib.import_module("bd_models.migrations.0003_delete_ball_delete_ballinstance_and_more")
for _op in _mod.Migration.operations:
    if isinstance(_op, RunPython) and getattr(_op.code, "__name__", "") == "execute_aerich_migration_check":
        _op.code = lambda apps, schema_editor: None

# older hosts crash in AppConfig.ready() while loading settings from a database that has no tables yet
from settings import apps as _settings_apps

_settings_apps.SettingsConfig.ready = lambda self: None
