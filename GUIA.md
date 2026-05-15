# MFG Control — Guia de Instalação e Uso

## Estrutura do projeto

```
mfg-control/
├── mfg-dashboard.html   ← Dashboard (abre no navegador)
└── api/
    └── main.py          ← Backend FastAPI
```

---

## 1. Rodar o backend (FastAPI)

### Pré-requisitos
- Python 3.10 ou superior

### Instalação

```bash
# Entre na pasta da API
cd api

# (Recomendado) Crie um ambiente virtual
python -m venv venv
source venv/bin/activate        # Linux/Mac
venv\Scripts\activate           # Windows

# Instale as dependências
pip install fastapi uvicorn
```

### Iniciar o servidor

```bash
uvicorn main:app --reload
```

O servidor sobe em: **http://localhost:8000**

### Documentação automática

FastAPI gera docs interativas automaticamente:

| URL | Descrição |
|-----|-----------|
| http://localhost:8000/docs | Swagger UI — teste os endpoints |
| http://localhost:8000/redoc | ReDoc — documentação legível |

---

## 2. Abrir o dashboard

Com o servidor rodando, abra o arquivo `mfg-dashboard.html` diretamente no navegador.

> **Importante:** o dashboard faz requisições para `http://localhost:8000`.
> Se sua API estiver em outro endereço, edite a linha no topo do HTML:
> ```js
> const API_BASE = 'http://localhost:8000'; // ← altere aqui
> ```

---

## 3. Endpoints da API

| Método | Endpoint | Parâmetros | Descrição |
|--------|----------|-----------|-----------|
| GET | `/kpis` | `shift=A\|B\|C` | KPIs do turno |
| GET | `/production/hourly` | `shift=A\|B\|C` | Produção hora a hora |
| GET | `/production/historical` | `range=7d\|14d\|30d\|shift` | Histórico para gráficos |
| GET | `/lines/status` | — | Status das linhas |
| GET | `/alerts` | — | Alertas do turno |
| GET | `/defects` | `shift=A\|B\|C` | Defeitos por categoria |

---

## 4. Conectar ao banco de dados real

Os dados mocados estão nas listas no topo de `main.py` (ex: `BASE_DAILY_PRODUCTION`).
Para conectar ao banco real, instale o driver e substitua cada função.

### Exemplo com PostgreSQL (psycopg2 ou asyncpg)

```bash
pip install sqlalchemy psycopg2-binary
```

```python
# Em main.py, substitua a função get_kpis:

from sqlalchemy import create_engine, text

engine = create_engine("postgresql://usuario:senha@localhost/mfgdb")

@app.get("/kpis")
def get_kpis(shift: str = "A"):
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM kpis_view WHERE shift = :shift"),
            {"shift": shift}
        ).fetchone()
    return dict(row._mapping)
```

### Exemplo com MySQL

```bash
pip install sqlalchemy pymysql
```

```python
engine = create_engine("mysql+pymysql://usuario:senha@localhost/mfgdb")
```

### Exemplo com SQL Server

```bash
pip install sqlalchemy pyodbc
```

```python
engine = create_engine(
    "mssql+pyodbc://usuario:senha@servidor/mfgdb?driver=ODBC+Driver+17+for+SQL+Server"
)
```

---

## 5. Estrutura esperada dos dados

### `/kpis`
```json
{
  "shift": "A",
  "total_produced": 3847,
  "daily_target": 4800,
  "first_pass_yield": 94.2,
  "defect_rate": 2.3,
  "downtime_minutes": 38,
  "efficiency": 87.6,
  "scrapped": 88,
  "reworked": 145,
  "cycle_time_seconds": 42.3,
  "oee": 81.4
}
```

### `/production/historical` (um item da lista)
```json
{
  "label": "Seg",
  "produced": 3720,
  "defects": 88,
  "target": 4800,
  "fpy": 93.4,
  "oee": 80.1,
  "availability": 91.2,
  "performance": 87.6,
  "line1": 1050,
  "line2": 920,
  "line3": 880,
  "line4": 870,
  "shift_a_efficiency": 89,
  "shift_b_efficiency": 85,
  "shift_c_efficiency": 79,
  "defect_screen": 28,
  "defect_camera": 18,
  "defect_battery": 15,
  "defect_other": 12
}
```

### `/lines/status` (um item)
```json
{
  "id": 1,
  "name": "Linha 1",
  "model": "PhoneX Pro",
  "status": "running",
  "produced": 1124,
  "target": 1200,
  "fpy": 95.8,
  "speed_pct": 98,
  "operator": "Carlos Mendes"
}
```

### `/alerts` (um item)
```json
{
  "id": 1,
  "severity": "critical",
  "time": "14:18",
  "line": "Linha 3",
  "message": "Parada não planejada — sensor de conveyor com falha",
  "acknowledged": false
}
```

### `/defects` (um item)
```json
{
  "category": "Tela (display)",
  "count": 34,
  "percentage": 28.8
}
```

---

## 6. Deploy em produção

### Com Nginx (recomendado)

```bash
# Instale gunicorn
pip install gunicorn

# Rode com múltiplos workers
gunicorn main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
```

Configure o Nginx para fazer proxy reverso e servir o HTML estático:

```nginx
server {
    listen 80;
    server_name seu-dominio.com;

    # Serve o dashboard HTML
    location / {
        root /var/www/mfg-control;
        try_files $uri $uri/ /index.html;
    }

    # Proxy para a API FastAPI
    location /api/ {
        proxy_pass http://127.0.0.1:8000/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

> Se usar proxy reverso com prefixo `/api/`, lembre de alterar no HTML:
> ```js
> const API_BASE = '/api';
> ```

---

## 7. Atualização em tempo real (opcional)

O dashboard já atualiza automaticamente a cada **30 segundos** via polling.
Para tempo real verdadeiro (ex: via WebSocket), adicione ao `main.py`:

```bash
pip install websockets
```

```python
from fastapi import WebSocket
import asyncio

@app.websocket("/ws/live")
async def websocket_live(websocket: WebSocket):
    await websocket.accept()
    while True:
        data = get_kpis("A")  # ou busque do banco
        await websocket.send_json(data)
        await asyncio.sleep(5)  # envia a cada 5 segundos
```

E no dashboard HTML, substitua o `setInterval` por:
```js
const ws = new WebSocket('ws://localhost:8000/ws/live');
ws.onmessage = (event) => {
    appData.kpis = JSON.parse(event.data);
    renderKPIs();
};
```
