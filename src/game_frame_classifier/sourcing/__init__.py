"""Shared frame sourcing: recipe, probe, bucket_v1 sampler, tiers and packs (D26).

Every module in this package imports only the Python standard library, so the
Frame Export Kit can ship it with an embeddable Python and no third-party packages.
"""

SCHEMA_RECIPE = "gfc.recipe/1"
SCHEMA_USER = "gfc.user/1"
SCHEMA_PACK = "gfc.pack/1"
SCHEMA_INGEST = "gfc.ingest/1"
SAMPLER = "bucket_v1"
