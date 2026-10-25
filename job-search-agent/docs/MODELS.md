# MODELS.md

Chosen model ids and routing for the job-matching pipeline. All picks are **$0.00**.
Model ids are confirmed live at setup with `python -m jobagent.cli models` (calls
`GET {base}/models` with the user's key). If a chosen model disappears from the free
catalog, the adapter moves to the next row down this file; it must never silently drop to a
tiny toy model while a DeepSeek-V4-class / Kimi-K3-class endpoint is still free.

Sources: `docs/RESEARCH.md` sections C.1–C.5. LiveBench release **2026-06-25**.

---

## 1. Quality target (LiveBench 2026-06-25, $0-reachable)

| Rank | Model (LiveBench id) | Overall\* | Coding | Agentic Coding | Reached via |
|---|---|---|---|---|---|
| 1 | deepseek-v4.1-flash-max | 81.1 | 80.0 | **77.3** | NVIDIA |
| 2 | muse-spark-1.3-xhigh | 81.6 | 81.1 | 64.1 | Zen contributor-free (opt-in) |
| 3 | kimi-k3 | 79.2 | 81.4 | 62.2 | NVIDIA |
| 4 | qwen3.8-max | 78.5 | 72.9 | 64.6 | NVIDIA/other free |
| 5 | deepseek-v4-pro-0813 | 77.4 | 77.2 | 54.9 | NVIDIA |
| 6 | glm-5.3 | 76.1 | 79.0 | 60.9 | NVIDIA |
| 7 | qwen3.8-flash-next | 76.2 | 72.6 | 61.6 | fast fallback |
| 8 | glm-5.3-flash | 71.6 | 79.0 | 56.8 | fast fallback |

\*Overall recomputed as the mean of the 7 LiveBench category averages. Agentic Coding here
= mean(javascript, typescript, python) in this release.

**Primary judge = DeepSeek V4.1 Flash** (`deepseek-ai/deepseek-v4.1-flash` on NVIDIA):
best Agentic Coding among $0 models, and good enough at instruction-following to emit
validated JSON rationales.

---

## 2. Routing

| Role | Model id (NVIDIA unless noted) | Why |
|---|---|---|
| Resume structured extraction (once, cached) | `deepseek-ai/deepseek-v4.1-flash` | Best $0 all-rounder; runs once |
| Judge / matcher / evidence rationale | `moonshotai/kimi-k3` | Best $0 Reasoning (90.7); see §7 |
| Long, messy job descriptions | `moonshotai/kimi-k3` then `deepseek-ai/deepseek-v4.1-flash` | Long context |
| Bulk classify (easy_apply vs external, spam) | `nvidia/nemotron-3.5-lightning-30b-a3b`, then `nvidia/nemotron-3-ultra-550b-a55b` (IF 73.4) | Fast, then verified |
| Backup judge #1 (privacy-safe) | Zen `space-bunny-free` / `longcat-2.5-preview-free` | Zero-retention |
| Backup judge #2 | OpenRouter `:free` (`nvidia/nemotron-3-ultra-550b-a55b:free`) | 20 RPM / 50 RPD |
| Backup judge #3 | Groq free (`openai/gpt-oss-120b`) | 30 RPM / 1K RPD |
| Last resort | **deterministic scorer only** | Never pay, never stop |

**Escalation order for a judge call:** primary NVIDIA → secondary NVIDIA → privacy-safe Zen
free → OpenRouter/Groq free → deterministic-only. A 429 on one model fails over to the next;
it never authorises a paid model.

---

## 3. Privacy gate (mandatory, enforced in code)

NVIDIA Trial ToS §2.6(a) forbids sending **personal data**, and §3.3 trains on inputs.
Meta contributor-free trains on inputs. Therefore:

- **Never send to any hosted model:** name, email, phone, address, links, employer names,
  CTC/LPA numbers, notice period, PAN/Aadhaar, passwords.
- **Allowed to send:** job title, must-have/nice-to-have skill tokens, years bands, seniority,
  location city, remote flag, de-identified resume bullet text (skills-per-bullet only).
- A local `PIIRedactor` strips the deny-list before every cloud call, and a unit test asserts
  no raw PII field can reach the adapter.

Models that are acceptable for **non-PII** work but **not** for PII: all NVIDIA trial endpoints,
`muse-spark-1.3-contributor-free`, `big-pickle`, `mimo-*`, `ling-*`.
Privacy-safe for redacted text: `space-bunny-free`, `longcat-2.5-preview-free`, OpenRouter
`:free`, Groq free.

---

## 4. Free ids — reference

**NVIDIA** (`https://integrate.api.nvidia.com/v1`, OpenAI-compatible):
`deepseek-ai/deepseek-v4.1-flash`, `deepseek-ai/deepseek-v4-pro-0813`, `z-ai/glm-5.3`,
`moonshotai/kimi-k3` (verify live), `nemotron-3-ultra-550b-a55b`,
`nemotron-3.5-lightning-30b-a3b`, `nemotron-3-super-120b-a12b`, `gpt-oss-20b`.

**OpenCode Zen free** (`https://opencode.ai/zen/v1`):
`space-bunny-free`, `longcat-2.5-preview-free`, `nemotron-3-ultra-free`,
`nemotron-3.5-lightning-free`, `muse-spark-1.3-contributor-free`, `big-pickle`,
`mimo-v2.6-flash-free`, `mimo-v2.5-free`, `ling-3.0-flash-fin-free`, `jev-1.13-free`.
(Paid Zen ids are banned and must never be configured.)

**OpenRouter free:** `:free` suffix. **Groq free:** per `console.groq.com/docs/rate-limits`.

---

## 5. Why the judge follows IF+Reasoning, not Agentic Coding (re-verified 2026-10-05)

Recomputed from the live `table_2026_06_25.csv` (66 models). The judge's job is
following strict JSON-output rules with evidence (IF) plus nuanced fit reasoning
(Reasoning) — not writing code. IF = paraphrase/simplify/story_generation/summarize;
Reasoning = theory_of_mind/zebra_puzzle/spatial/logic_with_navigation.

| $0-reachable model | IF | Reasoning | Language | Coding | Agentic | $0 path |
|---|---|---|---|---|---|---|
| muse-spark-1.3-xhigh | **78.0** | 89.7 | 82.8 | 81.1 | 64.1 | Zen free (trains on data — opt-in) |
| qwen3.8-flash-next | 77.1 | 87.4 | 74.6 | 72.6 | 61.6 | none verified — not used |
| nemotron-3-ultra-550b-a55b | 73.4 | 74.7 | 70.8 | 70.7 | 38.7 | NVIDIA live |
| qwen3.8-27b | 72.7 | 80.0 | 74.3 | 75.7 | 61.4 | Groq free |
| kimi-k3 | 71.4 | **90.7** | 85.5 | 81.4 | 62.2 | NVIDIA live — **judge primary** |
| deepseek-v4.1-flash-max | 70.0 | 86.7 | 81.2 | 80.0 | 77.3 | NVIDIA live — judge secondary |
| glm-5.3 | 69.3 | 85.8 | 79.9 | 79.0 | 60.9 | none on this key — not used |
| deepseek-v4-pro-0813 | 67.7 | 85.8 | 82.1 | 77.2 | 54.9 | none on this key — not used |
| qwen3.8-max | 74.1 | 88.2 | 79.7 | 72.9 | 64.6 | none verified — not used |
| muse-spark-1.2-xhigh | 74.3 | 90.0 | 78.6 | 77.5 | 57.6 | Zen free (trains on data — opt-in) |

Correction to the earlier routing: DeepSeek V4.1 Flash led on Agentic Coding
(javascript/typescript/python), which measures *writing code*, not judging fit —
irrelevant to emitting a validated match-JSON. On the judge's actual skills Kimi K3
wins (Reasoning 90.7, Language 85.5; IF 71.4), with 1M+ context for messy JDs as a
bonus. DeepSeek stays second as the best all-rounder and the codegen-helper model.
`gemini-3.7-flash` (IF 79.9) has no allowed $0 source in this project, so it is out
of scope despite the score.

## 6. Reranker-first scoring (researched 2026-10-05, verified live)

For single (candidate, job) scoring, the literature converges on one stack —
bi-encoder retrieve → cross-encoder rerank → LLM judge only where judgment is
ambiguous (Lassance & Clinchant 2024: cross-encoders match GPT-4 listwise
in-domain; ConFit/ConFit-v2: contrastive bi-encoder + hard negatives for stage 1;
RankGPT/RankVicuna: listwise LLM judges most accurate but 10-100x the latency;
G-Eval: rubric + reference + validation for calibrated LLM scores; JudgeBench:
decompose hard inferences into verifiable sub-checks).

The pipeline mirrors it: deterministic skill/year/location features (free,
instant) → cross-encoder rerank 0-100 (one fast forward pass) → LLM judge only
inside the [60, 93] borderline band, with must-have misses hard-capped in code
(never by the model). Above 93 goes to inbox on deterministic evidence; below 60
is discarded without spending a token.

Rerank providers ($0 only), in chain order:
1. **Jina** (`jina-reranker-v2-base-multilingual`) — free key, ~10M tokens, 100 RPM.
2. **Voyage** (`rerank-2.5-lite`) — 200M tokens free one-time.
3. **local_bge** (`BAAI/bge-reranker-v2-m3`, Apache-2.0) — zero network, zero key.
4. **Cohere trial** (`rerank-v3.5`) — ~1k calls/month, kept last as audit reserve.

NVIDIA's hosted rerank paths are dead (ai.api… 410 end-of-life 2026-05-18;
integrate…/v1/ranking 404), so NVIDIA is not in the rerank chain.

**Live proof on this machine (2026-10-05, CPU-only torch, bge-reranker-v2-m3):**
good-fit resume–JD pair **99.2 in 0.44s**, bad-fit pair **0.1 in 0.26s** —
decisive discrimination at ~3 pairs/second with no network and no key. Model
loads once (~54s first run, cached in RAM after), weights cached on disk.

Setup: `pip install torch --index-url https://download.pytorch.org/whl/cpu`
then `pip install -e ".[local]"`. For Jina/Voyage/Cohere, create the free key on
the provider dashboard and paste it into `.env` (`JINA_API_KEY` etc.) — no code
changes; absent keys fail soft.

## 7. Rate-limit strategy

NVIDIA publishes no numeric free-tier limit; expect 429s. Design:

- Per-model **daily call budget** in SQLite; reset at UTC midnight.
- **Exponential backoff** with jitter on 429/5xx; honour `Retry-After` if present.
- **Queue** judge calls; never fire a model call per job in a large result set.
- **Cache** by `(resume_hash, job_hash, prompt_version)` — a repeat run costs zero tokens.
- Deterministic pre-filter discards obvious misses before any model call.
- On exhaustion: fall through the escalation order, then deterministic-only.

## 8. Full free-provider landscape (researched 2026-10-06)

Card-free, persistent $0 sources worth wiring, in priority order:

1. **Groq free** — `openai/gpt-oss-120b`, `qwen/qwen3.8-27b` (the only chat ids on
   the free plan): 30 RPM / 1K RPD / 200K TPD each, OpenAI-compatible,
   no card. Qwen3.8-27B is the best verified $0 judge (LiveBench IF 72.7,
   IFBench 79.5%, ~450 tok/s); gpt-oss-120b is the fastest fallback (~500 tok/s).
   Verified live 2026-10-06: valid judge JSON in 0.9s through the adapter.
   Note: api.groq.com also Cloudflare-blocks urllib (1010) — the adapter
   retries any urllib 403 once via the OS curl binary, which passes.
2. ~~Mistral Studio free mode~~ — **BLOCKED, verified 2026-10-06 on the live
   console**: the API Keys page shows "Upgrade to use your API keys — Your
   organization is on the Free plan. Upgrade to activate your API keys," with
   key creation disabled. The docs' "free mode, no card" does not extend to
   API keys. Removed from chains; provider plumbing stays (one-line re-add if
   this ever changes).
3. **OpenRouter `:free`** — 20 RPM / 50 RPD; diversity overflow only. Verified
   live 2026-10-06: key works, 16 free ids (incl. our
   `nvidia/nemotron-3-ultra-550b-a55b:free`), inference OK in ~3s over plain
   urllib (no fingerprint block). Note: `qwen/qwen3.8-27b:free` is currently
   absent from the free list — free ids rotate; check before depending on one.
4. **Google AI Studio free** — evaluated and deferred: generous, but closed
   models that train on free-tier inputs; no allowed need while open options exist.
5. **Cloudflare Workers AI** — deferred: 10K neurons/day is tight and the endpoint
   is not vanilla OpenAI-shaped (wrapper work for ~30-150 calls/day).

Explicitly excluded after verification: GitHub Models (**retired** 2026-07-30),
Cerebras/Nebius/Together/Fireworks (card-mandated or expiring trials only),
Alibaba/Novita/Chutes/etc. (no verifiable persistent card-free tier).

Cross-source quality picture (LiveBench IF / Reasoning recomputed 2026-10-05;
LMArena open text; AA intelligence@speed): kimi-k3 (90.7 Reas) and qwen3.8-max
remain the quality kings with no verified free endpoint; among reachable ones,
qwen3.8-27b (72.7/80.0) then DeepSeek-V4.1-Flash (70.0/86.7, fastest at 213 tok/s).
Papers agree 27B reasoning models match 200B+ on verifiable-constraint following
within points (JudgeBench/CodeJudgeBench/MM-JudgeBench), so the small-fast
judge tier is principled, not a compromise.

## 9. Checks run at setup

```
python -m jobagent.cli models        # GET {base}/models, print free ids actually served
```
Write the ids that returned 200 into this file's "confirmed live" list below.

### Confirmed live (verified 2026-09-28 with the user's key; 81 models served; chains re-verified 2026-10-05)
- `deepseek-ai/deepseek-v4.1-flash` — judge primary. Live.
- `moonshotai/kimi-k3` — long-context + judge secondary. Live.
- `nvidia/nemotron-3-ultra-550b-a55b` — judge tertiary. Live (note the `nvidia/` prefix).
- `nvidia/nemotron-3.5-lightning-30b-a3b` — bulk classifier. Live (note the `nvidia/` prefix).
- `mistralai/mistral-7b-instruct-v0.3` — classifier fallback. Live.
- NOT served on this key (removed from chains): `z-ai/glm-5.3`, `z-ai/glm-5.3-flash`,
  `deepseek-ai/deepseek-v4-pro-0813`, bare `nemotron-3.5-lightning-30b-a3b` (needs prefix).
- _zen (key added 2026-10-06, shootout 2026-10-06):_ only `space-bunny-free`
  is callable from scripts. All other free ids (`longcat-2.5-preview-free`,
  `nemotron-3.5-lightning-free`, `mimo-*`, `ling-3.1-flash-free`,
  `fledge-alpha-free`, `muse-spark-1.3-contributor-free`) return
  `FreeTierError: OpenCode's free tier can only be used from within OpenCode`
  on direct API calls — removed from chains (one-line re-add if that changes).
- _zen shootout (real judge prompts, 3 pairs):_ `space-bunny-free` returns
  valid evidence-backed JSON with sensible scores (86 on a 78.4 borderline job),
  ~17-31s per call, zero-retention provider. Rank: working fallback behind
  NVIDIA, not a primary (unknown benchmark standing; reasoning-heavy latency).
  Note: it needs generous max_tokens (reasoning trace precedes the JSON).