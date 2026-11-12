# How official university CV guides show (a) an accepted-but-not-started degree and (b) a degree in progress

Date: 2026-10-12. Scope: academic CVs (admissions, fellowships, academic jobs), from university careers services and graduate schools only.

## Answer

**(b) Degree in progress: settled.** Every academic CV guide that addresses it puts the word **"expected"** next to the completion date. None of them prints a bare future date. The phrasing is consistent:

- Berkeley: `Comparative Biochemistry, expected May 2026`.[^1]
- Colorado Boulder Graduate School: completion date only, with "(expected)" next to the year.[^2]
- University of Washington: the word 'expected' goes with the anticipated completion date.[^3]
- Princeton: the date the degree "is expected to be" conferred, as [Month YYYY].[^4]
- Bradford (UK, general CV): the same idea applied to the grade, "expected 2:1".[^5]

Two guides add that the candidate should be able to back up the expected date. Berkeley says to be ready to explain why you can finish by then.[^6] UW suggests a short status line, such as a scheduled defence.[^7]

**(a) Accepted but not started: no official guidance found.** None of the official guides I read says how to list a degree or position that has been accepted but has not started. That includes how to word it and whether to list it at all. Searches for "incoming", "admitted", "starting" and "offer of a place" on university domains turned up only Reddit, Quora and commercial résumé blogs, and none of those count as sources here. The nearest official rule is for publications that are accepted but not yet out:

- List them only once they are actually accepted, not when submitted.[^8]
- Put a status word ("forthcoming", "in press", "accepted") where the date would go.[^9][^10]
- Berkeley also has you list presentations you "will deliver", so future items do belong on an academic CV.[^11]

That supports a rule by analogy: list the future degree only if the admission is confirmed, and print its status where the date would go. It does not give exact wording for a degree.

## Recommendation for the CV generator

This is my synthesis from the sources above. No source prescribes it word for word.

- **In progress:** keep the start date and mark the end date as expected, for example `Sep 2024 – Jun 2026 (expected)`. A guide that lists completion dates only (Berkeley, Colorado) would print just `expected Jun 2026`.[^1][^2] Either way, "expected" must sit next to any future end date.
- **Accepted, not started:** never print `Oct 2026 – present`, because "present" claims the student is already enrolled. Print the status where the date goes, the same way "forthcoming" replaces a publication's year. For example: `Admitted; starts Oct 2026`, or `Incoming, from Oct 2026`. Only print it when the admission is confirmed; an application that is still pending does not count.[^8]
- **Placement:** in Education, as the first entry, because every guide orders Education newest first.[^12] Putting it there is an inference; no source discusses it. Whether to include it at all is a product decision (see Open questions). It may be irrelevant to a master's application, and for an application to a competing programme it is arguably harmful.

## Per-guide table

| Guide | Kind | (b) in progress, verbatim | (a) accepted, not started |
|---|---|---|---|
| UC Berkeley Career Engagement, "The CV – Part 2" | Academic CV (faculty jobs) | `Comparative Biochemistry, expected May 2026`[^1] | NOT FOUND. Analogy: accepted works are "forthcoming"; list presentations you "will deliver".[^8][^11] |
| Colorado Boulder Graduate School, "How to Write a CV" | Academic CV | Completion dates only, with "(expected)". Example layout: `2019 (expected) PhD History`[^2] | NOT FOUND |
| University of Washington C&IC, "Academic CVs" | Academic CV | the word 'expected' with your anticipated completion date, plus a status line[^3][^7] | NOT FOUND. Analogy: accepted article → 'in press' / 'forthcoming' instead of the year.[^9] |
| Princeton Center for Career Development, "CV Writing Guide for Graduate Students" | Academic CV | date [Month YYYY] the degree "is expected to be" conferred[^4] | NOT FOUND. Analogy: accepted work counts as published.[^10] |
| Harvard Mignone Center (GSAS) | Academic **cover letter** wording (the CV samples are in a PDF I did not read) | "with an expected degree [or defense] in [Month, Year]"[^13] | NOT FOUND |
| University of Bradford Careers | General UK CV (the page also covers academic CVs) | `BSc (Hons) Computer Science – expected 2:1` (the expected *result*, not the date)[^5] | NOT FOUND |
| Oregon State Graduate Career Guide (PDF) | **Résumé** checklist | **Unverified** (search snippet only; the PDF could not be fetched): it says to put the projected date (e.g. June 2026) "vs. explaining that it is expected or anticipated". This is the one dissent, and it is résumé guidance. | NOT FOUND |
| Cambridge Careers, "CVs & Cover Letters for PhDs & Postdocs" (PDF) | Academic CV | **Unverified** (search snippet only): its sample CV shows `Geography PhD – nearing completion` | NOT FOUND |
| Oxford Careers, "Academic Applications" | Academic CV (also for postgraduate course applications) | Example CVs are PDFs, not read. The HTML page has no date wording. | NOT FOUND |
| Imperial, Toronto, UCC | Academic CV (PDF handouts) | Not read (PDF only) | NOT FOUND |
| MIT, Stanford, ETH, TUM, Europass | n/a | No relevant page surfaced in the searches | NOT FOUND |

## How the sources were found

- Exa `web_search_exa` with three queries: academic CV + expected date; listing an accepted-but-not-started programme; incoming students' education section. Also Exa `web_search_advanced_exa` restricted to 15 university domains.
- Brave `brave_web_search` with five queries using "incoming", "accepted", "offer of a place" and site:ac.uk / site:edu.
- Every page cited was fetched live with scrapling `get`. PDFs failed in scrapling ("All strings must be XML compatible"), so the PDF guides are marked Unverified or not read.
- Tools that were available but not used: Tavily and Context7 (not relevant here).

## Sources

[^1]: https://career.berkeley.edu/grad-students-postdocs/academic-job-search/the-cv-part-2-elements/ "Comparative Biochemistry, expected May 2026"
[^2]: https://www.colorado.edu/graduateschool/services-resources/career-resources/how-write-cv "List completion dates only, with the text “(expected)” included along with the completion year of your current degree."
[^3]: https://careers.uw.edu/resources/academic-careers-cvs/ "If you are ABD, include the word ‘expected’ with your anticipated completion date"
[^4]: https://careerdevelopment.princeton.edu/guides/resume-cv-cover-letter-perspective-statement/cv-writing-guide-for-graduate-students "List each institution, degree, field concentration and date [Month YYYY] your degree was (or is expected to be) conferred."
[^5]: https://www.bradford.ac.uk/careers/applications/cv/ "If you have not yet graduated, you can give your predicted or expected degree results, e.g. BSc (Hons) Computer Science – expected 2:1."
[^6]: https://career.berkeley.edu/grad-students-postdocs/academic-job-search/the-cv-part-2-elements/ "be prepared to explain the basis for your confidence that you can finish by that date"
[^7]: https://careers.uw.edu/resources/academic-careers-cvs/ "consider including a brief statement regarding the status of your dissertation so the search committee has some idea how realistic your anticipated completion date is"
[^8]: https://career.berkeley.edu/grad-students-postdocs/academic-job-search/the-cv-part-2-elements/ "You should only do this if your work has in fact been accepted, and not if it has only been submitted or is under review."
[^9]: https://careers.uw.edu/resources/academic-careers-cvs/ "If an article has been accepted for publication, indicate ‘in press’ or ‘forthcoming’ in lieu of the"
[^10]: https://careerdevelopment.princeton.edu/guides/resume-cv-cover-letter-perspective-statement/cv-writing-guide-for-graduate-students "If your work is accepted and/or in the final process of production, consider it published work."
[^11]: https://career.berkeley.edu/grad-students-postdocs/academic-job-search/the-cv-part-2-elements/ "List all the papers and presentations you have delivered or will deliver"
[^12]: https://www.colorado.edu/graduateschool/services-resources/career-resources/how-write-cv "Education entries, like almost everything else in your CV, will be listed in reverse chronological order with current degree first."
[^13]: https://careerservices.fas.harvard.edu/resources/gsas-cv-cover-letter-guide-2/ "I am completing my PhD in [department or field] with an expected degree [or defense] in [Month, Year]."

## Open questions

- **Wording for an accepted-but-not-started degree.** No official careers or admissions guide was found that covers it. The exact string ("Admitted; starts Oct 2026" or "Incoming, from Oct 2026") is a product decision based on the publication analogy, not a sourced convention.
- **Whether to include it on a master's admissions CV at all.** No source discusses this. Whether listing a confirmed place elsewhere helps or hurts an application to another programme is a judgement call for the owner.
- **European / Europass convention.** I found no ETH, TUM or Europass text on this. The Europass editor's "ongoing" handling was not checked.
- **PDF guides not read** (scrapling cannot parse PDFs): Harvard GSAS CV samples, Oxford example CVs, the Cambridge PhD CV book, Imperial, Toronto, UCC and Oregon State. Their wording is unverified.
