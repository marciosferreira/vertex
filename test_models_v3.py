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
        "imageclassification-efficientnet",
        "occupancy-analytics",
        "multimodalembedding",
        "pt-test",
        "imageclassification-vit",
        "bert-base",
        "vehicle-detector",
        "language-v1-classify-text-v1",
        "language-v1-analyze-sentiment",
        "language-v1-analyze-entity-sentiment",
        "language-v1-analyze-syntax",
        "resnet50",
        "imagesegmentation-deeplabv3",
        "imageobjectdetection-yolo",
        "owlvit-base-patch32",
        "object-detector",
        "ppe-detector",
        "people-blur",
        "product-recognizer",
        "tag-recognizer",
        "imageclassification-proprietary-vit",
        "imageobjectdetection-proprietary-spinenet",
        "imageclassification-proprietary-efficientnet",
        "t5-flan",
        "t5-1.1",
        "textembedding-gecko",
        "imagegeneration",
        "automl-e2e",
        "content-moderation",
        "pretrained-ocr",
        "face-detector",
        "pretrained-form-parser",
        "label-detector-pali-001",
        "tab-net",
        "text-detector",
        "imagewatermarkdetector",
        "imagetext",
        "language-v1-moderate-text",
        "text-translation",
        "bart-large-cnn",
        "vit-jax",
        "pic2word",
        "imageobjectdetection-proprietary-yolo",
        "imageclassification-proprietary-maxvit",
        "bert-base-uncased",
        "tfvision-yolov7",
        "tfvision-movinet-vcn",
        "chirp-2",
        "f-vlm-jax",
        "keras-yolov8",
        "automl-vision-image-classification",
        "automl-vision-image-object-detection",
        "cxr-foundation",
        "tfvision-movinet-var",
        "dito",
        "jax-owl-vit-v2",
        "cloudnerf-pytorch-zipnerf",
        "functiongemma",
        "gemma",
        "paligemma",
        "codegemma",
        "text-multilingual-embedding-002",
        "text-embedding-005",
        "mammut",
        "translategemma",
        "gemma3n",
        "chirp-3",
        "imagen-3.0-generate-002",
        "imagen-4.0-generate-001",
        "imagen-4.0-fast-generate-001",
        "imagen-4.0-ultra-generate-001",
        "imagen-3.0-capability-001",
        "imagen-3.0-capability-002",
        "timesfm",
        "gemma2",
        "translate-llm",
        "video-text-detection",
        "video-speech-transcription",
        "path-foundation",
        "derm-foundation",
        "txgemma",
        "hear",
        "medgemma",
        "medsiglip",
        "medasr",
        "gemma4",
        "image-segmentation-001",
        "gemma3",
        "shieldgemma2",
        "lyria-3-pro-preview",
        "lyria-3-clip-preview",
        "veo-2.0-generate-001",
        "gemini-2.0-flash-001",
        "text-embedding-large-exp-03-07",
        "gemini-embedding-001",
        "gemini-2.0-flash-lite-001",
        "weathernext",
        "lyria-002",
        "gemini-2.5-pro",
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "t5gemma",
        "veo-3.0-generate-001",
        "veo-3.0-fast-generate-001",
        "gemini-2.5-computer-use-preview-10-2025",
        "embeddinggemma",
        "gemini-2.5-flash-preview-09-2025",
        "gemini-2.5-flash-lite-preview-09-2025",
        "gemini-2.5-flash-image",
        "gemini-2.5-pro-tts",
        "gemini-2.5-flash-tts",
        "earth-ai-imagery-owlvit-eap-10-2025",
        "earth-ai-imagery-mammut-eap-10-2025",
        "gemini-3-pro-preview",
        "gemini-3-pro-image-preview",
        "gemini-live-2.5-flash-native-audio",
        "veo-3.1-generate-001",
        "veo-3.1-fast-generate-001",
        "weather-next-v2",
        "gemini-3-flash-preview",
        "virtual-try-on-001",
        "gemini-3.1-flash-lite-preview",
        "gemini-3.1-flash-image-preview",
        "gemini-3.1-pro-preview",
        "gemini-3.5-flash",
        "veo-3.1-lite-generate-001",
        "gemini-3.1-flash-tts-preview",
        "gemma-4-26b-a4b-it-maas",
        "gemini-embedding-2",
        "gemini-3.1-flash-lite",
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
