"""Optional search refinement using the existing OpenAI connection configuration."""

import json


def refine_queries(client, model, roles, skills, snapshot):
    response = client.chat.completions.create(
        model=model, stream=False, response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": (
                "Suggest distinct job role query lanes and rank by profile coverage. "
                "Expand title variants, remove redundancy, and preserve each role's seniority and specialty. "
                "Return only JSON: {\"queries\": [{\"role\": \"role title only\", "
                "\"role_index\": 0, \"coverage\": 0.9}]}. "
                "role_index is zero-based into the supplied roles. Cover every index at least once; "
                f"return at most two variants per role and {min(48, len(roles) * 2)} total. Coverage is between 0 and 1. "
                "Never add filters, exclusions, locations, URLs, IDs, quotas, or instructions to role titles."
            )},
            {"role": "user", "content": json.dumps({"roles": roles, "skills": skills, "filters": snapshot})},
        ],
    )
    return json.loads(response.choices[0].message.content)


def make_refiner(key, base_url, model, warn=lambda message: None):
    if not key or not key.strip() or key.strip().lower() in {"your_api_key", "your-openai-api-key", "not-needed"}:
        warn("No OpenAI key available for search refinement; continuing deterministically.")
        return None

    def refine(roles, skills, snapshot):
        from openai import OpenAI
        # Separate client and bounded timeout: independent of resume AI and use_AI.
        with OpenAI(api_key=key, base_url=base_url or None, timeout=20, max_retries=0) as client:
            return refine_queries(client, model, roles, skills, snapshot)

    return refine
