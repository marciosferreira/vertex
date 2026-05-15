from vertexai.generative_models import GenerationConfig, GenerativeModel
from dotenv import load_dotenv
import vertexai
import os
import json
import pandas as pd
from datetime import datetime

def get_env_var(name: str, required: bool = True) -> str:
    value = os.getenv(name)
    if required and not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value

def main():
    load_dotenv()
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = f"{os.getcwd()}\\credentials.json"

    vertexai.init(project = get_env_var("PROJECT_ID"), location = get_env_var("LOCATION"))

    model = GenerativeModel(
        get_env_var("MODEL_NAME"),
        generation_config = GenerationConfig(
            temperature = 0.0,
            top_p = 0.95,
            top_k = 20,
            response_mime_type = "application/json"
        )
    )

    response = model.generate_content(["ola chat, tudo bem?"])
    print(response.text)

if __name__ == "__main__":
    main()