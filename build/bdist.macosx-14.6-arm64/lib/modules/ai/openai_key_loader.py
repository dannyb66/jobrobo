import os
import requests
from dotenv import load_dotenv

CLOUD_FUNCTION_URL = "https://us-central1-gen-lang-client-0786628200.cloudfunctions.net/get_openai_key"
AUTH_TOKEN = "your-strong-shared-secret"  # You can choose to load this from env too

def load_openai_key():
    """
    Tries to fetch the OpenAI key from a cloud function.
    Falls back to loading from .env if the request fails.
    Sets os.environ["OPENAI_API_KEY"].
    Returns True if key was loaded from cloud, False if from .env.
    """
    try:
        headers = {
            "Authorization": f"Bearer {AUTH_TOKEN}"
        }
        response = requests.get(CLOUD_FUNCTION_URL, headers=headers, timeout=5)
        if response.status_code == 200:
            key = response.json().get("openai_key")
            if key:
                os.environ["OPENAI_API_KEY"] = key
                print("✅ Loaded OPENAI_API_KEY from cloud function")
                return True
            else:
                print("⚠️ Cloud function response missing key")
        else:
            print(f"⚠️ Cloud function returned status {response.status_code}: {response.text}")
    except Exception as e:
        print(f"⚠️ Exception while fetching key from cloud: {e}")

    load_dotenv()
    print("🔄 Loaded OPENAI_API_KEY from local .env")
    return False