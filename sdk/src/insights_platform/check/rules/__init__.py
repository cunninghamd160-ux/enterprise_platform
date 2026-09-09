from insights_platform.check.core import Rule
from insights_platform.check.rules import (
    apps_independent,
    manifest_valid,
    no_client_construction,
    no_private_imports,
    no_raw_drivers,
    scaffold_supported,
    use_create_app,
)

RULES: tuple[Rule, ...] = (
    no_raw_drivers.RULE,
    no_client_construction.RULE,
    use_create_app.RULE,
    no_private_imports.RULE,
    apps_independent.RULE,
    manifest_valid.RULE,
    scaffold_supported.RULE,
)
