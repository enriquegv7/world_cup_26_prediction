```
╔══════════════════════════════════════════════════════════════╗
║   11 MODELOS DE IA  ·  72 PARTIDOS  ·  1 MERCADO DE APUESTAS ║
║              FIFA WORLD CUP 2026 — GRUPO AI                  ║
╚══════════════════════════════════════════════════════════════╝
```

# Grupo AI ⚽

**Idea central:** Si juntas a los 11 mejores modelos de IA del mundo,
ponderados por su precisión histórica, ¿pueden encontrar valor
contra las cuotas de Polymarket?

Esto no es solo un benchmark. Es un sistema de inteligencia colectiva
que convierte predicciones en señales de apuesta con tamaño de posición
calculado por Criterio de Kelly.

---

## Las tres capas

### 1 — Benchmark
Cada modelo recibe el mismo prompt y devuelve JSON con predicciones para los 104 partidos del Mundial. Las predicciones se congelaron antes del partido inaugural. A medida que llegan los resultados reales, se calculan tres métricas por modelo: Brier score, precisión de resultado y acierto de marcador exacto.

### 2 — Consejo
Los 11 modelos se agregan en una sola probabilidad por partido. El peso de cada modelo es proporcional a `1 / brier_score` — quien predice mejor, más voz tiene. El resultado es un vector de probabilidades 1X2 colectivo que ningún modelo individual produce solo.

### 3 — Edge vs Polymarket
Las cuotas de Polymarket se descargan automáticamente desde su API. Se compara cada probabilidad del Consejo contra la cuota de mercado. Si hay edge (`prob × cuota > 1`) con suficiente consenso entre modelos, el motor Kelly calcula el tamaño óptimo de la apuesta.

---

## Instalación

```bash
git clone <tu-repo>
cd grupo-ai
python -m venv venv
# Windows:
venv\Scripts\activate
# Mac/Linux:
source venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
# Añade tu OPENROUTER_API_KEY en .env
```

---

## Comandos

```bash
# Recoger predicciones de todos los modelos
python src/run_predictions.py

# Solo algunos modelos
python src/run_predictions.py --models GPT-5.5 Grok-4.3

# Verificar configuración sin llamar a APIs
python src/run_predictions.py --dry-run

# Descargar cuotas en vivo de Polymarket
python src/fetch_odds.py

# Actualizar tabla de clasificación en el README
python src/generate_leaderboard.py --inject-readme
```

---

## Tabla de clasificación

<!-- LEADERBOARD:START -->

_Sin partidos puntuados aún._

<!-- LEADERBOARD:END -->

---

## Modelos incluidos

| Modelo | Laboratorio | ID en OpenRouter |
|--------|------------|-----------------|
| GPT-5.5 | OpenAI | `openai/gpt-5.5` |
| Claude Fable 5 | Anthropic | `anthropic/claude-fable-5` |
| Gemini 3.5 Flash | Google | `google/gemini-3.5-flash` |
| Grok 4.3 | xAI | `x-ai/grok-4.3` |
| DeepSeek V4-Pro | DeepSeek | `deepseek/deepseek-v4-pro` |
| Qwen 3.7 Max | Alibaba | `qwen/qwen-3.7-max` |
| Kimi K2.6 | Moonshot AI | `moonshotai/kimi-k2.6` |
| GLM-5.1 | Zhipu AI | `z-ai/glm-5.1` |
| MiniMax M3 | MiniMax | `minimax/minimax-m3` |
| MiMo V2.5-Pro | Xiaomi | `xiaomi/mimo-v2.5-pro` |
| Nex-N2-Pro | Nex AGI | `nex-agi/nex-n2-pro:free` |

Todos reciben el mismo prompt (`prompts/prediction_prompt.txt`) sin contexto adicional.

---

## Cuotas de Polymarket

`src/fetch_odds.py` consulta la Gamma API de Polymarket (serie `soccer-fifwc`) y guarda precios e cuotas decimales para los 72 partidos de grupos. Los partidos ya resueltos se omiten automáticamente.

```json
{
  "match_id": "25",
  "home_team": "GER",
  "away_team": "CUW",
  "date": "2026-06-14",
  "prices": { "home": 94.45, "draw": 3.9, "away": 2.05 },
  "odds":   { "home": 1.06,  "draw": 25.64, "away": 48.78 }
}
```

`prices` = probabilidad implícita × 100 · `odds` = cuota decimal (`1 / price`)

---

## Cómo funciona el Criterio de Kelly

```
edge   = (prob_consejo × cuota_polymarket) − 1
kelly  = edge / (cuota − 1)
apuesta = min(bankroll × kelly / 4,  bankroll × 5%)
```

Se aplica Kelly fraccionario (÷4) con tope del 5% del bankroll.
Una apuesta solo se recomienda si cumple los tres filtros:

- `edge > 5%`
- `agreement_rate ≥ 55%` (mayoría de modelos coincide)
- `confidence ≥ 45%` (la probabilidad del Consejo es alta)

---

## Métricas de puntuación

| Métrica | Qué mide |
|---------|---------|
| **Brier score ↓** | Calibración de las probabilidades 1X2 |
| **Precisión de resultado ↑** | ¿Acertó el resultado más probable? |
| **Marcador exacto ↑** | ¿Coincidió el marcador predicho con el real? |

La clasificación del leaderboard se basa en Brier score y precisión de resultado, ambos calculados desde las probabilidades 1X2. El marcador exacto es una métrica aparte.

Las predicciones se congelaron el 10 de junio de 2026 con commit `1bdceff`. Ver `FREEZE.md` para checksums y trazabilidad completa.

---

## Estructura del proyecto

```
grupo-ai/
├── src/
│   ├── run_predictions.py      # recoger predicciones
│   ├── models_config.py        # registro de modelos
│   ├── utils.py                # I/O, validación, parsing
│   ├── generate_leaderboard.py # actualizar README
│   ├── fetch_odds.py           # cuotas de Polymarket
│   ├── council.py              # agregador ponderado
│   └── betting.py              # motor Kelly
├── predictions/
│   └── pre-tournament/         # JSONs congelados
├── data/
│   ├── tournament.json         # fixture FIFA oficial
│   ├── results/                # resultados reales
│   ├── leaderboard.json        # puntuaciones calculadas
│   └── odds/odds.json          # cuotas Polymarket
├── schema/
│   └── predictions_schema.json # JSON Schema draft-07
├── prompts/
│   └── prediction_prompt.txt   # prompt único para todos
└── FREEZE.md                   # registro de auditoría
```

---

## Añadir un modelo nuevo

1. Registrarlo en `src/models_config.py`:
```python
{"name": "Nombre-Modelo", "model_id": "proveedor/modelo", "provider": "Lab"}
```
2. Ejecutar: `python src/run_predictions.py --models Nombre-Modelo`
3. El JSON generado va a `predictions/pre-tournament/`

---

## Inspiración

Proyecto inspirado en [WorldCupBench](https://github.com/mverab/WorldCupBench) de [@mverab](https://github.com/mverab). Esta versión reescribe la lógica de agregación, añade la integración con Polymarket y el motor de apuestas por Criterio de Kelly.

---

<p align="center">MIT License · 2026</p>
