"""Pipeline discovery preferences. Job filters remain in config/search.py."""

db_path = "data/job_pipeline/pipeline.sqlite3"
default_set = "startup-companies"
default_limit = 25
verification_freshness_days = 7
sources = ["greylock", "sequoia", "a16z", "yc", "hn", "hiringcafe"]
# Per-source options can include imported records and permitted public URLs.
source_config = {}
