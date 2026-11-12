# Story fingerprints: which embedding model, what threshold, and can plpgsql do the cosine

Date: 2026-10-14. Feeds the letter-story amendment spec §4.4 and §10.2
(`.worktrees/letter-shape/docs/superpowers/specs/2026-10-14-letter-story-and-research-fit-amendment-design.md`).

## Answer first

1. **Model.** The summaries are always English, so an English model is enough. A multilingual one
   buys nothing for this comparison (this is an inference, not a published finding). Two choices
   fit the constraints:
   - **`text-embedding-3-small` with `dimensions=256` or `512`**, if the OpenAI organisation is
     approved for Zero Data Retention (ZDR). `/v1/embeddings` is ZDR-eligible, but ZDR has to be
     approved by OpenAI first. Without that approval, inputs stay in abuse-monitoring logs for up
     to 30 days, which breaks the constraint. Cost is negligible: $0.02 per million tokens.
   - **`BAAI/bge-small-en-v1.5` run locally on CPU**: MIT licence, 384 dimensions, MTEB STS
     average 81.59. Nothing leaves the server, so ZDR does not come into it.
   - bge-m3 and multilingual-e5-large-instruct are both 1024-dimensional, ~0.6B-parameter
     multilingual models. That is more model than an English-only 40–80-word comparison needs.
2. **Threshold.** None of the primary sources I read gives a cosine cut-off that separates "same
   idea" from "same topic". Two model cards say the opposite: absolute scores mean little, and
   their values bunch together (BGE in about [0.6, 1], e5 in about [0.7, 1.0]). BGE suggests
   picking a threshold from the distribution on your own data, "such as 0.8, 0.85, or even 0.9".
   **Calibrate it in-house, separately for each model and each dimension count.**
3. **plpgsql.** Comparing a few hundred floats against tens to hundreds of rows is a small job:
   100 rows × 512 dimensions is about 51,000 multiply-adds. I found no published measurement at
   this exact size, so the per-call time is **Unverified**. The closest measurement shows
   plpgsql/SQL array functions running 1.4×–10× slower than C, on 23-element vectors.
   **pgvector is available on RDS for PostgreSQL 17**: version 0.8.2 on 17.11.

## Sub-questions

1. For each candidate model: licence, dimensions, cost, ZDR or self-hosting, and MTEB STS score.
2. Is there published guidance on cosine thresholds for "near-duplicate" vs "same topic"?
3. Is plpgsql cosine feasible at this size (any measured numbers), and is pgvector on RDS PG17?

## 1. Candidate models

### Where the list came from

- The caller named OpenAI `text-embedding-3-small/large`, `BAAI/bge-m3` and
  `intfloat/multilingual-e5`.
- For the "small local CPU model" slot I ran one Exa search ("Hugging Face model card for a small
  English sentence embedding model that runs fast on CPU, with MTEB STS results"). It returned
  all-MiniLM-L6-v2, bge-small-en-v1.5 (as a distillation base), model2vec/potion static models,
  ogma and jina-embeddings-v2-small-en.
- I kept bge-small-en-v1.5 and all-MiniLM-L6-v2 because their own cards publish their licence and
  dimensions.
- I did not repeat the discovery search on a second engine, so the local-model list is Exa-only.

### Comparison

| Model | Licence | Dimensions | Cost | Data path | STS score (source) |
|---|---|---|---|---|---|
| OpenAI text-embedding-3-small | proprietary API | 1536 by default, can be shortened with `dimensions`[^1][^2] | $0.02 / 1M tokens[^3] | `/v1/embeddings` is ZDR-eligible[^5]; ZDR needs prior approval[^6] | STS not found on a primary page. MTEB overall average 62.3%[^4] |
| OpenAI text-embedding-3-large | proprietary API | 3072 by default, can be shortened[^1] | $0.13 / 1M tokens[^3b] | same as above | STS not found. MTEB overall average 64.6%[^4b] |
| BAAI/bge-m3 | MIT[^8] | 1024, 8192-token input[^9] | free, self-hosted | local | No English STS score on its card. **Unverified** |
| intfloat/multilingual-e5-large-instruct | MIT[^10] | 1024[^11] | free, self-hosted | local | STSBenchmark 88.4 (tech report)[^12] |
| BAAI/bge-small-en-v1.5 | MIT[^13] | 384[^14] | free, runs on CPU | local | MTEB STS (10 tasks) average 81.59[^14] |
| sentence-transformers/all-MiniLM-L6-v2 | Apache-2.0[^15] | 384[^16] | free, runs on CPU | local | Not on its own card. **Unverified** |

### Notes per model

**OpenAI 3-small / 3-large**
- The `dimensions` parameter shortens a vector so it keeps its "concept-representing properties".
  A 3-large vector cut to 256 dimensions still beats an uncut ada-002 vector (1536) on MTEB.[^2]
  So a fingerprint of a few hundred floats does not need a different model.
- If you cut a vector yourself instead of using the parameter, re-normalise it. The guide shows
  how (no footnote).
- Price works out to about $0.000002 for an ~100-token summary. That is my arithmetic from the
  $0.00002 per 1k tokens price.[^3]
- **ZDR status:** in OpenAI's endpoint table, `/v1/embeddings` shows abuse-monitoring retention
  "30 days", application state "None", and ZDR-eligible "Yes".[^5]
- ZDR and Modified Abuse Monitoring "are subject to prior approval by OpenAI".[^6] Without them,
  abuse-monitoring logs, which may hold prompts, are kept for up to 30 days.[^7]
- **So the OpenAI route meets the constraint only if the organisation (or project) is already
  ZDR-approved.** Whether Elmify's is approved is **Unverified** here.

**bge-m3**
- It is multilingual and supports dense, sparse and multi-vector retrieval.
- Its card says it no longer needs a query instruction.[^17]
- The dense output is fixed at 1024 dimensions according to its spec table.[^9] The card says
  nothing about truncating it.

**multilingual-e5-large-instruct**
- It needs a one-sentence task instruction on the query side.[^18]
- For a symmetric story-to-story comparison, both sides would probably carry the same instruction.
  That is not stated on the card: **Unverified**.

**Local CPU options**
- bge-small-en-v1.5 is the strongest small English option with self-published numbers. On BGE's
  own MTEB table it ties gte-small on dimensions (384) and scores higher on average.[^14]
- all-MiniLM-L6-v2 cuts input off after 256 word pieces.[^16] That is plenty for 40–80 words.

**Do we need a multilingual model?** No, as long as summaries are always produced in English.
- A multilingual model only matters when the two texts being compared can be in different
  languages. Here the summariser makes the input English. This is reasoning, not a sourced claim.
- OpenAI's 3-series is described as having "higher multilingual performance" anyway.[^19]

**Fingerprint version.** Store the model id, the dimension count and the normalisation flag
together, e.g. `text-embedding-3-small@512` or `bge-small-en-v1.5@384`.
- Thresholds do not carry over between models. Both open-model cards say their score
  distributions are compressed and model-specific.[^20][^21]
- So a version change should mean re-embedding or not comparing. A threshold should never be
  reused across versions. This is a design inference from those cards.

## 2. Threshold guidance

**No primary source I read gives a "near-duplicate idea" vs "same topic" cut-off for these
models.** What the sources do say:

- **BGE:** scores bunch in about [0.6, 1], so "a similarity score greater than 0.5 does not
  indicate that the two sentences are similar". It tells you to choose a threshold from the score
  distribution on your own data, "such as 0.8, 0.85, or even 0.9".[^20]
- **multilingual-e5:** scores bunch around 0.7–1.0 because of a low training temperature. "What
  matters is the relative order of the scores instead of the absolute values".[^21]
- **OpenAI:** the embeddings guide I read gives cosine similarity as the ranking measure. It gives
  no threshold.[^22] A threshold page elsewhere on OpenAI's site was not found: **Unverified**.

Conclusion: calibrate in-house. Use labelled pairs of same story, same topic but different
story, and unrelated, built from real summaries. Fit the cut-off separately for each model and
dimension count.

## 3. Cosine in plpgsql, and pgvector on RDS

**What the evidence covers**
- PL/pgSQL hands every expression to the main SQL executor as a prepared `SELECT`.[^23] A
  per-element `FOR` loop over 512 floats therefore makes 512 executor calls per row.
- Doing the sum inside one set-based statement avoids those per-element round-trips. Example:
  `SELECT sum(a*b) FROM unnest(x, y) AS t(a, b)`, called from the plpgsql function. This is an
  inference from that page; I did not measure it.

**Closest measurement found** (Stormatics, a vendor blog that published its own runs)
- Cosine over PostgreSQL `float4[]`, comparing pl/pgSQL, SQL, a C function and pgvector.[^24]
- C beat pl/pgSQL and SQL "~1.44x at worst (253 ms : 175 ms), and ~10x at best (50ms : 5ms)".
- Those vectors had 23 elements (`num_peaks = 23`), the table held 109,143 spectra, and the
  number of rows scanned per query is not stated.
- **Not transferable as a per-call figure for 100 rows × 512 dimensions: Unverified.**
- A one-off `EXPLAIN ANALYZE` on the local Postgres 17 with synthetic rows would settle it in
  minutes.

**Shortcut that is documented**
- If vectors are stored already normalised to length 1, cosine equals the dot product, which
  removes two norm computations per row.
- pgvector's README says this about OpenAI embeddings: "If vectors are normalized to length 1
  (like OpenAI embeddings), use inner product for best performance."[^25]
- For local models, normalise at write time. Both BGE and MiniLM show this in their usage code.

**pgvector on RDS for PostgreSQL 17: available.**
- AWS's extension table for PG17 lists pgvector 0.8.2 on 17.11, 17.10R2 and 17.10, 0.8.1 on
  17.7–17.9R2, and older versions on earlier minors.[^26][^27]
- If adopted, a pgvector value costs `4 * dimensions + 8` bytes.[^28]
- pgvector's `<=>` operator gives cosine distance, and cosine similarity is 1 minus that.[^29]
  At tens to hundreds of rows, an exact scan needs no index.

## Tools and gaps

- **Used:** Exa (discovery), Brave (AWS and plpgsql searches), scrapling `get`/`bulk_get` (every
  cited page), and the AWS Knowledge MCP (to locate the PG17 section of the 155k-character
  extensions page; the citation for it still comes from the live page).
- **Not used:** Context7 (no library-docs question) and Tavily.
- The OpenAI embeddings guide came back as 95k characters. I read the first ~45k, which covers
  dimensions, pricing and use cases. I did not read its FAQ section, which may hold a
  normalisation or threshold note.

## Sources

[^1]: https://developers.openai.com/api/docs/guides/embeddings "By default, the length of the embedding vector is 1536 for text-embedding-3-small or 3072 for text-embedding-3-large"
[^2]: https://openai.com/index/new-embedding-models-and-api-updates/ "a text-embedding-3-large embedding can be shortened to a size of 256 while still outperforming an unshortened text-embedding-ada-002 embedding with a size of 1536"
[^3]: https://openai.com/index/new-embedding-models-and-api-updates/ "from a price per 1k tokens of $0.0001 to $0.00002"
[^3b]: https://openai.com/index/new-embedding-models-and-api-updates/ "text-embedding-3-large will be priced at $0.00013 / 1k tokens"
[^4]: https://openai.com/index/new-embedding-models-and-api-updates/ "has increased from 61.0% to 62.3%"
[^4b]: https://openai.com/index/new-embedding-models-and-api-updates/ "while on MTEB, the average score has increased from 61.0% to 64.6%"
[^5]: https://developers.openai.com/api/docs/guides/your-data "/v1/embeddings No 30 days None Yes No"
[^6]: https://developers.openai.com/api/docs/guides/your-data "Currently, these controls are subject to prior approval by OpenAI and acceptance of additional requirements."
[^7]: https://developers.openai.com/api/docs/guides/your-data "By default, abuse monitoring logs are generated for all API feature usage and retained for up to 30 days"
[^8]: https://huggingface.co/BAAI/bge-m3 "arxiv: 5 papers License: mit"
[^9]: https://huggingface.co/BAAI/bge-m3 "BAAI/bge-m3 1024 8192 multilingual; unified fine-tuning (dense, sparse, and colbert)"
[^10]: https://huggingface.co/intfloat/multilingual-e5-large-instruct "arxiv: 4 papers License: mit"
[^11]: https://huggingface.co/intfloat/multilingual-e5-large-instruct "This model has 24 layers and the embedding size is 1024."
[^12]: https://arxiv.org/html/2402.05672 "STSBenchmark 84.0 85.6 87.3 88.4"
[^13]: https://huggingface.co/BAAI/bge-small-en-v1.5 "FlagEmbedding is licensed under the MIT License. The released models can be used for commercial purposes free of charge."
[^14]: https://huggingface.co/BAAI/bge-small-en-v1.5 "BAAI/bge-small-en-v1.5 384 512 62.17 51.68 43.82 84.92 58.36 81.59"
[^15]: https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/raw/main/README.md "language: en license: apache-2.0"
[^16]: https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2 "By default, input text longer than 256 word pieces is truncated."
[^17]: https://huggingface.co/BAAI/bge-m3 "The only difference is that the BGE-M3 model no longer requires adding instructions to the queries."
[^18]: https://huggingface.co/intfloat/multilingual-e5-large-instruct "Each query must come with a one-sentence instruction that describes the task"
[^19]: https://developers.openai.com/api/docs/guides/embeddings "They feature lower costs, higher multilingual performance, and new parameters to control the overall size."
[^20]: https://huggingface.co/BAAI/bge-small-en-v1.5 "please select an appropriate similarity threshold based on the similarity distribution on your data (such as 0.8, 0.85, or even 0.9)"
[^21]: https://huggingface.co/intfloat/multilingual-e5-large-instruct "what matters is the relative order of the scores instead of the absolute values"
[^22]: https://developers.openai.com/api/docs/guides/embeddings "To retrieve the most relevant documents we use the cosine similarity between the embedding vectors of the query and each document"
[^23]: https://www.postgresql.org/docs/17/plpgsql-expressions.html "All expressions used in PL/pgSQL statements are processed using the server's main SQL executor."
[^24]: https://stormatics.tech/blogs/peak-performance-pgvector-vs-postgresql-array-for-mass-spectrometry-databases "With ARRAY, C functions outperform pl/pgSQL and SQL functions in all cases, ~1.44x at worst (253 ms : 175 ms), and ~10x at best (50ms : 5ms)."
[^25]: https://github.com/pgvector/pgvector "If vectors are normalized to length 1 (like OpenAI embeddings), use inner product for best performance."
[^26]: https://docs.aws.amazon.com/AmazonRDS/latest/PostgreSQLReleaseNotes/postgresql-extensions.html "The following table shows PostgreSQL extensions for PostgreSQL version 17 that are currently supported on Amazon RDS."
[^27]: https://docs.aws.amazon.com/AmazonRDS/latest/PostgreSQLReleaseNotes/postgresql-extensions.html "pgvector 0.8.2 0.8.2 0.8.2 0.8.1 0.8.1 0.8.1 0.8.0"
[^28]: https://github.com/pgvector/pgvector "Each vector takes 4 * dimensions + 8 bytes of storage."
[^29]: https://github.com/pgvector/pgvector "For cosine similarity, use 1 - cosine distance"

## Open questions

- Is Elmify's OpenAI organisation or project approved for ZDR? If not, the OpenAI route fails the
  constraint and only a local model qualifies.
- MTEB STS-category scores for OpenAI 3-small/3-large and for bge-m3 (English) were not found on a
  primary page. The MTEB leaderboard is a JavaScript app and was not read.
- How long does a plpgsql/SQL dot product over 100 rows × 256–1024 `float4[]` take on PG17?
  Needs one local `EXPLAIN ANALYZE`.
- Does multilingual-e5-large-instruct need the instruction on both sides for symmetric similarity?
- The thresholds for "same idea" and "same topic" must be calibrated in-house; nothing published
  covers them.
