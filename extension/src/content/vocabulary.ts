/**
 * What a control asking for a given profile field plausibly calls itself.
 *
 * DATA, not logic. Keyed by the KEY half of a profile field ("personal.
 * given_name" -> "given_name"), because the category half names where a fact
 * came from, not what a form calls it.
 *
 * ponytail: a token table, not a language model. Its ceiling is honest and
 * one-directional -- a portal in a language not represented here matches
 * nothing, so its fields are left UNFILLED and the student does them by hand
 * from the Application Kit. It never causes a wrong fill. When a real portal
 * measures badly, add tokens here; do not soften verify.ts.
 */
const TOKENS_INSTITUTION: readonly string[] = [
  "institution", "university", "school", "hochschule", "universitat", "universite",
  "universidad", "okul",
];
const TOKENS_DEGREE: readonly string[] = [
  "degree", "qualification", "abschluss", "diplome", "titulo", "derece",
];

export const TOKENS: Record<string, readonly string[]> = {
  given_name: ["given", "first", "forename", "christian", "vorname", "prenom", "nombre", "ad"],
  family_name: ["family", "last", "surname", "nachname", "familienname", "nom", "apellido", "soyad"],
  middle_name: ["middle", "zweiter"],
  full_name: ["full name", "nom complet", "vollstandiger", "ad soyad"],
  date_of_birth: ["date of birth", "birth date", "birthdate", "birthday", "born", "dob",
                  "geburtsdatum", "date de naissance", "fecha de nacimiento", "dogum tarihi",
                  "dogum tarixi"],
  place_of_birth: ["place of birth", "birthplace", "birth place", "geburtsort",
                   "lieu de naissance", "lugar de nacimiento", "dogum yeri", "dogdugu yer",
                   "anadan oldugu yer"],
  nationality: ["nationality", "citizen", "staatsangeh", "nationalite", "nacionalidad", "uyruk"],
  gender: ["gender", "sex", "geschlecht", "sexe", "cinsiyet"],
  email: ["email", "e-mail", "mail", "correo", "eposta", "e-posta"],
  phone: ["phone", "mobile", "telephone", "telefon", "movil", "cep"],
  address: ["address", "street", "adresse", "strasse", "direccion", "adres"],
  city: ["city", "town", "stadt", "ort", "ville", "ciudad", "sehir"],
  postal_code: ["postal", "post code", "zip", "plz", "postleitzahl", "code postal", "posta kodu"],
  country: ["country", "land", "pays", "pais", "ulke"],
  passport_number: ["passport", "reisepass", "passeport", "pasaporte", "pasaport"],
  national_id: ["national id", "identity", "personalausweis", "kimlik", "tc"],
  // Spec 2026-10-12 §4: the keys a passport read writes.
  given_names: ["given", "first", "forename", "christian", "vorname", "prenom", "nombre", "ad"],
  surname: ["family", "last", "surname", "nachname", "familienname", "nom", "apellido", "soyad"],
  sex: ["gender", "sex", "geschlecht", "sexe", "cinsiyet"],
  citizenship: ["citizenship", "nationality", "citizen", "staatsangeh", "nationalite",
                "nacionalidad", "uyruk", "vatandaslik"],
  number: ["passport number", "passport no", "document number", "reisepassnummer",
           "numero de passeport", "pasaport no", "pasaport numarasi"],
  expiry_date: ["expiry", "expiration", "valid until", "gultig bis", "date d expiration",
                "son gecerlilik"],
  issue_date: ["date of issue", "issue date", "issued on", "ausstellungsdatum",
               "date de delivrance", "verilis tarihi"],
  issuing_country: ["issuing country", "country of issue", "ausstellungsland",
                    "pays de delivrance", "veren ulke"],
  issuing_authority: ["issuing authority", "authority", "ausstellende behorde", "autorite"],
  document_type: ["document type", "type of document", "dokumententyp", "belge turu"],
  institution: TOKENS_INSTITUTION,
  degree: TOKENS_DEGREE,
  institution_original: TOKENS_INSTITUTION,
  degree_as_awarded: TOKENS_DEGREE,
  // normalise() folds "ı" -> "i", "ə" -> "e", "ß" -> "ss".
  start_date: ["start date", "start", "began", "beginn", "baslang", "baslangic", "debut"],
  end_date: ["end date", "graduation", "completed", "until", "bitis", "mezuniyet", "abschlussdatum"],
  field_of_study: ["field of study", "subject", "major", "studienfach", "domaine", "bolum"],
  graduation_date: ["graduation date", "date of graduation", "graduation", "completed",
                    "abschlussdatum", "obtention", "mezuniyet tarihi", "mezuniyyet tarixi", "mezuniyet"],
  grade: ["grade", "gpa", "mark", "note", "durchschnitt", "moyenne", "not"],
  // Spec 2026-10-12 §4.3-4.4: certificate and diploma keys. Phrases, never a bare
  // "test" or "date": "Test date" must not also match the test name, or the box
  // reads as ambiguous and is refused.
  language: ["test language", "language tested", "language of the test", "testsprache", "test dili"],
  test_name: ["test name", "name of test", "language test", "english test", "exam name",
              "sinav adi"],
  test_variant: ["test module", "ielts module", "test type", "test version"],
  test_date: ["test date", "date of test", "exam date", "testdatum", "sinav tarihi"],
  certificate_number: ["certificate number", "trf number", "trf", "test report form",
                       "score report number", "sertifika no"],
  test_score: ["overall", "overall score", "total score", "band score", "toplam puan"],
  score_listening: ["listening score", "listening band", "listening result", "horen", "dinleme puani"],
  score_reading: ["reading score", "reading band", "reading result", "lesen", "okuma puani"],
  score_writing: ["writing score", "writing band", "writing result", "schreiben", "yazma puani"],
  score_speaking: ["speaking score", "speaking band", "speaking result", "sprechen", "konusma puani"],
  cefr_level: ["cefr", "cefr level", "language level", "proficiency level"],
  diploma_number: ["diploma number", "diploma no", "diploma serial", "diploma series",
                   "diplom no"],
  institution_english: ["institution in english", "university in english",
                        "english name of institution"],
  degree_english: ["degree in english", "qualification in english",
                   "english title of degree"],
  grade_native: ["original grade", "grade as awarded", "native grade"],
  grade_conversion: ["converted grade", "german grade", "ects grade",
                     "umgerechnete note", "donusturulmus not"],
  grade_scale: ["grading scale", "maximum grade", "notenskala", "not olcegi",
                "qiymetlendirme skalasi"],
  ects_credits: ["ects credits", "total credits", "credit points",
                 "leistungspunkte", "toplam kredi", "kredit sayi"],
  class_rank: ["class rank", "percentile", "ranking", "studienrang",
               "sinif siralamasi"],
  relevant_coursework: ["relevant coursework", "key courses", "modules taken",
                        "relevante kurse", "ilgili dersler"],
  medium_of_instruction: ["medium of instruction", "language of instruction",
                          "unterrichtssprache", "egitim dili", "tedris dili"],
  // Open-ended narrative and essay prompts.
  motivation_letter: ["motivation letter", "letter of motivation", "statement of purpose",
                      "personal statement", "motivational statement", "motivationsschreiben",
                      "lettre de motivation", "motivasyon mektubu", "motivasiya mektubu"],
  why_programme: ["why this programme", "why this program", "choice of programme",
                  "choice of program", "interest in the programme", "interest in this program",
                  "program secimi", "proqram secimi"],
  why_country: ["why this country", "choose this country", "choice of country", "why study in",
                "ulke secimi", "olke secimi"],
  academic_preparation: ["academic preparation", "academic background", "prior studies",
                         "previous studies", "akademik hazirlik", "akademik hazirliq"],
  research_plan: ["research plan", "study plan", "proposed research", "research proposal",
                  "thesis topic", "forschungsplan", "studienplan", "arastirma plani",
                  "tedqiqat plani"],
  career_plan: ["career plan", "career goals", "future plans", "professional goals",
                "career objectives", "berufsziele", "kariyer plani", "karyera plani"],
  home_country_contribution: ["contribution to home country", "return to home country",
                              "benefit to your country", "development impact",
                              "ulkeye katki", "olkeye tohfe"],
  leadership_example: ["leadership experience", "leadership example", "leadership role",
                       "liderlik deneyimi", "liderlik tecrubesi"],
  personal_background: ["personal background", "extracurricular activities",
                        "personal circumstances", "kisisel gecmis", "sexsi melumat"],
  language_plan: ["language preparation", "language study plan", "how will you learn",
                  "dil hazirligi", "dil plani"],
  relationship_community: ["community involvement", "volunteering experience",
                           "civic engagement", "social impact", "toplumsal katki",
                           "ictimai fealiyyet"],
  opening: ["opening statement", "introduction paragraph"],
  closing: ["closing statement", "concluding remarks", "additional remarks"],
  // Experience, research, publication, award, skill, certification, reference, timeline.
  summary: ["personal summary", "profile summary", "short bio", "biography",
            "kurzprofil", "ozet"],
  statement: ["gap explanation", "timeline explanation", "chronological gap",
              "activity description"],
  kind: ["activity type", "entry type", "type of activity"],
  organisation: ["employer", "company name", "organisation name", "organization name",
                 "arbeitgeber", "employeur", "kurum adi", "sirket adi"],
  employer: ["employer", "company name", "organisation name", "organization name",
             "arbeitgeber", "employeur", "kurum adi", "sirket adi", "is yeri"],
  role: ["job title", "role title", "position held", "berufsbezeichnung",
         "poste occupe", "gorev", "vezife"],
  unpaid: ["unpaid", "volunteer", "voluntary", "ehrenamtlich", "gonullu", "odenissiz"],
  thesis_title: ["thesis title", "dissertation title", "title of thesis", "thema der abschlussarbeit",
                 "tez basligi", "dissertasiya movzusu"],
  location: ["work location", "city of employment", "arbeitsort", "lieu de travail",
             "calisma yeri"],
  bullets: ["responsibilities", "job description", "duties and achievements",
            "aufgabenbeschreibung", "is tanimi", "ohdelikler"],
  project: ["project title", "research project", "projekttitel", "proje basligi",
            "layihe adi"],
  supervisor: ["supervisor", "advisor", "thesis advisor", "betreuer", "danisman",
               "elmi rehber"],
  group: ["research group", "laboratory", "department or lab", "forschungsgruppe",
          "arastirma grubu"],
  methods: ["research methods", "methodology", "techniques used", "methodik",
            "yontemler", "metodlar"],
  outcomes: ["research outcomes", "key findings", "results achieved", "ergebnisse",
             "sonuclar", "neticeler"],
  funding: ["funding source", "grant number", "scholarship or grant", "forderung",
            "fon kaynagi"],
  title: ["job title", "role title", "position held", "publication title", "paper title",
          "award title", "achievement title", "certificate title", "berufsbezeichnung",
          "titel der publikation", "yayin basligi", "meqale adi", "vezife"],
  "publication.title": ["publication title", "paper title", "article title",
                        "titel der publikation", "yayin basligi", "meqale adi"],
  "award.title": ["award title", "achievement title", "prize name", "name of award",
                  "odul adi", "mukafat adi"],
  venue: ["journal", "conference name", "publication venue", "zeitschrift",
          "dergi", "konfrans"],
  year: ["publication year", "year of publication", "erscheinungsjahr", "yayin yili", "nesr ili"],
  doi: ["doi", "digital object identifier"],
  url: ["publication url", "paper link", "website url", "yayin baglantisi"],
  website_url: ["personal website", "portfolio url", "homepage", "webseite", "kisisel web sitesi"],
  linkedin_url: ["linkedin url", "linkedin profile", "linkedin link"],
  linkedin_handle: ["linkedin username", "linkedin handle"],
  github_url: ["github url", "github profile", "github link"],
  github_username: ["github username", "github handle"],
  orcid: ["orcid", "orcid id"],
  mother_tongue: ["mother tongue", "native language", "first language", "muttersprache",
                  "ana dili", "anadili"],
  spoken_interaction: ["spoken interaction", "oral interaction"],
  spoken_production: ["spoken production", "oral production"],
  evidence: ["skill evidence", "proof of skill", "where used"],
  date: ["publication date", "award date", "date received", "erscheinungsdatum",
         "yayin tarihi", "verilme tarixi"],
  "publication.date": ["publication date", "erscheinungsdatum", "yayin tarihi", "nesr tarixi"],
  "award.date": ["award date", "date received", "date of award", "verleihungsdatum",
                 "odul tarihi", "verilme tarixi"],
  "certification.date": ["certification date", "certificate date", "date obtained",
                         "sertifika tarihi", "verilme tarixi"],
  authors: ["co-authors", "author list", "authors", "autoren", "yazarlar",
            "muellifler"],
  doi_or_url: ["doi", "publication url", "paper link", "yayin baglantisi"],
  awarding_body: ["awarding body", "awarding institution", "granted by",
                  "verleihende stelle", "odulu veren"],
  name: ["referee name", "recommender name", "skill name", "certification name",
         "name des gutachters", "referans adi"],
  "reference.name": ["referee name", "recommender name", "name des gutachters", "referans adi"],
  "skill.name": ["skill name", "competency", "fahigkeit", "yetkinlik adi", "bacariq adi"],
  "certification.name": ["certification name", "certificate title", "certificate name",
                         "zertifikatsname", "sertifika adi"],
  issuer: ["issuing organisation", "issuing organization", "certifying body",
           "aussteller", "sertifika veren"],
  credential_id: ["credential id", "license number", "verification code",
                  "kimlik kodu"],
  level: ["skill level", "competency level", "kenntnisstand", "yetkinlik seviyesi",
          "bacariq seviyyesi"],
  position: ["referee position", "referee title", "academic rank",
             "position des gutachters", "referans unvani"],
  relationship: ["relationship to applicant", "how do you know",
                 "beziehung zum bewerber", "adayla iliskisi"],
  do_not_contact: ["do not contact", "contact permission"],
  detail: ["additional details", "further information", "remarks", "anmerkungen",
           "ek bilgi", "elave melumat"],
};

/** Everything a token match has to survive: case, accents and punctuation. */
export function normalise(text: string): string {
  return text
    .toLowerCase()
    .replace(/ə/g, "e")
    .replace(/ı/g, "i")
    .replace(/ß/g, "ss")
    .replace(/ø/g, "o")
    .replace(/ł/g, "l")
    .replace(/đ/g, "d")
    .replace(/æ/g, "ae")
    .replace(/œ/g, "oe")
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

/** The key half of "category.key". */
export function fieldKey(profileField: string): string {
  const parts = profileField.split(".");
  return parts[parts.length - 1] ?? profileField;
}

const KEY_ALIASES: Record<string, string> = {
  given_names: "given_name",
  surname: "family_name",
  sex: "gender",
  institution_original: "institution",
  degree_as_awarded: "degree",
};

/** Canonical token-group identifier for a profile field: uses a category-scoped
 *  entry in TOKENS when one exists (e.g. "publication.title" vs "award.title"),
 *  else the canonical fieldKey so same-concept fields across sections
 *  (e.g. "contact.email" and "reference.1.email") share one group. */
export function tokenGroupKey(profileField: string): string {
  const cls = profileField.replace(/\.\d+\./, ".");
  if (Object.hasOwn(TOKENS, cls)) return cls;
  const key = fieldKey(cls);
  return KEY_ALIASES[key] ?? key;
}

/** normalise() for document words: keeps every letter, not only a-z, so the
 *  Cyrillic tokens below survive (normalise() would turn "паспорт" into "").
 *  Combining marks are still stripped, identically on both sides. */
export function normaliseDoc(text: string): string {
  return text
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim();
}

/** Words a box's visible text uses for each document kind. Matched with
 *  normaliseDoc on both sides; a token that normalises to "" never matches. */
export const DOC_TOKENS: Record<string, readonly string[]> = {
  CV: ["cv", "resume", "curriculum", "lebenslauf", "ozgecmis", "резюме"],
  TRANSCRIPT: ["transcript", "grades", "records", "notenspiegel", "transkript",
               "приложение к диплому"],
  DIPLOMA: ["diploma", "degree certificate", "zeugnis", "diplom", "диплом"],
  PASSPORT: ["passport", "reisepass", "pasaport", "паспорт", "identity document"],
  LANGUAGE_CERTIFICATE: ["ielts", "toefl", "language certificate", "sprachnachweis",
                         "dil belgesi"],
  REFERENCE_LETTER: ["recommendation", "reference", "referenz", "tavsiye", "рекомендация"],
  MOTIVATION_LETTER: ["motivation", "statement of purpose", "personal statement",
                      "motivasyon"],
  OTHER: [],
};
