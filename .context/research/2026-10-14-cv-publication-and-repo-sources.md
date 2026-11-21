# Sources for CV publication and repository evidence (2026-10-14)

**Question.** Which metadata sources and libraries should the CV evidence engine use so that the text under a CV entry is accurate and can be traced to a source? Q1 covers publications reached from a DOI or other identifier. Q2 covers public GitHub repositories.

**Answer.**

- **Q1.** Keep Crossref as the authority for DOI bibliographic fields. Add OpenAlex beside it, not in its place. Send DataCite DOIs to DataCite, and arXiv IDs to the arXiv API.
- **Q1, ORCID.** Do not call the ORCID Public API. Its terms forbid use "in connection with any revenue-generating product or service", and students pay fees here.
- **Q1, Semantic Scholar.** Do not use it as an authority. Its data licences include CC BY-NC. Publishers remove abstracts from its output. In one of two test lookups it returned the wrong year.
- **Q2.** The REST plus stdlib approach is sound. The `/languages` endpoint already returns Linguist's byte counts, so a language detector adds little. GraphQL saves calls but needs a token.
- **Q2, authorship.** A commit belongs to whoever's GitHub account holds the author email. A co-author trailer counts only when it uses a linked email. A signed commit proves who held the key, but GitHub's default verification status does not prove the author agreed to the commit.

## Scope (sub-questions answered)

1. For each of Crossref, OpenAlex, DataCite, Semantic Scholar, ORCID, arXiv and Europe PMC: coverage claim, abstract availability, licence for commercial use, rate limits and keys, and one data-quality point.
2. OpenAlex API keys in 2026: required or optional?
3. Python clients: is habanero or pyalex worth using instead of plain REST?
4. GitHub: REST and GraphQL limits, unauthenticated and with a token, as documented in 2026.
5. Parsing and language detection: py-tree-sitter, Linguist and go-enry.
6. Proving that a student wrote a repository: commit emails, logins, forks, `Co-authored-by` and signatures.

**Where the candidate list came from.** Most options were named in the request. Two searches added to them:

- An Exa search for "official documentation pages of open scholarly metadata APIs…" added **OpenCitations Meta**.
- A Brave search for "dblp API documentation" added **dblp**.

Neither addition was investigated in depth (see Open questions).

**Tools.** Exa, Brave and scrapling were used. Context7 and Tavily were not needed.

**Pages that may fail the citation check.** The Semantic Scholar licence page and the Europe PMC API page render only in a browser. They were read with scrapling `fetch`, because `get` returned an empty page shell.

**dblp could not be read.** dblp.org returned an Anubis proof-of-work page to scrapling.

---

## Q1. Publication metadata

### Comparison

| Source | What it gives | Abstracts | Licence for commercial use | Limits and keys | Quality point |
|---|---|---|---|---|---|
| **Crossref** | Metadata that publishers deposit for Crossref DOIs | JATS, and optional[^3] | Open access with no signup[^1]; reuse licence not quoted (see Open questions) | Public pool 5 requests at 1 concurrent; polite pool (with `mailto`) 10 at 3[^2] | Measured: about 24% of records carry an abstract (below) |
| **OpenAlex** | Merged graph of Crossref, PubMed, ORCID and repositories | Inverted index only, "for legal reasons"[^8]; coverage over 60% for 2022 works, about 45% before 2000[^9] | CC0, with no personal-use carve-out[^7] | Key optional. No key: 10 requests/s and $0.10/day. Free key: 30 requests/s and $1/day[^4][^5][^6]. Single lookup by DOI is free[^6] | One author in six carries an ORCID[^11]; authorships capped at 100[^10] |
| **DataCite** | DataCite DOIs: datasets, software, many theses and preprints | Not checked in this pass | CC0 over all DOIs and deposited metadata[^16][^17] | 500 requests per 5 minutes unidentified, 1000 with a `mailto`[^15] | No published figure fetched |
| **Semantic Scholar** | Academic Graph covering 214M papers | Publishers can remove them (measured, below) | Data licences "such as CC BY-NC or ODC-BY"[^20]; attribution required[^21] | Without a key: 1000 requests/s shared by all users. With a key: 1 request/s to start[^18][^19] | One DOI not found; another returned the wrong year (below) |
| **ORCID Public API** | A researcher's self-maintained list of works | n/a | **Non-commercial only**[^24] | 25k reads/day anonymous[^23] | n/a (barred by its terms) |
| **arXiv API** | arXiv e-prints, no DOI needed | Yes: the abstract counts as descriptive metadata[^27] | Metadata is CC0[^26]; the full texts are not | One request every 3 seconds, one connection[^25] | No published figure fetched |
| **Europe PMC** | Life sciences: PubMed, Agricola, patents | Yes, through `resulttype=core`[^28] | Not found on the API page | Not found on the API page | No published figure fetched |

### Abstracts

**Crossref.** Publishers may include abstracts formatted as JATS XML.[^3] They are optional.

Measured on 2026-10-14 with two live counts:

- `api.crossref.org/works?filter=has-abstract:true&rows=0` returned `total-results` 45,616,437.
- `api.crossref.org/works?rows=0` returned 187,633,100.

That is **about 24% of Crossref records with any abstract**. The counts change daily, so they carry no quote footnote.

**OpenAlex.** The field `abstract_inverted_index` is confirmed. OpenAlex "does not ship plaintext abstracts for legal reasons; reconstruct the abstract from the index."[^8]

**Semantic Scholar.** A live call for DOI 10.1145/3065386 returned `"abstract": null` and a notice that "The following paper fields have been elided by the publisher".[^22]

### OpenAlex keys in 2026: the sources disagree

- **pyalex README** (third party): "Starting February 13, 2026, an API key is required to use the OpenAlex API."[^31] It quotes 100 credits/day without a key.
- **OpenAlex's own docs** (page last updated 2026-10-12): "you can make basic queries with no key at all".[^4] Without a key you get $0.10/day.[^6]

**OpenAlex owns this fact, so the key is optional.** In practice, the keyless budget is only "enough to try the API".[^6] Use a free key: it raises the budget tenfold and the rate from 10 to 30 requests per second.[^5] Lookups by DOI cost nothing whatever the budget.[^6]

### Author order, ORCIDs and disambiguation

**OpenAlex.**

- Each authorship carries `author_position` and `raw_orcid` exactly as deposited.
- ORCIDs reach OpenAlex only on the work itself. It "never looks the person up in the ORCID registry".[^12]
- Only one authorship in six carries an ORCID.[^11]
- An ORCID is dropped as untrusted "when it is stamped on more than one author of that work".[^13]
- Author profiles fail in two ways: splitting, and merging "works from different people collapsed into one profile".[^14]
- For a CV, use the printed name and position on that work (`raw_author_name`, `author_position`). Do not use the clustered author profile.

**Crossref.** Crossref is the upstream for most ORCIDs in OpenAlex.[^12] The exact fields Crossref uses for ORCID are not confirmed from a fetched page in this pass.

### Measured quality point: the same DOI from two sources

DOI 10.1145/3065386 is the 2017 Communications of the ACM version of AlexNet. Both calls were made on 2026-10-14.

| | OpenAlex | Semantic Scholar |
|---|---|---|
| Call | `api.openalex.org/works/doi:10.1145/3065386?select=…` | `api.semanticscholar.org/graph/v1/paper/DOI:10.1145/3065386?fields=…` |
| Year | **2017** (correct) | **2012** (wrong) |
| Venue | Communications of the ACM | Communications of the ACM |
| Authors | Krizhevsky, Sutskever, Hinton, in order | Same order |
| ORCID | `null` for all three | n/a |
| Abstract | n/a | Removed by the publisher[^22] |

Semantic Scholar appears to have merged the 2017 version with the 2012 conference paper. A CV line built from it would show the wrong year.

A second Semantic Scholar lookup, `DOI:10.1038/nature14539`, returned `Paper with id DOI:10.1038/nature14539 not found`. These are two single samples, not a coverage rate.

### Publications without a DOI

- **arXiv preprints.** Use the arXiv API. Metadata, including the abstract, is CC0.[^26][^27] Keep to one request every 3 seconds.[^25]
- **Theses and other repository items.** Many carry DataCite DOIs, which are covered by DataCite's CC0 metadata.[^16]
- **Theses or proceedings with no DOI at all.** No primary source that answers this was checked. See Open questions.
- **dblp.** It covers computer-science proceedings without DOIs. Its pages say "All metadata is released as open data under CC0 1.0 license", but that comes only from a Brave snippet. dblp.org blocked the fetch, so this is **Unverified**.

### Python clients

**pyalex.**

- It converts the inverted index into plain text "on the fly".[^32]
- Latest release: v0.21, dated 2026-02-23 on its GitHub release page.
- Its README is out of date on keys (above).
- Worth using for abstract reconstruction and paging. Plain REST plus a few lines of code does the same job.

**habanero.**

- "a low level client for working with Crossref's search API"[^34].
- Latest release: v2.9.2, dated 2026-06-17 on its GitHub release page.
- It adds little over plain REST for single DOI lookups.

The two release dates come from each page's `datetime` attribute, so they carry no quote footnote.

**Recommendation.** Stay on plain REST unless the engine starts doing searches or paging. Calling with a DOI needs one GET per source.

---

## Q2. Understanding GitHub repositories

### Rate limits (2026 docs)

**REST.**

- 60 requests per hour unauthenticated.[^35]
- 5,000 per hour with a personal token.[^36]

**GraphQL.**

- 5,000 points per hour per user.[^37]
- A query's cost is roughly the number of connection requests divided by 100.[^38]
- The docs describe only authenticated access (token, GitHub App or OAuth).[^39] That GraphQL refuses anonymous calls is **Unverified** from a fetched page.

**Both.**

- No more than 100 concurrent requests.[^40]

### REST or GraphQL

**GraphQL** can return languages, topics, the README object and recent commit history in one query of about one point. It requires a token.

**The current REST path** works without a token for public repositories.

The REST languages endpoint returns "the number of bytes of code written in that language".[^44] Those counts come from Linguist, which "is used on GitHub.com to detect blob languages … and generate language breakdown graphs".[^51]

**Recommendation.** Move to GraphQL only if the 60/hour unauthenticated REST budget becomes the bottleneck. At that point you need a token anyway.

### Parsing and language detection

**py-tree-sitter.**

- Ships pre-compiled wheels with no library dependencies.[^48] Each language grammar is its own wheel.[^49]
- Worth adding only when the engine must read languages other than Python. The stdlib `ast` module already covers Python.

**Linguist.**

- A Ruby gem that needs Ruby and native libraries.[^50]
- Not a fit for a Python service. Its output is already available through `/languages`.

**go-enry.**

- Has Python bindings for Python 3.9+, published on PyPI as `enry`.[^52]
- Wheels exist only for Linux x86_64 and macOS.[^53]
- It follows Linguist v9.5.0 data[^55] and does not support `.gitattributes` overrides.[^54] Its results can therefore differ from GitHub's own figures.
- Worth using only for per-file language detection of fetched files, if that is ever needed.

### Proving the student wrote the repository

**How GitHub links commits to people.**

- "GitHub links a commit to a user by matching the email address in the commit header to an email address on a GitHub account."[^45] The email is whatever the committer's Git configuration wrote.
- *Inference:* anyone can put the student's address in a commit. A linked login is therefore attribution, not proof.

**The contributors endpoint.**

- "GitHub identifies contributors by author email address."[^41]
- "only the first 500 author email addresses in the repository link to GitHub users". The rest come back as anonymous.[^42]

**Forks.**

- The `parent` and `source` objects "are present when the repository is a fork".[^43]
- A forked repository's history includes the upstream authors' commits. Count only commits linked to the student's login.

**Co-authored-by trailers.**

- They count as a contribution only with "an email address associated with their account on GitHub.com".[^46]
- A trailer with an unlinked email is free text.

**Signed commits.**

- A cryptographically verifiable GPG, SSH or S/MIME signature gets the "Verified" mark.[^47]
- Vigilant mode is off by default. When an author other than the committer has it on, "the commit signature doesn't guarantee the consent of the author".[^47]
- So "Verified" proves who held the key, not who wrote the code.

**Practical rule for the engine.** Accept as the student's:

- commits whose `author.login` equals the student's verified GitHub handle, and
- `Co-authored-by` trailers whose email links to that handle.

For a fork, count only the student's commits on top of the parent. Treat the share of commits as the strength of the claim. Never write "built X" from the repository owner field alone.

---

## Sources

[^1]: https://www.crossref.org/documentation/retrieve-metadata/rest-api/access-and-authentication/ "Anyone can access the REST API, no signup or registration is required."
[^2]: https://www.crossref.org/documentation/retrieve-metadata/rest-api/access-and-authentication/ "Public 5 1 Polite 10 3 Plus 150 None"
[^3]: https://www.crossref.org/documentation/principles-practices/best-practices/abstracts/ "You can include JATS-formatted abstracts with your metadata records."
[^4]: https://help.openalex.org/api/authentication/ "you can make basic queries with no key at all"
[^5]: https://help.openalex.org/api/authentication/ "a free key gives you 10× the keyless budget"
[^6]: https://help.openalex.org/access/example-costs.md "Without a key you get $0.10/day — a tenth of the above, enough to try the API."
[^7]: https://help.openalex.org/access/pricing.md "carve-out and no permission to ask"
[^8]: https://help.openalex.org/data/works/attributes/ "OpenAlex does not ship plaintext abstracts for legal reasons; reconstruct the abstract from the index."
[^9]: https://help.openalex.org/data/works/attributes/ "over 60% of 2022 works vs. ~45% of pre-2000 works"
[^10]: https://help.openalex.org/data/works/attributes/ "Capped at the first 100 authors for performance."
[^11]: https://help.openalex.org/data/authors/orcid.md "Across the whole corpus, one authorship in six carries an ORCID."
[^12]: https://help.openalex.org/data/authors/orcid.md "When OpenAlex matches a new work to an author, it never looks the person up in the ORCID registry."
[^13]: https://help.openalex.org/data/authors/orcid.md "An ORCID is not trusted on a work when it is stamped on more than one author of that work"
[^14]: https://help.openalex.org/data/authors/disambiguation.md "works from different people collapsed into one profile"
[^15]: https://support.datacite.org/docs/rate-limit "500 requests per 5 minutes per IP address"
[^16]: https://support.datacite.org/docs/datacite-data-file-use-policy "The DataCite Data File includes all DOIs and deposited metadata in our database."
[^17]: https://support.datacite.org/docs/datacite-data-file-use-policy "has waived all copyright and related or neighboring rights to DataCite Data File"
[^18]: https://www.semanticscholar.org/product/api "rate-limited to 1000 requests per second shared among all unauthenticated users"
[^19]: https://www.semanticscholar.org/product/api "The introductory rate limit for an API key is 1 RPS on all endpoints."
[^20]: https://www.semanticscholar.org/product/api/license "such as CC BY-NC or ODC-BY"
[^21]: https://www.semanticscholar.org/product/api/license "Licensee will include an attribution to “Semantic Scholar” on its website"
[^22]: https://api.semanticscholar.org/graph/v1/paper/DOI:10.1145/3065386?fields=title,abstract,authors,venue,year "The following paper fields have been elided by the publisher"
[^23]: https://info.orcid.org/ufaqs/what-are-the-api-limits/ "25k reads/day (Per IP address)"
[^24]: https://info.orcid.org/public-client-terms-of-service/ "you may not make use of the public APIs in connection with any revenue-generating product or service"
[^25]: https://info.arxiv.org/help/api/tou.html "make no more than one request every three seconds"
[^26]: https://info.arxiv.org/help/api/tou.html "Creative Commons Universal (CC0 1.0) Public Domain"
[^27]: https://info.arxiv.org/help/api/tou.html "includes fields such as title, abstract, authors"
[^28]: https://europepmc.org/RestfulWebService "returns full metadata for a given publication ID; including abstract, full text links, and MeSH terms"
[^31]: https://github.com/J535D165/pyalex "Starting February 13, 2026, an API key is required to use the OpenAlex API."
[^32]: https://github.com/J535D165/pyalex "PyAlex can convert the inverted abstracts into plaintext abstracts on the fly"
[^34]: https://github.com/sckott/habanero "This is a low level client for working with Crossref's search API."
[^35]: https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api "The primary rate limit for unauthenticated requests is 60 requests per hour."
[^36]: https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api "All of these requests count towards your personal rate limit of 5,000 requests per hour."
[^37]: https://docs.github.com/en/graphql/overview/rate-limits-and-query-limits-for-the-graphql-api "5,000 points per hour per user"
[^38]: https://docs.github.com/en/graphql/overview/rate-limits-and-query-limits-for-the-graphql-api "and round the result to the nearest whole number to get the final aggregate point value"
[^39]: https://docs.github.com/en/graphql/guides/forming-calls-with-graphql "You can authenticate to the GraphQL API using a personal access token, GitHub App, or OAuth app."
[^40]: https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api "No more than 100 concurrent requests are allowed."
[^41]: https://docs.github.com/en/rest/repos/repos?apiVersion=2022-11-28 "GitHub identifies contributors by author email address."
[^42]: https://docs.github.com/en/rest/repos/repos?apiVersion=2022-11-28 "only the first 500 author email addresses in the repository link to GitHub users"
[^43]: https://docs.github.com/en/rest/repos/repos?apiVersion=2022-11-28 "objects are present when the repository is a fork"
[^44]: https://docs.github.com/en/rest/repos/repos?apiVersion=2022-11-28 "The value shown for each language is the number of bytes of code written in that language."
[^45]: https://docs.github.com/en/pull-requests/how-tos/commit-changes/troubleshooting-commits "GitHub links a commit to a user by matching the email address in the commit header to an email address on a GitHub account."
[^46]: https://docs.github.com/en/pull-requests/how-tos/commit-changes/creating-a-commit-with-multiple-authors "For the commit to count as a contribution, use an email address associated with their account on GitHub.com."
[^47]: https://docs.github.com/en/authentication/managing-commit-signature-verification/about-commit-signature-verification "the commit signature doesn't guarantee the consent of the author"
[^48]: https://github.com/tree-sitter/py-tree-sitter "The package has no library dependencies and provides pre-compiled wheels for all major platforms."
[^49]: https://github.com/tree-sitter/py-tree-sitter "Tree-sitter language implementations also provide pre-compiled binary wheels."
[^50]: https://github.com/github-linguist/linguist "Linguist is a Ruby library so you will need a recent version of Ruby installed."
[^51]: https://github.com/github-linguist/linguist "This library is used on GitHub.com to detect blob languages"
[^52]: https://github.com/go-enry/go-enry "Python bindings using a C shared library and cffi are available for Python 3.9+."
[^53]: https://github.com/go-enry/go-enry "Pre-built wheels are available for Linux (x86_64) and macOS (Intel + Apple Silicon)."
[^54]: https://github.com/go-enry/go-enry "Overriding languages and types though .gitattributes is not yet supported."
[^55]: https://github.com/go-enry/go-enry "library is based on the data from github/linguist version v9.5.0"

## Open questions

- **Crossref reuse licence and abstract copyright.** The reuse terms were not quoted from a fetched page. Abstracts may stay the publisher's copyright even where the facts are free. Check Crossref's metadata licence page before storing abstracts.
- **ORCID Member API.** A fee-based membership is the only ORCID route for a revenue-generating product. The cost and terms were not fetched.
- **Europe PMC** rate limits and reuse licence. Neither appears on the API page.
- **Theses and proceedings with neither a DOI nor an arXiv ID.** No primary source was checked (candidates: BASE, CORE, national thesis repositories, dblp, OpenCitations Meta). The dblp CC0 claim is Unverified because the site blocked the fetch.
- **DataCite abstracts.** Whether DataCite records reliably carry an abstract-type description was not checked.
- **Semantic Scholar error rates.** The wrong year and the not-found DOI are two single samples. No published error rate was found.
- **GitHub GraphQL without a token.** Rejection of unauthenticated calls is inferred from the docs describing only token auth. It was not confirmed by a quote or a live call.
- **Crossref rate limit time unit.** The table gives 5/10/150 but leaves the interval to the `x-rate-limit-interval` header. That it means "per second" is Unverified.
