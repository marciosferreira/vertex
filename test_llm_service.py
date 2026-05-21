"""
Testa conexão com Gemini via google-genai (padrão LLMService),
usando credentials.json local, sem importar nada do projeto.
"""
from google.oauth2 import service_account
from google import genai
from google.genai import types

CREDENTIALS_FILE = "credentials.json"
PROJECT_ID = "dataservices-non-prod"
LOCATION = "us-central1"
MODEL = "gemini-2.0-flash-001"

credentials = service_account.Credentials.from_service_account_file(
    CREDENTIALS_FILE,
    scopes=["https://www.googleapis.com/auth/cloud-platform"],
)

client = genai.Client(
    vertexai=True,
    project=PROJECT_ID,
    location=LOCATION,
    credentials=credentials,
)

config = types.GenerateContentConfig(
    system_instruction="Você é um assistente útil.",
    temperature=0.0,
    max_output_tokens=64,
    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
)

print(f"Chamando {MODEL} via Vertex AI...")
response = client.models.generate_content(
    model=MODEL,
    contents=[types.Part.from_text(text="Diga olá em português.")],
    config=config,
)

text = getattr(response, "text", None) or ""
print(f"Resposta: {text.strip()}")
