"""Semantic search intent. Locations and filters belong in config/search.py."""

profile_name = "staff-principal-ai-platform"
profile_version = "6"
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
    # Top 5: confirmed by live LinkedIn tests on 2026-11-23 (Easy Apply, SF Bay Area, all workplace
    # types, agencies excluded). `rank` pins them to prompts #1-#5 in this order; `verbatim=True` sends
    # the exact tested text (no "Find ... roles." wrapper and no generic `skills` sentence).
    {"id": "fde-title",
     "query": "Forward Deployed Engineer roles",
     "role_label": "Forward Deployed Engineer",
     "rank": 1, "verbatim": True, "enabled": True},
    {"id": "healthcare-ai",
     "query": "Senior or Staff AI Engineer at a healthcare technology company building LLM agents "
              "on claims, payer contract or price transparency data",
     "role_label": "Senior AI Engineer healthcare",
     "rank": 2, "verbatim": True, "enabled": True},
    {"id": "staff-ai-platform-evals",
     "query": "Staff AI Platform Engineer owning LLM infrastructure: evaluation, observability, "
              "guardrails and cost controls for agents in production",
     "role_label": "Staff AI Platform Engineer",
     "rank": 3, "verbatim": True, "enabled": True},
    {"id": "senior-applied-ai",
     "query": "Senior Applied AI Engineer building production LLM agents with tool calling, RAG "
              "and evals in Python and TypeScript",
     "role_label": "Senior Applied AI Engineer",
     "rank": 4, "verbatim": True, "enabled": True},
    {"id": "staff-principal-agent-platform",
     "query": "Staff or Principal Software Engineer building an AI agent platform: agent runtime, "
              "tool calling, evals, guardrails and multi-tenant infrastructure",
     "role_label": "Staff Software Engineer AI agent platform",
     "rank": 5, "verbatim": True, "enabled": True},
    # Older prompts below run after the ranked five, in the previous role-priority order.
    {"id": "forward-deployed-engineer",
     "query": "Find Forward Deployed Engineer (FDE), Forward-Deployed Software Engineer, "
              "and Forward Deployed AI Engineer roles focused on customer-facing implementation, "
              "production AI deployments, technical integrations, and hands-on software engineering",
     "role_label": "Forward Deployed Engineer",
     "enabled": True},  # Uses switch_number from config/search.py.
    {"id": "ai-engineer",
     "query": "Find AI Engineer, Artificial Intelligence Engineer, Applied AI Engineer, "
              "Generative AI Engineer (GenAI), LLM Engineer, AI/ML Engineer, "
              "AI Software Engineer, AI Application Engineer, AI Product Engineer, "
              "Agentic AI Engineer, AI Agent Engineer, and AI Platform Engineer roles. "
              "Focus on hands-on software engineering for production AI applications, "
              "large language models, retrieval-augmented generation (RAG), semantic search, "
              "embeddings, vector databases, AI agents, multi-agent orchestration, tool calling, "
              "MCP, prompt and context engineering, fine-tuning, model evaluation, "
              "inference, AI APIs, deployment, LLMOps, and observability",
     "role_label": "AI Engineer",
     "enabled": True},  # Broad AI lane follows FDE, ahead of leveled searches.
    {"id": "senior-engineer",
     "query": "Find Senior Software Engineer, Senior Software Development Engineer, "
              "Senior Backend Engineer, Senior Platform Engineer, "
              "Senior Infrastructure Engineer, Senior Systems Engineer, "
              "Senior Site Reliability Engineer, Senior AI Engineer, "
              "Senior AI Platform Engineer, Senior Applied AI Engineer, "
              "Senior Machine Learning Engineer, Senior MLOps Engineer, "
              "Senior LLM Engineer, and Senior Generative AI Engineer roles. "
              "Hands-on design and operation of production AI and backend systems: "
              "large language models, agents and multi-agent orchestration, "
              "retrieval-augmented generation (RAG), embeddings and vector search, "
              "distributed systems, APIs and service design, Kubernetes and containers, "
              "observability, SLOs, incident response, and CI/CD",
     "role_label": "Senior Software Engineer",
     "enabled": True},  # Senior band: follows the two pinned lanes, ahead of staff/principal.
    # Previous first prompt retained for future reuse; set enabled=True to restore.
    {"id": "staff-ai-platform", "query": "Staff AI Platform Engineer",
     "enabled": False, "quota": 1},
]

# Resume the latest unfinished run with the same configuration automatically.
# Set False to start a new run; successful jobs are still skipped via CSV history.
resume_search_enabled = True
search_state_dir = "logs/search_runs"
