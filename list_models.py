import json
import urllib.request
import urllib.parse
from google.oauth2 import service_account
import google.auth.transport.requests

CREDENTIALS_FILE = "credentials.json"
PROJECT_ID = "dataservices-non-prod"
REGION = "us-central1"

with open(CREDENTIALS_FILE) as f:
    creds_data = json.load(f)

credentials = service_account.Credentials.from_service_account_info(
    creds_data,
    scopes=["https://www.googleapis.com/auth/cloud-platform"],
)
credentials.refresh(google.auth.transport.requests.Request())
token = credentials.token

def get(url):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read()), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.reason}"
    except Exception as e:
        return None, str(e)

# ── 1. Vertex AI Model Garden (publisher models) ──────────────────────────────
print("=" * 65)
print("1. VERTEX AI MODEL GARDEN — modelos Gemini/etc disponíveis")
print("=" * 65)
url = (f"https://{REGION}-aiplatform.googleapis.com/v1beta1"
       f"/projects/{PROJECT_ID}/locations/{REGION}/publishers/google/models")
data, err = get(url)
if data and "publisherModels" in data:
    for m in data["publisherModels"]:
        short = m.get("name", "").split("/")[-1]
        title = m.get("title", "")
        print(f"  {short:<50} {title}")
    print(f"\nTotal: {len(data['publisherModels'])} modelos")
elif err:
    url2 = f"https://{REGION}-aiplatform.googleapis.com/v1beta1/publishers/google/models"
    data2, err2 = get(url2)
    if data2 and "publisherModels" in data2:
        for m in data2["publisherModels"]:
            short = m.get("name", "").split("/")[-1]
            title = m.get("title", "")
            print(f"  {short:<50} {title}")
        print(f"\nTotal: {len(data2['publisherModels'])} modelos")
    else:
        print(f"Erro: {err2 or err}")
else:
    print(json.dumps(data or {}, indent=2)[:500])

# ── 2. Speech-to-Text v2 — modelos STT (Chirp, etc) ──────────────────────────
print()
print("=" * 65)
print("2. SPEECH-TO-TEXT v2 — modelos STT disponíveis")
print("=" * 65)
url = f"https://speech.googleapis.com/v2/projects/{PROJECT_ID}/locations/{REGION}/recognizers"
data, err = get(url)
if data:
    recognizers = data.get("recognizers", [])
    if recognizers:
        for r in recognizers:
            name = r.get("name", "").split("/")[-1]
            model = r.get("model", "?")
            state = r.get("state", "")
            print(f"  recognizer={name}  model={model}  state={state}")
    else:
        print("  Nenhum recognizer custom criado.")
elif err:
    print(f"  Erro: {err}")

print()
print("  Modelos STT globais disponíveis via Speech v2:")
url_global = f"https://speech.googleapis.com/v2/projects/{PROJECT_ID}/locations/global/recognizers"
data_g, err_g = get(url_global)
if err_g:
    print(f"  Erro: {err_g}")

# STT known models (hardcoded pois API não expõe lista de base models)
stt_models = [
    ("chirp",              "Multilingual, streaming, long-form audio"),
    ("chirp_2",            "Melhorado, baixa latência, multilingual"),
    ("latest_long",        "Long audio, batch, pt-BR suportado"),
    ("latest_short",       "Short utterances, latência baixa"),
    ("telephony",          "Áudio de telefone 8kHz"),
    ("medical_dictation",  "Domínio médico"),
    ("medical_conversation","Conversa médica"),
]
print()
print("  Modelos base STT (Google Speech v2 — referência):")
for name, desc in stt_models:
    print(f"    {name:<30} {desc}")
