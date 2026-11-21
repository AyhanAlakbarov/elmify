# Data processing agreement: template for agencies

**Template — for review by a licensed lawyer.** Not legal advice. Basis: spec
`docs/superpowers/specs/2026-10-03-consent-and-privacy-notice-design.md` §5 and the memo
`docs/legal/2026-10-03-consent-and-privacy-memo.md` (Azerbaijan's Law on Personal Data, No. 998-IIIQ,
Art. 2.1.9 and 2.1.10 define the owner and the operator; Art. 9.9 and 10.3: roles by contract). Fill the bracketed fields before signing; record the signed
version on `AgencyDataUseAgreementVersion` (`agreement_reference`, `effective_at`).

Between **[Agency legal name, registration number, address]** (the "Agency", the owner (mülkiyyətçi, controller) of
the personal data of its students) and **[Elmify company name, registration number, address — to be
completed before launch]** ("Elmify", the operator (processor) that processes that data on the Agency's behalf).

## 1. Subject, nature and duration

1.1 Elmify provides the Agency's students with software that finds programmes and funding, prepares
CVs, motivation letters and applications, and sends applications to the universities and funders the
student chooses.

1.2 Elmify processes the personal data the Agency's students enter or upload (identity, contact,
education, transcripts and grades, CVs and letters, programme and funding choices, application status
and outcomes, connected mailbox messages, technical logs) for as long as this agreement is in force and
for the retention period in clause 8.

## 2. Instructions

2.1 Elmify processes personal data only on the Agency's documented instructions, which are this
agreement, the Agency's use of the service, and written instructions the Agency adds later.

2.2 Elmify tells the Agency without delay if it considers an instruction to breach the law.

2.3 Elmify does not use the data for its own purposes, with the one exception in clause 5.

## 3. Notice and consent

3.1 The Agency's students accept Elmify's agency privacy notice, which names the Agency as owner
(controller) and Elmify as its operator (processor). The Agency may replace it with its own notice, which must carry everything
the template carries: identity and contact of the owner, what is processed and why, sensitive
information, recipients with their countries, transfers abroad, retention, rights and how to use them,
and how changes are announced.

3.2 The Agency is responsible for the lawful basis for its students' data, including the consent
required for special categories of data and for transfers abroad. Elmify records each student's
acceptance of the notice version shown.

## 4. Sub-processors

4.1 The Agency authorises these sub-processors. **[Confirm each entry and country before launch.]**

| Sub-processor | Purpose | Country |
|---|---|---|
| Amazon Web Services | hosting, storage, queues | United States (company); region **[to be confirmed]** |
| OpenAI | AI language models | United States |
| Anthropic | AI language models | United States |
| OpenRouter | AI model routing | United States |
| AI language-model providers in China, for example Zhipu AI, Moonshot AI, DeepSeek, Alibaba Cloud, MiniMax | AI language models | People's Republic of China |
| **[E-mail delivery provider]** | service e-mails | **[country]** |

4.2 Elmify tells the Agency in writing before it adds or replaces a sub-processor, and the Agency may
object within **[14]** days. Elmify binds each sub-processor to obligations no weaker than these.

4.3 The Agency understands that the text of a CV or letter can identify a student and that data reaches
the countries in the table, and confirms that its students' consent covers those transfers.

## 5. Anonymisation

5.1 The Agency instructs Elmify, as an agreed instruction, to anonymise each student's data at the end
of the retention period (or on erasure, if earlier), before the personal data is deleted. **This
instruction takes effect when Elmify has built the anonymiser; until then Elmify deletes the data without
keeping any derived copy.**

5.2 Anonymised data holds no free text and nothing that singles out one person: banded features (field
of study, degree level, grade band, destination country, intake-year band, award type) and the outcome,
with any combination shared by fewer than 5 students not stored at row level. Nobody, including Elmify,
can link it back to a student. Elmify may keep it indefinitely and use it for statistics, improving
recommendations and testing its models.

## 6. Confidentiality

6.1 Elmify keeps the personal data confidential and allows access only to staff and sub-processors who
need it to provide the service and who are bound by confidentiality.

6.2 **DRAFT — for lawyer review (owner decision 2026-10-11).** Elmify's own support staff can view and
download the documents of the Agency's students to help with their applications. Every view and
download is recorded before the file is served, and the record is visible to the Agency. Any other
access by Elmify staff to a student's personal data (editing, acting for a student) takes a
time-limited, reasoned support grant.

## 7. Security

7.1 Elmify keeps the Agency's data separate from every other agency's with database row-level security
(tenant isolation), encrypts data at rest through its hosting provider, and uses encrypted connections.
Support staff reach an agency's data only under a time-boxed, reason-bound, logged support grant, except the audited file view and download in clause 6.2 (DRAFT — for lawyer review, owner decision 2026-10-11).

7.2 Elmify tells the Agency without undue delay, and in any case within **[72 hours]**, after becoming
aware of a personal data breach, with what it knows about the data and students affected.

## 8. Students' requests and retention

8.1 Elmify logs each student request (access, correction, deletion, objection, withdrawal of consent)
that reaches it, whatever the channel, and helps the Agency answer within the legal deadline of **7
working days** (extendable by 7 with notice; a reasoned refusal within 5 working days). Elmify forwards a
request that reaches it by **[2]** working days so the Agency keeps most of the deadline.

8.2 An objection or a withdrawal of consent stops all processing for that student at once.

8.3 Elmify keeps a student's personal data for as long as the account is active plus 12 months, then
deletes it. Elmify deletes it earlier on the student's request, and on the Agency's written instruction.

## 9. End of the agreement

9.1 When the agreement ends, Elmify, at the Agency's choice, returns the Agency's students' data in a
common format or deletes it within **[30]** days, except data it must keep by law, and then confirms
in writing. Data already anonymised under clause 5 is not personal data and stays with Elmify.

## 10. Audit

10.1 Elmify gives the Agency the information needed to show it follows this agreement and allows
audits by the Agency or its auditor, on **[30]** days' notice, once a year (more often after a breach),
during working hours and under confidentiality.

## 11. Liability, law and disputes

11.1 **[Liability cap and allocation — for the lawyer.]**

11.2 This agreement is governed by the law of the Republic of Azerbaijan. **[Courts or arbitration — for
the lawyer.]**

## Signatures

Agency: ____________________  Name, title, date: ____________________

Elmify: ____________________  Name, title, date: ____________________
