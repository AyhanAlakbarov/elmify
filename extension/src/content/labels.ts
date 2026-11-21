import type { MarkLabels } from "./marks.js";

type Language = "az" | "tr" | "ru" | "en";

type Row = Omit<MarkLabels, "why" | "next"> & { why: string; fromAnswer: string; answer: string;
  fromPassport: string; fromDiploma: string; fromCertificate: string };
export const MARK_LABELS: Record<Language, Row> = {
  en: { filled: "Filled", check: "Check this", yourTurn: "Your turn", changed: "Changed by you", portalError: "Portal error",
        why: "From your verified facts", answer: "Answer this",
        fromAnswer: "From your earlier answer — check it",
        fromPassport: "From your passport", fromDiploma: "From your diploma", fromCertificate: "From your language certificate" },
  az: { filled: "Dolduruldu", check: "Yoxlayın", yourTurn: "Növbə sizdədir", changed: "Siz dəyişdiniz", portalError: "Portal xətası",
        why: "Təsdiqlənmiş məlumatlarınızdan", answer: "Bunu cavablayın",
        fromAnswer: "Əvvəlki cavabınızdan — yoxlayın",
        fromPassport: "Pasportunuzdan", fromDiploma: "Diplomunuzdan", fromCertificate: "Dil sertifikatınızdan" },
  tr: { filled: "Dolduruldu", check: "Kontrol edin", yourTurn: "Sıra sizde", changed: "Siz değiştirdiniz", portalError: "Portal hatası",
        why: "Doğrulanmış bilgilerinizden", answer: "Bunu yanıtlayın",
        fromAnswer: "Önceki cevabınızdan — kontrol edin",
        fromPassport: "Pasaportunuzdan", fromDiploma: "Diplomanızdan", fromCertificate: "Dil sertifikanızdan" },
  ru: { filled: "Заполнено", check: "Проверьте", yourTurn: "Ваш ход", changed: "Изменено вами", portalError: "Ошибка портала",
        why: "Из ваших подтверждённых данных", answer: "Ответьте здесь",
        fromAnswer: "Из вашего прежнего ответа — проверьте",
        fromPassport: "Из вашего паспорта", fromDiploma: "Из вашего диплома", fromCertificate: "Из вашего языкового сертификата" },
};

/** Whether the "Answer this" chip shows is the caller's call; null means no chip. */
export function contentLabels(
  language: string = "en",
  step: "answer" | null = null,
  fromAnswer: ReadonlySet<string> = new Set(), // fields typed back from the student's own answer
  fromDocument: ReadonlyMap<string, string> = new Map(), // key -> "passport" | "diploma" | "certificate"
): MarkLabels {
  // hasOwn, not `in`: the language arrives in a message, and "toString" is `in` every object.
  const t = MARK_LABELS[(Object.hasOwn(MARK_LABELS, language) ? language : "en") as Language];
  return { filled: t.filled, check: t.check, yourTurn: t.yourTurn, changed: t.changed, portalError: t.portalError,
           why: (key) => {
             if (fromAnswer.has(key)) return t.fromAnswer;
             const from = { passport: t.fromPassport, diploma: t.fromDiploma, certificate: t.fromCertificate }[
               fromDocument.get(key) ?? ""
             ];
             if (from) return from;
             return t.why;
           },
           next: step ? t.answer : null };
}
