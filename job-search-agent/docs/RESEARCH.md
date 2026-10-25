# RESEARCH.md

Primary-source research for a **single-user, local-only, $0.00** job-search operating
system. Target platforms: LinkedIn and Naukri.com (India). Target machine: the user's
own Windows 11 desktop. All research below was done against primary sources; every
non-primary claim is labelled **INFERENCE** or **COMMUNITY-REPORTED**.

Legend:
- **FACT** — read directly on a primary page (URL given).
- **INFERENCE** — reasoned conclusion, not stated verbatim.
- **COMMUNITY-REPORTED** — widely repeated but not confirmed on a primary page.

---

## 0. Method

Research ran in four parallel tracks: (A) LinkedIn terms + APIs + apply mechanics,
(B) Naukri/Info Edge terms + apply mechanics + DPDP, (C) free model catalogs
(LiveBench, NVIDIA NIM, OpenCode Zen, others), (D) free infrastructure (Gmail,
browser automation, scheduler, parsers). Each track fetched primary pages only.

A short "Disagreements with the brief" section is at the end (mandatory per the brief).

---

## A. LinkedIn

### A.1 Prohibited software and extensions — **FACT / ADVERSE**

URL: https://www.linkedin.com/help/linkedin/answer/a1341387

Exact quotes:

> "we don't permit the use of any third party software, including 'crawlers', bots,
> browser plug-ins, or browser extensions that scrape, modify the appearance of, or
> automate activity on LinkedIn's website."
>
> "Any member who uses tools for such purposes is in violation of the User Agreement.
> This means that they risk having their accounts restricted or shut down."

This is the single most adverse fact for any automation project. It explicitly names
"automate activity," not just scraping, and does not carve out "my own account / my own
logged-in browser."

**INFERENCE:** Even a local, user-session, low-volume worker that clicks Easy Apply is
covered by the plain text of this policy. The brief already accepts this risk; the design
must therefore minimise detection surface and document the risk in USER_GUIDE.md.

### A.2 User Agreement §8 "Dos and Don'ts" — **FACT**

URL: https://www.linkedin.com/legal/user-agreement (header: "Effective on November 3, 2025")

Exact current clauses:

- **8.2.2** "Develop, support or use software, devices, scripts, robots or any other means
  or processes (such as crawlers, browser plugins and add-ons or any other technology) to
  scrape or copy the Services, including profiles and other data from the Services."
- **8.2.3** "Override any security feature or bypass or circumvent any access controls or
  use limits of the Services (such as search results, profiles, or videos)."
- **8.2.13** "Use bots or other unauthorized automated methods to access the Services, add
  or download contacts, send or redirect messages, create, comment on, like, share, or
  re-share posts, or otherwise drive inauthentic engagement."
- **8.2.15** "Overlay or otherwise modify the Services or their appearance."
- **8.2.16** "Interfere with the operation of, or place an unreasonable load on, the Services."

Note: the current list has **19** clauses; the brief's numbering (8.2.2/8.2.3/8.2.13/8.2.16)
matches functionally but bots are 8.2.13 here, not 8.2.13-of-a-13-item list.

### A.3 Official developer APIs for job seekers — **FACT**

URLs: https://developer.linkedin.com/ ,
https://learn.microsoft.com/en-us/linkedin/ ,
https://learn.microsoft.com/en-us/linkedin/shared/authentication/getting-access

- Open (self-serve) permissions are **only**: Sign in with OpenID Connect (`profile`,
  `email`) and Share on LinkedIn (`w_member_social`). **No job-search or job-apply scope.**
- Recruiter System Connect, Apply Connect, Apply with LinkedIn, Job Posting API are
  **partner/ATS/employer gated**. Apply with LinkedIn: "we are currently **not accepting
  any new partners**." RSC: restricted to developers "approved by LinkedIn" who "sign an
  API agreement."

**INFERENCE:** There is **no free, self-serve API** for a job seeker to search and apply.
The local logged-in session is the only $0 path; it is a fallback, not a right.

### A.4 Easy Apply mechanics — **FACT**

URLs: https://www.linkedin.com/help/linkedin/answer/a512388 ,
https://www.linkedin.com/help/linkedin/answer/157 ,
https://www.linkedin.com/help/linkedin/answer/a510363

- "**Easy Apply**" applies on LinkedIn; "**Apply**" redirects to the company/third-party site.
- Flow: job title → Easy Apply → popup screens (required info) → Review → Submit.
- Resume: "recommend a file size less than 2MB... Microsoft Word or PDF." Up to 4 saved resumes.
- "You cannot edit or withdraw an application once submitted through LinkedIn."
- Requires desktop browser or the mobile app.

### A.5 Detection & limits — **FACT**

URLs: https://www.linkedin.com/help/linkedin/answer/a8068422 ,
https://www.linkedin.com/help/linkedin/answer/a7428062 ,
https://www.linkedin.com/help/linkedin/answer/a1441505

- "**Daily Easy Apply limit** — You can submit a set number of Easy Apply applications each
  day... resets at the end of the day (UTC)." (Numeric value **not published**.)
- "**Speed Easy Apply limit** — Rapidly submitting applications in a short time triggers a
  **temporary pause** on Easy Apply. This helps prevent automation and bots."
- LinkedIn "may **lower** a member's daily Easy Apply limit if we notice activity that seems
  inauthentic."
- Repeated violations → feature restriction; "some violations... will still result in
  **permanent account restriction**"; "Some cases may lead to account restriction at the
  first violation."

**FACT:** The only published numeric search limit is **1,000 results per search**.

**COMMUNITY-REPORTED (not primary):** CAPTCHA checkpoints, ~100–150 applications/week,
20–25 connection requests/day. Treat as unverified.

### A.6 Job search URL parameters — **FACT (observed) + INFERENCE**

Observed on a live LinkedIn SERP:
`https://www.linkedin.com/jobs/search/?keywords=...&f_TPR=r604800&f_AL=true&f_WT=2&f_E=3`

- `f_TPR=r604800` = time-posted range in **seconds** (604800 = 7 days). Directly observed.
- `f_AL=true` = Easy Apply. Directly observed.
- `f_WT=2` = Remote workplace type. Directly observed.
- `f_E=3` = experience level (observed value 3). Directly observed.
- `f_EA=true` = "Under 10 applicants." Directly observed.

**INFERENCE (not directly observed):** `f_TPR=r86400` = 24h and `r2592000` = 30 days follow
the same seconds convention. Other `f_WT` (1=onsite, 3=hybrid) and `f_E` (1–6) values are
community mappings. **Caution:** LinkedIn states it is "gradually retiring classic job
search starting in September"; filters are unstable. Collectors must not depend on one
exact param forever and must detect a changed UI.

---

## B. Naukri / Info Edge

### B.1 Terms & Conditions — **FACT / ADVERSE**

- `https://www.naukri.com/terms-conditions` → 404. `.../termsandconditions` → 404.
- Live page: **`https://www.naukri.com/termsconditions`** ("Terms & Conditions for Job
  Seekers and Recruiters"), a React SPA. Full text recovered via Wayback capture
  `https://web.archive.org/web/20250119170343/https://www.naukri.com/termsconditions`.

Exact clauses ("THE USER REPRESENTS, WARRANTS AND COVENANTS THAT ITS USE OF NAUKRI.COM
SHALL NOT BE DONE IN A MANNER SO AS TO"):

- **10.** "Use any device, software or routine to interfere or attempt to interfere with the
  proper working of Naukri.com."
- **11.** "Impose an unreasonable or disproportionately large load on Naukri.com infrastructure."
- **17.** "Use automated means to crawl and/or scrape content from Naukri.com and to manually
  scrape content from Naukri.com."
- **18.** "The Site uses technological means to exclude Robots etc. from crawling it and
  scraping content. You undertake not to circumvent these methods."
- **19.** "Access the Site except through the interfaces expressly provided by IEIL."
- **21.** "...Extracting data from Naukri.com using any automated process such as spiders,
  crawlers etc. or through any manual process for a purpose which has not been authorised in
  writing."

Also **ADVERSE / CONFIRMING**: `https://www.naukri.com/jobapi/v3/search` unauthenticated
returned `{"message":"recaptcha required","statusCode":406}` — active bot mitigation.

### B.2 robots.txt — **FACT**

URL: https://www.naukri.com/robots.txt

- For `User-agent: *`, search/apply paths are **not** disallowed (only `/advertiser/`,
  `/preview/`, `/photo/`, `/profilePic/`, `/gpw/`, `/jg/`, `/lls/tm/`, `/alljobs/job/`,
  `om.php`, `j2.php`, recruiter paths, `skill360*`).
- **All named AI crawlers** (`gptbot`, `claudebot`, `perplexitybot`, `ccbot`,
  `Google-Extended`, `ChatGPT-User`, ...) get **`Disallow: /`**.
- Header updated "May 13, 2026 (updated artificial intelligence crawlers)."

**INFERENCE:** robots.txt does not block a human-equivalent agent on search/apply paths,
but the AI-crawler blanket block plus T&C §§17–21 show clear anti-automation intent.

### B.3 Apply mechanics — **FACT + INFERENCE**

- Two modes exist: in-platform one-click **Apply** vs **"Apply on company website"**
  (employer/listing dependent).
- Resume upload constraints (from Naukri's own bundle `main.b88f6e6b.min.js`):
  extensions `doc, docx, pdf`, max size **2 MB**.
- T&C Jobseeker **clause 11**: Naukri is "not responsible for the content of the Employer's
  application form, messages, **screener questions**..."
- **Gated:** `help.naukri.com`, `support.naukri.com` unreachable; `www.naukri.com/faq/jobseeker`
  returns only an SPA shell. Could not read a primary jobseeker help page on apply flow.

### B.4 Search URL structure & filters — **FACT (observed) + INFERENCE**

From Naukri's route builder (`main.b88f6e6b.min.js`):

- `/{keyword}-jobs`, `/jobs-in-{location}`, `/{keyword}-jobs-in-{location}`,
  `/walkin-{keyword}-jobs-in-{location}`; pagination `-{pageNo}` appended.
- Query params used: `k` (keyword), `l` (location), `experience`, `jobType`.
- A live request echoed `jobAge=7&sort=dd`.

**INFERENCE:** `jobAge` = freshness in **days**; `sort=dd` = date descending. Day options
1/3/7/15/30 and `sort=r` (relevance) are community-reported; only `jobAge=7` and `sort=dd`
were confirmed.

### B.5 Job-alert emails — **FACT**

- `https://www.naukri.com/mnjuser/jobalerts` → 200 (login-gated).
- T&C §20(b): users "Receive job alerts (mails detailing jobs that match your profile...)";
  removable in "Privacy Setting section."
- Privacy Policy lists processing for "job alerts, calendar alerts, relevant search results."

**INFERENCE:** Alert emails are a viable fallback intake, but parsing them still processes
Naukri data outside an "interface expressly provided," so it carries §17/§21 risk too.

### B.6 Resume refresh — **FACT**

- `https://www.naukri.com/resume-refresh` → 200.
- T&C §19: changes "come into operation only after **24-48 hours**."
- T&C §6: multiple resumes beyond a reasonable limit → Info Edge may remove them.

**INFERENCE:** The widely repeated "refresh every 60–90 days" cadence is
COMMUNITY-REPORTED, not primary. Use no unofficial refresh endpoint.

### B.7 Rate limits / restrictions — **FACT**

No numeric rate limit is published on any primary Naukri page. The 406 "recaptcha required"
on the internal search API is the only concrete anti-bot evidence found.

### B.8 India DPDP Act 2023 — **FACT**

URL: https://www.meity.gov.in/data-protection-framework (Act No. 22 of 2023, MeitY)

- **§3(c)(i):** the Act "shall not apply to... personal data processed by an individual for
  any **personal or domestic purpose**."
- **§6(1):** consent must be "free, specific, informed, unconditional and unambiguous... limited
  to such personal data as is necessary for such specified purpose" (purpose limitation).

**INFERENCE:** This local, non-commercial tool processes only the user's own data for their
own job search → falls under the §3(c)(i) personal/domestic carve-out. Purpose limitation
still argues against collecting other people's data or reselling anything.

---

## C. Free model catalogs

### C.1 LiveBench (release 2026-06-25) — **FACT**

`https://livebench.ai/` is a JS app. Its data files were fetched directly:

- `https://livebench.ai/table_2026_06_25.csv`
- `https://livebench.ai/categories_2026_06_25.json`

**FACT (category composition):** Coding = `code_generation` + `code_completion`;
Agentic Coding = `javascript` + `typescript` + `python` (this release folds JS/TS/Python in).

**FACT (scores; category = mean of its tasks; Overall = mean of 7 category averages):**

| Model | Overall* | Coding | Agentic Coding |
|---|---|---|---|
| deepseek-v4.1-flash-max | 81.1 | 80.0 | **77.3** |
| muse-spark-1.3-xhigh | 81.6 | 81.1 | 64.1 |
| kimi-k3 | 79.2 | 81.4 | 62.2 |
| qwen3.8-max | 78.5 | 72.9 | 64.6 |
| deepseek-v4-pro-0813 | 77.4 | 77.2 | 54.9 |
| glm-5.3 | 76.1 | 79.0 | 60.9 |
| qwen3.8-flash-next | 76.2 | 72.6 | 61.6 |
| glm-5.3-flash | 71.6 | 79.0 | 56.8 |
| nemotron-3-ultra-550b-a55b | 67.4 | 70.7 | 38.7 |

`deepseek-v4.1-flash-max` has the best **Agentic Coding (77.3)** of any $0-reachable model,
matching the brief's snapshot. `deepseek-v4-pro` without the `-0813` tag is a **separate,
weaker** row (Overall 71.6, Agentic 42.6) — do not confuse the two.

### C.2 NVIDIA NIM free endpoints — **FACT**

URLs: https://build.nvidia.com/models , model pages e.g.
https://build.nvidia.com/deepseek-ai/deepseek-v4.1-flash , https://build.nvidia.com/z-ai/glm-5-3 ,
https://build.nvidia.com/moonshotai/kimi-k3

- Base URL: `https://integrate.api.nvidia.com/v1` (OpenAI-compatible).
- Confirmed IDs: `deepseek-ai/deepseek-v4.1-flash`, `deepseek-ai/deepseek-v4-pro-0813`,
  `z-ai/glm-5.3`, `moonshotai/kimi-k3` (ID inferred from path/publisher — the JS snippet was
  empty; verify live with the key), plus `nemotron-3-ultra-550b-a55b`,
  `nemotron-3.5-lightning-30b-a3b`, `nemotron-3-super-120b-a12b`, `gpt-oss-20b`.
- Each page: "governed by the NVIDIA API Trial Terms of Service."
- **No published RPM/RPD page exists** (`https://build.nvidia.com/rate-limits` → 404). The
  ToS only says limits are "defined by NVIDIA" and uses trial **Credits**.
- `https://integrate.api.nvidia.com/v1/models` requires the key (cannot be fetched bare).

**COMMUNITY-REPORTED (not primary):** ~40 RPM, ~1000 credits. Treat as unverified; measure
live with the key.

### C.3 NVIDIA API Trial Terms — **FACT / ADVERSE FOR PII**

Source: https://assets.ngc.nvidia.com/products/api-catalog/legal/NVIDIA%20API%20Trial%20Terms%20of%20Service.pdf

- §1.2: "limited trial purposes only and without use of the API Service or Generated Content
  in production."
- §2.3: NVIDIA "will not store or use User Content or Generated Content at the end of each
  API Service session" — with security-logging exceptions (§2.4).
- **§2.6(a):** you agree **not** to submit "confidential information, controlled or sensitive
  data, including protected health information, **personal data** (unless expressly permitted),
  payment card industry information..."
- **§3.3:** NVIDIA **will** collect "User Content and Generated Content to improve NVIDIA
  products and services, including AI models," "without identifying specific users."

**INFERENCE:** Real resumes/CTC/phone must **not** be sent to NVIDIA trial endpoints. This
alone mandates the PII-redaction design (skills, titles, date ranges, de-identified bullets
only — never name, email, phone, employer name).

### C.4 OpenCode Zen free models — **FACT**

URLs: https://opencode.ai/docs/zen/ , https://opencode.ai/zen/v1/models (public, no auth)

- Priced **Free** (input/output/cached all Free): `big-pickle`, `space-bunny-free`,
  `longcat-2.5-preview-free`, `mimo-v2.6-flash-free`, `mimo-v2.5-free`,
  `ling-3.0-flash-fin-free`, `nemotron-3-ultra-free`, `nemotron-3.5-lightning-free`,
  `muse-spark-1.3-contributor-free`, `jev-1.13-free`.
- All nine targets in the brief exist. Precision on two:
  - `muse-spark-1.3-contributor-free`: "permission to use your prompts and completions to
    train future Meta models."
  - `nemotron-3-ultra-free` / `nemotron-3.5-lightning-free`: Zen quotes NVIDIA trial terms —
    "do not submit personal or confidential data."
  - `space-bunny-free` / `longcat-2.5-preview-free`: **zero-retention, not used for training.**
  - `big-pickle`, `mimo-*`, `ling-*`: data "may be used to improve the model."
- Paid for contrast: `deepseek-v4.1-flash` ($0.30/$1.20), `kimi-k3` ($3/$15),
  `glm-5.3` ($1.40/$4.40), `qwen3.8-max` ($2/$6) — **banned**.
- Zen docs tell you to "add your billing details" on signup; whether the free tier gates on a
  card is not stated.

**INFERENCE:** For privacy, `space-bunny-free` / `longcat-2.5-preview-free` are the Zen free
models that do **not** train on the user's data. `muse-spark-1.3-contributor-free` and the
NVIDIA free endpoints do.

### C.5 Other genuinely $0 endpoints — **FACT**

- **Google AI Studio (free tier):** needs only a Google account; billing is required only to
  move to the **paid** tier (https://ai.google.dev/gemini-api/docs/rate-limits). Numeric
  per-model limits are JS-rendered and could not be extracted. **INFERENCE:** free-tier data
  may be used to improve Google products.
- **OpenRouter `:free` models:** e.g. `nvidia/nemotron-3-ultra-550b-a55b:free`,
  `inclusionai/ling-3.0-flash-fin:free`. Limits **20 RPM**; **50 RPD** (<$10 lifetime
  credits), **1000 RPD** (≥$10). Card not required to use free models
  (https://openrouter.ai/docs/api-reference/limits).
- **Groq free plan:** e.g. `openai/gpt-oss-120b` 30 RPM / 1K RPD / 8K TPM
  (https://console.groq.com/docs/rate-limits). Card requirement not stated.
- **Together:** no free tier; `prism-ml/ternary-bonsai-27b` at $0.00 but billing needed.
- **Cerebras:** pricing page JS-rendered; no primary confirmation of a card-free tier.

**INFERENCE:** These are acceptable **$0 fallbacks** but weaker on LiveBench. NVIDIA + Zen
free remain primary; OpenRouter/Groq are backup judges; the deterministic scorer always runs.

---

## D. Free infrastructure

### D.1 Gmail limits (personal @gmail.com) — **FACT**

URL: https://support.google.com/mail/answer/22839

> "more than **500 recipients in a single email** and or more than **500 emails sent in a day**."

Recovery 1–24h; anti-abuse soft limit, can change. (Workspace limits are higher and separate:
https://support.google.com/a/answer/166852.)

### D.2 App password + SMTP — **FACT**

URL: https://support.google.com/accounts/answer/185833

- 16-character app password; requires **2-Step Verification** on the account.
- Hosts/ports: SMTP `smtp.gmail.com:587` STARTTLS (465 SSL alt); IMAP `imap.gmail.com:993` SSL
  (https://support.google.com/a/answer/9003945).

### D.3 Gmail API quotas + OAuth — **FACT**

URL: https://developers.google.com/gmail/api/reference/quota (updated **May 1, 2026**)

- 1,200,000 quota units/minute/project; 6,000/minute/user/project; daily threshold
  80,000,000 units/day/project. `messages.send` = 100 units. "available at no additional cost."
- The often-quoted "1,000,000,000 units/day" is **not** the current number.
- **Credit card:** Free-Trial signup requires a card; enabling Gmail API under free quota does
  not itself require billing (https://cloud.google.com/free/docs/free-cloud-features).
- **OAuth Testing mode:** refresh tokens expire **seven days** for non-basic scopes
  (`gmail.send`/`gmail.readonly` are not excepted) (https://support.google.com/cloud/answer/15549945).

**INFERENCE:** IMAP + app password avoids the 7-day re-consent churn and the OAuth
verification burden. Gmail API is the future-proof option but needs a client-secret JSON and
weekly re-consent while in Testing.

### D.4 Reading job-alert mail — **FACT**

- `gmail.readonly` is a **restricted** scope; `gmail.send` is **sensitive**
  (https://developers.google.com/gmail/api/auth/scopes).
- **IMAP is always turned on in Gmail since Jan 2025**; with 2FA, use an app password
  (https://support.google.com/mail/answer/7126229).

**INFERENCE:** For a local single-user tool, **IMAP read + SMTP send with one app password**
is the lowest-friction $0 path once the Gmail UI filters create label folders.

### D.5 Attaching to the user's logged-in Chrome — **FACT (critical)**

- **Playwright:** `launch_persistent_context(user_data_dir, ...)` uses persistent storage at
  `user_data_dir`. Docs warn "browsers do not allow launching multiple instances with the same
  User Data Directory," and automating the **default** Chrome profile "is not supported... may
  result in pages not loading or the browser exiting. Create and use a separate directory."
  (https://playwright.dev/python/docs/api/class-browsertype)
- **CDP attach:** `connect_over_cdp("http://localhost:9222")` attaches to a running Chromium.
- **Chrome 136+:** `--remote-debugging-port` is **no longer respected for the default Chrome data
  directory**; it must be paired with a non-default `--user-data-dir`
  (https://developer.chrome.com/blog/remote-debugging-port).
- **Selenium:** accepts `--user-data-dir=...`; driver must match Chrome major version.

**INFERENCE (decisive design input):** You cannot safely point automation at the *default*
Chrome profile while that Chrome is open. The correct $0 pattern is:
1. create a **dedicated Chrome data dir** (e.g. `./.browser/profile`),
2. launch Chrome once **manually** with `--user-data-dir=<dedicated>` (and optionally
   `--remote-debugging-port=9222`),
3. log into LinkedIn + Naukri by hand in that window,
4. attach via **CDP** for all automated work.

This is still "the user's own logged-in browser session" (same machine, same human, real
login, no cookie theft) but keeps a stable, non-locked profile the tool can drive.

### D.6 Windows Task Scheduler — **FACT**

`schtasks` and PowerShell `Register-ScheduledTask` are OS-bundled and free.
(https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/schtasks)

### D.7 Local libraries — **FACT**

- `sqlite3` — Python stdlib, public domain (https://docs.python.org/3/library/sqlite3.html)
- `pdfplumber` — MIT (https://github.com/jsvine/pdfplumber)
- `PyMuPDF` — AGPL-3.0 or commercial (https://pypi.org/project/pymupdf)
- `python-docx` — MIT (https://github.com/python-openxml/python-docx)
- Playwright (Python) — Apache-2.0 (https://github.com/microsoft/playwright-python)

**INFERENCE:** Default to `pdfplumber` (MIT) for PDF; optional local OCR fallback only if
text extraction fails.

---

## E. Disagreements with the brief

This section is mandatory per the brief. Each line: what the brief said, what research found,
and what changed.

1. **"Attach to the user's already-logged-in local browser profile."**
   Research (D.5) shows Chrome 136+ ignores `--remote-debugging-port` for the **default**
   profile and that the default profile is **locked** while Chrome runs. **Changed to:**
   a dedicated Chrome data dir that the user logs into by hand, attached over **CDP**. Same
   machine, same human, real session; no cookie copying.

2. **"NVIDIA API key is an allowed money source" + "use DeepSeek V4.1 Flash as default."**
   It is $0 (allowed) but NVIDIA Trial ToS §2.6(a) forbids submitting **personal data** and
   §3.3 trains on inputs (C.3). **Changed to:** only **de-identified** job text and de-identified
   resume signals go to NVIDIA. PII stays local. The brief's redaction rule (its §7) is now a
   hard, code-enforced gate rather than advice.

3. **"The user's existing NVIDIA key" is named as the primary quality source.**
   Research found **no published free-tier RPM/RPD** and real 429 risk. **Changed to:**
   model-agnostic LLM adapter with a **queue, per-model daily budget, exponential backoff,
   and deterministic-only degradation**, plus OpenRouter `:free` / Groq free as backup judges.

4. **"Gmail API with OAuth on a free personal Google Cloud project."**
   Research (D.3) found OAuth **Testing** mode expires refresh tokens every 7 days for
   gmail scopes. **Changed to:** **IMAP-read + SMTP-send with one app password** as the
   default $0 mail path; Gmail API is optional and documented.

5. **"Zen free models such as Muse Spark 1.3 Contributor Free."**
   Research (C.4) confirms `muse-spark-1.3-contributor-free` exists and is Free, **but** its
   terms let Meta train on prompts/completions. **Changed to:** privacy-safe default is
   `space-bunny-free` / `longcat-2.5-preview-free` (zero-retention) or NVIDIA with redaction;
   contributor-free is opt-in only, never for PII.

6. **"Walk the filtered job search pages / open each new job" via live scraping.**
   Research confirms both platforms prohibit automation and Naukri returns `recaptcha required`
   on its internal API (A.1, B.1). **Confirmed the brief's risk acceptance, but changed the
   method:** prefer **UI-driven, human-paced, low-volume** interaction, never the private
   `jobapi/v3/search`; treat **job-alert email intake as a first-class channel**, not merely a
   backup, and make live collection degrade gracefully to email-only when challenged.

7. **LiveBench "overall" numbers in the brief.**
   Research recomputed them from the actual CSV (C.1). The brief's numbers are essentially
   right for the named models; `deepseek-v4-pro` (no date) is a **different, weaker** model
   than `deepseek-v4-pro-0813`.

8. **"Python, Node, SQLite, Playwright/Selenium, scheduler."**
   Confirmed as $0 and appropriate. Node is not required; keep to **Python** to minimise
   surface area and dependencies.

### Confirmed still correct
- $0.00 is achievable end-to-end with the stack above.
- 70/90 routing, deterministic-first matching, evidence-backed scoring, durable ledger.
- Never invent form answers; ask the user and store in `candidate_facts.yaml`.
- Both platforms' ToS make this a **documented account risk**; the brief's "never call it
  ToS-safe / undetectable" rule stands and is honored in USER_GUIDE.md.