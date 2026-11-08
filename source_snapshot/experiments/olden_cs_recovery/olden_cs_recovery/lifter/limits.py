"""Honest MVP lift bounds. Oversized methods stay claimable; they are not invented."""

# EventArgs methods are preferred and have no instruction cap beyond missing inputs.
# edb methods above this ISIL instruction count are refused for Phase 1 MVP lift.
EDB_MAX_ISIL_INSTRUCTIONS = 120

# Prefer EventArgs partitions before edb when both appear in one claim batch.
PARTITION_PRIORITY = (
    "Hex.Session.Battle.UnitMechanics",
    "Hex.Session.Battle",
    "edb",
)
