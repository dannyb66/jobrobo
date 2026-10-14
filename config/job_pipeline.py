"""Stage budgets and behavior. Job filters remain in config/search.py."""

db_path = "data/job_pipeline/pipeline.sqlite3"
default_set = "startup-companies"
default_limit = 25
sources = ["a16z", "greylock", "sequoia", "yc", "hn", "hiringcafe"]
# Per-source options can include imported records and permitted public URLs.
source_config = {}

# Discovery runs add to a cumulative set. CLI flags override these defaults.
discovery_limit_per_source = 50
discovery_target_companies = 250      # None disables the cumulative target.
discovery_source_limits = {}         # Example: {"a16z": 100, "hn": 25}.
discovery_refresh = False
discovery_render_enabled = False     # Ordinary public JavaScript rendering, enabled explicitly.

# Verification spends its budget on companies, independently of discovery/apply.
verification_limit_companies = 25
verification_refresh = False
verification_render_enabled = False
verification_prioritize_established = True
verification_freshness_days = 7       # Also bounds verified-role freshness for LinkedIn.

# Evidence-based maturity criteria shared by verification and role prioritization.
established_min_employees = 50
established_funding_stages = [f"Series {letter}" for letter in "BCDEFGHIJKLMNOPQRSTUVWXYZ"] + ["IPO", "Public"]

# Bounds apply only when a discovery/verification rendering flag is enabled.
public_render_max_pages = 5
public_render_timeout_seconds = 15
