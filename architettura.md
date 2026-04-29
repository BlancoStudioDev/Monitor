# News Impact Scoring — Architettura Python del Sistema

> Un monorepo uv workspace con sei pacchetti Python che implementa la pipeline completa: raccolta notizie → deduplicazione → classificazione LLM → scoring deterministico → API REST.

---

## 1. Struttura del progetto

Il sistema segue un layout `src/` con ogni componente come pacchetto Python separato, gestito da un **uv workspace** che fornisce un singolo lockfile e installazioni editabili automatiche tra i membri.

```
news-impact-scorer/
├── pyproject.toml                          # Workspace root (virtuale)
├── uv.lock                                 # Singolo lockfile
├── README.md
├── config/
│   ├── settings.toml                       # Configurazione globale
│   ├── sector_sensitivity.json             # Matrice settore × tipo-evento
│   ├── country_risk.json                   # Score rischio paese (da Damodaran)
│   ├── persistence_map.json                # Tipo evento → stime di persistenza
│   └── prompts/
│       └── classify_event_v1.txt           # Template prompt versionati
│
├── packages/
│   ├── shared-models/                      # Modelli Pydantic condivisi
│   ├── news-collector/                     # Raccolta notizie multi-sorgente
│   ├── news-deduplicator/                  # Deduplicazione e clustering
│   ├── event-classifier/                   # Classificazione LLM deterministica
│   ├── impact-scorer/                      # Pipeline di scoring
│   └── api/                                # FastAPI endpoints
│
└── tests/
    ├── test_collector/
    ├── test_deduplicator/
    ├── test_classifier/
    ├── test_scorer/
    └── test_api/
```

### Dettaglio dei pacchetti

#### `shared-models/` — Contratti di tipo della pipeline

```
shared_models/
├── __init__.py
├── news_item.py            # Modello NewsItem
├── event.py                # Modello Event (articoli raggruppati)
├── classified_event.py     # Modello ClassifiedEvent
├── impact_score.py         # ImpactScore + ScoringBreakdown
├── enums.py                # GICSSector, EventCategory, PESTLEDimension
└── config.py               # Modello Settings
```

#### `news-collector/` — Raccolta da fonti multiple

```
news_collector/
├── __init__.py
├── base.py                 # NewsSource ABC
├── rss_source.py           # RSSNewsSource (BBC, AP)
├── gdelt_source.py         # GDELTNewsSource
├── newsapi_source.py       # NewsAPISource
├── collector.py            # Orchestratore: esegue tutte le fonti
└── feed_config.py          # URL RSS, endpoint API
```

#### `news-deduplicator/` — Deduplicazione ibrida

```
news_deduplicator/
├── __init__.py
├── base.py                 # Deduplicator ABC
├── tfidf_dedup.py          # TF-IDF + similarità coseno
├── minhash_dedup.py        # MinHash/LSH (datasketch)
├── clustering.py           # Clusterizzazione articoli → Eventi
└── merger.py               # Merge articoli clusterizzati in Event
```

#### `event-classifier/` — Classificazione LLM deterministica

```
event_classifier/
├── __init__.py
├── base.py                 # Classifier ABC
├── llm_classifier.py       # Classificatore via Claude API
├── prompt_manager.py       # Caricamento prompt versionati
├── cache.py                # Cache di determinismo (hash input → output)
└── schemas.py              # Schemi output classificazione
```

#### `impact-scorer/` — Pipeline di scoring

```
impact_scorer/
├── __init__.py
├── base.py                 # Scorer ABC
├── scorer.py               # Pipeline di scoring principale
├── severity.py             # Calcolo severità base
├── sector_sensitivity.py   # Lookup matrice sensitività settoriale
├── country_risk.py         # Calcolo score rischio paese
├── context.py              # Moltiplicatore di contesto EPU/GPR
├── persistence.py          # Stima della durata
├── transmission.py         # Spillover modello IO (opzionale)
└── explainer.py            # Spiegazioni leggibili degli score
```

#### `api/` — Interfaccia REST FastAPI

```
api/
├── __init__.py
├── main.py                 # Factory dell'app FastAPI
├── routes/
│   ├── __init__.py
│   ├── collect.py          # POST /collect
│   ├── events.py           # GET /events, GET /events/{id}
│   ├── scores.py           # GET /scores/sector/{s}, /scores/country/{c}
│   └── health.py           # GET /health
├── dependencies.py         # Dependency Injection condivisa
├── storage.py              # Layer di persistenza SQLite/DuckDB
└── pipeline.py             # Pipeline completa collect→dedup→classify→score
```

---

## 2. Configurazione workspace e pacchetti

### Root `pyproject.toml` (workspace virtuale — nessuna tabella `[project]`)

```toml
[tool.uv.workspace]
members = ["packages/*"]

[tool.uv]
dev-dependencies = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "httpx>=0.27",
    "ruff>=0.8",
]
```

### Dipendenze per pacchetto

| Pacchetto | Dipendenze principali |
|---|---|
| **shared-models** | `pydantic>=2.6` |
| **news-collector** | `shared-models`, `httpx>=0.27`, `feedparser>=6.0` |
| **news-deduplicator** | `shared-models`, `scikit-learn>=1.4`, `datasketch>=1.6` |
| **event-classifier** | `shared-models`, `anthropic>=0.42` |
| **impact-scorer** | `shared-models`, `numpy>=1.26` |
| **api** | tutti i pacchetti precedenti + `fastapi>=0.115`, `uvicorn[standard]>=0.32`, `aiosqlite>=0.20` |

### Risoluzione delle dipendenze tra pacchetti

Le dipendenze tra membri del workspace sono **editabili di default** in uv — la direttiva `{ workspace = true }` risolve dal workspace locale anziché da PyPI.

```toml
# Esempio: packages/news-collector/pyproject.toml
[project]
name = "news-collector"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "shared-models",
    "httpx>=0.27",
    "feedparser>=6.0",
]

[tool.uv.sources]
shared-models = { workspace = true }

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

Per installare l'intera catena di dipendenze:

```bash
uv sync --package api
```

---

## 3. Modelli dati — I contratti di tipo della pipeline

### Enumerazioni (`shared_models/enums.py`)

```python
from enum import StrEnum

class GICSSector(StrEnum):
    ENERGY = "Energy"
    MATERIALS = "Materials"
    INDUSTRIALS = "Industrials"
    CONSUMER_DISCRETIONARY = "Consumer Discretionary"
    CONSUMER_STAPLES = "Consumer Staples"
    HEALTH_CARE = "Health Care"
    FINANCIALS = "Financials"
    INFORMATION_TECHNOLOGY = "Information Technology"
    COMMUNICATION_SERVICES = "Communication Services"
    UTILITIES = "Utilities"
    REAL_ESTATE = "Real Estate"

class EventCategory(StrEnum):
    TRADE_POLICY = "trade_policy"
    MONETARY_POLICY = "monetary_policy"
    FISCAL_POLICY = "fiscal_policy"
    REGULATORY_CHANGE = "regulatory_change"
    GEOPOLITICAL_CONFLICT = "geopolitical_conflict"
    SANCTIONS = "sanctions"
    SUPPLY_CHAIN = "supply_chain_disruption"
    PANDEMIC_HEALTH = "pandemic_health"
    NATURAL_DISASTER = "natural_disaster"
    CORPORATE_EVENT = "corporate_event"
    MARKET_SHOCK = "market_shock"
    TECHNOLOGY_DISRUPTION = "technology_disruption"
    LABOR_SOCIAL = "labor_social"
    ENVIRONMENTAL_CLIMATE = "environmental_climate"

class PESTLEDimension(StrEnum):
    POLITICAL = "Political"
    ECONOMIC = "Economic"
    SOCIAL = "Social"
    TECHNOLOGICAL = "Technological"
    LEGAL = "Legal"
    ENVIRONMENTAL = "Environmental"
```

### `NewsItem` — Singolo articolo raccolto (`shared_models/news_item.py`)

```python
from datetime import datetime
from pydantic import BaseModel, HttpUrl

class NewsItem(BaseModel):
    source_id: str                    # es. "bbc_rss", "gdelt", "newsapi"
    source_name: str                  # Nome leggibile della fonte
    title: str
    description: str | None = None
    content: str | None = None
    url: HttpUrl
    published_at: datetime
    language: str = "en"
    source_country: str | None = None
    image_url: HttpUrl | None = None
    raw_metadata: dict = {}           # Campi extra specifici della fonte
    fetched_at: datetime              # Quando il sistema l'ha recuperato
```

### `Event` — Articoli raggruppati/deduplicati (`shared_models/event.py`)

```python
from datetime import datetime
from pydantic import BaseModel, Field
import hashlib

class Event(BaseModel):
    event_id: str = Field(default_factory=lambda: "")
    primary_title: str                     # Miglior titolo dalle fonti
    description: str                       # Descrizione migliore/unificata
    articles: list[str]                    # Lista URL articoli sorgente
    source_count: int
    earliest_published: datetime
    latest_published: datetime
    countries_mentioned: list[str] = []    # ISO 3166-1 alpha-2
    avg_sentiment: float | None = None     # Da GDELT AvgTone o calcolato
    raw_articles: list[dict] = []          # Dict NewsItem completi

    def model_post_init(self, __context):
        if not self.event_id:
            content = f"{self.primary_title}:{self.earliest_published.isoformat()}"
            self.event_id = hashlib.sha256(content.encode()).hexdigest()[:16]
```

### `ClassifiedEvent` — Evento classificato dall'LLM (`shared_models/classified_event.py`)

```python
from pydantic import BaseModel, Field

class PESTLEScores(BaseModel):
    political: float = Field(ge=0, le=5)
    economic: float = Field(ge=0, le=5)
    social: float = Field(ge=0, le=5)
    technological: float = Field(ge=0, le=5)
    legal: float = Field(ge=0, le=5)
    environmental: float = Field(ge=0, le=5)
```

### `ImpactScore` — Risultato finale della pipeline (`shared_models/impact_score.py`)

```python
from datetime import datetime
from pydantic import BaseModel, Field

class ScoringBreakdown(BaseModel):
    base_severity: float
    sector_sensitivity: float
    context_multiplier: float
    geographic_factor: float
    persistence_factor: float
    contributing_factors: list[str]         # Spiegazioni leggibili

class SectorScore(BaseModel):
    score: float = Field(ge=0, le=10)
    confidence: float = Field(ge=0, le=1)
    breakdown: ScoringBreakdown

class CountryScore(BaseModel):
    score: float = Field(ge=0, le=10)
    confidence: float = Field(ge=0, le=1)
    country_risk_premium: float
    vulnerability_factor: float

class ImpactScore(BaseModel):
    event_id: str
    timestamp: datetime
    event_category: str
    base_severity: float
    affected_sectors: dict[str, SectorScore]
    affected_countries: dict[str, CountryScore]
    global_score: float = Field(ge=0, le=10)
    persistence_estimate_days: int
    scoring_version: str
    sources: list[str]
```

---

## 4. Implementazione dei componenti — Pattern ad interfacce

### News Collector — Interfaccia astratta con tre implementazioni concrete

```python
# news_collector/base.py
from abc import ABC, abstractmethod
from datetime import datetime
from shared_models.news_item import NewsItem

class NewsSource(ABC):
    @abstractmethod
    async def fetch_items(self, since: datetime) -> list[NewsItem]: ...

    @property
    @abstractmethod
    def source_id(self) -> str: ...
```

#### Fonti concrete

| Fonte | Endpoint | Note |
|---|---|---|
| **BBC RSS** | `feeds.bbci.co.uk/news/world/rss.xml`, `/business/rss.xml`, `/technology/rss.xml` | Usa `feedparser` + `httpx` |
| **AP RSS** | `apnews.com/world-news.rss`, `/business.rss` | Usa `feedparser` + `httpx` |
| **GDELT** | `api.gdeltproject.org/api/v2/doc/doc?query=...&mode=artlist&format=json&maxrecords=250&timespan=1d&sort=datedesc` | Nessuna API key richiesta |
| **NewsAPI** | `newsapi.org/v2/everything` | Richiede header API key |

> **Nota:** Reuters ha dismesso gli RSS a giugno 2020 — usare le fonti GDELT o NewsAPI in alternativa.

### Deduplicator — Pipeline ibrida per velocità e accuratezza

```python
# news_deduplicator/base.py
from abc import ABC, abstractmethod
from shared_models import NewsItem, Event

class Deduplicator(ABC):
    @abstractmethod
    def deduplicate(self, items: list[NewsItem]) -> list[Event]: ...
```

#### Pipeline a tre stadi

1. **Deduplicazione esatta** — hash SHA-256 del titolo normalizzato + URL
2. **Generazione candidati** — MinHash/LSH dalla libreria `datasketch` (soglia Jaccard 0.6, 128 permutazioni, 4-grammi di carattere) per recupero candidati in tempo sub-lineare
3. **Re-ranking** — similarità coseno TF-IDF sulle coppie candidate, filtraggio a soglia 0.8

I cluster di articoli simili vengono uniti in oggetti `Event`, selezionando la descrizione più lunga e il tempo di pubblicazione più vecchio.

### Event Classifier — Classificazione LLM deterministica via Claude API

```python
# event_classifier/llm_classifier.py
from anthropic import Anthropic
from shared_models import Event, ClassifiedEvent

class LLMClassifier:
    def __init__(self, prompt_version: str = "v1"):
        self.client = Anthropic()
        self.prompt_version = prompt_version
        self._cache: dict[str, ClassifiedEvent] = {}

    async def classify(self, event: Event) -> ClassifiedEvent:
        cache_key = hashlib.sha256(
            f"{event.event_id}:{self.prompt_version}".encode()
        ).hexdigest()

        if cache_key in self._cache:
            return self._cache[cache_key]

        response = self.client.messages.create(
            model="claude-sonnet-4-5-20250514",
            max_tokens=2048,
            temperature=0,
            messages=[{"role": "user", "content": self._build_prompt(event)}],
            output_config={
                "format": {
                    "type": "json_schema",
                    "schema": CLASSIFICATION_SCHEMA  # Forzato a livello di decodifica
                }
            },
        )

        result = ClassifiedEvent.model_validate_json(response.content[0].text)
        result.prompt_version = self.prompt_version
        self._cache[cache_key] = result
        return result
```

#### I quattro meccanismi di determinismo

| Meccanismo | Scopo |
|---|---|
| `temperature=0` | Elimina la casualità del campionamento |
| `output_config.format` con JSON schema | Usa decodifica vincolata, previene violazioni dello schema |
| Template prompt versionati (`config/prompts/classify_event_v1.txt`) | Garantisce lo stesso testo di prompt tra esecuzioni |
| Cache hash-input | Garantisce che input identici restituiscano output identici anche tra riavvii (persistere su SQLite) |

#### Template del prompt di classificazione

```
You are a financial news event classifier. Given a news event, output a JSON
classification with these fields:
- event_category: one of [trade_policy, monetary_policy, fiscal_policy,
  regulatory_change, geopolitical_conflict, sanctions, supply_chain_disruption,
  pandemic_health, natural_disaster, corporate_event, market_shock,
  technology_disruption, labor_social, environmental_climate]
- base_severity: float 0-10, calibrated as: 0-2 routine, 2-4 notable,
  4-6 significant, 6-8 major, 8-10 crisis-level
- affected_sectors: list of GICS sectors directly impacted
- affected_countries: list of ISO alpha-2 country codes
- pestle_scores: score 0-5 for each PESTLE dimension
- classification_confidence: your confidence 0-1
- reasoning: brief explanation of your classification logic
```

### Impact Scorer — La pipeline di scoring

```python
# impact_scorer/scorer.py
class ImpactScorer:
    def __init__(self, config_dir: Path):
        self.sector_matrix = load_json(config_dir / "sector_sensitivity.json")
        self.country_risk = load_json(config_dir / "country_risk.json")
        self.persistence_map = load_json(config_dir / "persistence_map.json")

    def score(self, event: ClassifiedEvent) -> ImpactScore:
        sector_scores = {}
        for sector in GICSSector:
            sensitivity = self.sector_matrix[event.event_category].get(sector, 0.5)
            context_mult = self._get_context_multiplier()
            geo_factor = self._geographic_factor(event.affected_countries, sector)
            persist = self._persistence_factor(event.event_category)

            raw = event.base_severity * sensitivity * context_mult * geo_factor
            normalized = min(10.0, raw * persist)
            confidence = self._compute_confidence(event, sector)

            sector_scores[sector] = SectorScore(
                score=round(normalized, 2),
                confidence=round(confidence, 2),
                breakdown=ScoringBreakdown(
                    base_severity=event.base_severity,
                    sector_sensitivity=sensitivity,
                    context_multiplier=context_mult,
                    geographic_factor=geo_factor,
                    persistence_factor=persist,
                    contributing_factors=self._explain(event, sector, sensitivity),
                ),
            )

        global_score = self._compute_global(event, sector_scores)
        persistence_days = self.persistence_map.get(event.event_category, 30)

        return ImpactScore(
            event_id=event.event_id,
            timestamp=datetime.utcnow(),
            event_category=event.event_category,
            base_severity=event.base_severity,
            affected_sectors=sector_scores,
            affected_countries=self._score_countries(event),
            global_score=global_score,
            persistence_estimate_days=persistence_days,
            scoring_version="1.0.0",
            sources=event.articles if hasattr(event, 'articles') else [],
        )
```

---

## 5. API REST — FastAPI con cinque endpoint

### Endpoint esposti

| Metodo | Endpoint | Descrizione |
|---|---|---|
| `POST` | `/collect` | Esegue la pipeline completa: raccogli → deduplica → classifica → score |
| `GET` | `/events` | Interroga eventi con score, con filtri opzionali |
| `GET` | `/events/{event_id}` | Dettaglio completo di un evento con breakdown |
| `GET` | `/scores/sector/{sector}` | Score recenti che impattano un dato settore GICS |
| `GET` | `/scores/country/{country_code}` | Score recenti che impattano un dato paese |

### Implementazione delle route

```python
# api/routes/collect.py
@router.post("/collect")
async def trigger_collection(since_hours: int = 24):
    """Esegue la pipeline completa: collect → dedup → classify → score."""
    items = await collector.collect_all(
        since=datetime.utcnow() - timedelta(hours=since_hours)
    )
    events = deduplicator.deduplicate(items)
    classified = [await classifier.classify(e) for e in events]
    scored = [scorer.score(c) for c in classified]
    await storage.save_scored_events(scored)
    return {
        "events_processed": len(scored),
        "event_ids": [s.event_id for s in scored]
    }

# api/routes/events.py
@router.get("/events")
async def list_events(
    category: str | None = None,
    min_severity: float = 0,
    limit: int = 50,
):
    """Interroga eventi con score e filtri opzionali."""
    return await storage.query_events(
        category=category, min_severity=min_severity, limit=limit
    )

@router.get("/events/{event_id}")
async def get_event(event_id: str):
    """Dettaglio completo dell'evento con breakdown."""
    return await storage.get_event(event_id)

# api/routes/scores.py
@router.get("/scores/sector/{sector}")
async def scores_by_sector(sector: str, days: int = 7):
    """Score recenti che impattano un dato settore GICS."""
    return await storage.get_sector_scores(sector, days=days)

@router.get("/scores/country/{country_code}")
async def scores_by_country(country_code: str, days: int = 7):
    """Score recenti che impattano un dato paese."""
    return await storage.get_country_scores(country_code, days=days)
```

---

## 6. Flusso dati — Le cinque fasi di trasformazione

I dati fluiscono linearmente attraverso cinque stadi di trasformazione:

```
                    ┌──────────┐    ┌──────────┐    ┌──────────┐
  BBC RSS ─────┐   │          │    │          │    │          │
  AP RSS  ─────┤   │  Dedup   │    │ Classify │    │  Score   │
  GDELT   ─────┼──▶│  (LSH +  │──▶│ (Claude  │──▶│ (Matrix  │──▶ ImpactScore[]
  NewsAPI ─────┘   │  TF-IDF) │    │  t=0)    │    │  lookup) │
                   │          │    │          │    │          │
  NewsItem[]       └──────────┘    └──────────┘    └──────────┘
                   Event[]         ClassifiedEvent[]
                                                        │
                                                        ▼
                                                   ┌──────────┐
                                                   │  SQLite   │
                                                   │  Storage  │
                                                   └──────────┘
                                                        │
                                                        ▼
                                                   ┌──────────┐
                                                   │  FastAPI  │
                                                   │ Endpoints │
                                                   └──────────┘
```

Ogni stadio è **testabile indipendentemente**. Il modulo `pipeline` nel pacchetto API orchestra il flusso completo:

```
collect_all() → deduplicate() → classify() per evento → score() per evento classificato → save() su SQLite
```

### Come eseguire

```bash
uv run --package api uvicorn api.main:app --reload
```

---

## 7. Conclusione — Le decisioni architetturali critiche

La proposta di valore del sistema poggia su **tre scelte architetturali**:

### 1. Calibrazione da letteratura accademica, non da training ML

La matrice di sensitività settoriale, la scala di severità e le stime di persistenza sono tutte fondate su dati CAAR pubblicati, coefficienti EPU e premi di rischio di Damodaran — non apprese da un modello black-box. Questo rende **ogni score completamente spiegabile**.

### 2. Classificazione LLM deterministica

`temperature=0`, decodifica JSON vincolata, prompt versionati e caching hash-input eliminano la varianza che tipicamente rende i sistemi basati su LLM inaffidabili per lo scoring in produzione.

### 3. Separazione classificazione / scoring

L'LLM gestisce solo il **giudizio soggettivo** (che tipo di evento è? quanto è severo?) mentre il layer di scoring applica **formule puramente meccaniche** — l'output dell'LLM è un input a una funzione deterministica, non lo score stesso.

---

## 8. Miglioramenti futuri ad alto impatto

I due miglioramenti con il maggiore leverage oltre la build iniziale sono:

1. **Popolare la tabella di lookup CAAR** con dati reali di event study da 50+ eventi per categoria — questo trasforma la scala di severità da stime calibrate da esperti a **misurazioni empiricamente fondate**

2# News Impact Scoring — Architettura Python del Sistema

> Un monorepo uv workspace con sei pacchetti Python che implementa la pipeline completa: raccolta notizie → deduplicazione → classificazione LLM → scoring deterministico → API REST.

---

## 1. Struttura del progetto

Il sistema segue un layout `src/` con ogni componente come pacchetto Python separato, gestito da un **uv workspace** che fornisce un singolo lockfile e installazioni editabili automatiche tra i membri.

```
news-impact-scorer/
├── pyproject.toml                          # Workspace root (virtuale)
├── uv.lock                                 # Singolo lockfile
├── README.md
├── config/
│   ├── settings.toml                       # Configurazione globale
│   ├── sector_sensitivity.json             # Matrice settore × tipo-evento
│   ├── country_risk.json                   # Score rischio paese (da Damodaran)
│   ├── persistence_map.json                # Tipo evento → stime di persistenza
│   └── prompts/
│       └── classify_event_v1.txt           # Template prompt versionati
│
├── packages/
│   ├── shared-models/                      # Modelli Pydantic condivisi
│   ├── news-collector/                     # Raccolta notizie multi-sorgente
│   ├── news-deduplicator/                  # Deduplicazione e clustering
│   ├── event-classifier/                   # Classificazione LLM deterministica
│   ├── impact-scorer/                      # Pipeline di scoring
│   └── api/                                # FastAPI endpoints
│
└── tests/
    ├── test_collector/
    ├── test_deduplicator/
    ├── test_classifier/
    ├── test_scorer/
    └── test_api/
```

### Dettaglio dei pacchetti

#### `shared-models/` — Contratti di tipo della pipeline

```
shared_models/
├── __init__.py
├── news_item.py            # Modello NewsItem
├── event.py                # Modello Event (articoli raggruppati)
├── classified_event.py     # Modello ClassifiedEvent
├── impact_score.py         # ImpactScore + ScoringBreakdown
├── enums.py                # GICSSector, EventCategory, PESTLEDimension
└── config.py               # Modello Settings
```

#### `news-collector/` — Raccolta da fonti multiple

```
news_collector/
├── __init__.py
├── base.py                 # NewsSource ABC
├── rss_source.py           # RSSNewsSource (BBC, AP)
├── gdelt_source.py         # GDELTNewsSource
├── newsapi_source.py       # NewsAPISource
├── collector.py            # Orchestratore: esegue tutte le fonti
└── feed_config.py          # URL RSS, endpoint API
```

#### `news-deduplicator/` — Deduplicazione ibrida

```
news_deduplicator/
├── __init__.py
├── base.py                 # Deduplicator ABC
├── tfidf_dedup.py          # TF-IDF + similarità coseno
├── minhash_dedup.py        # MinHash/LSH (datasketch)
├── clustering.py           # Clusterizzazione articoli → Eventi
└── merger.py               # Merge articoli clusterizzati in Event
```

#### `event-classifier/` — Classificazione LLM deterministica

```
event_classifier/
├── __init__.py
├── base.py                 # Classifier ABC
├── llm_classifier.py       # Classificatore via Claude API
├── prompt_manager.py       # Caricamento prompt versionati
├── cache.py                # Cache di determinismo (hash input → output)
└── schemas.py              # Schemi output classificazione
```

#### `impact-scorer/` — Pipeline di scoring

```
impact_scorer/
├── __init__.py
├── base.py                 # Scorer ABC
├── scorer.py               # Pipeline di scoring principale
├── severity.py             # Calcolo severità base
├── sector_sensitivity.py   # Lookup matrice sensitività settoriale
├── country_risk.py         # Calcolo score rischio paese
├── context.py              # Moltiplicatore di contesto EPU/GPR
├── persistence.py          # Stima della durata
├── transmission.py         # Spillover modello IO (opzionale)
└── explainer.py            # Spiegazioni leggibili degli score
```

#### `api/` — Interfaccia REST FastAPI

```
api/
├── __init__.py
├── main.py                 # Factory dell'app FastAPI
├── routes/
│   ├── __init__.py
│   ├── collect.py          # POST /collect
│   ├── events.py           # GET /events, GET /events/{id}
│   ├── scores.py           # GET /scores/sector/{s}, /scores/country/{c}
│   └── health.py           # GET /health
├── dependencies.py         # Dependency Injection condivisa
├── storage.py              # Layer di persistenza SQLite/DuckDB
└── pipeline.py             # Pipeline completa collect→dedup→classify→score
```

---

## 2. Configurazione workspace e pacchetti

### Root `pyproject.toml` (workspace virtuale — nessuna tabella `[project]`)

```toml
[tool.uv.workspace]
members = ["packages/*"]

[tool.uv]
dev-dependencies = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "httpx>=0.27",
    "ruff>=0.8",
]
```

### Dipendenze per pacchetto

| Pacchetto | Dipendenze principali |
|---|---|
| **shared-models** | `pydantic>=2.6` |
| **news-collector** | `shared-models`, `httpx>=0.27`, `feedparser>=6.0` |
| **news-deduplicator** | `shared-models`, `scikit-learn>=1.4`, `datasketch>=1.6` |
| **event-classifier** | `shared-models`, `anthropic>=0.42` |
| **impact-scorer** | `shared-models`, `numpy>=1.26` |
| **api** | tutti i pacchetti precedenti + `fastapi>=0.115`, `uvicorn[standard]>=0.32`, `aiosqlite>=0.20` |

### Risoluzione delle dipendenze tra pacchetti

Le dipendenze tra membri del workspace sono **editabili di default** in uv — la direttiva `{ workspace = true }` risolve dal workspace locale anziché da PyPI.

```toml
# Esempio: packages/news-collector/pyproject.toml
[project]
name = "news-collector"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "shared-models",
    "httpx>=0.27",
    "feedparser>=6.0",
]

[tool.uv.sources]
shared-models = { workspace = true }

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

Per installare l'intera catena di dipendenze:

```bash
uv sync --package api
```

---

## 3. Modelli dati — I contratti di tipo della pipeline

### Enumerazioni (`shared_models/enums.py`)

```python
from enum import StrEnum

class GICSSector(StrEnum):
    ENERGY = "Energy"
    MATERIALS = "Materials"
    INDUSTRIALS = "Industrials"
    CONSUMER_DISCRETIONARY = "Consumer Discretionary"
    CONSUMER_STAPLES = "Consumer Staples"
    HEALTH_CARE = "Health Care"
    FINANCIALS = "Financials"
    INFORMATION_TECHNOLOGY = "Information Technology"
    COMMUNICATION_SERVICES = "Communication Services"
    UTILITIES = "Utilities"
    REAL_ESTATE = "Real Estate"

class EventCategory(StrEnum):
    TRADE_POLICY = "trade_policy"
    MONETARY_POLICY = "monetary_policy"
    FISCAL_POLICY = "fiscal_policy"
    REGULATORY_CHANGE = "regulatory_change"
    GEOPOLITICAL_CONFLICT = "geopolitical_conflict"
    SANCTIONS = "sanctions"
    SUPPLY_CHAIN = "supply_chain_disruption"
    PANDEMIC_HEALTH = "pandemic_health"
    NATURAL_DISASTER = "natural_disaster"
    CORPORATE_EVENT = "corporate_event"
    MARKET_SHOCK = "market_shock"
    TECHNOLOGY_DISRUPTION = "technology_disruption"
    LABOR_SOCIAL = "labor_social"
    ENVIRONMENTAL_CLIMATE = "environmental_climate"

class PESTLEDimension(StrEnum):
    POLITICAL = "Political"
    ECONOMIC = "Economic"
    SOCIAL = "Social"
    TECHNOLOGICAL = "Technological"
    LEGAL = "Legal"
    ENVIRONMENTAL = "Environmental"
```

### `NewsItem` — Singolo articolo raccolto (`shared_models/news_item.py`)

```python
from datetime import datetime
from pydantic import BaseModel, HttpUrl

class NewsItem(BaseModel):
    source_id: str                    # es. "bbc_rss", "gdelt", "newsapi"
    source_name: str                  # Nome leggibile della fonte
    title: str
    description: str | None = None
    content: str | None = None
    url: HttpUrl
    published_at: datetime
    language: str = "en"
    source_country: str | None = None
    image_url: HttpUrl | None = None
    raw_metadata: dict = {}           # Campi extra specifici della fonte
    fetched_at: datetime              # Quando il sistema l'ha recuperato
```

### `Event` — Articoli raggruppati/deduplicati (`shared_models/event.py`)

```python
from datetime import datetime
from pydantic import BaseModel, Field
import hashlib

class Event(BaseModel):
    event_id: str = Field(default_factory=lambda: "")
    primary_title: str                     # Miglior titolo dalle fonti
    description: str                       # Descrizione migliore/unificata
    articles: list[str]                    # Lista URL articoli sorgente
    source_count: int
    earliest_published: datetime
    latest_published: datetime
    countries_mentioned: list[str] = []    # ISO 3166-1 alpha-2
    avg_sentiment: float | None = None     # Da GDELT AvgTone o calcolato
    raw_articles: list[dict] = []          # Dict NewsItem completi

    def model_post_init(self, __context):
        if not self.event_id:
            content = f"{self.primary_title}:{self.earliest_published.isoformat()}"
            self.event_id = hashlib.sha256(content.encode()).hexdigest()[:16]
```

### `ClassifiedEvent` — Evento classificato dall'LLM (`shared_models/classified_event.py`)

```python
from pydantic import BaseModel, Field

class PESTLEScores(BaseModel):
    political: float = Field(ge=0, le=5)
    economic: float = Field(ge=0, le=5)
    social: float = Field(ge=0, le=5)
    technological: float = Field(ge=0, le=5)
    legal: float = Field(ge=0, le=5)
    environmental: float = Field(ge=0, le=5)
```

### `ImpactScore` — Risultato finale della pipeline (`shared_models/impact_score.py`)

```python
from datetime import datetime
from pydantic import BaseModel, Field

class ScoringBreakdown(BaseModel):
    base_severity: float
    sector_sensitivity: float
    context_multiplier: float
    geographic_factor: float
    persistence_factor: float
    contributing_factors: list[str]         # Spiegazioni leggibili

class SectorScore(BaseModel):
    score: float = Field(ge=0, le=10)
    confidence: float = Field(ge=0, le=1)
    breakdown: ScoringBreakdown

class CountryScore(BaseModel):
    score: float = Field(ge=0, le=10)
    confidence: float = Field(ge=0, le=1)
    country_risk_premium: float
    vulnerability_factor: float

class ImpactScore(BaseModel):
    event_id: str
    timestamp: datetime
    event_category: str
    base_severity: float
    affected_sectors: dict[str, SectorScore]
    affected_countries: dict[str, CountryScore]
    global_score: float = Field(ge=0, le=10)
    persistence_estimate_days: int
    scoring_version: str
    sources: list[str]
```

---

## 4. Implementazione dei componenti — Pattern ad interfacce

### News Collector — Interfaccia astratta con tre implementazioni concrete

```python
# news_collector/base.py
from abc import ABC, abstractmethod
from datetime import datetime
from shared_models.news_item import NewsItem

class NewsSource(ABC):
    @abstractmethod
    async def fetch_items(self, since: datetime) -> list[NewsItem]: ...

    @property
    @abstractmethod
    def source_id(self) -> str: ...
```

#### Fonti concrete

| Fonte | Endpoint | Note |
|---|---|---|
| **BBC RSS** | `feeds.bbci.co.uk/news/world/rss.xml`, `/business/rss.xml`, `/technology/rss.xml` | Usa `feedparser` + `httpx` |
| **AP RSS** | `apnews.com/world-news.rss`, `/business.rss` | Usa `feedparser` + `httpx` |
| **GDELT** | `api.gdeltproject.org/api/v2/doc/doc?query=...&mode=artlist&format=json&maxrecords=250&timespan=1d&sort=datedesc` | Nessuna API key richiesta |
| **NewsAPI** | `newsapi.org/v2/everything` | Richiede header API key |

> **Nota:** Reuters ha dismesso gli RSS a giugno 2020 — usare le fonti GDELT o NewsAPI in alternativa.

### Deduplicator — Pipeline ibrida per velocità e accuratezza

```python
# news_deduplicator/base.py
from abc import ABC, abstractmethod
from shared_models import NewsItem, Event

class Deduplicator(ABC):
    @abstractmethod
    def deduplicate(self, items: list[NewsItem]) -> list[Event]: ...
```

#### Pipeline a tre stadi

1. **Deduplicazione esatta** — hash SHA-256 del titolo normalizzato + URL
2. **Generazione candidati** — MinHash/LSH dalla libreria `datasketch` (soglia Jaccard 0.6, 128 permutazioni, 4-grammi di carattere) per recupero candidati in tempo sub-lineare
3. **Re-ranking** — similarità coseno TF-IDF sulle coppie candidate, filtraggio a soglia 0.8

I cluster di articoli simili vengono uniti in oggetti `Event`, selezionando la descrizione più lunga e il tempo di pubblicazione più vecchio.

### Event Classifier — Classificazione LLM deterministica via Claude API

```python
# event_classifier/llm_classifier.py
from anthropic import Anthropic
from shared_models import Event, ClassifiedEvent

class LLMClassifier:
    def __init__(self, prompt_version: str = "v1"):
        self.client = Anthropic()
        self.prompt_version = prompt_version
        self._cache: dict[str, ClassifiedEvent] = {}

    async def classify(self, event: Event) -> ClassifiedEvent:
        cache_key = hashlib.sha256(
            f"{event.event_id}:{self.prompt_version}".encode()
        ).hexdigest()

        if cache_key in self._cache:
            return self._cache[cache_key]

        response = self.client.messages.create(
            model="claude-sonnet-4-5-20250514",
            max_tokens=2048,
            temperature=0,
            messages=[{"role": "user", "content": self._build_prompt(event)}],
            output_config={
                "format": {
                    "type": "json_schema",
                    "schema": CLASSIFICATION_SCHEMA  # Forzato a livello di decodifica
                }
            },
        )

        result = ClassifiedEvent.model_validate_json(response.content[0].text)
        result.prompt_version = self.prompt_version
        self._cache[cache_key] = result
        return result
```

#### I quattro meccanismi di determinismo

| Meccanismo | Scopo |
|---|---|
| `temperature=0` | Elimina la casualità del campionamento |
| `output_config.format` con JSON schema | Usa decodifica vincolata, previene violazioni dello schema |
| Template prompt versionati (`config/prompts/classify_event_v1.txt`) | Garantisce lo stesso testo di prompt tra esecuzioni |
| Cache hash-input | Garantisce che input identici restituiscano output identici anche tra riavvii (persistere su SQLite) |

#### Template del prompt di classificazione

```
You are a financial news event classifier. Given a news event, output a JSON
classification with these fields:
- event_category: one of [trade_policy, monetary_policy, fiscal_policy,
  regulatory_change, geopolitical_conflict, sanctions, supply_chain_disruption,
  pandemic_health, natural_disaster, corporate_event, market_shock,
  technology_disruption, labor_social, environmental_climate]
- base_severity: float 0-10, calibrated as: 0-2 routine, 2-4 notable,
  4-6 significant, 6-8 major, 8-10 crisis-level
- affected_sectors: list of GICS sectors directly impacted
- affected_countries: list of ISO alpha-2 country codes
- pestle_scores: score 0-5 for each PESTLE dimension
- classification_confidence: your confidence 0-1
- reasoning: brief explanation of your classification logic
```

### Impact Scorer — La pipeline di scoring

```python
# impact_scorer/scorer.py
class ImpactScorer:
    def __init__(self, config_dir: Path):
        self.sector_matrix = load_json(config_dir / "sector_sensitivity.json")
        self.country_risk = load_json(config_dir / "country_risk.json")
        self.persistence_map = load_json(config_dir / "persistence_map.json")

    def score(self, event: ClassifiedEvent) -> ImpactScore:
        sector_scores = {}
        for sector in GICSSector:
            sensitivity = self.sector_matrix[event.event_category].get(sector, 0.5)
            context_mult = self._get_context_multiplier()
            geo_factor = self._geographic_factor(event.affected_countries, sector)
            persist = self._persistence_factor(event.event_category)

            raw = event.base_severity * sensitivity * context_mult * geo_factor
            normalized = min(10.0, raw * persist)
            confidence = self._compute_confidence(event, sector)

            sector_scores[sector] = SectorScore(
                score=round(normalized, 2),
                confidence=round(confidence, 2),
                breakdown=ScoringBreakdown(
                    base_severity=event.base_severity,
                    sector_sensitivity=sensitivity,
                    context_multiplier=context_mult,
                    geographic_factor=geo_factor,
                    persistence_factor=persist,
                    contributing_factors=self._explain(event, sector, sensitivity),
                ),
            )

        global_score = self._compute_global(event, sector_scores)
        persistence_days = self.persistence_map.get(event.event_category, 30)

        return ImpactScore(
            event_id=event.event_id,
            timestamp=datetime.utcnow(),
            event_category=event.event_category,
            base_severity=event.base_severity,
            affected_sectors=sector_scores,
            affected_countries=self._score_countries(event),
            global_score=global_score,
            persistence_estimate_days=persistence_days,
            scoring_version="1.0.0",
            sources=event.articles if hasattr(event, 'articles') else [],
        )
```

---

## 5. API REST — FastAPI con cinque endpoint

### Endpoint esposti

| Metodo | Endpoint | Descrizione |
|---|---|---|
| `POST` | `/collect` | Esegue la pipeline completa: raccogli → deduplica → classifica → score |
| `GET` | `/events` | Interroga eventi con score, con filtri opzionali |
| `GET` | `/events/{event_id}` | Dettaglio completo di un evento con breakdown |
| `GET` | `/scores/sector/{sector}` | Score recenti che impattano un dato settore GICS |
| `GET` | `/scores/country/{country_code}` | Score recenti che impattano un dato paese |

### Implementazione delle route

```python
# api/routes/collect.py
@router.post("/collect")
async def trigger_collection(since_hours: int = 24):
    """Esegue la pipeline completa: collect → dedup → classify → score."""
    items = await collector.collect_all(
        since=datetime.utcnow() - timedelta(hours=since_hours)
    )
    events = deduplicator.deduplicate(items)
    classified = [await classifier.classify(e) for e in events]
    scored = [scorer.score(c) for c in classified]
    await storage.save_scored_events(scored)
    return {
        "events_processed": len(scored),
        "event_ids": [s.event_id for s in scored]
    }

# api/routes/events.py
@router.get("/events")
async def list_events(
    category: str | None = None,
    min_severity: float = 0,
    limit: int = 50,
):
    """Interroga eventi con score e filtri opzionali."""
    return await storage.query_events(
        category=category, min_severity=min_severity, limit=limit
    )

@router.get("/events/{event_id}")
async def get_event(event_id: str):
    """Dettaglio completo dell'evento con breakdown."""
    return await storage.get_event(event_id)

# api/routes/scores.py
@router.get("/scores/sector/{sector}")
async def scores_by_sector(sector: str, days: int = 7):
    """Score recenti che impattano un dato settore GICS."""
    return await storage.get_sector_scores(sector, days=days)

@router.get("/scores/country/{country_code}")
async def scores_by_country(country_code: str, days: int = 7):
    """Score recenti che impattano un dato paese."""
    return await storage.get_country_scores(country_code, days=days)
```

---

## 6. Flusso dati — Le cinque fasi di trasformazione

I dati fluiscono linearmente attraverso cinque stadi di trasformazione:

```
                    ┌──────────┐    ┌──────────┐    ┌──────────┐
  BBC RSS ─────┐   │          │    │          │    │          │
  AP RSS  ─────┤   │  Dedup   │    │ Classify │    │  Score   │
  GDELT   ─────┼──▶│  (LSH +  │──▶│ (Claude  │──▶│ (Matrix  │──▶ ImpactScore[]
  NewsAPI ─────┘   │  TF-IDF) │    │  t=0)    │    │  lookup) │
                   │          │    │          │    │          │
  NewsItem[]       └──────────┘    └──────────┘    └──────────┘
                   Event[]         ClassifiedEvent[]
                                                        │
                                                        ▼
                                                   ┌──────────┐
                                                   │  SQLite   │
                                                   │  Storage  │
                                                   └──────────┘
                                                        │
                                                        ▼
                                                   ┌──────────┐
                                                   │  FastAPI  │
                                                   │ Endpoints │
                                                   └──────────┘
```

Ogni stadio è **testabile indipendentemente**. Il modulo `pipeline` nel pacchetto API orchestra il flusso completo:

```
collect_all() → deduplicate() → classify() per evento → score() per evento classificato → save() su SQLite
```

### Come eseguire

```bash
uv run --package api uvicorn api.main:app --reload
```

---

## 7. Conclusione — Le decisioni architetturali critiche

La proposta di valore del sistema poggia su **tre scelte architetturali**:

### 1. Calibrazione da letteratura accademica, non da training ML

La matrice di sensitività settoriale, la scala di severità e le stime di persistenza sono tutte fondate su dati CAAR pubblicati, coefficienti EPU e premi di rischio di Damodaran — non apprese da un modello black-box. Questo rende **ogni score completamente spiegabile**.

### 2. Classificazione LLM deterministica

`temperature=0`, decodifica JSON vincolata, prompt versionati e caching hash-input eliminano la varianza che tipicamente rende i sistemi basati su LLM inaffidabili per lo scoring in produzione.

### 3. Separazione classificazione / scoring

L'LLM gestisce solo il **giudizio soggettivo** (che tipo di evento è? quanto è severo?) mentre il layer di scoring applica **formule puramente meccaniche** — l'output dell'LLM è un input a una funzione deterministica, non lo score stesso.

---

## 8. Miglioramenti futuri ad alto impatto

I due miglioramenti con il maggiore leverage oltre la build iniziale sono:

1. **Popolare la tabella di lookup CAAR** con dati reali di event study da 50+ eventi per categoria — questo trasforma la scala di severità da stime calibrate da esperti a **misurazioni empiricamente fondate**

2. **Integrare la matrice inversa di Leontief del WIOD** nel modulo di trasmissione — questo abiliterebbe il calcolo automatico degli effetti di spillover settoriale di secondo e terzo ordine, anziché affidarsi alla sola matrice di sensitività più semplice
. **Integrare la matrice inversa di Leontief del WIOD** nel modulo di trasmissione — questo abiliterebbe il calcolo automatico degli effetti di spillover settoriale di secondo e terzo ordine, anziché affidarsi alla sola matrice di sensitività più semplice

