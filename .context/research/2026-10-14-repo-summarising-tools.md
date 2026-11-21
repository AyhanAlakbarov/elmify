# Repo-to-one-text-file tools for LLMs: which one could summarise untrusted student repos on our server?

Researched 2026-10-14. Question: which open-source tools turn a repository into one text file for an LLM, and is any of them fit to run on Elmify's own server against untrusted student GitHub repos, to build evidence text (about 24,000 characters) that a model turns into a CV description?

## Answer

**Adopt none of them whole. If one tool must be named, Repomix is the only one built for untrusted remote repos, and it brings a Node 22 runtime into a Python stack.** The better route is a short Python step of our own that copies three of Repomix's protections and gitingest's notebook handling:

- **Repomix** (MIT, Node >= 22, release v1.18.1 on 2026-09-21) is the only candidate that:
  - treats a remote repo as hostile by design (it refuses the repo's own config file, deletes the cloned `.git`, and blocks git config helpers);
  - scans for secrets by default;
  - follows no symlinks;
  - can shrink code to signatures with tree-sitter.

  It has also published five security advisories in 2026, two of them High, and every one is fixed in the version above. The advisories show both that real flaws were found and that they get fixed. Its `tokenBudget` setting fails the run when the output is too big. It does not cut the output down to fit, so we would still have to choose which files make the 24,000 characters.
- **gitingest** (MIT, Python) fits our language and turns `.ipynb` notebooks into plain scripts. But it has had no release since 2025-07-31, has no secret scanning, and its default output limits (up to 500 MB) are far beyond our budget.
- **yek** (MIT, Rust binary) is the only tool that *trims to a token cap by importance*, ranking files by git history. It reads local folders only.
- **code2prompt** (MIT, Rust plus Python bindings) and **files-to-prompt** (Apache-2.0, Python) read local folders only. files-to-prompt has had no release since 2025-02-19 and reads any file a symlink points to.
- **onefilellm** (MIT) fetches GitHub through the GitHub API and also crawls the web, YouTube and arXiv. That is far more outbound reach than this job needs.
- **Hosted versions (repomix.com, gitingest.com): do not send student repos there.**
  - repomix.com stores uploads on its servers for a while and runs Google Analytics.
  - The gitingest.com footer links no terms or privacy page.
  - Self-hosted gitingest sends personal data to Sentry by default once Sentry is switched on.

**What to borrow (the "glue" in buy-before-build terms):**

1. A depth-1 clone with no submodules, the same command Repomix and gitingest use.
2. Delete `.git` after cloning, or run git with the repo's config helpers turned off, as Repomix does.
3. Never follow symlinks.
4. Skip binary files and files over a size limit.
5. Turn notebooks into plain scripts, as gitingest does.
6. Rank README, manifest files and the most-changed files first, as yek does.
7. Cut at our own 24,000-character limit, not the tool's.

Run tree-sitter signature extraction (Repomix `--compress`) only if source code still overflows the budget after README and manifests.

## Sub-questions

1. For each tool: what licence, when was the latest release, what runtime, and how does it fetch a remote repo?
2. Which tools are safe against a hostile repo? This covers symlinks, a malicious `.git/config`, repo-supplied config, secrets in the code, and outbound calls or telemetry.
3. Which tools help fit a ~24,000-character budget? This covers token counting, size limits, comment stripping and compression, and git-history ranking.
4. Do hosted versions exist, and on what terms?

## How the candidate list was built

- **Exa** `web_search_exa` ("GitHub repository of an open-source command-line tool that packs an entire codebase into a single text file for feeding to an LLM") returned repomix, fln, repogrok, llmpack, Flatty, pilepack, CodeSqueeze, ai-pack, fuoricode and baler.
- **Brave** (`"repomix" OR "gitingest" alternative codebase to single file LLM site:github.com`) returned repomix, gitingest, the GitHub topic pages `repomix`/`gitingest` (which name yek), and many repomix forks.
- **GitHub repository search** (stars > 1000/2000) returned only repomix (28.8k stars) and code2prompt (7.7k stars).

The six named tools were evaluated. The other hits (fln, repogrok, llmpack, fuoricode, pilepack, ai-pack and similar) showed no sign of comparable adoption in these searches and were not evaluated. Their adoption is **Unverified**.

Tools available: scrapling, Exa, Brave and the GitHub MCP were used. Context7 and Tavily were not needed. Release and commit dates marked "GitHub API" came from the GitHub MCP. A date with no quotable page is marked Unverified.

## Comparison table

| | Repomix | gitingest | code2prompt | files-to-prompt | yek | onefilellm |
|---|---|---|---|---|---|---|
| Licence | MIT | MIT | MIT | Apache-2.0 | MIT | MIT |
| Latest release | v1.18.1, 2026-09-21 | v0.3.1, 2025-07-31 | 4.3.0, 2026-06-13 | 0.6, 2025-02-19 | v0.25.5, 2026-06-29 | no GitHub releases |
| Runtime | Node >= 22 (npm) | Python >= 3.8 (PyPI) | Rust binary; Python SDK | Python >= 3.8 | Rust binary | Python |
| Remote fetch | `git clone --depth 1`, then deletes `.git` | shallow `git clone` (`--depth=1`, single branch) | none (local path) | none (local path) | none (local path) | GitHub API (ref parameter) |
| Submodules | not fetched (no recurse flag) | opt-in `--include-submodules` | n/a | n/a | n/a | Unverified |
| Symlinks | not followed | Unverified | Unverified | followed for files (inference from code) | Unverified | Unverified |
| Secret scanning | yes, Secretlint, on by default | no (none found) | no (none found) | no | no (none found) | no (none found) |
| Compression / comments | tree-sitter `--compress`; `--remove-comments` | no | no (none found) | no | no | n/a |
| Notebooks | via an opt-in shell processor (local CLI only) | converted to a script, outputs included by default | "Smart File Reading" covers notebooks | read as raw JSON | Unverified | yes (`notebook.ipynb` example) |
| Git log | `includeLogs` (local repos only) | no | diffs, logs, branch comparisons | no | ranks files by git history | issues and PRs via API |
| Tokens / limits | o200k counting; `tokenBudget` fails the run; `maxFileSize` | tiktoken; 10 MB per file, 10,000 files, 500 MB total | per-file token estimate | none | `--tokens` cap that drops low-priority files; 10 MB max size | Unverified |
| Telemetry (CLI) | none stated | none in the CLI dependencies (inference); the server can use Sentry and PostHog | Unverified | none (inference from code) | Unverified | contacts many hosts by design |
| Published advisories | 5 (2 High) | none found (not searched beyond PyPI) | not searched | not searched | not searched | not searched |

The rows "Secret scanning: no" for tools other than Repomix and files-to-prompt mean that their READMEs mention no such feature. That an absence is real is **Unverified**.

## Per-tool findings

### Repomix (yamadashy/repomix)

**Licence, release and runtime**
- MIT licence.[^r1] MIT allows use, modification and sale, provided the copyright and permission notice is kept.[^r2]
- Latest release v1.18.1, a security patch.[^r3] Its advisory was published on Sep 21, 2026.[^r4]
- Runs on Node >= 22.[^r5]

**How it fetches a remote repo**
- `--remote` runs a depth-1 `git clone`.[^r6] It passes no `--recurse-submodules` flag, so submodules are not fetched. That is an inference from the clone command.
- After cloning it deletes `.git`, which also blocks git-config command execution.[^r7]
- It refuses a remote repo's own `repomix.config.*` unless told to trust it.[^r8]
- Git commands it runs in a target folder now disable the config keys that name executables.[^r9]
- File discovery does not follow symlinks.[^r10]

**Outbound calls**
- The CLI claims fully offline operation apart from install, `--remote` and manual update checks.[^r11]
- The repomix.com website temporarily stores uploaded files on its servers[^r12] and uses Google Analytics.[^r13]

**Content handling**
- Secret scan: Secretlint is enabled by default.[^r14]
- Binary file contents are left out; only their paths are listed.[^r15]
- Files over a configurable byte limit are skipped.[^r16]
- Notebooks are only converted through a user-defined `input.processors` shell command (e.g. `jupyter nbconvert`). Because processors run arbitrary commands, they work only in local CLI runs.[^r17]
- Compression keeps signatures and drops function bodies, using tree-sitter.[^r18] Comment removal is a separate option.[^r19]

**Git log and token counting**
- Git log inclusion is an option[^r20], but `--remote` deletes `.git` (above), so a remote run has no history to include. That is an inference from [^r7].
- Tokens are counted with gpt-tokenizer encodings.[^r21] `tokenBudget` fails the run when the output is over budget. It does not trim.[^r22]

**Advisories:** five published, including:
- a High-severity command injection through `--remote-branch`;[^r23]
- a Moderate cleartext-credential exposure in URL logging.[^r24]

### gitingest (coderamp-labs/gitingest)

**Licence, release and runtime**
- MIT licence.[^g1]
- Latest release 0.3.1 on 2025-07-31.[^g2] The last commit on the default branch is 2025-08-16 (GitHub API). That date is **Unverified** by a quotable page.
- Runs on Python 3.8+.[^g3]

**How it fetches a remote repo**
- Clones the repo with git.[^g4] The clone arguments in the same file (`clone_kwargs`, `cmd_args`) are depth 1 and single-branch; that detail is read from code and has no quote here.
- Submodules only when asked for.[^g5]

**Limits**
- 10 MB per file and 10,000 files at most.[^g6]

**Notebooks**
- Converted to a Python script.[^g7] Cell outputs are included by default.[^g8]

**Token counting**
- tiktoken.[^g9]

**Telemetry**
- The self-hosted server can run Sentry, and its default sends personal data.[^g10] The README also lists PostHog analytics.[^g11]
- The base CLI's dependency list carries neither library (PyPI `requires_dist`). That the CLI sends no telemetry is an inference.

**Hosted version**
- gitingest.com serves a digest for any GitHub URL.[^g12] Its footer links only the extension, the package and Discord, with no terms or privacy page.[^g13]

**Not found**
- Secret scanning: none mentioned in the README.
- Symlink handling: **Unverified**.

### code2prompt (mufeedvh/code2prompt)

- MIT licence.[^c1]
- The newest GitHub release is v4.2.0.[^c2] The GitHub API dates it 2025-12-11. crates.io and docs.rs list a later 4.3.0 on 2026-06-13. Both dates are **Unverified**: no quote names them.
- Rust CLI installed with cargo; the Python SDK comes from `code2prompt-rs`.[^c3]
- Works on a local directory.[^c4] No remote-URL mode was found in the README; the absence is **Unverified**.
- Token estimates are per file.[^c5]
- Notebooks are read through "Smart File Reading".[^c6]
- Git diffs and logs can be included.[^c7]
- Include/exclude globs and `.gitignore` are respected.[^c8]
- Secret scanning, compression and telemetry: none found; **Unverified**.

### files-to-prompt (simonw/files-to-prompt)

- Apache-2.0 licence.[^f1] Apache-2.0 also allows commercial use, with notice and NOTICE-file duties and a patent licence; this summary is **Unverified** because the licence text was not fetched.
- Latest release 0.6, Feb 19, 2025.[^f2]
- Python >= 3.8.[^f3]
- Local paths only.[^f4]
- Files that are not valid UTF-8, such as binaries, are skipped with a warning.[^f5]
- It opens every listed file with `open()`. A symlinked file inside a cloned repo is therefore read from wherever it points; that is an inference from the same code as [^f5].
- `.gitignore` is respected unless turned off.[^f6]
- No size limit, token count, secret scan or git log.

### yek (mohsen1/yek, formerly bodo-run/yek)

- MIT licence.[^y1]
- Latest release v0.25.5 on 2026-06-29.[^y2]
- A Rust tool[^y3], installed by a `curl | bash` script or built from source.[^y4]
- Local paths and globs only.[^y5]
- Ranks files by git history[^y6] and skips binary and large files.[^y7]
- `--tokens` drops the files that do not fit, keeping the more important ones.[^y8]
- `--max-size` sets a maximum size per output.[^y9] The help text shows a 10MB default, but that value is not part of the quote.
- Secret scanning and telemetry: none mentioned; **Unverified**.

### onefilellm (jimmc414/onefilellm)

- MIT licence.[^o1]
- No GitHub releases (the GitHub API returns 404 for latest release). The last commit is 2026-06-12 (GitHub API). The README says `pip install onefilellm`, but `pypi.org/pypi/onefilellm/json` returned Not Found on 2026-10-14. All three facts are **Unverified** by a quotable page.
- Python, installed from `requirements.txt`.[^o2]
- Fetches GitHub through the API with a `ref` parameter, not git clone.[^o3] A token is recommended.[^o4]
- It also crawls web pages, YouTube, arXiv and DOIs.[^o5] An `OFFLINE_MODE` switch skips network operations.[^o6]
- This is a wider outbound surface than a repo summariser needs.

## Fit against Elmify's constraints

- **Language.** Elmify is Python and Django. Repomix needs Node >= 22 in the worker image. code2prompt and yek are standalone Rust binaries. gitingest and files-to-prompt are Python but either dormant or lacking safeguards.
- **Untrusted input.** Only Repomix documents a threat model for hostile repos: refusing repo config, deleting `.git`, git-config hardening, no symlinks.[^r7][^r8][^r9][^r10]
  - Its advisory list shows the class of bug to expect: argument injection through a ref name, and credentials leaking into logs.[^r23][^r24]
  - Any glue we write must validate the ref and the URL in the same way, and run in a container with no credentials.
- **Budget.** None of the tools targets a 24,000-character summary.
  - yek's priority trimming is the closest technique.[^y8]
  - Repomix's budget is a pass/fail gate.[^r22]
  - The selection policy (README → manifests → entry points → compressed signatures) is ours to write whichever tool is used.
- **Hosted versions.** Excluded without a terms review, per the brief.[^r12][^g13]

## Sources

[^r1]: https://repomix.com/guide/privacy "Released under the MIT License."
[^r2]: https://raw.githubusercontent.com/yamadashy/repomix/main/LICENSE "to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software"
[^r3]: https://github.com/yamadashy/repomix/releases/tag/v1.18.1 "This patch release fixes a security issue in the CLI's git handling"
[^r4]: https://github.com/yamadashy/repomix/security/advisories "GHSA-4p5g-gh74-q524 published Sep 21, 2026"
[^r5]: https://repomix.com/guide/installation "System Requirements Node.js: ≥ 22.0.0 Git: Required for remote repository processing"
[^r6]: https://raw.githubusercontent.com/yamadashy/repomix/main/src/core/git/gitCommand.ts "['clone', '--depth', '1', '--', url, directory]"
[^r7]: https://raw.githubusercontent.com/yamadashy/repomix/main/src/core/git/gitCommand.ts "Drop the clone's .git. This keeps git internals out of the packed output, but it is also load-bearing for safety"
[^r8]: https://repomix.com/guide/remote-repository-processing "This prevents untrusted repositories from executing code via config files such as"
[^r9]: https://github.com/yamadashy/repomix/releases/tag/v1.18.1 "All git commands Repomix runs in a target directory now disable these settings."
[^r10]: https://raw.githubusercontent.com/yamadashy/repomix/main/src/core/file/fileSearch.ts "absolute: false, dot: true, followSymbolicLinks: false,"
[^r11]: https://repomix.com/guide/privacy "Repomix CLI operates fully offline after installation."
[^r12]: https://repomix.com/guide/privacy "your files are temporarily stored on our servers for processing"
[^r13]: https://repomix.com/guide/privacy "to collect usage data, such as page views and user interactions"
[^r14]: https://repomix.com/guide/security "Security checks are enabled by default."
[^r15]: https://repomix.com/guide/security "Binary file contents are excluded from output, but their paths are listed in the directory structure"
[^r16]: https://repomix.com/guide/configuration "Maximum file size in bytes to process. Files larger than this will be skipped."
[^r17]: https://repomix.com/guide/configuration "Runs arbitrary commands, so it runs only for local CLI runs"
[^r18]: https://repomix.com/guide/code-compress "The compression algorithm processes code using tree-sitter parsing to extract and preserve essential structural elements while removing implementation details."
[^r19]: https://repomix.com/guide/configuration "Whether to remove comments from supported file types."
[^r20]: https://repomix.com/guide/configuration "Whether to include git logs in the output. Shows commit history with dates, messages, and file paths"
[^r21]: https://repomix.com/guide/configuration "Token count encoding for OpenAI-compatible tokenization"
[^r22]: https://repomix.com/guide/configuration "Fail with a non-zero exit code when the packed output exceeds this many tokens."
[^r23]: https://github.com/yamadashy/repomix/security/advisories "Argument Injection GHSA-9mm9-rqhj-j5mx published May 27, 2026 by yamadashy High"
[^r24]: https://github.com/yamadashy/repomix/security/advisories "Cleartext Credential Exposure via Unredacted URL Logging in Remote Repository Processing"
[^g1]: https://raw.githubusercontent.com/coderamp-labs/gitingest/main/LICENSE "MIT License Copyright (c) 2024 Romain Courtois"
[^g2]: https://github.com/coderamp-labs/gitingest/releases/tag/v0.3.1 "0.3.1 (2025-07-31) Bug Fixes make cache aware of subpaths"
[^g3]: https://raw.githubusercontent.com/coderamp-labs/gitingest/main/README.md "## 📚 Requirements - Python 3.8+"
[^g4]: https://raw.githubusercontent.com/coderamp-labs/gitingest/main/src/gitingest/clone.py "It can clone a specific branch, tag, or commit if provided"
[^g5]: https://raw.githubusercontent.com/coderamp-labs/gitingest/main/README.md "Include repository submodules gitingest https://github.com/username/repo-with-submodules --include-submodules"
[^g6]: https://raw.githubusercontent.com/coderamp-labs/gitingest/main/src/gitingest/config.py "MAX_FILES = 10_000 # Maximum number of files to process"
[^g7]: https://raw.githubusercontent.com/coderamp-labs/gitingest/main/src/gitingest/utils/notebook.py "Process a Jupyter notebook file and return an executable Python script as a string."
[^g8]: https://raw.githubusercontent.com/coderamp-labs/gitingest/main/src/gitingest/utils/notebook.py "def process_notebook(file: Path, *, include_output: bool = True) -> str:"
[^g9]: https://raw.githubusercontent.com/coderamp-labs/gitingest/main/README.md "[tiktoken](https://github.com/openai/tiktoken) - Token estimation"
[^g10]: https://raw.githubusercontent.com/coderamp-labs/gitingest/main/README.md "GITINGEST_SENTRY_SEND_DEFAULT_PII**: Send default personally identifiable information"
[^g11]: https://raw.githubusercontent.com/coderamp-labs/gitingest/main/README.md "[posthog](https://github.com/PostHog/posthog) - Amazing analytics"
[^g12]: https://raw.githubusercontent.com/coderamp-labs/gitingest/main/README.md "in any GitHub URL to access the corresponding digest"
[^g13]: https://gitingest.com/ "Chrome Extension Python Package Discord"
[^c1]: https://raw.githubusercontent.com/mufeedvh/code2prompt/main/LICENSE "MIT License Copyright (c) 2024 Mufeed VH"
[^c2]: https://github.com/mufeedvh/code2prompt/releases/tag/v4.2.0 "Automatically generated release for refs/tags/v4.2.0"
[^c3]: https://raw.githubusercontent.com/mufeedvh/code2prompt/main/README.md "Provides fast Python bindings to the Rust Core."
[^c4]: https://raw.githubusercontent.com/mufeedvh/code2prompt/main/README.md "generating a prompt from your codebase is as simple as pointing the tool to your directory"
[^c5]: https://raw.githubusercontent.com/mufeedvh/code2prompt/main/README.md "Estimate prompt size using parallel per-file token counts and estimated template overhead"
[^c6]: https://raw.githubusercontent.com/mufeedvh/code2prompt/main/README.md "Simplify reading various file formats for LLMs (CSV, Notebooks, JSONL, etc.)"
[^c7]: https://raw.githubusercontent.com/mufeedvh/code2prompt/main/README.md "Include diffs, logs, and branch comparisons in your prompts"
[^c8]: https://raw.githubusercontent.com/mufeedvh/code2prompt/main/README.md "Include/exclude files using glob patterns and respect `.gitignore` rules"
[^f1]: https://pypi.org/project/files-to-prompt/ "License Apache Software License (Apache-2.0)"
[^f2]: https://pypi.org/project/files-to-prompt/ "Released: Feb 19, 2025 Latest release"
[^f3]: https://pypi.org/project/files-to-prompt/ "Requires Python >=3.8 Provides Extra test"
[^f4]: https://raw.githubusercontent.com/simonw/files-to-prompt/main/README.md "provide the path to one or more files or directories you want to process"
[^f5]: https://raw.githubusercontent.com/simonw/files-to-prompt/main/files_to_prompt/cli.py "Warning: Skipping file {path} due to UnicodeDecodeError"
[^f6]: https://raw.githubusercontent.com/simonw/files-to-prompt/main/README.md "Ignore `.gitignore` files and include all files."
[^y1]: https://raw.githubusercontent.com/mohsen1/yek/main/LICENSE "MIT License Copyright (c) 2025 Mohsen Azimi"
[^y2]: https://github.com/mohsen1/yek/releases/tag/v0.25.5 "[0.25.5] - 2026-06-29 Release V0.25.5"
[^y3]: https://raw.githubusercontent.com/mohsen1/yek/main/README.md "Rust based tool to serialize text-based files in a repository or directory for LLM consumption"
[^y4]: https://raw.githubusercontent.com/mohsen1/yek/main/README.md "curl -fsSL https://azimi.me/yek.sh | bash"
[^y5]: https://raw.githubusercontent.com/mohsen1/yek/main/README.md "Input files and/or directories to process"
[^y6]: https://raw.githubusercontent.com/mohsen1/yek/main/README.md "Uses the Git history to infer what files are more important."
[^y7]: https://raw.githubusercontent.com/mohsen1/yek/main/README.md "Infers additional ignore patterns (binary, large, etc.)."
[^y8]: https://raw.githubusercontent.com/mohsen1/yek/main/README.md "will remove any files that won't fit in the capped context size. It will try to fit in more important files"
[^y9]: https://raw.githubusercontent.com/mohsen1/yek/main/README.md "Maximum size limit per output"
[^o1]: https://raw.githubusercontent.com/jimmc414/onefilellm/master/LICENSE "MIT License Copyright (c) 2024 Jim McMillan"
[^o2]: https://github.com/jimmc414/onefilellm "pip install -r requirements.txt"
[^o3]: https://github.com/jimmc414/onefilellm "sends the request with a ref parameter so that the specified branch or tag is retrieved"
[^o4]: https://github.com/jimmc414/onefilellm "For GitHub API access (recommended):"
[^o5]: https://github.com/jimmc414/onefilellm "Academic : ArXiv papers, DOIs, PMIDs"
[^o6]: https://github.com/jimmc414/onefilellm "Set to 1 to skip network operations"

## Open questions

- **Symlinks, Git LFS and submodule handling for gitingest, code2prompt, yek and onefilellm** were not checked in source.
  - Before adopting any of them for hostile input, read its file walker.
  - Git LFS: no tool documents it. By default a depth-1 clone checks out LFS pointer files unless git-lfs is installed; this is **Unverified**. Our own clone should set `GIT_LFS_SKIP_SMUDGE=1` (**Unverified** that every tool respects it).
- **Security advisories** were only checked for Repomix (GitHub advisories) and gitingest (PyPI JSON lists none). For the others, neither GitHub advisory pages nor OSV were checked.
- **Whether gitingest is abandoned.** No release since 2025-07-31 and no commit after 2025-08-16 (GitHub API), but the repository is not marked archived in anything fetched.
- **How good Repomix `--compress` output is for CV evidence**, and how many characters a typical student repo takes after README + manifests + signatures. This needs a measurement on real repos, not a source.
- **Whether `apps/documents/evidence/` already fetches GitHub repos** in a way this would replace or extend. The repo was not read for this note.
