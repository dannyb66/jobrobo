import os
import requests
from dotenv import load_dotenv

CLOUD_FUNCTION_URL = "https://us-central1-gen-lang-client-0786628200.cloudfunctions.net/get_openai_key"
AUTH_TOKEN = "your-strong-shared-secret"  # You can choose to load this from env too

def load_openai_key():
    """
    Prefer an existing environment key, then local .env, then the cloud fallback.
    Return True only when a key was loaded from the cloud (legacy contract).
    """
    if os.environ.get('OPENAI_API_KEY', '').strip():
        print('🔄 Using OPENAI_API_KEY from environment')
        return False
    load_dotenv(override=False)
    if os.environ.get('OPENAI_API_KEY', '').strip():
        print('🔄 Loaded OPENAI_API_KEY from local .env')
        return False
    try:
        headers = {
            "Authorization": f"Bearer {AUTH_TOKEN}"
        }
        response = requests.get(CLOUD_FUNCTION_URL, headers=headers, timeout=5)
        if response.status_code == 200:
            key = response.json().get("openai_key")
            if isinstance(key, str) and key.strip():
                os.environ["OPENAI_API_KEY"] = key.strip()
                print("✅ Loaded OPENAI_API_KEY from cloud function")
                return True
            else:
                print("⚠️ Cloud function response missing key")
        else:
            print(f"⚠️ Cloud key service returned status {response.status_code}; no key loaded")
    except Exception as e:
        print(f"⚠️ Cloud key service unavailable ({type(e).__name__})")

    print("⚠️ No OPENAI_API_KEY configured in the environment, local .env or cloud fallback")
    return False
