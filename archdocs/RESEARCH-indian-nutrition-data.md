# Research: Nutrition Data Sources for Indian-Subcontinent Foods

**Status:** Research only — no decision made, no code written. Input to a future ADR-007.
**Date:** 2026-09-12
**Author:** Research pass for Siddhant Tomar
**Motivates:** ADR-004's committed baseline of **37.1% calorie MAPE** on `parse_meal_text`

---

## Why this was investigated

The ADR-004 baseline says item precision is 91.2% and item recall is 99.0%, but calorie MAPE is 37.1%. The model is *identifying* foods almost perfectly and *quantifying* them badly. That is a numeric-recall failure, and prompt iteration has no headroom against it — you cannot prompt a model into remembering a number it never reliably encoded.

The obvious fix is to stop asking the LLM for numbers and look them up instead. The original plan was USDA FoodData Central. That plan is wrong for this project, for two independent reasons found during this pass.

---

## Finding 0: USDA is the wrong source, and unreachable anyway

**Wrong source.** CalAI's own eval dataset is Indian-dominant. Of 70 examples:

| Dataset file | Examples |
|---|---|
| `north_indian.jsonl` | 17 |
| `south_indian.jsonl` | 17 |
| `snacks.jsonl` | 16 |
| `meals.jsonl` | 12 |
| `western_and_desserts.jsonl` | 8 |

34 of 70 sit in explicitly Indian category files; 37 of 70 match an Indian-dish keyword anywhere in the record. The actual inputs are `"2 rotis with dal"`, `"a bowl of chicken biryani"`, `"paneer butter masala with rice"`, `"a bowl of curd rice"`, `"aloo paratha with curd"`. A US food-composition table is not the reference data for that workload.

**Unreachable.** `api.nal.usda.gov` returns no response from either sandbox this project is developed in — the Claude Code cloud container's egress proxy denies it by organization policy, and the local device VM cannot reach it either. `integrate.api.nvidia.com` is also unreachable from the device VM, which separately means **`evals/run_eval.py` cannot be run from an agent session** — only from the host Mac directly. Any design that depends on a live third-party nutrition API cannot be verified in the environment where the code gets written.

Both reasons point the same way: prefer an offline, vendored dataset over a live API.

---

## The landscape splits into three layers

No single free source covers all three. Conflating them is the main way this decision goes wrong.

### Layer 1 — Raw ingredients: solved, free, authoritative

**IFCT 2017** (Indian Food Composition Tables, National Institute of Nutrition / ICMR, Hyderabad) is the authoritative Indian reference. Verified directly against the packaged CSV:

- **542 foods, 421 columns**, measured across six regions
- Energy is `enerc` in **kJ**, not kcal — divide by 4.184 (spot-check: Bengal gram dal `enerc=1377` → 329 kcal/100g, correct for dry chana dal)
- Macros: `protcnt` (protein), `fatce` (fat), `choavldf` (available carbohydrate), `fibtg` (fibre)
- Every value has a paired `_e` column carrying its measurement error
- **`lang` column holds regional-language synonyms per food** — e.g. Bengal gram dal lists `Cholar dal` (Bengali), `Chana-ki-dal` (Hindi), `Kadale bele` (Kannada), `Kadala parippu` (Malayalam), `Sanaga papu` (Telugu), `Kadalaiparuppu` (Tamil), `Harabara dal` (Marathi)
- Companion tables in the same package: **`yieldfactors`** and **`retentionfactors`** — the raw→cooked conversion data

The `lang` column is the standout asset. It means Hinglish and regional meal text ("sanaga papu", "kadalaiparuppu") can resolve to one food code. No US-centric source offers that at any price.

**Availability:** packaged as CSV at [github.com/nodef/ifct2017](https://github.com/ifct2017/compositions) (`compositions/index.csv`, 1.15 MB) — **AGPL-3.0-or-later**. Original source PDF is free from NIN at [nin.res.in/ebooks/IFCT2017.pdf](https://www.nin.res.in/ebooks/IFCT2017.pdf). A [Kaggle mirror](https://www.kaggle.com/datasets/gijoe707/ifct2017) exists. The web front-end at [ifct2017.github.io](https://ifct2017.github.io/) has a rich natural-language query UI but **documents no HTTP API** — it is not programmatically consumable.

**The catch:** IFCT is a *raw ingredient* table. Its food groups are Marine Fish (92), Other Vegetables (78), Fruits (68), Animal Meat (63), Green Leafy Vegetables (34), Condiments and Spices (33), Grain Legumes (25), Cereals and Millets (24) — and essentially no prepared dishes. A name search for cooked preparations returns 8 hits, all boiled eggs. "Bengal gram dal" is dry split chana at 329 kcal/100g; a katori of cooked dal is mostly water and nothing like that number.

### Layer 2 — Cooked dishes: not solved by any free source at usable scale

This is where CalAI's actual eval inputs live, and it is the hard layer.

- **Kaggle dish datasets** — e.g. [Indian Food Nutritional Values (2025)](https://www.kaggle.com/datasets/batthulavinay/indian-food-nutrition), roughly 250-300 dishes, license not verifiable without opening the page in a browser. Fixture-grade, not product-grade.
- **IFCT** — does not cover this layer at all, by design.
- **[Bon Happetee](https://www.bonhappetee.com/nutrition-database-api)** — the only source that genuinely targets this layer. Claims ~20,000 items, "50+ types of dosas, 20+ rotis, 30+ subjis, 15+ dals, each with regional variants", computed from standard Indian recipes with ingredient values sourced from IFCT/NIN and USDA. Critically, it ships **Indian portion units**: katori = 125 g of dal or sabzi, 1 idli = 40 g, ladle of sabzi, cup of cooked rice — plus cross-language aliases (Aloo = Batata = Urulai Kizhangu) and stated Hinglish handling.
  **But:** no published pricing, no public API documentation (the docs link on their site is a dead anchor), no self-serve keys, access via sales call with "get started in 24 hours". Not something you can start coding against tonight, and not costable without contacting them.

### Layer 3 — Packaged/branded: free and easy, but not your problem

**[Open Food Facts India](https://in.openfoodfacts.org/)** — 22,952 products, free public API, no key required, Hindi locale available. This is barcode-scanned retail SKUs (Amul, Britannia, Maggi), not home-cooked food. Genuinely useful *later*, for a barcode-scan feature. Irrelevant to the MAPE problem.

---

## The architectural consequence

Layer 1 is free and authoritative. Layer 2 is where the workload actually is, and it is either paid, gated, or absent. The gap between them is a **recipe decomposition** problem — and that is the one part of this that an LLM is genuinely good at.

This suggests splitting `parse_meal_text`'s single job in two:

1. **LLM decomposes the dish into ingredients with gram weights.** `"1 katori sambar"` → toor dal 30 g (dry), mixed vegetables 80 g, oil 5 g, tamarind 10 g. This is language and structure work — recall of *composition*, not recall of *numbers* — and is squarely in the model's competence.
2. **IFCT arithmetic computes the calories deterministically** from those grams, applying yield factors for cooking.

Why this is worth doing beyond the MAPE number:

- It converts an unverifiable numeric guess into a **verifiable structured claim**. You can look at "30 g toor dal" and judge it wrong. You cannot look at "412 kcal" and judge anything.
- It gives every item a **provenance field** — grounded from IFCT code `B001` vs. LLM estimate — which is both a real UX affordance (show the user what's a guess) and a strong portfolio detail.
- It makes the eval harness sharper: decomposition accuracy and lookup accuracy become separately scorable, instead of one opaque MAPE.
- Failure degrades gracefully: an unmatched ingredient falls back to the LLM's own estimate for that item only, not the whole meal.

The honest risk: decomposition introduces its own error, and portion estimation ("a bowl of", "1 katori") stays a guess either way. It is plausible this lands at similar MAPE with better explainability rather than dramatically better MAPE. That is exactly what `run_eval.py --gate --baseline evals/report/latest.json` exists to settle, behind a `USE_IFCT_GROUNDING` flag defaulting off — the same rollout shape ADR-003 used for `USE_ORCHESTRATOR`.

---

## Open decisions (not made here)

1. **Data sourcing and licensing.** The convenient CSV is AGPL-3.0-or-later. Vendoring it into CalAI implies CalAI is AGPL if distributed. Options: commit it and go AGPL; fetch it at setup into a gitignored `data/` dir so nothing AGPL is redistributed; or extract from the NIN PDF directly, where the underlying data is an ICMR government publication rather than someone's AGPL packaging.
2. **Whether to pay for layer 2.** Bon Happetee is the shortcut past the hard part. Worth one sales email to find out the number before committing to build decomposition.
3. **Portion unit table.** "Katori", "bowl", "plate", "1 roti" need gram weights regardless of which source backs the lookup. This is a small hand-built table (~30 entries) and is needed under every option above.

## Unverified items

- Kaggle dish dataset licenses — pages are JavaScript-rendered and were not readable programmatically.
- Open Food Facts' exact license name (ODbL is likely but was not confirmed on the pages read) and exact India product count via the v2 API (robots.txt blocks the API path to automated fetchers; a plain `curl` from the host Mac will return it).
- Bon Happetee's pricing, endpoints, and real item count — all sales-gated.
