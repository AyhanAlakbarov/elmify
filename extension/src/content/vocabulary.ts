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
export const TOKENS: Record<string, readonly string[]> = {
  given_name: ["given", "first", "forename", "christian", "vorname", "prenom", "nombre", "ad"],
  family_name: ["family", "last", "surname", "nachname", "familienname", "nom", "apellido", "soyad"],
  middle_name: ["middle", "zweiter"],
  full_name: ["full name", "nom complet", "vollstandiger", "ad soyad"],
  date_of_birth: ["birth", "born", "dob", "geburt", "naissance", "nacimiento", "dogum"],
  place_of_birth: ["place of birth", "birthplace", "geburtsort", "lieu de naissance"],
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
  institution: ["institution", "university", "school", "hochschule", "universitat", "universite", "universidad", "okul"],
  degree: ["degree", "qualification", "abschluss", "diplome", "titulo", "derece"],
  field_of_study: ["field of study", "subject", "major", "studienfach", "domaine", "bolum"],
  graduation_date: ["graduation", "completed", "abschlussdatum", "obtention", "mezuniyet"],
  grade: ["grade", "gpa", "mark", "note", "durchschnitt", "moyenne", "not"],
};

/** Everything a token match has to survive: case, accents and punctuation. */
export function normalise(text: string): string {
  return text
    .toLowerCase()
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
