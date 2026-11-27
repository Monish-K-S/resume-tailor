# resume-tailor

Tailor your LaTeX resume to a job description and get a **one-page PDF** back.

You paste a job description. The tool sends only text to an LLM — your base
resume, `profile.json`, the JD, and a fixed prompt — then validates the result,
compiles it locally with `pdflatex`, and checks the page count. Invented
numbers, URLs, emails, new macros and changed sections are rejected before
anything is compiled.

```
base/resume.tex ─┐
profile.json ────┼─> LLM ─> validate ─> pdflatex ─> page check ─> resumes/<company>_<date>/
prompt.md ───────┤                     (one retry per failure type)
job description ─┘
```

---

## Quick start

From the project root:

```sh
# 1. Create the environment and install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Add your API key
cp .env.example .env
# open .env and set GEMINI_API_KEY=...

# 3. Check that Python, TeX and the API key are all found
python tailor.py --check

# 4. Tailor your resume
python tailor.py --company stripe
# paste the job description, press Enter, then Ctrl-D
```

> **Ctrl-D doesn't submit?** It only signals end-of-input at the start of an
> empty line. If you pasted text without a trailing newline, the first Ctrl-D
> just flushes it — press **Enter**, then **Ctrl-D** (or press Ctrl-D twice).
> Easier alternatives: `--clipboard`, or pipe it:
> `pbpaste | python tailor.py --company stripe --stdin`.

The result lands in:

```
resumes/stripe_2026-11-27/
├── resume.pdf     the tailored, one-page PDF
├── resume.tex     the full LaTeX source
└── diff.txt       what changed vs base/resume.tex
```

Open `resume.pdf`. That's it.

> **Always use the venv's Python.** After `source .venv/bin/activate`, `python`
> is the venv interpreter. If you skip activation, call
> `.venv/bin/python tailor.py ...` explicitly. If your shell aliases `python`
> to a system interpreter (common on macOS), the CLI detects it and re-execs
> itself with `.venv/bin/python` automatically. Set
> `RESUME_TAILOR_NO_VENV=1` to disable that.

> **First time only:** if `--check` reports `pdflatex FAIL`, install TeX — see
> [Installing TeX](#installing-tex). If it reports `provider FAIL`, the message
> is the real API error (bad key, retired model, network).

---

## What you need

- **Python 3.11+**
- **A TeX distribution** with `pdflatex` (BasicTeX is enough on macOS)
- **`pdfinfo` and `pdftotext`** (from `poppler`)
- **An API key** for Gemini (default) or any OpenAI-compatible provider

### Installing TeX

**macOS**

```sh
brew install --cask basictex
brew install poppler
eval "$(/usr/libexec/path_helper)"

sudo tlmgr update --self
sudo tlmgr install enumitem titlesec cm-super
```

If you cannot use `sudo`, install into your user TeX tree instead:

```sh
tlmgr init-usertree
tlmgr --usermode install enumitem titlesec cm-super
```

You do **not** need `pdflatex` on your `PATH`. The app also looks in
`/Library/TeX/texbin`, `/usr/local/texlive/*/bin/*`, `/opt/homebrew/bin` and
`/usr/local/bin`.

**Linux (Debian/Ubuntu)**

```sh
sudo apt install texlive-latex-recommended texlive-latex-extra poppler-utils
```

---

## Everyday usage

### 1. Pick how to provide the job description

**Paste it** (default). Paste the JD, press <kbd>Enter</kbd>, then
<kbd>Ctrl-D</kbd>. If nothing happens, press <kbd>Ctrl-D</kbd> a second time —
the first one only flushes a line that did not end with a newline.

```sh
python tailor.py --company stripe
```

**From the clipboard** — copy the JD first, then:

```sh
python tailor.py --company stripe --clipboard
```

**Piped on macOS** — no Ctrl-D needed:

```sh
pbpaste | python tailor.py --company stripe --stdin
```

**From a file** — handy for long JDs or repeated runs:

```sh
python tailor.py --company stripe --jd-file jd.txt
```

`--company` is required and only names the output folder. It is slugified, so
`Acme Corp` becomes `acme-corp`.

### 2. Read the report

```
Tailored resume for Stripe
  output    resumes/stripe_2026-11-27/resume.pdf  (1 page)
  elapsed   14.2s  (1 API call)
  matched   18 keywords: Python, PostgreSQL, Kafka, AWS, Docker, ...
  missing   6 keywords
            in profile but unused: Terraform, gRPC
            not in profile:        Kubernetes, Rust
  diff      +11 / -9 lines  (full diff: resumes/stripe_2026-11-27/diff.txt)
```

- **matched** — JD keywords the tailored resume now contains.
- **in profile but unused** — you have this skill, but the model left it out.
  Useful when a JD emphasises something you actually know.
- **not in profile** — the JD wants something you have not listed. This is a
  **gap report only**; it is never injected into the resume.
- **diff** — line changes vs `base/resume.tex`. Add `--verbose` to print the
  whole diff in the terminal.

The missing-keyword list is informational. If you genuinely have one of those
skills, add it to `profile.json` (see [Customising](#customising)) and re-run.

### 3. Review and iterate

Read the PDF before sending it. If a bullet is weaker than you want, edit
`prompt.md` or `profile.json` and run again — each run is independent and gets
its own timestamped folder.

To use the result as your new baseline, copy it back:

```sh
cp resumes/stripe_2026-11-27/resume.tex base/resume.tex
```

Only do this after you have checked the PDF; it changes what future runs start
from.

---

## If something goes wrong

| Message | What to do |
| --- | --- |
| `GEMINI_API_KEY (or GOOGLE_API_KEY) is not set` | Put the key in `.env` at the project root, or export it in your shell. Also make sure you are running the venv's Python (see [Quick start](#quick-start)). |
| `google-genai is not installed` even though you installed it | Your shell's `python` is probably an alias to a system interpreter that bypasses the venv. Run `.venv/bin/python tailor.py ...`, or let the CLI re-exec automatically (default). |
| `404 NOT_FOUND ... no longer available to new users` | The model was retired. Set `RESUME_TAILOR_MODEL` to a current model (the default is `gemini-3.8-flash`). |
| `503 UNAVAILABLE` / `Connection reset` | Transient provider or network failure. The client retries twice automatically; re-run if it persists. |
| `pdflatex not found` | Install BasicTeX/MacTeX or TeX Live, then run `python tailor.py --check`. |
| `File 'enumitem.sty' not found` | `sudo tlmgr install enumitem titlesec cm-super`, or use `tlmgr --usermode`. |
| `still 2 pages after one retry` | The content is too long. Trim `profile.json` or `base/resume.tex`, or allow `--max-pages 2`. |
| `Validation failed` with a number or URL | The model tried to invent a fact. Re-run; if it repeats, remove that detail from `prompt.md` or add the real fact to `profile.json`. |
| `clipboard` is empty on Linux | Install `xclip` or `xsel` (`sudo apt install xclip`). |
| `unknown provider` | Use `gemini`, `openai`, `openrouter`, `groq` or `ollama`. |
| `RESUME_TAILOR_MODEL is required` | Set it in `.env` for OpenRouter/Groq/Ollama. |
| Anything unexpected | Re-run with `--verbose` to see the traceback and the full diff. |

Failed runs keep the rejected body and compiler log next to the output:

```
resumes/stripe_2026-11-27/
├── resume.rejected.tex   what the model produced
└── compile.log           pdflatex's complaint
```

A failed run never overwrites a previous good `resume.pdf`.

### Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Success |
| `1` | Unexpected failure (`--verbose` for details) |
| `2` | Input or configuration error |
| `3` | Validation failed |
| `4` | `pdflatex` failed or is missing |
| `5` | Still over the page limit after the retry |
| `6` | Provider/API failure |
| `130` | Interrupted |

---

## Customising

### `profile.json` — the fact pool

This is the **only** source of facts the model may use (together with the base
resume). If a number, tool or achievement is not here, it does not exist as far
as the tool is concerned.

The `additional` object starts empty. Fill it with internships,
certifications, other projects, awards, publications — anything you want the
model to be able to add. The shape is free-form: the fact checker reads every
string in the file, so use whatever structure is clearest to you.

```json
{
  "additional": {
    "internships": [
      {
        "company": "Example Corp",
        "role": "Software Engineering Intern",
        "dates": "May 2025 - Aug 2025",
        "bullets": [
          "Built an ingestion service in Python handling 1.2M events/day.",
          "Cut p95 latency from 480ms to 120ms."
        ]
      }
    ]
  }
}
```

Numbers you add here become legal to use in the tailored resume.

### `base/resume.tex` — the starting document

- Keep it compiling to **one page**.
- The preamble is frozen; only the body between `\begin{document}` and
  `\end{document}` is rewritten.
- The section titles and their order are the contract. Keep the five sections
  you want in the output; the model may not add, remove or reorder them.
- Custom macros already used in the body are automatically allowed.

### `prompt.md` — the editing strategy

Sent verbatim as the system prompt, after which the app appends a generated
contract (your section list, allowed commands, allowed environments). You can
rewrite the strategy freely, but do not remove the contract section at the
bottom.

---

## All flags

| Flag | Meaning |
| --- | --- |
| `--company NAME` | **Required.** Names the output folder. |
| `--clipboard` | Read the JD from the clipboard. |
| `--jd-file PATH` | Read the JD from a file. |
| `--stdin` | Read the JD from stdin without printing the prompt. |
| `--check` | Check inputs, TeX tools and API configuration (makes one live provider call), then exit. |
| `--strict` | Treat unverified skills/terms as fatal instead of warnings. |
| `--max-pages N` | Page limit (default `1`). |
| `--provider NAME` | `gemini` (default) or an OpenAI-compatible provider. |
| `--model NAME` | Override `RESUME_TAILOR_MODEL`. |
| `--out-root PATH` | Output root (default `resumes/`, project-relative). |
| `--no-color` | Disable ANSI colours. |
| `--verbose` | Print the full diff and tracebacks. |

---

## Providers

Configuration is environment-only. `.env` in the project root is loaded
automatically, so it works from any directory.

| Provider | `RESUME_TAILOR_PROVIDER` | Key | Default model |
| --- | --- | --- | --- |
| Gemini | `gemini` | `GEMINI_API_KEY` or `GOOGLE_API_KEY` | `gemini-3.8-flash` |
| OpenAI | `openai` | `OPENAI_API_KEY` | `gpt-4o-mini` |
| OpenRouter | `openrouter` | `OPENAI_API_KEY` | required |
| Groq | `groq` | `OPENAI_API_KEY` | required |
| Ollama | `ollama` | none (uses `ollama`) | required |

Example with OpenRouter:

```sh
RESUME_TAILOR_PROVIDER=openrouter \
RESUME_TAILOR_MODEL=anthropic/claude-sonnet-4 \
OPENAI_API_KEY=sk-or-... \
python tailor.py --company acme
```

Example with a local Ollama server:

```sh
RESUME_TAILOR_PROVIDER=ollama \
RESUME_TAILOR_MODEL=llama3.1 \
python tailor.py --company acme
```

The tool makes **at most three generation calls** per run: one generation, one
compile fix, one page cut. A typical successful run is one call and finishes in
10–30 seconds with Gemini Flash. Transient `429`/`5xx`/connection errors are
retried twice at the transport level before the run fails.

---

## What is enforced

**Frozen preamble.** The base file is split at `\begin{document}`. The model
only ever returns the body, and the original preamble is re-attached
byte-for-byte. Any drift fails validation.

**Exact structure.** Same section titles, same order, same count. Page-fit
retries may delete bullets, never sections.

**Command allowlist.** Only the macros named in the brief plus every command
already present in the base body (`\achieveItem`, `\begin{center}`, `\hfill`,
`\quad`, `\small`, `\LARGE`, `$\vert$`, …). No new packages, no new macro
definitions, no unknown environments.

**Balanced LaTeX.** Braces and `\begin`/`\end` pairs.

**No invented facts.** Every number, URL and email in the output must already
exist in `profile.json` or the base resume. Layout numbers (`\vspace{12pt}`,
`\hspace`, `\\[4pt]`) are ignored. Unknown skills, tools, acronyms and
multi-word proper nouns are reported as **warnings**; `--strict` makes them
fatal.

**One page.** `pdfinfo` counts pages. If the PDF overflows, the model gets one
retry with the actual overflow text and a line-cut target.

---

## Tests

```sh
.venv/bin/python -m pytest -q
```

The suite needs no API key and no TeX installation. It covers the preamble
split/join, the command allowlist, the invented-fact check, section/brace
validation, prompt assembly, the retry state machine (mocked LLM and compiler)
and the CLI.

---

## Privacy

Only text leaves your machine: `profile.json`, `base/resume.tex`, the job
description and `prompt.md`. No PDF, image or rendered page is ever uploaded.
The PDF is compiled locally by `pdflatex` with `-no-shell-escape`.

## Project layout

```
tailor.py               CLI entry point
tailorlib/
├── tex.py              split/join, section extraction, brace checks
├── validate.py         preamble, structure, allowlist, environment checks
├── facts.py            fact corpus + invented-number/URL/email detection
├── compile.py          pdflatex, pdfinfo, pdftotext wrappers
├── prompts.py          system prompt + generated output contract
├── pipeline.py         generate → validate → compile → page retry loop
├── report.py           JD keyword gap analysis + unified diff
└── llm/                Gemini and OpenAI-compatible adapters
base/resume.tex         frozen starting document
profile.json            authoritative fact pool
prompt.md               editing strategy
resumes/                generated output (git-ignored)
tests/                  pytest suite
```
