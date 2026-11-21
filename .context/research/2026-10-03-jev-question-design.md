# Designing Jev (jev-1.13) questions: what TypeSafe's own docs say

Date: 2026-10-03. Scope: rules for auditing ~40 Jev questions that read multilingual scholarship pages.

## How this was researched

- Sources: docs.typesafe.ai pages fetched live as Markdown (`<page>.md`, which the site serves for any docs page), TypeSafe's own agent skill (`github.com/typesafe-ai/skills`, linked from docs.typesafe.ai/agent-skill), and OpenRouter's Jev guide. All quotes were copied from scrapling `get` output.
- Pages read in full: llms.txt index, primitives, choice, noul, advanced (structure), confidence, state, models, model-jaggedness/jev-1.13, how-to-build-with-system-one, AI primer, API reference, agent-skill, SKILL.md, plus these cookbooks: SDE cascade, date extraction, self-consistency (noul), self-consistency (choice), parallel questions, pre-parsed value extraction, guardrails for LLMs, classifying RAG passages, line-by-line search, classification using confidence.
- **Not read** (step budget): the cookbooks on re-ranking, structure recovery, function calling, skill suggestion, entity alignment, citation check, hierarchical classification and autoresearch, plus the Score, System One, Patterns and use-case pages. They may hold more guidance.
- No search engines were needed, because the brief named the sources. Exa, Brave and Tavily were not used.

---

## 1. Noul vs Choice, options, criteria

**When to use each.**
- Use Noul for a yes/no judgment and Score for a position on a spectrum.[^4] A Noul near 0.5 means yes and no are about equally likely. It does not mean a medium amount of something.[^100]
- When two question types both seem to fit, prefer the one whose answer your code can act on directly.[^5]
- TypeSafe's own skill says to use one Noul per label when several labels may apply, because a Choice picks exactly one.[^98]

**Choice with `none` / `not_stated` options: yes, the docs recommend it.**
- Primitives: give the full list of options, and add an `other` or `none of the above` option when the list might not cover every input.[^3]
- The jaggedness page recommends an explicit "not stated" option for date parts, so that a missing part is reported rather than guessed.[^44]
- The date cookbook puts a `none` option, with a description, on every part question. The pre-parsed extraction cookbook gives every selection a `none` escape hatch.[^81]
- The skill says to include a no-match outcome, or to use a separate presence judgment when that is independently useful.[^95][^96]
- **Important caveat:** Choice probabilities always sum to 1. Some option therefore ranks first even when nothing fits. The line-search cookbook pairs the Choice with a Noul that checks whether an answer exists at all.[^89] A Noul's probability does not depend on the other options.[^90]

**Limits on option count.**
- The API accepts at most 255 options per Choice.[^91][^82]
- The classification cookbook says a Choice "works reliably up to roughly 240 options".[^83]
- Options are cheap: each one costs a few tokens, and the docs say to give the full list rather than a shortlist.[^11]
- The date cookbook offers 153 year options, but suggests pulling the year-like numbers out of the text first and offering only those.[^73]

**Option names vs descriptions.**
- Both the option names and their descriptions are sent to the model. Write descriptions that separate the options from each other.[^10]
- A `null` description is fine when the name is clear on its own.[^14]
- Start with a one-line description per option.[^15] Move to an object only when the model keeps confusing two similar options.[^12]
- **Unverified:** whether names or descriptions carry more weight. No page compares the two.

**Writing criteria.**
- Noul `criteria` is an optional pair of `true`/`false` descriptions.[^22] Try each question with and without criteria, and keep whichever version gives better answers on your documents.[^19]
- The `{what, not_for, examples}` object shape is a convention, not part of the API. The field names `question`, `focus`, `what`, `not_for` and `examples` are not reserved. The model sees the field names, so use short names that label what follows.[^13]
- Use the same field names across all options so the model can compare them directly.[^59]
- Examples inside criteria are endorsed. For a subtle yes/no boundary, structured `true`/`false` descriptions can carry a definition and examples on each side.[^24]
- Criteria must agree with the instructions. A Noul whose `true` maps to "no" performs worse.[^49]

## 2. State shape, `inspect`/`focus`, size, batching

- **Keyed objects are recommended over plain strings.** Use an object for most requests so each part of the state has a descriptive name.[^32] Arrays are listed for sequences of messages or records.
- **Pointing at parts of the state** is done in the question text, with backticks. Name the part with a dot-and-index path, including the backticks.[^6][^58]
- **`inspect` / `focus` are not API fields; they are a text convention.** The API's `instructions` field accepts a string, object or array. Field names such as `focus` are explicitly not reserved and are seen by the model as labels.[^13]
  - `inspect` and `compare` appear only as example keys in the how-to-build guide, which puts the question in one field and its guiding data in the others.[^63]
  - **Unverified:** whether `inspect` gets any special handling. Nothing says so, and the API reference lists no such field.
- **Unrelated state hurts. This is a named failure mode.**
  - Accuracy falls as the state grows with content unrelated to the decision.[^46]
  - Jev "suffers from context rot".[^52]
  - The fix: retrieve and filter in code first, and send only the fields the question needs.[^47] Where you cannot filter in code, use a Noul to filter for relevance (worked example in the RAG cookbook).
- **Chunking.** The docs give no fixed chunk size.
  - Patterns shown: one request per passage in the RAG cookbook[^88]; line IDs as Choice options, in windows of at most 255 lines, in line search.
  - **Unverified:** any recommended chunk length.
- **Token limits, and the sources disagree.**
  - TypeSafe's Models page: 64k tokens per request, of which 32k is for `state` plus the single longest question.[^34] It also says the 64k budget covers the `state` plus all questions combined, and the 32k budget applies to the `state` plus the single longest question.[^35]
  - OpenRouter's guide: "Context length is 32,000 tokens".[^93] Its FAQ says the 32,000 covers "the state you send plus the questions".
  - TypeSafe owns the model, but OpenRouter owns its own routing limits. For calls through OpenRouter, budget for 32k covering state plus all questions until that is measured.
- **Questions are independent.** Every question sees the same state and is evaluated on its own.[^1] One answer is not hidden context for another.[^8] The parallel-questions cookbook measured this: no question's answer depended on the 12 other questions in its request.[^79]
- **Per-question cost.** Extra questions cost only their own tokens, which are cheap.[^7] Billing is per input token; output is free.[^38]
  - **Unverified, my own arithmetic:** the parallel-questions cookbook's cost table implies about 50–60 input tokens of overhead per short Noul.
- **Question IDs are not sent to the model.** Write the complete question in `instructions`.[^2][^92]

## 3. Wording

- **Literalness.** "`jev-1.13` answers the question you wrote, not the one you meant."[^39] Scoping words, negations and implied conditions are read at face value. Where interpretation is unavoidable, split it into two literal questions and combine them in code.[^40]
- **Negation and indirection.** Double negatives and complex indirection are answered less reliably.[^45]
- **Compound questions.** Ask one yes/no question per Noul.[^16] "Hiding several judgments inside one question" is on the jaggedness page's list of things to avoid.[^57]
- **Yes means present.** Phrase the question so that a high value means yes. The docs give "Is the message free of personal data?" as the inverted example to avoid.[^17]
  - The SDE cascade frames every verifier question so that the bad case is `true`. That is the same rule applied to error-checking: the escalate case gets the yes.[^69]
- **Statement vs question.** A statement works as well as a question; try both with your own data.[^18]
- **Snap judgments.** Ask for a judgment a knowledgeable person makes in a second.[^9] Ask the most explicit, narrow, atomic questions you can.[^62]
- **Wording variance vs repeat variance.**
  - Repeat variance is documented:
    - The Noul cookbook measured a mean per-question standard deviation of 0.0102.[^74] One borderline question still crossed 0.5 across repeats.[^75]
    - In the Choice cookbook, labels flipped within repeats, including TypeSafe's.[^77]
    - Six of eight Nouls in the parallel-questions cookbook were identical on every repeat.
  - **Unverified:** how much answers vary across *wordings*. No page measures it.
- **A/B testing wordings.**
  - The only guidance is to try phrasings and criteria on your own data[^18][^19], and to reorder Choice options to check the answer stays the same.[^51]
  - The playground lets you change wording without writing any code.[^71]
  - TypeSafe says agents are not good at writing questions and their questions should be edited.[^101] No A/B testing method is documented.

## 4. Confidence

- **How it is computed.** It is derived from the probabilities: 1 when all the probability is on one outcome, 0 when it is spread evenly.[^25]
  - Choice: `(p_max − 1/n)/(1 − 1/n)`, which measures how far the top probability sits above an even split.[^26] Only the top probability counts.
  - Noul: no confidence field.[^20] For a matching number, use `|2p − 1|`.[^30]
  - TypeSafe calls its formula "one reasonable way" to summarise a distribution.[^31]
- **Calibration.**
  - The claim is that higher probability means a higher chance of being correct.[^64] This holds across groups of predictions, not for any single answer.[^65]
  - The skill says typed output guarantees the interface, not the truth, and tells you to validate performance in your own domain.[^97]
  - **Unverified:** any published calibration measurement for jev-1.13.
- **Thresholds.** None are universal; scale them with risk.[^21]
  - Example values in the docs: a 0.5 Choice confidence floor[^28]; Noul review bands of 0.3–0.7 or 0.2–0.8; a 0.6 top-probability floor in the Choice cookbook; 0.9 in the classification cookbook; a 0.7 escalation gate in the SDE cascade.
  - Each of these is labelled illustrative.[^76][^99]
  - Start conservative and tune on your own data.[^29] Plot confidence against accuracy.[^61]
- **Comparability across question types.**
  - Top probability depends on the option count: 0.5 is weak among two options and strong among ten, so set the threshold per question.[^27]
  - `confidence` is on the same 0–1 scale across Choice questions, but a Noul has none. Use `|2p−1|` to compare it with a Choice.[^30]
- **Low-confidence handling.**
  - Use three paths: act, confirm or review, or do not act.
  - Escalate to a person or to a more expensive reasoning model.[^60]
  - Answer at a coarser level, for example the division above the group.[^84]
  - If you only need the best option, take the top one; no threshold is needed.[^102]
  - When versions change, pin the version ID if your thresholds were tuned against it.[^37]
- **SDE cascade (escalating to another model).**
  - The pattern: extract with a cheap LLM, then verify each field with narrow Nouls in which `true` means wrong. Escalate if any per-field P(wrong) exceeds 0.7.[^68] The cascade takes the max, not the mean.
  - Good verifier questions are narrow and grounded, for example one checkable yes/no about one field against the source.[^69] Vague questions give "mushy, uncalibrated scores".[^66] Per-field flags localise the error.[^67]
  - The cookbook ran `jev-1.12`.

## 5. Multilingual

- Jev's primary training language is English. Other languages, including CJK scripts, are accepted but currently have lower accuracy.[^33] Test on your own content before relying on Jev for a non-English workload.[^36]
- **Unverified:** whether to translate the state, whether question text should be in English, and any language hints. No page addresses these.
- One related note: number formats vary by locale. For a decimal comma versus a decimal point, ask a Noul which convention the document uses and branch on it in code.[^103]

## 6. Numbers, dates, counting

- Jev is not a calculator.[^41] Keep the arithmetic in code.
- **Counting** is unreliable.[^42] Iterate over the candidates in code, ask one question each, and sum the answers.[^56]
- **Numeric representations** are weaker than semantic ones. Hex colours, for example, do worse than English colour names.[^53] Score levels are weak in numerical calibration, so do not interpolate between them to recover a number.[^54]
- **Dates** are read as text, not as ordered quantities.[^43] Extract each part as a Choice that includes a "not stated" option[^44], then compare and resolve in code.[^72] The date cookbook takes a date's confidence as the minimum across its parts.[^72]
- **Values** should be selected, not generated. Find candidates with a regex or an LLM, and let Jev pick one.[^55] Jev cannot invent a value outside the candidates it is given.[^81]

## 7. Adversarial or injected state

- State is data, and jev-1.13 does not treat it as hostile by default. Injected or self-arguing text can move the answer.[^48] Mitigation: write explicit criteria and test edge cases.
- The guardrails cookbook claims a jailbreak "scores as a jailbreak instead of working as one".[^85] Two notes on that claim:
  - It ran `jev-1.12` on a curated sample.
  - It conflicts in tone with the jaggedness page. The jaggedness page, which is versioned and reviewed 2026-10-02, is the more authoritative of the two for jev-1.13.
- The RAG cookbook asks a dedicated "attempts to control the system" Noul. It says this question is a filter, not a security boundary.[^86][^87]

## 8. Other documented anti-patterns and jagged edges

- **Option order:** Jev leans toward the first option.[^50] Reorder the options to check the answer stays the same.[^51]
- **Generation:** Jev is not trained to generate text. Do not chain Choices to produce strings.
- **Mismatch between instructions and criteria:** align them.[^49]
- **Noul as a degree scale:** a Noul gives the probability of yes, not an intensity. Use a Score for degree.[^4][^100]
- **Irrelevant fields:** the cookbooks' changing `uid` field could not separate sensitivity to an irrelevant field from plain repeat noise.[^104]
- **No explanations:** Jev returns no reasoning or text. If you need a justification, use a chat model.[^94]

---

## Checklist for auditing a Jev question

1. The `instructions` text states the whole question; nothing depends on the question ID.[^2]
2. Exactly one judgment: no "and/or" across two conditions.[^16][^57]
3. Phrased so that yes or high means the thing is present (no "free of…" inversions).[^17]
4. No double negatives or multi-hop indirection.[^45]
5. Literal: the exact condition and its boundary cases are written out, not implied.[^39][^40]
6. The right type: a yes/no condition is a Noul; mutually exclusive options are a Choice; several labels that can co-occur are separate Nouls.[^4][^98]
7. Every Choice has a `none`/`not_stated`/`other` option when the list may not cover the input.[^3][^44]
8. Where "is it there at all?" matters, a separate presence Noul is asked alongside the Choice.[^89][^96]
9. A Choice has at most 255 options, and ideally no more than about 240.[^91][^83]
10. Option descriptions separate neighbouring options, use the same field names across options, and use objects only where options get confused.[^10][^12][^59]
11. Noul `true`/`false` criteria agree with the instructions; the question was tested with and without them.[^49][^19]
12. Parts of the state are named with backticked dot paths.[^6]
13. The state holds only what the question needs, with no page chrome or unrelated sections.[^46][^52]
14. The state plus the longest question fits in 32k tokens, and the whole request in 32k when called through OpenRouter.[^34][^93]
15. No counting, arithmetic or date comparison is asked of Jev. These are done in code, with dates read part by part.[^41][^42][^43]
16. Values are selected from candidates found in code, never generated.[^55]
17. Option order was varied in testing and the answer stayed the same.[^50][^51]
18. Non-English pages were tested on real content, and their thresholds watch confidence.[^33][^36]
19. Thresholds are set per question on labelled data, with a review band; Noul and Choice cut-offs are not mixed.[^27][^29][^30]
20. The state is treated as possibly adversarial: criteria are explicit, and an injection check is a filter, not a boundary.[^48][^87]

## Open questions

- Whether option names or option descriptions carry more weight in a Choice. Not documented.
- How much answers vary across wordings compared with repeats, and any method for A/B testing wordings. Not documented beyond "try both on your data".
- Whether to translate non-English state, or write questions in the page's language. Not documented.
- The real context limit through OpenRouter: 32k total, or TypeSafe's 64k with 32k for state plus the longest question. Measure with a large request.
- Any recommended chunk size, and the exact per-question token overhead. Neither is published.
- Whether `inspect` (unlike `focus`, which is explicitly non-reserved) gets any special treatment. Unlikely, but not stated.
- Unread cookbooks (re-ranking, citation check, entity alignment, hierarchical classification, function calling, skill suggestion, structure recovery, autoresearch) and the Score page may contain more rules.

## Sources

[^1]: https://docs.typesafe.ai/primitives.md "Every question in a request sees the same state, is evaluated independently, and returns a typed answer under the ID you chose."
[^2]: https://docs.typesafe.ai/primitives.md "Question IDs are for your code. They are not sent to the model."
[^3]: https://docs.typesafe.ai/primitives.md "Give the full list of options, and add an `other` or `none of the above` option when the list might not cover every input."
[^4]: https://docs.typesafe.ai/primitives.md "Use Noul for a yes/no judgment and Score to measure a position on a spectrum."
[^5]: https://docs.typesafe.ai/primitives.md "If two types both seem to fit, prefer the one whose answer your code can act on directly."
[^6]: https://docs.typesafe.ai/primitives.md "name it in the `instructions` with a dot-and-index path to its key, including the backticks"
[^7]: https://docs.typesafe.ai/primitives.md "Adding questions barely changes the response time and costs only the tokens for the extra questions, which are cheap."
[^8]: https://docs.typesafe.ai/primitives.md "One question's answer is not hidden context for another."
[^9]: https://docs.typesafe.ai/primitives.md "Ask for a judgment a knowledgeable person makes in a second given the right context."
[^10]: https://docs.typesafe.ai/primitives/choice.md "The option names and their descriptions are both sent to the model, so write descriptions that separate the options from each other."
[^11]: https://docs.typesafe.ai/primitives/choice.md "A Choice question accepts up to 255 options, and adding options costs a few tokens each"
[^12]: https://docs.typesafe.ai/primitives/choice.md "When two options are similar and the model keeps confusing them, describe each one with an object instead of a string."
[^13]: https://docs.typesafe.ai/primitives/choice.md "The field names `question`, `focus`, `what`, `not_for`, and `examples` are not part of the API, and none are reserved."
[^14]: https://docs.typesafe.ai/primitives/choice.md "The `tone` question uses `null` descriptions because the option names are clear on their own."
[^15]: https://docs.typesafe.ai/primitives/choice.md "Start with a one-line description per option."
[^16]: https://docs.typesafe.ai/primitives/noul.md "Ask one yes/no question per Noul."
[^17]: https://docs.typesafe.ai/primitives/noul.md "Phrase the question so that a high value means yes."
[^18]: https://docs.typesafe.ai/primitives/noul.md "Try both phrasings with your own data to see which works better."
[^19]: https://docs.typesafe.ai/primitives/noul.md "try your questions with and without `criteria` and keep whichever gives better answers on your documents"
[^20]: https://docs.typesafe.ai/primitives/noul.md "There is no separate `confidence` value for a Noul"
[^21]: https://docs.typesafe.ai/primitives/noul.md "Where to set the threshold depends on the cost of being wrong."
[^22]: https://docs.typesafe.ai/primitives/noul.md "Make the boundary between yes and no unambiguous."
[^24]: https://docs.typesafe.ai/primitives/advanced.md "structured `true` and `false` descriptions let you pin it down with a definition and examples on each side"
[^25]: https://docs.typesafe.ai/confidence.md "It is 1 when all the probability is on one outcome and 0 when the probability is spread evenly."
[^26]: https://docs.typesafe.ai/confidence.md "This measures how far the top probability sits above an even split"
[^27]: https://docs.typesafe.ai/confidence.md "since 0.5 is a weak answer among two options and a strong one among ten, so set its threshold per question"
[^28]: https://docs.typesafe.ai/confidence.md "The 0.5 confidence floor catches anything the model reports as genuinely uncertain."
[^29]: https://docs.typesafe.ai/confidence.md "Start with conservative thresholds, test with your own data, and adjust as you observe results."
[^30]: https://docs.typesafe.ai/confidence.md "for example to gate Nouls and Choices with the same code, use the distance from 0.5"
[^31]: https://docs.typesafe.ai/confidence.md "TypeSafe's `confidence` is one reasonable way to summarize a distribution, not the only one."
[^32]: https://docs.typesafe.ai/concepts/state.md "Use an object for most requests so each part of the state has a descriptive name and its relationships remain clear."
[^33]: https://docs.typesafe.ai/concepts/state.md "Jev's primary training language is English; other languages, including CJK scripts, are accepted but currently have lower accuracy"
[^34]: https://docs.typesafe.ai/models.md "64k tokens per request; 32k tokens for `state` plus the longest question"
[^35]: https://docs.typesafe.ai/models.md "The 64k budget covers the `state` plus all questions combined; the 32k budget applies to the `state` plus the single longest question."
[^36]: https://docs.typesafe.ai/models.md "test on your own content before relying on Jev for a non-English workload"
[^37]: https://docs.typesafe.ai/models.md "If you have tuned confidence thresholds against a specific version, pin that version's ID instead of the alias"
[^38]: https://docs.typesafe.ai/models.md "Charged per input token. Output tokens are free."
[^39]: https://docs.typesafe.ai/model-jaggedness/jev-1.13.md "`jev-1.13` answers the question you wrote, not the one you meant."
[^40]: https://docs.typesafe.ai/model-jaggedness/jev-1.13.md "Where interpretation is unavoidable, split it into two literal questions and combine them in code."
[^41]: https://docs.typesafe.ai/model-jaggedness/jev-1.13.md "Jev is not a calculator."
[^42]: https://docs.typesafe.ai/model-jaggedness/jev-1.13.md "`jev-1.13` does not count reliably."
[^43]: https://docs.typesafe.ai/model-jaggedness/jev-1.13.md "`jev-1.13` reads dates as text, not as ordered quantities."
[^44]: https://docs.typesafe.ai/model-jaggedness/jev-1.13.md "so a missing part is reported rather than guessed"
[^45]: https://docs.typesafe.ai/model-jaggedness/jev-1.13.md "Instructions carrying double negatives or complex indirection are answered less reliably."
[^46]: https://docs.typesafe.ai/model-jaggedness/jev-1.13.md "Accuracy falls as the state grows with content unrelated to the decision."
[^47]: https://docs.typesafe.ai/model-jaggedness/jev-1.13.md "retrieve and filter in code first, and send only the fields the question needs"
[^48]: https://docs.typesafe.ai/model-jaggedness/jev-1.13.md "State is data, and `jev-1.13` does not treat it as hostile by default."
[^49]: https://docs.typesafe.ai/model-jaggedness/jev-1.13.md "For example, a Noul where `true` maps to no and `false` maps to yes will perform worse."
[^50]: https://docs.typesafe.ai/model-jaggedness/jev-1.13.md "`jev-1.13` leans toward the option that comes first"
[^51]: https://docs.typesafe.ai/model-jaggedness/jev-1.13.md "reorder the options to double check that the answer stays consistent"
[^52]: https://docs.typesafe.ai/model-jaggedness/jev-1.13.md "Jev suffers from context rot, so unrelated material in the `state` costs you accuracy."
[^53]: https://docs.typesafe.ai/model-jaggedness/jev-1.13.md "questions about colors using hex values will underperform compared to those using the English names"
[^54]: https://docs.typesafe.ai/model-jaggedness/jev-1.13.md "`jev-1.13`'s score levels are weak in numerical calibration"
[^55]: https://docs.typesafe.ai/model-jaggedness/jev-1.13.md "it is better to extract possible options using regex or a generative model and let `jev-1.13` pick the correct extraction"
[^56]: https://docs.typesafe.ai/model-jaggedness/jev-1.13.md "iterate in code over the candidates and ask one question for each"
[^57]: https://docs.typesafe.ai/model-jaggedness/jev-1.13.md "Hiding several judgments inside one question."
[^58]: https://docs.typesafe.ai/concepts/how-to-build-with-system-one.md "Use a backticked dot-and-index path to point a question at a specific nested value"
[^59]: https://docs.typesafe.ai/concepts/how-to-build-with-system-one.md "Use the same field names across options so the model can compare them directly."
[^60]: https://docs.typesafe.ai/concepts/how-to-build-with-system-one.md "Escalate uncertain cases to a person or a more expensive reasoning model."
[^61]: https://docs.typesafe.ai/concepts/how-to-build-with-system-one.md "Test thresholds by plotting confidence against accuracy on your data."
[^62]: https://docs.typesafe.ai/concepts/how-to-build-with-system-one.md "Ask the most explicit, narrow, specific, atomic questions you can."
[^63]: https://docs.typesafe.ai/concepts/how-to-build-with-system-one.md "Put the question in one field and the data that guides the question in the others."
[^64]: https://docs.typesafe.ai/introduction/machine-learning-primer.md "Higher probability should correspond to a greater chance that the answer is correct."
[^65]: https://docs.typesafe.ai/introduction/machine-learning-primer.md "These rates describe groups of predictions, not a guarantee about any single answer."
[^66]: https://docs.typesafe.ai/cookbooks/sde_cascade.md "vague questions give mushy, uncalibrated scores"
[^67]: https://docs.typesafe.ai/cookbooks/sde_cascade.md "a per-field flag localizes the error and stays sparse and strong"
[^68]: https://docs.typesafe.ai/cookbooks/sde_cascade.md "escalate if any per-field P(wrong) exceeds this"
[^69]: https://docs.typesafe.ai/cookbooks/sde_cascade.md "one checkable yes/no about one field against the source"
[^71]: https://docs.typesafe.ai/cookbooks/date_extraction_cookbook.md "to change the wording without writing any code"
[^72]: https://docs.typesafe.ai/cookbooks/date_extraction_cookbook.md "a date's confidence is the lowest one among the parts that went into it"
[^73]: https://docs.typesafe.ai/cookbooks/date_extraction_cookbook.md "If a list that long bothers you, pull the year-like numbers out of the text first and offer the model only those."
[^74]: https://docs.typesafe.ai/cookbooks/consistency_noul_cookbook.md "TypeSafe's mean per-question probability standard deviation is `0.0102`"
[^75]: https://docs.typesafe.ai/cookbooks/consistency_noul_cookbook.md "Its `covered` answers span `0.43` to `0.53`, crossing a `0.5` decision threshold."
[^76]: https://docs.typesafe.ai/cookbooks/consistency_noul_cookbook.md "The band is illustrative; it is neither a calibrated guarantee nor an optimized threshold."
[^77]: https://docs.typesafe.ai/cookbooks/consistency_choice_cookbook.md "picked labels can flip inside a single condition, including TypeSafe"
[^79]: https://docs.typesafe.ai/cookbooks/parallel_questions.md "no question's answer depends on the 12 other questions sharing its request"
[^81]: https://docs.typesafe.ai/cookbooks/pre_parsed_value_extraction_cookbook.md "Because TypeSafe only ever chooses among the spans the regex found"
[^82]: https://docs.typesafe.ai/cookbooks/pre_parsed_value_extraction_cookbook.md "A `Choice` question allows at most 255 options."
[^83]: https://docs.typesafe.ai/cookbooks/classification_using_confidence.md "a Choice works reliably up to roughly 240 options"
[^84]: https://docs.typesafe.ai/cookbooks/classification_using_confidence.md "When the model is unsure of the group, report the division it belongs to."
[^85]: https://docs.typesafe.ai/cookbooks/llm_guardrails.md "scores as a jailbreak instead of working as one"
[^86]: https://docs.typesafe.ai/cookbooks/classifying_rag_passages.md "The injection question is a filter, and only one."
[^87]: https://docs.typesafe.ai/cookbooks/classifying_rag_passages.md "Nothing here is a security boundary."
[^88]: https://docs.typesafe.ai/cookbooks/classifying_rag_passages.md "Nothing batches passages into one request, because each question is about one pair."
[^89]: https://docs.typesafe.ai/cookbooks/semantic_find.md "Choice probabilities always add up to 1, so some line ranks first even when the document doesn't answer the question."
[^90]: https://docs.typesafe.ai/cookbooks/semantic_find.md "Unlike the Choice probabilities, the Noul probability doesn't depend on the other options"
[^91]: https://docs.typesafe.ai/api.md "You can have a maximum of 255 options per Choice."
[^92]: https://docs.typesafe.ai/api.md "The key is not sent to the underlying model and is not used in inference."
[^93]: https://openrouter.ai/docs/guides/community/jev "Context length is 32,000 tokens."
[^94]: https://openrouter.ai/docs/guides/community/jev "Jev does not produce reasoning traces, explanations, or free-form text."
[^95]: https://raw.githubusercontent.com/typesafe-ai/skills/main/skills/typesafe-ai/SKILL.md "Include a no-match outcome when nothing may fit"
[^96]: https://raw.githubusercontent.com/typesafe-ai/skills/main/skills/typesafe-ai/SKILL.md "use a separate presence judgment when it is independently useful"
[^97]: https://raw.githubusercontent.com/typesafe-ai/skills/main/skills/typesafe-ai/SKILL.md "Typed output guarantees the interface, not truth."
[^98]: https://raw.githubusercontent.com/typesafe-ai/skills/main/skills/typesafe-ai/SKILL.md "use one per label when several may apply"
[^99]: https://raw.githubusercontent.com/typesafe-ai/skills/main/skills/typesafe-ai/SKILL.md "Treat cookbook thresholds and demo results as examples to evaluate"
[^100]: https://raw.githubusercontent.com/typesafe-ai/skills/main/skills/typesafe-ai/SKILL.md "means similar probability for yes and no, not medium intensity"
[^101]: https://docs.typesafe.ai/agent-skill.md "Agents aren't great at writing questions, so expect to edit collaboratively with them."
[^102]: https://docs.typesafe.ai/agent-skill.md "If all you care about is choosing the best option, you just need to choose the option with the highest confidence"
[^103]: https://docs.typesafe.ai/cookbooks/pre_parsed_value_extraction_cookbook.md "Ask a `Noul` question which convention the document uses, and branch on it in code."
[^104]: https://docs.typesafe.ai/cookbooks/consistency_noul_cookbook.md "This setup cannot separate sensitivity to the irrelevant field from variation that would occur on identical requests."
