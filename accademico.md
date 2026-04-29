# News Impact Scoring — Fondamenti Accademici e Framework Statistici

> Un sistema deterministico e rule-based che converte eventi di cronaca in punteggi di impatto numerici multi-dimensionali, costruito interamente su framework accademici consolidati.

---

## 1. Event Studies — La spina dorsale empirica per calibrare la severità

La metodologia degli **event study**, formalizzata da MacKinlay (1997, *Journal of Economic Literature*) e raffinata da Kothari & Warner (2007, *Handbook of Empirical Corporate Finance*), è il gold standard per misurare l'effetto di eventi specifici sui prezzi degli asset.

### Il processo in tre passi

**Passo 1 — Stima dei rendimenti normali** utilizzando un modello di mercato su una finestra di stima di 120–250 giorni precedenti l'evento:

$$R_{i,t} = \alpha_i + \beta_i \cdot R_{m,t} + \varepsilon_{i,t}$$

**Passo 2 — Calcolo dei rendimenti anomali** durante la finestra dell'evento (tipicamente \[−1, +1\] o \[0, +5\] giorni):

$$AR_{i,t} = R_{i,t} - (\hat{\alpha}_i + \hat{\beta}_i \cdot R_{m,t})$$

**Passo 3 — Aggregazione in CAAR** (Cumulative Average Abnormal Returns) su N eventi storici simili:

$$CAAR(t_1, t_2) = \frac{1}{N} \sum_i CAR_i(t_1, t_2)$$

### Perché è fondamentale per il sistema di scoring

I valori CAAR possono essere **pre-calcolati come tabelle di lookup** per ogni categoria di evento. Ad esempio:

| Categoria evento | CAAR tipico \[0, +2\] | Fonte |
|---|---|---|
| Sanzioni | −3.2% sul settore target | Ahn & Ludema, 2020 |
| Escalation tariffaria | −1.8% su industriali | Caldara et al., 2020 |
| Sorpresa tassi d'interesse | −0.5% per 25bp imprevisti | Bernanke & Kuttner, 2005 |

Questi valori CAAR storici si traducono direttamente nella **scala di severità base** (0–10) del sistema di scoring: un CAAR del 3.2% in un evento di sanzioni corrisponde a un `base_severity` di circa 5–6 sulla scala calibrata.

---

## 2. Indici di incertezza — Il moltiplicatore di contesto

### Economic Policy Uncertainty (EPU)

L'indice **EPU di Baker, Bloom & Davis** (2016, *Quarterly Journal of Economics*) combina tre componenti:

1. **Copertura giornalistica** — frequenza di termini legati all'incertezza economica in 10 testate principali
2. **Scadenze fiscali** — previsioni CBO sulle disposizioni del codice fiscale in scadenza
3. **Dispersione dei forecaster** — disaccordo tra economisti su inflazione e spesa pubblica

L'indice è disponibile a livello mensile/giornaliero per 27+ paesi, con sotto-indici specifici per sanità, regolamentazione finanziaria e sicurezza nazionale. I dati sono accessibili tramite FRED, Bloomberg e Haver.

**Evidenza empirica chiave:** un aumento di una deviazione standard dell'EPU prevede cali del PIL fino al **2.3%** e aumenti della volatilità implicita del settore finanziario di **23.8 punti logaritmici**.

### Geopolitical Risk (GPR)

L'indice **GPR di Caldara & Iacoviello** (2022, *American Economic Review*) si basa su una ricerca testuale automatizzata in 10 giornali internazionali, contando articoli su tensioni geopolitiche organizzate in **8 categorie**:

1. Minacce di guerra
2. Minacce alla pace
3. Buildup militari
4. Minacce nucleari
5. Minacce terroristiche
6. Inizio di guerra
7. Escalation di guerra
8. Atti terroristici

L'indice si divide in **GPR Threats** (categorie 1–5) e **GPR Acts** (categorie 6–8). Dati mensili/giornalieri disponibili gratuitamente su matteoiacoviello.com/gpr.htm per 18+ paesi.

**Evidenza empirica:** un GPR elevato prevede minori investimenti e occupazione, con effetti più marcati nelle industrie esposte al rischio geopolitico.

### Trade Policy Uncertainty (TPU)

L'indice **TPU di Caldara et al.** (2020, *Journal of Monetary Economics*) combina misure basate su giornali, earnings call aziendali e volatilità dei tassi tariffari.

**Evidenza empirica:** i picchi di TPU durante le tensioni commerciali riducono gli investimenti dell'**1–2%**.

### Come si usano nel sistema di scoring

Il livello ambientale di incertezza agisce come **moltiplicatore di contesto**:

$$\text{context\_multiplier} = 1 + \alpha \cdot \frac{EPU_{current} - EPU_{mean}}{EPU_{std}}$$

Dove α ∈ \[0.1, 0.5\] è un parametro di sensibilità regolabile.

In alternativa, si può usare una **classificazione a regime basata sullo z-score**:

| Regime | Condizione | Moltiplicatore |
|---|---|---|
| **Crisi** | z > 2 | ×1.5 |
| **Elevato** | 1 < z < 2 | ×1.2 |
| **Normale** | z < 1 | ×1.0 |

---

## 3. Sensitività settoriale — Impatto differenziato per settore GICS

Diversi settori GICS rispondono a diverse categorie di eventi con magnitudini nettamente differenti, documentate in molteplici studi:

| Tipo di evento | Settori più sensibili | Settori meno sensibili | Evidenza |
|---|---|---|---|
| **Politica commerciale/tariffe** | Materials (1.8×), Industrials (1.5×), IT (1.4×) | Utilities (0.3×), Real Estate (0.4×) | Caldara et al. 2020; event studies tariffari |
| **Variazioni tassi d'interesse** | Financials (1.8×), Real Estate (1.7×), Utilities (1.5×) | Materials (0.5×), Energy (0.6×) | Letteratura sui beta settoriali |
| **Pandemia/crisi sanitaria** | Health Care (1.8×), Consumer Disc. (1.6×), Energy (1.5×) | Utilities (0.4×), Consumer Staples (0.7×) | Ramelli & Wagner 2020; Pagano et al. 2020 |
| **Cambiamento regolatorio** | Health Care (1.6×), Financials (1.5×), IT (1.3×) | Energy (0.7×), Utilities (0.8×) | Baker, Bloom & Davis 2016 |
| **Conflitto geopolitico** | Energy (1.7×), Financials (1.4×), Industrials (1.3×) | Consumer Staples (0.5×), Utilities (0.4×) | Caldara & Iacoviello 2022 |
| **Disruzione supply chain** | Industrials (1.7×), IT (1.5×), Materials (1.4×) | Financials (0.5×), Utilities (0.3×) | Studi settoriali COVID-19 |

### Calibrazione empirica

Baker, Bloom & Davis hanno trovato che le aziende con alta esposizione a contratti governativi (difesa, sanità, ingegneria) mostrano una sensibilità EPU significativamente più alta.

- **Financials** presentano la più alta sensibilità assoluta all'EPU: **23.8 punti logaritmici** di risposta in volatilità
- **Healthcare** è al secondo posto con **13.9 punti logaritmici**

Questi moltiplicatori — memorizzati come `sensitivity_matrix[event_type][sector]` — costituiscono il cuore del layer di scoring settoriale. Devono essere calibrati empiricamente usando il rapporto tra il CAAR settore-specifico e il CAAR medio cross-settoriale per ogni tipo di evento.

---

## 4. Rischio paese — Score composito fondamentali + indicatori real-time

### Country Risk Premium (CRP) di Damodaran

La metodologia CRP di Damodaran (aggiornata semestralmente, dati su stern.nyu.edu/~adamodar/) fornisce la baseline strutturale:

$$CRP = \text{Sovereign\_Default\_Spread} \times \text{Equity\_Bond\_Volatility\_Scalar}$$

Dove lo scalare di volatilità (σ\_equity / σ\_bond ≈ 1.42 nel 2023) traduce il rischio del mercato obbligazionario in rischio del mercato azionario.

$$\text{Total Equity Risk Premium} = \text{Mature Market ERP} + CRP$$

**Esempi:**
- India (Baa3): CRP = 2.35% × 1.42 = **3.34%**
- Argentina (Caa1): CRP ≈ **9.71%**

### Score composito per la pipeline di scoring

$$\text{country\_risk\_score} = w_1 \cdot CRP_{norm} + w_2 \cdot CDS_{norm} + w_3 \cdot GPR_{country,norm}$$

Dove `CRP_normalized = CRP / max_CRP × 10` (mappato su scala 0–10), e `CDS_normalized` e `GPR_country_normalized` seguono lo stesso schema.

I **fattori di vulnerabilità paese** (apertura commerciale, dipendenza dalle commodities, integrazione finanziaria) servono come moltiplicatori aggiuntivi per tipi specifici di evento:
- Un'economia **dipendente dal commercio** amplifica gli impatti tariffari
- Un'economia **dipendente dalle commodities** amplifica gli shock di offerta
- Un'economia **finanziariamente integrata** amplifica gli shock monetari

---

## 5. Trasmissione degli shock — Modello input-output di Leontief

### Il framework teorico

Il modello input-output di Leontief fornisce un modello rigoroso per come gli shock si propagano tra settori e paesi. L'equazione fondamentale:

$$x = (I - A)^{-1} \cdot d = L \cdot d$$

Dove:
- **A** è la matrice dei coefficienti tecnici (a\_ij = input dal settore i per unità di output del settore j)
- **d** è il vettore dello shock di domanda
- **L = (I − A)⁻¹** è l'**inversa di Leontief**

L'elemento l\_ij mostra l'**impatto totale** sul settore i da una variazione unitaria della domanda nel settore j, catturando tutti gli effetti diretti e indiretti attraverso l'intera catena di fornitura. Il **moltiplicatore di output** per il settore j è la somma della colonna: μ\_j = Σ\_i l\_ij.

### Importanza sistemica e struttura di rete

**Acemoglu, Carvalho, Ozdaglar & Tahbaz-Salehi** (2012, *Econometrica*) hanno dimostrato che la struttura della rete determina se gli shock idiosincratici si aggregano o si diversificano. Settori con alta **centralità dell'autovettore** nella rete input-output (come il manifatturiero) sono **sistemicamente importanti** — gli shock a questi settori si propagano a cascata nelle catene a valle anziché mediare.

$$\sigma_{agg} = \sigma \cdot \|v_n\|_2$$

dove v\_n è il vettore d'influenza delle centralità di rete.

### Dati empirici

Il **World Input-Output Database (WIOD)**, dell'Università di Groningen, fornisce i dati empirici: **43 paesi × 56 industrie** (ISIC Rev. 4) dal 2000 al 2014.

Per la trasmissione cross-paese, le **matrici di esposizione commerciale** T\_ij = exports\_i→j / total\_exports\_i quantificano come gli shock a livello paese si propagano attraverso le reti commerciali.

Il **contagio finanziario** aggiunge un ulteriore livello, modellato attraverso framework come:
- **DebtRank** (Battiston et al., 2012) — per la propagazione continua delle perdite
- **Indici di spillover di Diebold-Yilmaz** — per misurare l'interconnessione cross-mercato

---

## 6. Classificazione testuale — Da notizie non strutturate a vettori d'impatto

Tre framework forniscono la struttura tassonomica:

### CAMEO (Conflict and Mediation Event Observations)

Una gerarchia a 3 livelli con **20 categorie radice** — da "Make Public Statement" (01) a "Unconventional Mass Violence" (20) — per un totale di **~300+ tipi di evento**. Ogni codice mappa su un valore della **Scala di Goldstein** (da −10 a +10) che cattura l'impatto teorico sulla stabilità. Gli eventi si classificano anche in **QuadClass**: Cooperazione Verbale, Cooperazione Materiale, Conflitto Verbale, Conflitto Materiale.

### GDELT Project

Operazionalizza CAMEO su **scala planetaria**, processando notizie da **65 lingue** ogni 15 minuti. Ogni record include:
- Attributi Actor1/Actor2
- Codici evento CAMEO
- Punteggi Goldstein
- Sentiment AvgTone
- Coordinate geografiche
- Proxy di importanza (NumMentions, NumSources, NumArticles)
- Il **Global Knowledge Graph** aggiunge 2,500+ tag tematici

### FinBERT

Un modello BERT adattato al dominio finanziario (Araci 2019; Huang et al. 2023) che raggiunge un'accuratezza dell'**88.2%** nella classificazione del sentiment finanziario, superando significativamente i dizionari Loughran-McDonald (62.1%). Produce probabilità softmax per Positivo/Negativo/Neutro e può essere fine-tuned per classificazione multi-classe.

### Dimensioni PESTLE come asse di classificazione

Per la pipeline di scoring, le dimensioni **PESTLE** (Political, Economic, Social, Technological, Legal, Environmental) servono come asse naturale di classificazione. Ogni evento mappa su un **vettore PESTLE con punteggio 0–5** per dimensione, con pesi specifici per settore:

| Settore | Dimensioni PESTLE con peso maggiore |
|---|---|
| **Financials** | Economic, Legal |
| **Energy** | Political, Environmental |
| **Technology** | Technological, Legal |

Questi pesi, derivabili dall'analisi storica delle reazioni dei prezzi azionari a eventi classificati PESTLE, creano **profili d'impatto differenziati per settore**.

---

## 7. La formula completa di scoring — Sintesi di tutti i framework

### Scala di severità degli eventi (0–10)

Calibrata dalle magnitudini storiche dei CAAR:

| Severità | Range | Esempi | \|CAAR\| tipico |
|---|---|---|---|
| Minimale | 0–2 | Earnings di routine, cambi di personale minori | 0–1% |
| Bassa | 2–4 | Aggiornamento regolatorio minore, colloqui commerciali bilaterali | 1–3% |
| Moderata | 4–6 | Annuncio politico importante, sorpresa banca centrale | 3–5% |
| Alta | 6–8 | Escalation guerra commerciale, sanzioni importanti, ondata pandemica | 5–8% |
| Severa | 8–10 | Crisi finanziaria, shock sistemico, scoppio di guerra | 8%+ |

### Formula impatto settoriale

```
sector_score(event, sector) = base_severity
    × sensitivity_matrix[event_type][sector]
    × context_multiplier
    × geographic_factor
    × persistence_factor
```

Dove:
- `base_severity` ∈ \[0, 10\] — dal classificatore LLM, calibrato sulla scala CAAR
- `sensitivity_matrix` ∈ \[0.0, 2.0\] — dalla matrice settore-evento pre-calcolata
- `context_multiplier` = 1 + α · (EPU\_z o GPR\_z), tipicamente ∈ \[0.8, 1.5\]
- `geographic_factor` = Σ\_c (revenue\_share\_c × country\_risk\_c / 10) per i paesi coinvolti
- `persistence_factor` = 1 + β · ln(expected\_duration\_days / 5), dove β ≈ 0.2

### Formula impatto paese

```
country_score(event, country) = base_severity
    × country_risk_score(country) / 10
    × event_country_relevance
    × vulnerability_multiplier(country, event_type)
```

Dove `vulnerability_multiplier` tiene conto di apertura commerciale (per eventi commerciali), dipendenza dalle commodities (per shock di offerta) o integrazione finanziaria (per eventi monetari).

### Formula score globale

```
global_score = base_severity × breadth_factor × context_multiplier
breadth_factor = 1 + (n_sectors_affected − 1) / 10
```

### Stima della persistenza

Mappa i tipi di evento a range di durata attesa basati sulla letteratura degli event study:

| Tipo di evento | Persistenza tipica | Base |
|---|---|---|
| Earnings surprise | 1–5 giorni | Event studies a finestra breve |
| Annuncio regolatorio | 5–30 giorni | Timeline di implementazione policy |
| Cambio politica commerciale | 30–180 giorni | Persistenza TPU (Caldara et al.) |
| Conflitto geopolitico | 30–365 giorni | Pattern di decadimento GPR |
| Crisi sistemica | 180–730 giorni | Crisi 2008, timeline di recupero COVID |

### Score di confidenza

```
confidence = min(1.0, w₁ · source_factor + w₂ · classification_confidence + w₃ · calibration_factor)
```

Dove:
- `source_factor` = min(1.0, n\_sources / 5)
- `classification_confidence` — dall'output strutturato dell'LLM
- `calibration_factor` = min(1.0, n\_historical\_events / 30) — riflette quanti dati storici supportano il lookup CAAR

### Spiegabilità — ogni score porta un breakdown completo

```json
{
  "base_severity": 6.5,
  "sector_sensitivity": 1.4,
  "context_multiplier": 1.15,
  "geographic_factor": 0.82,
  "persistence_factor": 1.31,
  "final_score": 8.67,
  "contributing_factors": [
    "Alta sensibilità alla politica commerciale per il settore IT (1.4×)",
    "Ambiente EPU elevato (+15% boost di contesto)",
    "Esposizione primaria a USA (CRP 0.0) e Cina (CRP 1.2)"
  ]
}
```

