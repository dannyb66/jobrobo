"""Semantic search intent. Locations and filters belong in config/search.py."""

profile_name = "staff-principal-ai-platform"
profile_version = "3"
dynamic_search_enabled = True
ai_query_refinement_enabled = True

role_lanes = [
    "Staff Software Engineer",
    "Principal Software Engineer",
    "AI Platform Engineer",
    "Staff Machine Learning Engineer",
    "Staff Backend Engineer",
    "Staff Infrastructure Engineer",
    "Principal Platform Engineer",
    "Staff Systems Engineer",
    "Principal Inference Engineer",
    "Staff SDK Engineer",
    "Member of Technical Staff - Systems",
    "Member of Technical Staff - Inference Runtime",
    "Member of Technical Staff - Machines",
    "Member of Technical Staff - ML Performance",
    "Member of Technical Staff - Platform Engineering",
    "Member of Technical Staff - Product Backend",
    "Member of Technical Staff - SDK",
    "Member of Technical Staff - Storage",
    "Systems Engineer",
    "Inference Engineer",
    "SDK Engineer",
    "Founding Engineer",
]
skills = [
    "AI systems", "agent platforms", "LLM applications", "evaluation",
    "cloud infrastructure", "distributed systems", "Python", "TypeScript",
    "AWS", "GCP", "Kubernetes", "APIs", "production reliability",
]

manual_searches = [
    {"id": "forward-deployed-engineer",
     "query": "Find Forward Deployed Engineer (FDE), Forward-Deployed Software Engineer, "
              "and Forward Deployed AI Engineer roles focused on customer-facing implementation, "
              "production AI deployments, technical integrations, and hands-on software engineering",
     "role_label": "Forward Deployed Engineer",
     "enabled": True},  # Uses switch_number from config/search.py.
    # Previous first prompt retained for future reuse; set enabled=True to restore.
    {"id": "staff-ai-platform", "query": "Staff AI Platform Engineer",
     "enabled": False, "quota": 1},
]

# Resume the latest unfinished run with the same configuration automatically.
# Set False to start a new run; successful jobs are still skipped via CSV history.
resume_search_enabled = True
search_state_dir = "logs/search_runs"
