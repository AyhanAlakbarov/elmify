# Running Claude Code heavily as a solo developer with many parallel sessions: what the primary sources recommend (2025-2026)

Date: 2026-10-15. Scope: the ten topics the caller named, 1-3 primary-source recommendations each, as a yardstick for auditing a real setup. Not a survey.

## Method and sources

- Sources are the ones the caller named, in their order of preference: Anthropic's Claude Code docs (code.claude.com), Anthropic engineering posts, OpenAI's AGENTS.md guide, Cursor's rules docs, Boris Cherny's and Simon Willison's own posts. No candidate list had to be built from searches (the question is "what do these sources say", not "what options exist"), so no option-discovery search was run.
- One Exa search located Boris Cherny's thread. threads.com returned only a login wall to scrapling, so his thread is cited from the ThreadReaderApp mirror (threadreaderapp.com), which reproduces the X thread verbatim. It is a mirror, not his own domain.
- Every quote below was copied from a scrapling `get` of the live page.
- Not used: Context7 (these are product docs and posts, not library API docs), Tavily, Brave. Not read: `code.claude.com/docs/en/sandboxing` and `/skills`-adjacent reference pages beyond what is cited (the sandboxing page was too large to load; its claims here come from Anthropic's sandboxing engineering post instead), and the hooks *reference* page's "Security considerations" section.

Sub-questions used:
1. What size, structure and placement do Anthropic, OpenAI and Cursor give for instruction files, and what do they say about adherence falling with length?
2. What does Claude Code load at session start from auto memory, and what limits apply?
3. When does Anthropic say to use a hook instead of a prose rule, and what hook pitfalls do the docs name?
4. What does a large tool set cost in context, and what does tool search change?
5. How are skills matched, and what does a large skill set cost?
6. How do the docs and named practitioners run parallel sessions?
7. When do subagents or multi-agent setups pay off, and at what token multiple?
8. What verification loops do the sources recommend?
9. What do the sources recommend for permissions, sandboxing, prompt injection and secrets?
10. What do the sources recommend for context, compaction, /clear and model or effort choice?

---

## 1. Instruction files (CLAUDE.md / AGENTS.md)

**Size.** Anthropic's memory docs give a number: aim for under 200 lines per CLAUDE.md, because longer files cost more context and are followed less reliably.[^1] Splitting a file into `@imports` keeps it organised but saves no context, since imported files also load at launch.[^2] Cursor's limit is looser and applies per rule file: under 500 lines.[^3] OpenAI's Codex stops reading instruction files once their combined size reaches 32 KiB.[^4] That cap is a hard cut-off: the docs advise raising it or splitting files across directories when you hit it, and they do not present it as a recommended size. Boris Cherny's team CLAUDE.md for the Claude Code repo is reported at 2.5k tokens, but only by InfoQ: **Unverified** from a primary source.

**How instructions decay.** Anthropic gives the symptoms, not a curve: when Claude keeps breaking a rule that exists, the file is probably too long and the rule is getting lost.[^5] A bloated file makes Claude ignore the instructions that matter.[^6] Emphasis stops working once it is spread over many lines.[^7] Two instructions that contradict each other get resolved arbitrarily.[^8] None of the sources consulted publishes a measured number for how adherence falls with length; see Open questions.

**What belongs where.**
- The pruning test for each line: would deleting it cause Claude to make mistakes? If not, cut it.[^6]
- CLAUDE.md holds facts needed in every session. Procedures with several steps, and guidance that applies to only part of the codebase, go into skills or path-scoped rules.[^9]
- Path-scoped rules (`.claude/rules/*.md` with a `paths:` frontmatter) load only when Claude works with a matching file.[^10]
- `/doctor` proposes cutting content Claude can work out from the code itself, such as directory layouts, dependency lists and architecture overviews. It keeps pitfalls, rationale, and conventions that differ from tool defaults.[^11]
- Cursor's version of the same advice: start simple, and add a rule only after the agent repeats a mistake.[^12]

**Prose is not enforcement.** CLAUDE.md and auto memory are treated as context, not as enforced configuration.[^13] Hard rules belong in hooks (topic 3).

## 2. Memory across sessions

- **What loads at start:** the first 200 lines or 25KB of `MEMORY.md`, whichever limit is reached first, are loaded at the start of every conversation.[^14] Topic files are not preloaded. Claude reads them on demand when it needs them.[^15]
- **One store per repository:** auto memory lives under `~/.claude/projects/<project>/memory/`. Every worktree and subdirectory of the same repository shares one auto-memory directory.[^16] All of your parallel sessions in a repository therefore read and write the same index.
- **What auto memory skips:** it does not save what it can work out from the codebase, such as architecture, file paths or debugging fixes.[^17] A MEMORY.md full of state that could be derived from the code is working against the design.
- **Compaction:** the project-root CLAUDE.md survives compaction, because Claude re-reads it from disk and re-injects it into the session.[^18]

## 3. Hooks versus prose rules

**When to use a hook.** Hooks are deterministic: unlike CLAUDE.md, which is advisory, a hook guarantees its action runs.[^19] Anthropic's rule of thumb is that anything that must hold every time should be a hook, not a prompt instruction.[^20] The best-practices "over-specified CLAUDE.md" fix makes the same point: if Claude already does something correctly without an instruction, delete the instruction or turn it into a hook.[^6] Hooks also save context. A hook that filters test or log output can cut what reaches Claude from tens of thousands of tokens to hundreds.[^21]

**Pitfalls named in the hooks guide:**
- **Bypass through the shell:** Claude can also create or modify files with shell commands,[^22] so a hook that matches only `Edit|Write` misses some changes.
- **Hooks run in parallel:** when several hooks rewrite the same tool input, the order is non-deterministic.[^23]
- **PostToolUse cannot undo:** by the time it runs, the tool has already executed.[^24]
- **Stop-hook loops:** a Stop hook that blocks eight times in a row, with no tool call from Claude in between, is overridden.[^25] Check `stop_hook_active` before blocking again.
- **The `if` filter is best-effort:** use permission rules, not hooks, for a hard allow or deny.[^26]
- **Hooks only tighten:** hooks can add restrictions but cannot loosen them past what permission rules allow.[^27]

## 4. MCP servers and tool count

- **What tools cost.** In Anthropic's five-server example, 58 tools take about 55K tokens before the conversation starts.[^28] Anthropic has seen tool definitions alone consume 134K tokens before optimisation.[^29]
- **What tool search changes.** Tool search cut token use by 85% while keeping the whole tool library available.[^30] Claude Code now defers MCP tool definitions by default: until a tool is used, only tool names and server instructions enter context.[^31]
- **Recommended thresholds.** Anthropic recommends tool search once definitions exceed about 10K tokens[^32] (the post's list also names "10+ tools available"; that phrase is not separately quoted here). Keep the three to five most-used tools loaded and defer the rest.[^33]
- **Choosing tools.** A bloated or overlapping tool set is "one of the most common failure modes".[^34] A CLI is the most context-efficient way to reach an external service,[^35] because it adds no per-tool listing at all.[^36]
- **Unverified:** a hard cap on MCP tool count for Claude Code or Cursor. No primary source consulted gives one for Claude Code. Cursor's current docs were not checked for a tool limit.

## 5. Skills and plugins

- **How skills are matched:** Claude compares the task against skill descriptions.[^37] Vague or overlapping descriptions make it load the wrong skill or miss the right one (same page).
- **Cost of having many skills:** every skill in the listing adds to context on every turn, whether or not it is ever used.[^38] The listing's budget is 1% of the context window.[^39] When the listing overflows, descriptions are dropped first for the least-used skills.[^40] Each description is capped at 1,536 characters.[^41] Setting `disable-model-invocation: true` removes a skill from context entirely.[^42]
- **Size of one skill:** keep SKILL.md under 500 lines and move reference material to separate files.[^43]
- **After compaction:** invoked skills are re-attached at 5,000 tokens each, within a shared budget of 25,000 tokens.[^44] Put the important instructions near the top of a skill.
- **Audit:** `/skill-doctor` reports each skill's cost and how often it is used (skills page). No source gives a maximum skill count. The binding limit is the listing budget above.

## 6. Parallel sessions

- **Isolation:** Anthropic recommends a separate git worktree for each session so edits do not collide.[^45] `.worktreeinclude` copies gitignored files such as `.env` into new worktrees (same page).
- **Boris Cherny** (creator of Claude Code) runs 5 Claudes in parallel in numbered terminal tabs, with system notifications telling him which one needs input.[^46] He runs 5-10 more on claude.ai/code (same thread). His team updates its shared CLAUDE.md whenever Claude gets something wrong.[^47] He later wrote that auto mode lets him run more Claudes in parallel.[^48] InfoQ reports that he gives each local session its own git checkout rather than a worktree. That claim comes from InfoQ, not from him, so it is **Unverified**.
- **Simon Willison** says human review is the bottleneck. He lands only one significant change at a time and runs low-overhead work, mostly research and small maintenance, in parallel.[^49] He also uses fresh checkouts rather than worktrees.[^50]
- **Fresh context for review:** a second session reviews better because it is not biased toward code it just wrote.[^51]

## 7. Subagents and multi-agent systems

- **Token multiples:** agents use about 4x the tokens of chat, and multi-agent systems about 15x.[^52] Agent teams in Claude Code use about 7x the tokens of a standard session when teammates run in plan mode.[^53]
- **When they pay off:** multi-agent beat single-agent by 90.2% on Anthropic's internal research eval.[^54] Coding is the weaker fit, because coding tasks contain fewer truly parallel pieces than research.[^55]
- **Main use in coding:** keeping context clean. Subagents run in separate context windows and report back summaries,[^56] usually 1,000-2,000 tokens.[^57]
- **Prompting them:** each subagent needs an objective, an output format, tool guidance and clear task boundaries.[^58] Scale effort to the task, for example 1 agent with 3-10 tool calls for simple fact-finding.[^59]

## 8. Verification loops

- **Give Claude a check it can run,** such as tests, a build or a screenshot.[^60] Boris calls this the most important tip and says it improves the final result 2-3x.[^61]
- **Make the gate harder for unattended runs:** a Stop hook runs the check and blocks the turn from ending until it passes.[^62] Ask Claude for evidence, such as test output, rather than a claim that it passed.[^63]
- **Bound the adversarial reviewer:** a reviewer told to find gaps will report some even when the work is sound, and chasing every finding leads to over-engineering.[^64] Tell it to flag only correctness gaps or gaps against the stated requirements.[^65]

## 9. Permissions and security

- **Sandboxing:** cut permission prompts by 84% in Anthropic's internal use.[^66] It needs both filesystem isolation and network isolation. Either one alone can be escaped.[^67]
- **Auto mode:** manual approval mostly fails as a safeguard, because users accept 93% of prompts.[^68] Auto mode's classifier misses 17% of real overeager actions.[^69] Anthropic says it is not a drop-in replacement for careful human review on high-stakes infrastructure.[^70] Entering auto mode drops allow rules that grant arbitrary code execution, such as blanket shell access.[^71] It stops after 3 consecutive denials or 20 in total.[^72]
- **Prompt injection from tool output:** auto mode's probe scans tool outputs before they enter Claude's context.[^73] Anthropic's own advice is to avoid piping untrusted content directly to Claude,[^74] and to use VMs when Claude interacts with external web services.[^75] Simon Willison's "lethal trifecta" is the combination of private data, untrusted content and a way to send data out. His advice is to avoid that combination of tools.[^76]
- **Secrets:** in Claude Code on the web, credentials are never inside the sandbox with Claude.[^77] Boris does not use `--dangerously-skip-permissions`.[^78] He pre-allows commands he knows are safe instead.[^79]

## 10. Cost and context control

- **Context rot:** recall drops as the context window fills.[^80] Claude Code's docs say performance degrades as context fills.[^81] The goal is the smallest set of high-signal tokens that gets the job done.[^82]
- **When to /clear:** after two failed corrections on the same issue, the context is cluttered with failed approaches.[^83] A clean session with a better prompt almost always wins.[^84]
- **Hidden spend:**
  - Every request resends the full conversation.[^85]
  - Scheduled tasks resend the full context each time they fire, even in an idle session.[^86]
  - Thinking tokens are billed as output, and the default budget can be tens of thousands of tokens per request.[^87]
- **Model choice (the sources disagree):** the Claude Code cost docs say Sonnet handles most coding tasks[^88] and to reserve Opus for complex architectural decisions or multi-step reasoning.[^89] Boris uses Opus with thinking for everything,[^90] because he finds it almost always faster in the end.[^91] The docs speak to cost and Boris speaks to his own speed, so the two measure different things.
- **Baseline cost:** in enterprise deployments, the average is about $13 per developer per active day.[^92] Treat that as a yardstick only: a heavy solo developer running parallel sessions is not the average user.

---

## Top recommendations

1. **CLAUDE.md under 200 lines,** facts only. Move procedures to skills and area-specific guidance to path-scoped rules. Imports save nothing.[^1][^2][^9]
2. **Turn rules that must hold every time into hooks** or permission rules, and delete the prose copy.[^20][^26]
3. **Keep MEMORY.md as a short index** that fits within 200 lines / 25KB, with detail in topic files. All worktrees share it.[^14][^16]
4. **Audit the always-loaded surface:** skill listing (1% budget), MCP servers (prefer a CLI), plugins. Use `/context`, `/doctor` and `/skill-doctor`.[^38][^39][^35]
5. **One worktree or checkout per session.** Keep the number of parallel sessions to what you can review.[^45][^49]
6. **Use subagents to keep the main context clean,** not to parallelise ordinary coding. Budget roughly 4-15x tokens for multi-agent work.[^52][^55][^56]
7. **Every task needs a runnable check.** Use Stop hooks for unattended runs, and give the reviewer a scope.[^60][^62][^65]
8. **Use sandbox plus auto mode or a narrow allowlist,** not `--dangerously-skip-permissions`. Treat tool output as untrusted.[^66][^69][^76]
9. **/clear between tasks** and after two failed corrections. Watch idle scheduled tasks and other background spend.[^83][^86]

## Open questions

- **No measured length-to-adherence curve** was found in any primary source. Anthropic gives the 200-line target and symptoms only. The memory docs mention a warning when instruction files together pass a "combined limit", but give no number.
- **Hard tool-count caps:** none found for Claude Code, where tool search is the default. Cursor's current MCP tool limit was not checked.
- **Boris Cherny's checkout-vs-worktree practice** and the 2.5k-token CLAUDE.md come from InfoQ, not from his own post.
- **The `code.claude.com/docs/en/sandboxing` page** (too large to load) and the hooks reference "Security considerations" section were not read. Sandboxing claims here rest on Anthropic's engineering post.

## Sources

[^1]: https://code.claude.com/docs/en/memory "target under 200 lines per CLAUDE.md file. Longer files consume more context and reduce adherence."
[^2]: https://code.claude.com/docs/en/memory "helps organization but doesn’t reduce context, since imported files load at launch."
[^3]: https://cursor.com/docs/rules "Keep rules under 500 lines"
[^4]: https://learn.chatgpt.com/docs/agent-configuration/agents-md "Codex skips empty files and stops adding files once the combined size reaches the limit defined by project_doc_max_bytes (32 KiB by default)"
[^5]: https://code.claude.com/docs/en/best-practices "If Claude keeps doing something you don’t want despite having a rule against it, the file is probably too long and the rule is getting lost."
[^6]: https://code.claude.com/docs/en/best-practices "If not, cut it. Bloated CLAUDE.md files cause Claude to ignore your actual instructions!"
[^7]: https://code.claude.com/docs/en/best-practices "If you emphasize many lines, none of them stands out."
[^8]: https://code.claude.com/docs/en/memory "if two instructions contradict each other, Claude may pick one arbitrarily."
[^9]: https://code.claude.com/docs/en/memory "Keep it to facts Claude should hold in every session: build commands, conventions, project layout,"
[^10]: https://code.claude.com/docs/en/memory "These conditional rules only apply when Claude is working with files matching the specified patterns."
[^11]: https://code.claude.com/docs/en/memory "it cuts content Claude can derive from the codebase, such as directory layouts, dependency lists, and architecture overviews, and keeps pitfalls, rationale, and conventions that differ from tool defaults."
[^12]: https://cursor.com/docs/rules "Start simple. Add rules only when you notice Agent making the same mistake repeatedly."
[^13]: https://code.claude.com/docs/en/memory "Claude treats them as context, not enforced configuration."
[^14]: https://code.claude.com/docs/en/memory "or the first 25KB, whichever comes first, are loaded at the start of every conversation."
[^15]: https://code.claude.com/docs/en/memory "Claude reads them on demand using its standard file tools when it needs the information."
[^16]: https://code.claude.com/docs/en/memory "so all worktrees and subdirectories within the same repo share one auto memory directory."
[^17]: https://code.claude.com/docs/en/memory "Claude skips anything it can derive from the codebase, such as architecture, file paths, or debugging fixes."
[^18]: https://code.claude.com/docs/en/memory "Claude re-reads it from disk and re-injects it into the session."
[^19]: https://code.claude.com/docs/en/best-practices "Unlike CLAUDE.md instructions which are advisory, hooks are deterministic and guarantee the action happens."
[^20]: https://code.claude.com/docs/en/features-overview "If a rule must hold every time, make it a hook rather than a prompt instruction."
[^21]: https://code.claude.com/docs/en/costs "reducing context from tens of thousands of tokens to hundreds."
[^22]: https://code.claude.com/docs/en/hooks-guide "Claude can also create or modify files by running shell commands."
[^23]: https://code.claude.com/docs/en/hooks-guide "Since hooks run in parallel, the order is non-deterministic."
[^24]: https://code.claude.com/docs/en/hooks-guide "hooks can’t undo actions since the tool has already executed."
[^25]: https://code.claude.com/docs/en/hooks-guide "Claude Code overrides a Stop hook after it blocks eight times in a row with no tool call from Claude in between."
[^26]: https://code.claude.com/docs/en/hooks-guide "Because the filter is best-effort, use the permission system rather than a hook to enforce a hard allow or deny."
[^27]: https://code.claude.com/docs/en/hooks-guide "can tighten restrictions but not loosen them past what permission rules allow."
[^28]: https://www.anthropic.com/engineering/advanced-tool-use "That's 58 tools consuming approximately 55K tokens before the conversation even starts."
[^29]: https://www.anthropic.com/engineering/advanced-tool-use "At Anthropic, we've seen tool definitions consume 134K tokens before optimization."
[^30]: https://www.anthropic.com/engineering/advanced-tool-use "This represents an 85% reduction in token usage while maintaining access to your full tool library."
[^31]: https://code.claude.com/docs/en/costs "so only tool names and server instructions enter context until Claude uses a specific tool."
[^32]: https://www.anthropic.com/engineering/advanced-tool-use "Tool definitions consuming >10K tokens"
[^33]: https://www.anthropic.com/engineering/advanced-tool-use "Keep your three to five most-used tools always loaded, defer the rest."
[^34]: https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents "One of the most common failure modes we see is bloated tool sets that cover too much functionality or lead to ambiguous decision points about which tool to use."
[^35]: https://code.claude.com/docs/en/best-practices "CLI tools are the most context-efficient way to interact with external services."
[^36]: https://code.claude.com/docs/en/costs "are still more context-efficient than MCP servers because they don’t add any per-tool listing."
[^37]: https://code.claude.com/docs/en/features-overview "Claude matches your task against skill descriptions to decide which are relevant."
[^38]: https://code.claude.com/docs/en/skills "adds to your context on every turn, whether or not Claude ever uses it."
[^39]: https://code.claude.com/docs/en/skills "The budget scales at 1% of the model’s context window."
[^40]: https://code.claude.com/docs/en/skills "When the listing overflows, Claude Code drops descriptions starting with the skills you invoke least, so the skills you use most keep their full text."
[^41]: https://code.claude.com/docs/en/skills "each entry’s combined text is capped at 1,536 characters regardless of budget."
[^42]: https://code.claude.com/docs/en/skills "This removes the skill from Claude’s context entirely."
[^43]: https://code.claude.com/docs/en/skills "under 500 lines. Move detailed reference material to separate files."
[^44]: https://code.claude.com/docs/en/skills "keeping the first 5,000 tokens of each. Re-attached skills share a combined budget of 25,000 tokens."
[^45]: https://code.claude.com/docs/en/worktrees "Running each Claude Code session in its own worktree gives it a separate copy of the files to edit, so one session can build a feature while a second fixes a bug."
[^46]: https://threadreaderapp.com/thread/2007179832300581177.html "I run 5 Claudes in parallel in my terminal. I number my tabs 1-5, and use system notifications to know when a Claude needs input"
[^47]: https://threadreaderapp.com/thread/2007179832300581177.html "Anytime we see Claude do something incorrectly we add it to the"
[^48]: https://threadreaderapp.com/thread/2007179832300581177.html "More than that, it means you can run more Claudes in parallel."
[^49]: https://simonwillison.net/2025/Oct/5/parallel-coding-agents/ "I can only focus on reviewing and landing one significant change at a time, but I’m finding an increasing number of tasks that can still be fired off in parallel without adding too much cognitive overhead to my primary work."
[^50]: https://simonwillison.net/2025/Oct/5/parallel-coding-agents/ "if I want to run two agents in isolation against the same repo I do a fresh checkout"
[^51]: https://code.claude.com/docs/en/best-practices "A fresh context improves code review since Claude won’t be biased toward code it just wrote."
[^52]: https://www.anthropic.com/engineering/multi-agent-research-system "agents typically use about 4× more tokens than chat interactions, and multi-agent systems use about 15× more tokens than chats."
[^53]: https://code.claude.com/docs/en/costs "Agent teams use approximately 7x more tokens than standard sessions when teammates run in plan mode"
[^54]: https://www.anthropic.com/engineering/multi-agent-research-system "outperformed single-agent Claude Opus 4 by 90.2% on our internal research eval."
[^55]: https://www.anthropic.com/engineering/multi-agent-research-system "most coding tasks involve fewer truly parallelizable tasks than research, and LLM agents are not yet great at coordinating and delegating to other agents in real time."
[^56]: https://code.claude.com/docs/en/best-practices "Subagents run in separate context windows and report back summaries"
[^57]: https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents "returns only a condensed, distilled summary of its work (often 1,000-2,000 tokens)."
[^58]: https://www.anthropic.com/engineering/multi-agent-research-system "Each subagent needs an objective, an output format, guidance on the tools and sources to use, and clear task boundaries."
[^59]: https://www.anthropic.com/engineering/multi-agent-research-system "Simple fact-finding requires just 1 agent with 3-10 tool calls, direct comparisons might need 2-4 subagents with 10-15 calls each"
[^60]: https://code.claude.com/docs/en/best-practices "Give Claude a check it can run: tests, a build, a screenshot to compare."
[^61]: https://threadreaderapp.com/thread/2007179832300581177.html "If Claude has that feedback loop, it will 2-3x the quality of the final result."
[^62]: https://code.claude.com/docs/en/best-practices "runs your check as a script and blocks the turn from ending until it passes."
[^63]: https://code.claude.com/docs/en/best-practices "Have Claude show evidence rather than asserting success"
[^64]: https://code.claude.com/docs/en/best-practices "Chasing every finding leads to over-engineering: extra abstraction layers, defensive code, and tests for cases that can’t happen."
[^65]: https://code.claude.com/docs/en/best-practices "Tell the reviewer to flag only gaps that affect correctness or the stated requirements, and treat the rest as optional."
[^66]: https://www.anthropic.com/engineering/claude-code-sandboxing "In our internal usage, we've found that sandboxing safely reduces permission prompts by 84%."
[^67]: https://www.anthropic.com/engineering/claude-code-sandboxing "Without network isolation, a compromised agent could exfiltrate sensitive files like SSH keys; without filesystem isolation, a compromised agent could easily escape the sandbox and gain network access."
[^68]: https://www.anthropic.com/engineering/claude-code-auto-mode "in practice users accept 93% of them anyway."
[^69]: https://www.anthropic.com/engineering/claude-code-auto-mode "The 17% false-negative rate on real overeager actions is the honest number."
[^70]: https://www.anthropic.com/engineering/claude-code-auto-mode "It is not a drop-in replacement for careful human review on high-stakes infrastructure."
[^71]: https://www.anthropic.com/engineering/claude-code-auto-mode "on entering auto mode, we drop permission rules that are known to grant arbitrary code execution"
[^72]: https://www.anthropic.com/engineering/claude-code-auto-mode "If a session accumulates 3 consecutive denials or 20 total, we stop the model and escalate to the human."
[^73]: https://www.anthropic.com/engineering/claude-code-auto-mode "a server-side prompt-injection probe scans tool outputs (file reads, web fetches, shell output, external tool responses) before they enter the agent's context."
[^74]: https://code.claude.com/docs/en/security "Avoid piping untrusted content directly to Claude"
[^75]: https://code.claude.com/docs/en/security "Use virtual machines (VMs) to run scripts and make tool calls, especially when interacting with external web services"
[^76]: https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/ "We need to avoid the lethal trifecta combination of tools ourselves to stay safe."
[^77]: https://www.anthropic.com/engineering/claude-code-sandboxing "sensitive credentials (such as git credentials or signing keys) are never inside the sandbox with Claude Code."
[^78]: https://threadreaderapp.com/thread/2007179832300581177.html "I don't use --dangerously-skip-permissions."
[^79]: https://threadreaderapp.com/thread/2007179832300581177.html "Instead, I use /permissions to pre-allow common bash commands that I know are safe in my environment"
[^80]: https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents "as the number of tokens in the context window increases, the model’s ability to accurately recall information from that context decreases."
[^81]: https://code.claude.com/docs/en/best-practices "This matters since LLM performance degrades as context fills."
[^82]: https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents "find the smallest set of high-signal tokens that maximize the likelihood of your desired outcome."
[^83]: https://code.claude.com/docs/en/best-practices "If you’ve corrected Claude more than twice on the same issue in one session, the context is cluttered with failed approaches."
[^84]: https://code.claude.com/docs/en/best-practices "A clean session with a better prompt almost always outperforms a long session with accumulated corrections."
[^85]: https://code.claude.com/docs/en/costs "Claude Code sends your full conversation with every request"
[^86]: https://code.claude.com/docs/en/costs "fires on its interval even while the session is idle, sending your full context each time"
[^87]: https://code.claude.com/docs/en/costs "Thinking tokens are billed as output tokens, and the default budget can be tens of thousands of tokens per request depending on the model."
[^88]: https://code.claude.com/docs/en/costs "Sonnet handles most coding tasks well and costs less than Opus."
[^89]: https://code.claude.com/docs/en/costs "Reserve Opus for complex architectural decisions or multi-step reasoning."
[^90]: https://threadreaderapp.com/thread/2007179832300581177.html "I use Opus 4.5 with thinking for everything."
[^91]: https://threadreaderapp.com/thread/2007179832300581177.html "it is almost always faster than using a smaller model in the end."
[^92]: https://code.claude.com/docs/en/costs "the average cost is around $13 per developer per active day and $150-250 per developer per month"
