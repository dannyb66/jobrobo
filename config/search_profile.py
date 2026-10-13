"""Semantic search intent. Locations and filters belong in config/search.py."""

profile_name = "staff-principal-ai-platform"
profile_version = "1"
dynamic_search_enabled = True
ai_query_refinement_enabled = True

role_lanes = [
    "Staff Software Engineer",
    "Principal Software Engineer",
    "AI Platform Engineer",
    "Staff Machine Learning Engineer",
    "Staff Backend Engineer",
    "Founding Engineer",
]
skills = [
    "AI systems", "agent platforms", "LLM applications", "evaluation",
    "cloud infrastructure", "distributed systems", "Python", "TypeScript",
    "AWS", "GCP", "Kubernetes", "APIs", "production reliability",
]

manual_searches = [
    {"id": "staff-ai-platform", "query": "Staff AI Platform Engineer",
     "enabled": True, "quota": 1},
]

# Resume the latest unfinished run with the same configuration automatically.
# Set False to start a new run; successful jobs are still skipped via CSV history.
resume_search_enabled = True
search_state_dir = "logs/search_runs"
