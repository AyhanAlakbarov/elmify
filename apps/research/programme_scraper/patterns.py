"""Regex patterns and vocabulary tables for programme scraping."""

from __future__ import annotations

import re

_TUITION_LINK_RE = re.compile(
    r"tuition|fee|fees|cost|costs|finance|financial|studiengeb|beitrag|"
    r"droits|inscription|tasse|contributi|collegegeld|등록금|학비|学费|授業料|الرسوم",
    re.IGNORECASE,
)
_ADMISSION_LINK_RE = re.compile(
    r"admission|admitted|apply|application|requirement|eligib|prerequisite|"
    r"entry|bewerbung|zulassung|candidature|ammissione|requisiti|toelating|"
    r"입학|지원자격|申请|募集|شروط|القبول",
    re.IGNORECASE,
)
_DOCUMENT_LINK_RE = re.compile(
    r"document|checklist|cv|resume|europass|motivation|statement-of-purpose|"
    r"reference|referee|recommendation|unterlagen|pièces|documenti|서류",
    re.IGNORECASE,
)
_SCHOLARSHIP_LINK_RE = re.compile(
    r"scholarship|scholarships|funding|fellowship|grant|stipend|waiver|bursary|"
    r"stipendium|stipendien|bourse|bourses|borsa|borse|beurs|burs|장학금|奖学金|奨学金|منحة|منح|beasiswa",
    re.IGNORECASE,
)

_NON_EU_RE = re.compile(
    r"non[- ]?eu(?:/eea)?|non[- ]?eea|international|overseas|third[- ]country|foreign|"
    r"außerhalb\s+der\s+eu|hors\s+ue|extra[- ]?ue|외국인",
    re.IGNORECASE,
)
_EU_DOMESTIC_RE = re.compile(
    r"(?<!non[- ])(?<!non)\b(?:eu/eea|eu\s+and\s+eea|eea/eu|eu\s+citizens|domestic|"
    r"home\s+students|home\s+fees?|swiss\s+and\s+eu|national\s+students)\b",
    re.IGNORECASE,
)
_APPLICATION_FEE_RE = re.compile(
    r"application\s+fee|processing\s+fee|admission\s+fee|registration\s+fee|"
    r"bewerbungsgeb|frais\s+de\s+candidature|frais\s+de\s+dossier|"
    r"contributo\s+di\s+ammissione|전형료",
    re.IGNORECASE,
)
_TUITION_WORD_RE = re.compile(
    r"tuition|studiengeb|droits\s+d'inscription|tasse\s+universitarie|"
    r"participation\s+cost|programme\s+fee|program\s+fee|course\s+fee|"
    r"academic\s+fee|"
    r"(?:international|overseas|non[- ]?eu|eu/eea|home|domestic|annual|"
    r"semester|study|full[- ]?time)\s+fees?\b|"
    r"등록금|授業料|学费|الرسوم\s+الدراسية",
    re.IGNORECASE,
)
_FEE_HEADING_RE = re.compile(
    r"\b(?:tuition|fees?\s+and\s+funding|costs?\s+and\s+fees?|tuition\s+and\s+fees?|"
    r"programme\s+fees?|program\s+fees?|course\s+fees?|annual\s+fees?|studiengebühren)\b",
    re.IGNORECASE,
)
_NON_TUITION_COST_RE = re.compile(
    r"\b(?:living\s+costs?|cost\s+of\s+living|accommodation|housing|rent|food|meal|"
    r"health\s+insurance|insurance\s+fee|visa\s+fee|residence\s+permit|"
    r"enrolment\s+deposit|confirmation\s+deposit|deposit\s+of|late\s+fee)\b",
    re.IGNORECASE,
)
_RANGE_PROSE_RE = re.compile(
    r"\b(?:ranges?\s+from|ranging\s+from|var(?:y|ies)\s+(?:from|between)|"
    r"between\s+[^.;]{1,40}\band\b)\b",
    re.IGNORECASE,
)
_FREE_TUITION_RE = re.compile(
    r"\b(?:no\s+tuition\s+fees?|tuition[- ]free|free\s+of\s+tuition|"
    r"0\s*eur\s+tuition|keine\s+studiengebühren|"
    r"(?:droits\s+d'inscription|frais\s+de\s+scolarité|scolarité)\s+(?:sont\s+)?gratuits?|"
    r"sans\s+frais\s+de\s+scolarité)\b",
    re.IGNORECASE,
)
_SEMESTER_CONTRIB_RE = re.compile(
    r"\b(?:semesterbeitrag|semester\s+contribution|student\s+union\s+fee|"
    r"studentenwerksbeitrag|cvec|studierendenwerk)\b",
    re.IGNORECASE,
)
_CONDITIONAL_GUARD_RE = re.compile(
    r"\b(?:except|unless|partner\s+universit|exchange\s+students?|bilateral|"
    r"selected\s+applicants|up\s+to|top\s+\d+|quota|if\s+you\s+hold|"
    r"waived\s+for\s+citizens\s+of|only\s+for\s+eu|eu/eea\s+only)\b",
    re.IGNORECASE,
)
_CATEGORY_REF_RE = re.compile(
    r"\b(?:fee\s+category|tuition\s+category|tuition\s+band|fee\s+band|"
    r"fee\s+group|tuition\s+tier|category|band|tariff)\s+([A-Z0-9]{1,3})\b",
    re.IGNORECASE,
)
_ECTS_DURATION_RE = re.compile(
    r"\b(60|90|120)\s*ects\b|\bects(?:\s+credits?|\s+points?)?\s*[:|]?\s*(60|90|120)\b",
    re.IGNORECASE,
)
_LANGUAGE_NAMES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("English", re.compile(r"\benglish\b|\benglisch\b|\banglais\b|\binglese\b", re.IGNORECASE)),
    ("German", re.compile(r"\bgerman\b|\bdeutsch\b|\ballemand\b", re.IGNORECASE)),
    ("French", re.compile(r"\bfrench\b|\bfrançais\b|\bfranzösisch\b", re.IGNORECASE)),
    ("Italian", re.compile(r"\bitalian\b|\bitaliano\b", re.IGNORECASE)),
    ("Spanish", re.compile(r"\bspanish\b|\bespañol\b", re.IGNORECASE)),
    ("Dutch", re.compile(r"\bdutch\b|\bnederlands\b", re.IGNORECASE)),
    ("Korean", re.compile(r"\bkorean\b|\b한국어\b", re.IGNORECASE)),
    ("Japanese", re.compile(r"\bjapanese\b|\b日本語\b", re.IGNORECASE)),
    ("Chinese", re.compile(r"\bchinese\b|\bmandarin\b|\b中文\b", re.IGNORECASE)),
    ("Arabic", re.compile(r"\barabic\b|\bالعربية\b", re.IGNORECASE)),
)
_TEACHING_CONTEXT_RE = re.compile(
    r"teaching\s+language|language\s+of\s+instruction|taught\s+(?:entirely\s+|fully\s+)?in|"
    r"(?:conducted|delivered|offered)\s+(?:entirely\s+|fully\s+|100%\s+)?in\b|"
    r"(?:programme|program|course)\s+language|"
    r"instruction\s+language|medium\s+of\s+instruction|unterrichtssprache|"
    r"langue\s+d'enseignement|lingua\s+di\s+erogazione|schema\.org\s+teaching\s+language",
    re.IGNORECASE,
)
_DEADLINE_CONTEXT_RE = re.compile(
    r"deadline|application\s+period|apply\s+by|closing\s+date|"
    r"bewerbungsfrist|date\s+limite|scadenza|마감|접수기간|آخر\s+موعد",
    re.IGNORECASE,
)

_EUROPASS_REQ_RE = re.compile(
    r"europass(?:\s+cv)?(?:\s+format)?\s+(?:is\s+)?(?:required|mandatory|compulsory|must)",
    re.IGNORECASE,
)
_EUROPASS_PREF_RE = re.compile(
    r"europass(?:\s+cv)?(?:\s+format)?\s+(?:is\s+)?(?:preferred|recommended)",
    re.IGNORECASE,
)
_CV_LINE_RE = re.compile(
    r"\b(?:cv|curriculum\s+vitae|résumé|resume|lebenslauf|europass)\b",
    re.IGNORECASE,
)
_LETTER_LINE_RE = re.compile(
    r"\b(?:motivation(?:al)?\s+letter|letter\s+of\s+motivation|statement\s+of\s+purpose|"
    r"personal\s+statement|cover\s+letter|motivationsschreiben|lettre\s+de\s+motivation)\b",
    re.IGNORECASE,
)
_LETTER_OPTIONAL_RE = re.compile(r"\b(?:optional|if\s+applicable|voluntary)\b", re.IGNORECASE)
_NOT_REQUIRED_RE = re.compile(
    r"\b(?:not\s+required|not\s+requested|not\s+needed|"
    r"no\s+(?:reference|recommendation|motivation(?:al)?)\s+letters?|"
    r"do\s+not\s+(?:submit|send|include))\b",
    re.IGNORECASE,
)
_HEADER_CURRENCY_RE = re.compile(
    r"(?:\bin\s+|\(|\b)(EUR|USD|GBP|CHF|SEK|NOK|DKK|PLN|CZK|HUF|"
    r"CAD|AUD|NZD|JPY|KRW|CNY|SGD|AED|SAR|QAR|KWD|BHD|TRY|AZN|RUB|INR|€|\$|£|¥|₩)(?:\)|\b)",
    re.IGNORECASE,
)
_BINARY_ASSET_EXT_RE = re.compile(
    r"\.(?:jpg|jpeg|png|gif|webp|svg|ico|mp4|mp3|zip|tar|gz|css|js|woff2?)$",
    re.IGNORECASE,
)
_REFEREE_LINE_RE = re.compile(
    r"\b(?:reference\s+letters?|letters?\s+of\s+recommendation|recommendation\s+letters?|"
    r"referees?|academic\s+references?|empfehlungsschreiben|lettres?\s+de\s+recommandation)\b",
    re.IGNORECASE,
)
_REFEREE_COUNT_RE = re.compile(
    r"\b(?:(1|one|2|two|3|three)\s+(?:academic\s+|professional\s+)?(?:reference|recommendation|referee))",
    re.IGNORECASE,
)
_TRANSCRIPT_LINE_RE = re.compile(
    r"\b(?:transcript\s+of\s+records|academic\s+transcripts?|diploma\s+supplement|"
    r"bachelor(?:'s)?\s+degree\s+certificate|official\s+transcripts?)\b",
    re.IGNORECASE,
)
_PORTFOLIO_LINE_RE = re.compile(r"\b(?:portfolio|work\s+samples)\b", re.IGNORECASE)
_APS_LINE_RE = re.compile(r"\b(?:aps\s+certificate|akademische\s+prüfstelle)\b", re.IGNORECASE)
_GRE_GMAT_LINE_RE = re.compile(r"\b(?:gre|gmat)\b", re.IGNORECASE)

_THIRD_PARTY_RE = re.compile(
    r"supervisor|referee|recommender|nominator|\bhost\b|professor|"
    r"employer|\bstaff\b|faculty\s+member",
    re.IGNORECASE,
)
_CV_MAX_PAGES_RE = re.compile(
    r"\b(?:max(?:imum|\.)?\s*(?:of\s*)?|up\s+to\s+|no\s+more\s+than\s+|"
    r"at\s+most\s+)(\d{1,2})\s*(?:pages?|seiten?)\b"
    r"|\b(\d{1,2})\s*(?:pages?|seiten?)\s*(?:max(?:imum|\.)?|limit)\b",
    re.IGNORECASE,
)
_FILE_MB_RE = re.compile(
    r"\b(?:max(?:imum|\.)?\s*(?:of\s*)?|up\s+to\s+|limit\s*(?:of\s*)?)?"
    r"(\d{1,3}(?:\.\d+)?)\s*(?:mb|megabytes?|mo)\b",
    re.IGNORECASE,
)
_PHOTO_FORBIDDEN_RE = re.compile(
    r"\b(?:without\s+(?:a\s+)?photo(?:graph)?|no\s+photo(?:graph)?|"
    r"do\s+not\s+include\s+(?:a\s+)?photo(?:graph)?|ohne\s+foto)\b",
    re.IGNORECASE,
)
_PHOTO_REQUIRED_RE = re.compile(
    r"\b(?:with\s+(?:a\s+)?(?:recent\s+)?photo(?:graph)?|"
    r"photo(?:graph)?\s+(?:is\s+)?required|mit\s+foto)\b",
    re.IGNORECASE,
)
_DOB_FORBIDDEN_RE = re.compile(
    r"\b(?:without\s+date\s+of\s+birth|no\s+date\s+of\s+birth|"
    r"do\s+not\s+include\s+date\s+of\s+birth)\b",
    re.IGNORECASE,
)
_CV_SIGNED_RE = re.compile(
    r"\b(?:signed\s+cv|cv\s+must\s+be\s+signed|dated\s+and\s+signed|"
    r"unterschriebener\s+lebenslauf)\b",
    re.IGNORECASE,
)
_CV_NO_GAPS_RE = re.compile(
    r"\b(?:without\s+(?:any\s+)?(?:unexplained\s+)?gaps|"
    r"no\s+(?:unexplained\s+)?gaps|without\s+omissions|lückenlos)\b",
    re.IGNORECASE,
)
_REVERSE_CHRONO_RE = re.compile(
    r"\b(?:reverse[- ]chronological|most\s+recent\s+first|umgekehrt\s+chronologisch)\b",
    re.IGNORECASE,
)
_CHRONO_RE = re.compile(
    r"\b(?:in\s+chronological\s+order|chronologischer\s+reihenfolge)\b",
    re.IGNORECASE,
)
_PDF_FORMAT_RE = re.compile(r"\bpdf\b", re.IGNORECASE)
_SINGLE_PDF_BUNDLE_RE = re.compile(
    r"\b(?:single\s+pdf|one\s+pdf(?:\s+file)?|"
    r"combined\s+into\s+(?:a\s+|one\s+)?pdf|all\s+documents\s+in\s+one\s+pdf)\b",
    re.IGNORECASE,
)
_REFEREE_ACADEMIC_RE = re.compile(
    r"\b(?:academic\s+refere|from\s+(?:a\s+)?professors?|university\s+professors?)\b",
    re.IGNORECASE,
)
_REFEREE_INST_EMAIL_RE = re.compile(
    r"\b(?:institutional\s+email|official\s+university\s+email)\b",
    re.IGNORECASE,
)

_WORD_NUM = {
    "one": "ONE",
    "1": "ONE",
    "two": "TWO",
    "2": "TWO",
    "three": "THREE_OR_MORE",
    "3": "THREE_OR_MORE",
}

_CLAUSE_SPLIT_RE = re.compile(
    r";|,\s+(?:while|whereas|and|but|for)\b|\b(?:while|whereas|but)\b|\band\b",
    re.IGNORECASE,
)
