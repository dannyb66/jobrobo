###################################################### CONFIGURE YOUR TOOLS HERE ######################################################


# Login Credentials for LinkedIn (Optional)
username = "deepakbasavaraju7@gmail.com"       # Enter your username in the quotes
password = "Adarsh*11"           # Enter your password in the quotes


## Artificial Intelligence (Beta Not-Recommended)
# Use AI
use_AI = False                          # True or False, Note: True or False are case-sensitive
# Use AI for optimizing resume
use_AI_for_resume = True               # True or False, Note: True or False are case-sensitive. OPENAI API KEY is required for this feature.
'''
Note: Set it as True only if you want to use AI, and If you either have a
1. Local LLM model running on your local machine, with it's APIs exposed. Example softwares to achieve it are:
    a. Ollama - https://ollama.com/
    b. llama.cpp - https://github.com/ggerganov/llama.cpp
    c. LM Studio - https://lmstudio.ai/ (Recommended)
    d. Jan - https://jan.ai/
2. OR you have a valid OpenAI API Key, and money to spare, and you don't mind spending it.
CHECK THE OPENAI API PIRCES AT THEIR WEBSITE (https://openai.com/api/pricing/). 
'''

# Your Local LLM url or other AI api url and port
llm_api_url = "https://api.openai.com/v1/"       # Examples: "https://api.openai.com/v1/", "http://127.0.0.1:1234/v1/", "http://localhost:1234/v1/"
'''
Note: Don't forget to add / at the end of your url
'''

# Your Local LLM API key or other AI API key 
llm_api_key = ""              # Enter your API key in the quotes, make sure it's valid, if not will result in error.
'''
Note: Leave it empyt as "" or "not-needed" if not needed. Else will result in error!
'''

# Your local LLM model name or other AI model name
llm_model = "gpt-4o-mini"          # Examples: "gpt-3.5-turbo", "gpt-4o", "llama-3.2-3b-instruct"


#
llm_spec = "openai"                # Examples: "openai", "openai-like", "openai-like-github", "openai-like-mistral"
'''
Note: Currently "openai" and "openai-like" api endpoints are supported.
'''

# # Yor local embedding model name or other AI Embedding model name
# llm_embedding_model = "nomic-embed-text-v1.5"

# Do you want to stream AI output?
stream_output = True                    # Examples: True or False. (False is recommended for performance, True is recommended for user experience!)
'''
Set `stream_output = True` if you want to stream AI output or `stream_output = False` if not.
'''
##

## Twitter bot (Beta Not-Recommended)
# Twitter bot
twitter_bot = False                     # True or False, Note: True or False are case-sensitive
'''
Note: Set it as True only if you want to use Twitter bot
'''

# Twitter bot Client credentials
twitter_client_id = "c0s1QjdRR05zN3NDaTV4a3E4MWo6MTpjaQ"       # Enter your client id in the quotes
twitter_client_secret = "jy1vWF08azRBU48k2gEcXMoSDzMIdTuEhlL6ke2Thw-N-dD-4Q"       # Enter your client secret in the quotes
'''
Note: Set it as "" if you don't want to use Twitter bot
Note: Twitter bot is not recommended as it is not stable and may result in errors.
'''
