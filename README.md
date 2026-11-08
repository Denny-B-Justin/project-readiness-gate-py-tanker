# PCN Assessment — Python clone

A Python rebuild of the core Project Concept Note (PCN) workflow: a proposer
fills in the model PCN with per-field AI feedback, submits it, and an assessor
works through AI-drafted findings and prioritisation scores. One template,
no accounts, no database, no Node.js.

This project reproduces the core behaviour and brand of the reference
application, a Next.js app, in Dash on a FastAPI backend.

## Setup

Requires Python 3.11.9 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync                                  # creates .venv with pinned dependencies
uv run python -m pcn_clone.app           # dev server with hot reload, http://127.0.0.1:8050
uv run uvicorn pcn_clone.app.server:server --port 8050   # production shape
```

Checks:

```bash
uv run pytest -q -m "not browser and not live"    # unit tests, about 7 s
uv run pytest -q -m browser                       # headless Chrome suite, about 2.5 min
uv run pytest -q -m "not live"                    # everything offline: the gate for a PR
uv run pytest -q -m live                          # one real mAI Gateway call, on Posit Connect only
uv run ruff check . && uv run ruff format --check .   # lint and formatting
uv run mypy pcn_clone                             # types
```

A plain `uv run pytest -q` runs every marker, including `live`, so it spends
one real call whenever the gateway settings are present. The browser suite
under `tests/browser/` starts the real app with the offline provider and
drives it in headless Chrome over the DevTools Protocol; it skips itself when
Chrome is not installed. No Node.js is involved.

## Layout

- `pcn_clone/content/` — the model PCN as data: template, per-field criteria,
  assessment dimensions, MCA matrix and the default project, each loaded and
  validated by the pydantic models in `models.py`.
- `pcn_clone/core/` — the deterministic logic: number parsing and formatting,
  per-field validation and serialization, the cost worksheet and scenario
  tables, submission canonicalization, the serialized document and its
  digest, MCA scoring, and evidence-quote verification.
- `pcn_clone/ai/` — the model layer: prompts and JSON schemas pinned to
  golden fixtures, the Posit mAI Gateway client (`mai.py`) with an offline
  fake, field evaluation, and the assessment and prioritisation engines.
- `pcn_clone/app/` — the web application (see the primer below).
  - `__init__.py` builds the Dash app; `server.py` exposes it for uvicorn;
    `__main__.py` runs the dev server; `routing.py` is the query router.
  - `shell.py` is the suite header and page frame; `theme.py` the Mantine
    theme; `icons.py`, `notify.py`, `a11y.py` and `gate.py` are small helpers
    for icons, toasts, ARIA attributes and the "does this record exist" gate
    that pages with an id share.
  - `form/` is the proposer workspace on a project's page: the context bar,
    sections, field cards, one module per input kind, the field dialogs and
    the evaluate and readiness callbacks.
  - `review/` is the assessor side: the submit snapshot, the nine-call
    review run, the review record contract, and `workspace/` with the hub,
    finding and score cards, MCA summary and reviewer summary.
  - `pages/` holds one module per page; `pages/__init__.py` lists them in
    the router's table.
  - `assets/` holds the stylesheets, the browser-side scripts (`store.js`
    owns the projects' localStorage and `review-store.js` the reviews';
    `form.js` owns a project's answers while its form is open, with
    `numbers.js` for the live amounts; `review.js` runs a review session
    and `review-ui.js` the assessor workspace; `projects.js` and `gate.js`
    hold page behaviour), the logo, favicon and images. Dash serves this
    folder as is.
- `tests/` — pytest suite. `tests/fixtures/` holds golden outputs generated
  from the reference implementation; the serializer must reproduce them byte
  for byte, including the default project's digest.

## AI provider

Field evaluation, and the nine review calls after Submit, call a model
through the **Posit mAI Gateway** with a strict JSON schema, using the same
prompts as the reference app (pinned by golden fixtures). The gateway serves
GPT, Gemini and Claude models; `MAI_ENDPOINT` (or `MAI_MODEL`) picks the
family. It authenticates the app itself: there is no API key, token or
subscription key anywhere in the app.

Configuration lives in `.env` (gitignored; copy `.env.example`); variables
already set in the environment win. The app refuses to start unless
`MAI_BASE_URL` and `MAI_ENDPOINT` are set and it runs on Posit Connect
(which sets `CONNECT_CONTENT_GUID`), or `PCN_AI_PROVIDER=fake` is chosen, so
a misconfigured server fails at startup rather than on the first click:

| Variable | Required | Default | Meaning |
| --- | --- | --- | --- |
| `PCN_AI_PROVIDER` | no | `WB-mAI` | `WB-mAI` (the gateway) or `fake` (offline deterministic replies, for development and the browser tests), in any letter case. |
| `MAI_BASE_URL` | for `WB-mAI` | — | The gateway URL; a missing trailing `/` is added. |
| `MAI_ENDPOINT` | for `WB-mAI` | — | The mAI endpoint, sent as the `mai-endpoint` query parameter. Also names the model family. |
| `MAI_MODEL` | no | per family | A model the gateway allows, of the same family as `MAI_ENDPOINT`. Defaults: `gpt-5.6-luna`, `gemini-3.8-flash`, `claude-haiku-5-5`. |
| `CONNECT_CONTENT_GUID` | set by Connect | — | Sent as `X-Posit-App-Id`. Never set it by hand except as a dummy against the local fake gateway. |
| `PCN_AI_TIMEOUT_SECONDS` | no | `600` | Per-attempt timeout, above 0. |
| `PCN_AI_MAX_RETRIES` | no | `2` | Retries on retryable failures, 0 to 5. |
| `PCN_AI_MAX_OUTPUT_TOKENS` | no | unset | Output cap per call. Unset leaves GPT and Gemini at the model default and sends 8192 for Claude. |
| `PCN_AI_FAKE_DELAY_SECONDS`, `PCN_AI_FAKE_FAIL` | no | `0`, empty | Fake-provider latency and failure injection. |

Only three settings describe the connection: `MAI_BASE_URL`, `MAI_ENDPOINT`
and, optionally, `MAI_MODEL`. Requests carry `X-Posit-App-Id` and
`x-source-type: interactive`; sampling and reasoning settings are left to
the model. Connection failures and HTTP 408, 409, 425, 429 and 5xx are
retried with backoff (a `Retry-After`, or the gateway's "try again in N
seconds" or quota text, is honoured up to 60 s; a longer wait ends the
retries). Refusals (400, 401, 403, 404) are not retried; the server log
names the fix. If a provider rejects the response schema, the client
resends once with a portable schema (references inlined, `const` as `enum`)
and then once more without length bounds, and keeps that level; replies are
validated in full either way. Leave SDK debug logging off in production
(for example, do not set `OPENAI_LOG=debug`): the SDKs log request bodies,
and proposals are confidential.

### Gateway reference

From the *Posit mAI Gateway – Developer Guide*. Use QA with QA, and
Production with Production.

| | QA | Production |
| --- | --- | --- |
| `MAI_BASE_URL` | `https://apiqa2.worldbank.org/posit-mai/conversationalai/` | `https://api.worldbank.org/posit-mai/conversationalai/` |
| `MAI_ENDPOINT`, GPT | `https://azapimqa.worldbank.org/maifactory/openai/responses` | `https://azapim.worldbank.org/maifactory/openai/responses` |
| `MAI_ENDPOINT`, Gemini | `https://azapimqa.worldbank.org/maifactory/gemini/interactions` | `https://azapim.worldbank.org/maifactory/gemini/interactions` |
| `MAI_ENDPOINT`, Claude | `https://azapimqa.worldbank.org/maifactory/bedrock/model/us.anthropic.<model>/converse` | `https://azapim.worldbank.org/maifactory/bedrock/model/us.anthropic.<model>/converse` |

Allowed models (anything else is refused with 403 *Model not allowed for
Posit applications*; ask the platform team for more): GPT `gpt-6-luna`,
`gpt-5.6-luna`; Gemini `gemini-3.1-flash-lite`, `gemini-3.5-flash-lite`,
`gemini-3.6-flash`, `gemini-3.7-flash`, `gemini-3.8-flash`; Claude
`claude-haiku-5-5`. The Claude endpoint names its model in its path: the
app writes the resolved model there (filling in `<model>`), so `MAI_MODEL`
alone selects it and reviews record it as `claude-haiku-5-5`.

| Family | Wire format | Call |
| --- | --- | --- |
| GPT | OpenAI Responses API | `openai` SDK, strict `json_schema` text format |
| Gemini | Interactions API | `google-genai` SDK, schema as `response_format` |
| Claude | Bedrock Converse | plain HTTP `POST <gateway>converse`, the JSON as one forced `answer` tool call |

### Local development

The gateway only answers apps running on Posit Connect; it refuses local
machines. Locally, use `PCN_AI_PROVIDER=fake`, or run the whole app through
the real gateway client against the local fake gateway:

```bash
uv run python -m tests.ai.fake_gateway --family gpt --port 9000   # or gemini, claude
# in another shell:
PCN_AI_PROVIDER=WB-mAI \
MAI_BASE_URL=http://127.0.0.1:9000/posit-mai/conversationalai/ \
MAI_ENDPOINT=https://mai.example.invalid/maifactory/openai/responses \
CONNECT_CONTENT_GUID=00000000-0000-0000-0000-000000000000 \
uv run python -m pcn_clone.app
```

The fake gateway answers like the offline provider; the endpoint is only
passed through, never called.

### Checking the gateway on Connect

`uv run pytest -q -m live` makes one real evaluation and is skipped unless
`MAI_BASE_URL`, `MAI_ENDPOINT` and `CONNECT_CONTENT_GUID` are all set; every
other test runs offline. `python -m tests.ai.live_check`, run with the
app's Connect environment, makes one small call per output contract (field
evaluation, assessment finding, MCA score) on the sample project and
reports pass or fail, the time taken, the schema level each settled at and
the gateway's error, if any. `--fake` runs it against the local fake
gateway to test the script itself.

### Migration from the previous provider

Reviews record the model that drafted them, and a retry is refused when
the configured model differs. Reviews started before this change recorded
the previous provider's model string, so retrying one of their failed
calls now ends in the existing `model_mismatch` error. This is expected:
start a new review from the project.

## How the app is put together

Dash renders a tree of Python components (`html.Div`, `html.Button`, …) into
a React page and wires interactivity through *callbacks*: a callback declares
which component properties it reads (`Input`, `State`) and which it writes
(`Output`); Dash calls it whenever an input changes and applies the result to
the page. Two kinds are used here:

- **Clientside callbacks** are JavaScript functions that run in the browser.
  They own everything that touches localStorage, which the browser holds and
  Python never sees. Each script in `assets/` registers its own namespace
  under `window.dash_clientside` (`pcnForm`, `pcnProjects`, `pcnReview`,
  …); `store.js` and `review-store.js` are the localStorage layer they share.
- **Server callbacks** are Python functions. Any that wait on something (a
  model call, a file, the network) are `async def`, because the FastAPI
  backend runs synchronous callbacks on the event loop and they would block
  every other request.

Every page is served at the app's root address and chosen by its query
string: `?page=projects`, `?page=project&project_id=…`, no `page` for Home.
One callback in `routing.py` reads the query string, ignores the path, and
renders the matching `layout` from the table in `pages/__init__.py`, passing
only the parameters that page takes; an unknown page or a missing id shows
the not-found page. Page links are relative (`routing.page_url`), so a
visitor stays on whichever root they arrived at, while assets, callbacks and
the WebSocket follow Dash's path prefix. The shell wraps every page with the
header and a toast container. Overlays (dialogs, menus, popovers, toasts) are
dash-mantine-components themed to the brand in `theme.py`; everything else is
plain HTML elements with classes from `assets/brand.css`, which carries the
brand tokens copied from the reference app.

Assets are automatic: any `.css` or `.js` file in `assets/` is included on
every page, so there is no build step. Images are served from `/assets/...`.

To add a page, give its module in `pages/` a `layout` function, add it to
`PAGES` in `pages/__init__.py` with its title, header link and query
parameters, and link to it with `page_url`.

## Why FastAPI instead of Flask

Dash runs on Flask by default, but only its FastAPI and Quart backends
support WebSocket callbacks, and the assessor review needs one. Submitting a
Concept Note starts nine model calls at once (five assessment dimensions,
four prioritisation criteria), each result appears on its card as it lands,
and a call can run well past the roughly 30 seconds after which a plain HTTP
request is usually cut off. On Flask that would mean a job queue and polling
instead. The run is `run_review` in `app/review/run.py`.

## Deploying on Posit Connect

Deploy as a FastAPI app with the entrypoint `pcn_clone.app.server:server`.
In the content settings (Settings → Runtime → Environment Variables), set
`DASH_REQUESTS_PATHNAME_PREFIX` to the content URL's path,
`/content/<GUID>/`, and the `PCN_*` and `MAI_*` variables above. Connect
sets `CONNECT_CONTENT_GUID` itself; do not set it. Leave Integrations empty:
do not attach *mai Integration-QA* or *mai-posit*, and add no key. Connect
serves the app at that content URL and at its vanity URL. The app is
designed to work at both, with assets, callbacks and the WebSocket always
going through the content URL; that is tested locally against a
Connect-like proxy but not yet checked on Connect itself.

Roll out the model provider in three steps:

1. First deploy with `PCN_AI_PROVIDER=fake`, and check the pages (below).
2. Set the QA `MAI_BASE_URL` and `MAI_ENDPOINT` (and `MAI_MODEL` if not the
   family default) and `PCN_AI_PROVIDER=WB-mAI`. The log shows one line,
   `AI provider WB-mAI: <family> family, model <model>`. Run
   `python -m tests.ai.live_check` with the app's environment, then a field
   evaluation and a full review in the app.
3. Switch both URLs to their Production values.

On the first deploy, check:

- at both the vanity URL and `/content/<GUID>/`: a direct link to each
  page, stylesheets and callbacks loading, and a complete review run;
- that the WebSocket opens: Connect must pass on a `Host` that matches the
  browser's `Origin`, or Dash refuses the socket (403) and the review run
  fails;
- that requests keep reaching the app the way Connect was observed to
  forward them: with the full path, `/content/<GUID>/…`, and the mount
  location in the ASGI `root_path`. The app folds the root away only for
  Dash's page and `_dash-*` requests (`pcn_clone/app/root_path.py`);
  everything else (assets, the WebSocket, FastAPI's `/docs`) keeps the
  mount location.

`manifest.json` and `requirements.txt` describe the deployment for
rsconnect-python: Python 3.11, the FastAPI app mode and entrypoint, the
runtime packages pinned from `uv.lock`, and the files to bundle (the app,
without tests, caches or `.env`). `uv.lock` stays the source of truth, so
regenerate both whenever dependencies or app files change:

```bash
uv export --no-dev --no-hashes --no-annotate --no-emit-project --format requirements-txt -o requirements.txt
uv run --with rsconnect-python rsconnect write-manifest fastapi . --overwrite \
  --entrypoint pcn_clone.app.server:server -r requirements.txt \
  -x '.env' -x '.env.*' -x 'tests' -x 'tests/**' -x '.venv' -x '.venv/**' \
  -x '.mypy_cache/**' -x '.pytest_cache/**' -x '.ruff_cache/**' -x '**/*.pyc' \
  -x 'uv.lock' -x '.python-version' -x 'tasks/**' -x 'dist/**'
```

## Reviewing a phase in dev

1. `uv sync` and `uv run python -m pcn_clone.app`.
2. Open http://127.0.0.1:8050. A fresh browser starts with no projects.
3. Projects: create a Concept Note with tags, open it, load the default from
   *Defaults*, delete one. Reload the page; what remains is read back from
   localStorage.
4. Open a Concept Note, edit a field and press *Evaluate field*; feedback
   arrives from the model and goes stale when the answer changes.
5. Press *Submit*. The assessor workspace opens and drafts five findings and
   four prioritisation scores in parallel; accept, edit, adjust or dismiss
   them, write the summary, and watch the readiness list empty. The
   *Assessment* page lists every submitted review.
6. Home, Methodology and Release Notes are static pages whose content is a
   snapshot of the reference application as of 26 August 2026.
