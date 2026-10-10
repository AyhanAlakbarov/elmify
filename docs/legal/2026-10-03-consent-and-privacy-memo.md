# Consent and privacy: legal position at launch (research memo, 2026-10-03)

Model-written research memo, not legal advice. Written to inform the consent and privacy-notice
spec. Every "needs a lawyer" item below must be confirmed by a licensed Azerbaijani lawyer before
launch.

## Bottom line

For an Azerbaijani company serving students located in Azerbaijan, **Azerbaijan's Law on Personal
Data (No. 998-IIIQ, 11 May 2010, last amended by No. 1193-VIQD, 28 Jun 2024) is the binding
constraint, not the GDPR.** Text read: https://frameworks.e-qanun.az/19/f_19675.html

## 1. When the GDPR / UK GDPR applies

- No EU establishment + students located in Azerbaijan: the GDPR does not apply (Art. 3(2) protects
  people "in the Union"; nationality is irrelevant; EDPB Guidelines 3/2018). High confidence.
- It starts to apply if Tehsil targets people in the EU (post-arrival services, EU marketing),
  monitors their behaviour in the EU (profiling students after arrival), or opens an EU
  establishment. Under Art. 3(2) an Art. 27 EU representative is then required. Acting as a
  processor for an EU university does not by itself bring Tehsil under the GDPR.
- An EU-incorporated Tehsil is under the GDPR for all processing (Art. 3(1)); sending data to
  Azerbaijani agencies is then a Chapter V transfer (no adequacy decision for Azerbaijan).
- UK GDPR: same Art. 3 analysis; Data (Use and Access) Act 2025 effects not verified.

## 2. Azerbaijan, Law on Personal Data

- **Lawful bases (Art. 9.6) are only four:** consent (or "open" data); a law setting the purpose;
  scientific/statistical research with mandatory anonymisation; protection of life or health.
  **There is no legitimate-interests basis.** High confidence.
- **Consent must be written (Art. 8.1):** paper, or an electronic document with an enhanced
  (qualified) e-signature; or information the subject submitted in writing. Art. 8.2 lists its
  contents: subject and owner identity, purpose, data and operations, validity and withdrawal
  terms, destruction/archiving terms. Art. 8.6 (2024) routes consent and withdrawal through the
  E-Government Information System — implementation for private companies unconfirmed.
  **A ticked checkbox very likely does not meet "written".** Medium-high confidence.
- **Special categories (Art. 2.1.6, 9.7):** race/ethnicity, family life, religion, health, criminal
  record — written consent required. Motivation letters often reveal health or family facts.
- **Retention (Art. 9.4):** destroy without delay once the purpose is achieved. Statistics need
  irreversible **anonymisation** (Art. 2.1.15, 9.6.3, 9.13); pseudonymised data is not enough.
- **Rights (Art. 7):** access, correction, destruction, a ban on processing, and an objection that
  needs no reasons; processing stops immediately (Art. 7.2). Requests come in writing: paper with ID,
  or electronic with an enhanced e-signature (Art. 7.5). Reply within 7 working days, extendable by
  7 (Art. 12.4); a reasoned refusal within 5 working days (Art. 12.6).
- **Disclosure to third parties, including an agency:** written consent (Art. 13.1).
- **Cross-border transfer (Art. 14):** barred if it threatens national security or the destination
  lacks equivalent protection; permitted regardless with the subject's consent. No official
  adequacy list found.
- **Registration (Art. 15.1–15.2):** register the information system before processing (1 month;
  changes notified within 3 working days). Cabinet Decision No. 237 (17 Dec 2010) reportedly exempts
  systems under 1,000 subjects — primary text not read. Art. 9.14 licence status unverified.
- **Localisation:** none found in this Law.
- **Penalties:** Code of Administrative Offences Art. 375, AZN 300–500; court damages (Art. 10.1).

## 3. GDPR legitimate interests (only if the GDPR applies)

- Three-step test (EDPB Guidelines 1/2024; CJEU C-621/22 *KNLTB*).
- Improving recommendations with pseudonymised, minimised outcome data: viable (medium-high).
- Training/testing own models on CVs and letters: accepted in principle (EDPB Opinion 28/2024; CNIL
  2025), with safeguards: clear information, minimisation, pseudonymisation, filtering Art. 9 data,
  anti-memorisation, and an unconditional opt-out offered before processing. Keeping full raw
  documents after the service is the weakest element (medium).
- Aggregate statistics: viable; better anonymised first (high).
- **Checkbox:** with contract + legitimate interests no consent is needed; the notice is provided,
  not agreed to. "I agree to the Privacy Notice" implies consent and would be invalid consent for
  optional processing (Art. 7(2), Recital 43; CJEU C-252/21 *Meta v Bundeskartellamt*). Use "I agree
  to the Terms" with a linked Privacy Notice.

## 4. Objection by email only

- GDPR: Art. 12(2) duty to facilitate; Art. 21(4) right shown "explicitly … clearly and separately";
  Art. 21(5) automated means for online services; EDPB Guidelines 01/2022 and 03/2022 (deceptive
  design). A monitored privacy mailbox is probably lawful, but an online-only service offering no
  in-account route while relying on the opt-out as its balancing safeguard risks an "obstructing"
  finding (medium). One month to respond, extendable by two; direct-marketing objection is absolute.
- Azerbaijan: email alone is not a statutory form; paper and enhanced-e-signature requests must be
  accepted.

## 5. Marketing to former customers

- ePrivacy Art. 13(2) soft opt-in: email obtained in a sale, own similar services, opt-out at
  collection and in every message. Agency-sourced (B2B) students do not qualify.
- Azerbaijan E-Commerce Law Art. 6.2 allows unsolicited commercial email with a working opt-out
  register (WIPO copy may be outdated); processing the address still needs a Personal Data Law
  basis, in practice consent.

## 6. Retention

- GDPR Art. 5(1)(e): justify per purpose. A flat 5 years for raw CVs and letters is hard to defend;
  defensible for minimised outcome features with a documented reason.
- Pseudonymised data stays personal data for the controller (Recital 26; EDPB Guidelines 01/2025;
  CJEU C-413/23 P *EDPS v SRB*, 4 Sep 2025).
- Azerbaijan: the term must appear in the written consent (Art. 8.2.5–8.2.6, 9.4).

## 7. Transfers to Chinese AI hosts

- GDPR: no adequacy for China; SCCs (Decision 2021/914) plus a transfer impact assessment
  (*Schrems II*); Art. 49 cannot cover systematic transfers; stripped CVs/letters remain personal
  data. The notice names countries and safeguards (Art. 13(1)(f)). OpenRouter does not remove the
  transfer. (Irish DPC TikTok decision, May 2025, cited from memory, not fetched.)
- Azerbaijan Art. 14: use the consent route.

## 8. B2B

- GDPR Art. 26 joint control is lawful with an arrangement whose essence is shown to students, but
  the likelier correct model is agency = controller, Tehsil = processor (Art. 28) for the service,
  Tehsil = separate controller for its own analytics/training (EDPB Guidelines 07/2020).
- Azerbaijan: owner/operator roles by contract (Art. 9.9, 10.3); no joint-controller concept found.

## 9. Minors

- GDPR Art. 8 thresholds apply only to consent-based services. Azerbaijan Art. 8.3: under 18,
  a parent or guardian consents. Recommendation: an 18+ age gate with a parental-consent path.

## Needs a licensed Azerbaijani lawyer

- Whether a click-through or the E-Gov route satisfies "written" consent; status of Art. 8.6.
- Cabinet Decision 237 (registration threshold) and the Art. 9.14 licence.
- Any adequacy list; whether China passes Art. 14.2.2.
- Current consolidated E-Commerce Law Art. 6.
- The reported draft new data law.
- Whether the Law reaches Tehsil if it incorporates in the EU.
