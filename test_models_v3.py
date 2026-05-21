"""
Testa quais modelos da família Gemini 3.x estão disponíveis no Vertex AI.
Faz uma chamada generateContent simples em cada candidato e reporta o resultado.
"""
import json
import urllib.request
import urllib.error
from google.oauth2 import service_account
import google.auth.transport.requests

CREDENTIALS_FILE = "credentials.json"
PROJECT_ID = "dataservices-non-prod"
REGION = "us-central1"

credentials = service_account.Credentials.from_service_account_file(
    CREDENTIALS_FILE,
    scopes=["https://www.googleapis.com/auth/cloud-platform"],
)
credentials.refresh(google.auth.transport.requests.Request())
token = credentials.token

# Candidatos da família 3.x (listados pelo Model Garden)
CANDIDATES = [
    "gemini-3-flash-preview",
    "gemini-3-pro-image-preview",
    "gemini-3-pro-preview",
    "gemini-3.1-flash-image-preview",
    "gemini-3.1-flash-lite",
    "gemini-3.1-flash-lite-preview",
    "gemini-3.1-flash-tts-preview",
    "gemini-3.1-pro-preview",
    "gemini-3.5-flash",
]

PAYLOAD = json.dumps({
    "contents": [{"role": "user", "parts": [{"text": "Hi"}]}],
    "generationConfig": {"maxOutputTokens": 5},
}).encode()


def test_model(model_id: str) -> tuple[bool, str]:
    url = (
        f"https://{REGION}-aiplatform.googleapis.com/v1"
        f"/projects/{PROJECT_ID}/locations/{REGION}"
        f"/publishers/google/models/{model_id}:generateContent"
    )
    req = urllib.request.Request(
        url,
        data=PAYLOAD,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = json.loads(resp.read())
            text = body["candidates"][0]["content"]["parts"][0].get("text", "")
            return True, f'resposta: "{text.strip()}"'
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        try:
            msg = json.loads(body)["error"]["message"]
        except Exception:
            msg = body[:120]
        return False, f"HTTP {e.code} — {msg}"
    except Exception as e:
        return False, str(e)


print(f"{'MODELO':<40} {'STATUS':<10} DETALHE")
print("-" * 100)

available = []
for model in CANDIDATES:
    ok, detail = test_model(model)
    status = "OK" if ok else "ERRO"
    print(f"{model:<40} {status:<10} {detail}")
    if ok:
        available.append(model)

print()
print("=" * 100)
if available:
    print(f"Modelos disponíveis ({len(available)}):")
    for m in available:
        print(f"  {m}")
else:
    print("Nenhum modelo da linha 3.x retornou sucesso.")
