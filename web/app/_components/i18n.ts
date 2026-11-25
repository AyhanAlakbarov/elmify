import { SITE_URL, appLinks } from "./app-links";

export type Locale = "en" | "az" | "ru";

export const LOCALES: readonly Locale[] = ["en", "az", "ru"] as const;

export function localePath(locale: Locale): string {
  return locale === "en" ? "/" : `/${locale}`;
}

export function localeUrl(locale: Locale): string {
  return locale === "en" ? SITE_URL : `${SITE_URL}/${locale}`;
}

export function localizedAppLinks(locale: Locale) {
  return {
    signup: `${appLinks.signup}?lang=${locale}`,
    login: appLinks.login,
    studentDemo: `${appLinks.studentDemo}&lang=${locale}`,
    terms: `${appLinks.terms}?lang=${locale}`,
    privacy: `${appLinks.privacy}?lang=${locale}`,
  };
}

/** The scholarships named on the page, each linked to its official site. Names stay
 *  in their own language in every locale: that is how students search for them. */
export const SCHOLARSHIPS: ReadonlyArray<{ name: string; url: string }> = [
  { name: "Dövlət Proqramı", url: "https://dp.edu.az/" },
  { name: "HTP / Stipendium Hungaricum", url: "https://htp.edu.az/" },
  { name: "Erasmus Mundus", url: "https://erasmus-plus.ec.europa.eu/opportunities/opportunities-for-individuals/students/erasmus-mundus-joint-masters" },
  { name: "DAAD", url: "https://www.daad.de/en/Studying-in-Germany/scholarships/" },
  { name: "Chevening", url: "https://www.chevening.org/scholarships/" },
  { name: "Swedish Institute", url: "https://si.se/en/apply/scholarships/swedish-institute-scholarships-for-global-professionals/" },
  { name: "NL Scholarship", url: "https://www.studyinnl.org/finances/nl-scholarship" },
];

/** The hero's example match. Illustrative, and labelled as an example on the page. */
export interface HeroMatch {
  country: string;
  programme: string;
  funding: string;
  chance: number;
}

export interface LocaleCopy {
  locale: Locale;
  ogLocale: string;
  langLabel: string;
  metaTitle: string;
  metaDescription: string;
  keywords: string[];
  skipToMain: string;
  nav: {
    how: string;
    product: string;
    faq: string;
    login: string;
    signup: string;
    homeAria: string;
    langAria: string;
  };
  hero: {
    h1: string;
    body: string;
    ctaPrimary: string;
    ctaSecondary: string;
    example: string;
    profileName: string;
    profileFacts: readonly string[];
    matchesLabel: string;
    chanceLabel: string;
    matches: readonly HeroMatch[];
    shotAlt: string;
  };
  stats: ReadonlyArray<{ value: number; suffix: string; label: string }>;
  scholarshipsLabel: string;
  booking: { cta: string; note: string };
  how: {
    h2: string;
    stages: ReadonlyArray<{ title: string; body: string }>;
  };
  extensionPreview: {
    h2: string;
    body: string;
    points: readonly string[];
  };
  product: {
    h2: string;
    cells: ReadonlyArray<{ title: string; alt: string }>;
  };
  faq: {
    h2: string;
    items: ReadonlyArray<readonly [string, string]>;
  };
  closing: {
    h2: string;
    body: string;
    ctaPrimary: string;
    ctaSecondary: string;
  };
  footer: {
    updatedLabel: string;
    updatedDateText: string;
    links: {
      how: string;
      faq: string;
      studentDemo: string;
      login: string;
      terms: string;
      privacy: string;
    };
  };
  schema: {
    articleName: string;
    faqName: string;
    educationalUse: string;
    audienceType: string;
    offerDescription: string;
    featureList: string[];
  };
}

export const COPY: Record<Locale, LocaleCopy> = {
  en: {
    locale: "en",
    ogLocale: "en_US",
    langLabel: "EN",
    metaTitle: "Elmify — Funded Master's & Scholarships Across 50+ Countries (Tailored AI Applications)",
    metaDescription:
      "Elmify reads official university and scholarship regulations across 50+ countries, checks your GPA, ECTS credits, and IELTS or TOEFL scores against State Program (Dövlət Proqramı), HTP, Erasmus Mundus, DAAD, Chevening, university tuition waivers, regional grants, and RA/TA assistantships, and builds tailored CVs, motivation letters, and referee briefs from your documents and profile (Master's live, Bachelor's coming soon).",
    keywords: [
      "study abroad scholarships Azerbaijan",
      "Dövlət Proqramı xaricdə təhsil magistratura",
      "HTP Stipendium Hungaricum Azerbaijan",
      "funded master's programmes across 50+ countries",
      "Erasmus Mundus Joint Masters",
      "DAAD scholarship Azerbaijan",
      "Chevening scholarship Azerbaijan",
      "Swedish Institute SISGP Azerbaijan",
      "tailored academic CV and motivation letter generator",
    ],
    skipToMain: "Skip to main content",
    nav: {
      how: "How it works",
      product: "Product",
      faq: "FAQ",
      login: "Log in",
      signup: "Sign up free",
      homeAria: "Elmify home",
      langAria: "Language switcher",
    },
    hero: {
      h1: "Get into a funded master’s abroad",
      body: "Elmify finds the programmes and scholarships that fit you, and gets your documents ready.",
      ctaPrimary: "Sign up free",
      ctaSecondary: "Log in",
      example: "Example",
      profileName: "Aysel, Baku",
      profileFacts: ["BSc Chemistry", "GPA 88/100", "IELTS 7.0"],
      matchesLabel: "Your matches",
      chanceLabel: "chance",
      matches: [
        { country: "Germany", programme: "MSc Chemistry", funding: "DAAD · full", chance: 72 },
        { country: "Hungary", programme: "MSc Applied Chemistry", funding: "HTP · full", chance: 81 },
        { country: "Sweden", programme: "MSc Molecular Science", funding: "Swedish Institute", chance: 58 },
      ],
      shotAlt: "Example: a student profile matched to three funded master’s programmes with their chances",
    },
    stats: [
      { value: 1400, suffix: "+", label: "funding awards checked" },
      { value: 53, suffix: "", label: "countries searched" },
      { value: 10, suffix: " min", label: "to build your profile" },
      { value: 0, suffix: "", label: "portal passwords stored" },
    ],
    scholarshipsLabel: "Scholarships we check, from their official pages",
    booking: { cta: "Book a free 20-min call", note: "On Google Meet, at a time that suits you" },
    how: {
      h2: "How it works",
      stages: [
        { title: "Tell us about you", body: "Your degree, grades, languages and budget." },
        { title: "Get your matches", body: "Programmes and scholarships you can really win." },
        { title: "Get documents ready", body: "CV, motivation letters and referee briefs." },
        { title: "Apply yourself", body: "We fill in the portal. You press Submit." },
      ],
    },
    extensionPreview: {
      h2: "We fill in the portal. You press Submit.",
      body: "The Elmify browser extension types your approved answers into the official portal and stops before Submit.",
      points: ["Fills every field", "Attaches your PDFs", "Flags new questions", "Never presses Submit"],
    },
    product: {
      h2: "Everything in one place",
      cells: [
        { title: "Programmes and the scholarship that pays", alt: "Programmes grouped by the scholarship that pays for them" },
        { title: "Every deadline on one board", alt: "The application board with every deadline" },
        { title: "Transcript, CV and letters", alt: "Documents page with transcript, CV and letters" },
        { title: "Your counsellor, beside your applications", alt: "Messages with a counsellor next to the application" },
      ],
    },
    faq: {
      h2: "Questions",
      items: [
        [
          "What is Elmify?",
          "An AI helper for applying to a master’s abroad. It finds programmes and scholarships that fit your profile, prepares your CV and letters, and keeps every deadline in one place.",
        ],
        [
          "Who is it for?",
          "Students from Azerbaijan and the region applying for a master’s (MSc, MA, LLM, MRes). Bachelor's degree support will be done soon. PhD is not covered.",
        ],
        [
          "Is it free?",
          "Yes. Creating an account, building your profile and getting your matches is free during early access.",
        ],
        [
          "Which scholarships and countries?",
          "Universities across Europe and the UK, with Azerbaijan’s State Program (dp.edu.az), HTP / Stipendium Hungaricum (htp.edu.az), Erasmus Mundus, DAAD, Chevening, Swedish Institute and university awards.",
        ],
        [
          "How does it know what fits me?",
          "It reads each official university and scholarship page and checks your grades, credits, language scores, citizenship and budget against every rule. Each rule links to the sentence it came from.",
        ],
        [
          "Does Elmify apply for me?",
          "No. You apply in your own browser. Our extension fills in the answers you approved and stops before Submit.",
        ],
        [
          "What happens to my data?",
          "It is used only for your applications. You can download your documents or delete your account at any time in Settings.",
        ],
      ],
    },
    closing: {
      h2: "Your profile takes ten minutes",
      body: "Your first matches are ready as soon as you finish.",
      ctaPrimary: "Sign up free",
      ctaSecondary: "Log in",
    },
    footer: {
      updatedLabel: "Updated",
      updatedDateText: "November 2026",
      links: {
        how: "How it works",
        faq: "FAQ",
        studentDemo: "Student walkthrough",
        login: "Log in",
        terms: "Terms",
        privacy: "Privacy",
      },
    },
    schema: {
      articleName: "How Elmify Evaluates Funded Master's & Scholarship Eligibility Across 50+ Countries",
      faqName: "Elmify Postgraduate & Scholarship Application FAQ (50+ Countries Worldwide)",
      educationalUse: "Postgraduate degree and scholarship application preparation",
      audienceType: "Master's degree applicants in Azerbaijan and worldwide",
      offerDescription: "Free during early access for postgraduate programme matching and document preparation.",
      featureList: [
        "Official university and scholarship page reading with sentence-level source links",
        "Eligibility matching for Azerbaijan State Program (Dövlət Proqramı 2022–2028), HTP / Stipendium Hungaricum, Erasmus Mundus, DAAD, Chevening, Swedish Institute, Türkiye Bursları, and NL Scholarship",
        "Postgraduate eligibility checks across GPA, Bachelor's ECTS credits, IELTS/TOEFL/TestDaF scores, citizenship, and AZN/EUR/USD budgets (Bachelor's support coming soon)",
        "Zero-fabrication academic CV, motivation letter, scholarship essay, and referee briefing preparation",
      ],
    },  },
  az: {
    locale: "az",
    ogLocale: "az_AZ",
    langLabel: "AZ",
    metaTitle: "Elmify — 50+ Ölkədə Təqaüdlü Magistratura və Fərdiləşdirilmiş Sənəd Hazırlığı",
    metaDescription:
      "Elmify 50+ ölkədə magistratura dərəcələri (MSc, MA, LLM, MRes — bakalavr dəstəyi tezliklə) üçün rəsmi universitet və təqaüd əsasnamələrini oxuyur, GPA, AKTS (ECTS) kreditləri və IELTS/TOEFL ballarınızı Dövlət Proqramı, HTP, Erasmus Mundus, DAAD, Chevening, universitet güzəştləri və RA/TA qaydaları ilə yoxlayır, hər proqrama fərdi uyğunlaşdırılmış CV və motivasiya məktublarınızı hazırlayır.",
    keywords: [
      "xaricdə təhsil təqaüd proqramları",
      "Dövlət Proqramı 2022-2028 magistratura",
      "HTP təqaüd proqramı Macarıstan",
      "50+ ölkədə təqaüdlü magistratura",
      "Erasmus Mundus təqaüdü Azərbaycan",
      "DAAD təqaüdü Azərbaycan",
      "Chevening təqaüdü Azərbaycan",
      "Swedish Institute SISGP Azərbaycan",
      "fərdiləşdirilmiş motivasiya məktubu və akademik CV hazırlanması",
    ],
    skipToMain: "Əsas məzmuna keç",
    nav: {
      how: "Necə işləyir",
      product: "Məhsul",
      faq: "Suallar",
      login: "Daxil ol",
      signup: "Pulsuz qeydiyyat",
      homeAria: "Elmify ana səhifə",
      langAria: "Dil seçimi",
    },
    hero: {
      h1: "Xaricdə təqaüdlü magistraturaya qəbul ol",
      body: "Elmify sənə uyğun proqram və təqaüdləri tapır, sənədlərini hazırlayır.",
      ctaPrimary: "Pulsuz qeydiyyat",
      ctaSecondary: "Daxil ol",
      example: "Nümunə",
      profileName: "Aysel, Bakı",
      profileFacts: ["Kimya üzrə bakalavr", "GPA 88/100", "IELTS 7.0"],
      matchesLabel: "Sənə uyğun",
      chanceLabel: "şans",
      matches: [
        { country: "Almaniya", programme: "MSc Kimya", funding: "DAAD · tam", chance: 72 },
        { country: "Macarıstan", programme: "MSc Tətbiqi Kimya", funding: "HTP · tam", chance: 81 },
        { country: "İsveç", programme: "MSc Molekulyar Elmlər", funding: "Swedish Institute", chance: 58 },
      ],
      shotAlt: "Nümunə: tələbə profili üç təqaüdlü magistratura proqramı və şansları ilə",
    },
    stats: [
      { value: 1400, suffix: "+", label: "təqaüd və qrant yoxlanılır" },
      { value: 53, suffix: "", label: "ölkədə axtarış" },
      { value: 10, suffix: " dəq", label: "profilin hazırdır" },
      { value: 0, suffix: "", label: "portal şifrəsi saxlanılmır" },
    ],
    scholarshipsLabel: "Yoxladığımız təqaüdlər — rəsmi səhifələrindən",
    booking: { cta: "Pulsuz 20 dəqiqəlik görüş təyin et", note: "Google Meet-də, sənə uyğun vaxtda" },
    how: {
      h2: "Necə işləyir",
      stages: [
        { title: "Özün haqqında yaz", body: "Dərəcən, qiymətlərin, dillər və büdcən." },
        { title: "Uyğun proqramları al", body: "Həqiqətən qazana biləcəyin proqram və təqaüdlər." },
        { title: "Sənədləri hazırla", body: "CV, motivasiya məktubları və tövsiyəçi xülasələri." },
        { title: "Özün müraciət et", body: "Portalı biz doldururuq. Göndər düyməsini sən basırsan." },
      ],
    },
    extensionPreview: {
      h2: "Portalı biz doldururuq. Göndər düyməsini sən basırsan.",
      body: "Elmify brauzer əlavəsi təsdiqlədiyin cavabları rəsmi portala yazır və Göndər düyməsindən əvvəl dayanır.",
      points: ["Bütün xanaları doldurur", "PDF-ləri əlavə edir", "Yeni sualları göstərir", "Göndər düyməsini heç vaxt basmır"],
    },
    product: {
      h2: "Hər şey bir yerdə",
      cells: [
        { title: "Proqramlar və onları ödəyən təqaüd", alt: "Ödəyən təqaüdə görə qruplaşdırılmış proqramlar" },
        { title: "Bütün son tarixlər bir lövhədə", alt: "Bütün son tarixləri göstərən müraciət lövhəsi" },
        { title: "Transkript, CV və məktublar", alt: "Transkript, CV və məktublar səhifəsi" },
        { title: "Məsləhətçin müraciətlərinin yanında", alt: "Müraciətin yanında məsləhətçi ilə yazışma" },
      ],
    },
    faq: {
      h2: "Suallar",
      items: [
        [
          "Elmify nədir?",
          "Xaricdə magistraturaya müraciət üçün süni intellekt köməkçisi. Profilinə uyğun proqram və təqaüdləri tapır, CV və məktublarını hazırlayır, bütün son tarixləri bir yerdə saxlayır.",
        ],
        [
          "Kimin üçündür?",
          "Magistraturaya (MSc, MA, LLM, MRes) müraciət edən Azərbaycan və regiondan olan tələbələr üçün; bakalavr proqramları üzrə dəstək isə tezliklə əlavə olunacaq. Doktorantura (PhD) daxil deyil.",
        ],
        [
          "Pulsuzdur?",
          "Bəli. Erkən giriş dövründə hesab yaratmaq, profil doldurmaq və uyğun proqramları görmək pulsuzdur.",
        ],
        [
          "Hansı təqaüdlər və ölkələr?",
          "Avropa və Böyük Britaniya universitetləri: Dövlət Proqramı (dp.edu.az), HTP / Stipendium Hungaricum (htp.edu.az), Erasmus Mundus, DAAD, Chevening, Swedish Institute və universitet təqaüdləri.",
        ],
        [
          "Mənə nəyin uyğun olduğunu necə bilir?",
          "Hər rəsmi universitet və təqaüd səhifəsini oxuyur, qiymətlərini, kreditlərini, dil ballarını, vətəndaşlığını və büdcəni hər qayda ilə yoxlayır. Hər qayda götürüldüyü cümləyə keçid verir.",
        ],
        [
          "Elmify mənim yerimə müraciət edir?",
          "Xeyr. Müraciəti öz brauzerində edirsən. Əlavəmiz təsdiqlədiyin cavabları doldurur və Göndər düyməsindən əvvəl dayanır.",
        ],
        [
          "Məlumatlarıma nə olur?",
          "Yalnız müraciətlərin üçün istifadə olunur. Sənədlərini yükləyə və ya hesabını istənilən vaxt Parametrlərdən silə bilərsən.",
        ],
      ],
    },
    closing: {
      h2: "Profilin on dəqiqəyə hazırdır",
      body: "Bitirən kimi ilk uyğun proqramların hazır olur.",
      ctaPrimary: "Pulsuz qeydiyyat",
      ctaSecondary: "Daxil ol",
    },
    footer: {
      updatedLabel: "Yenilənib",
      updatedDateText: "Noyabr 2026",
      links: {
        how: "Necə işləyir",
        faq: "Suallar",
        studentDemo: "Tələbə nümayişi",
        login: "Daxil ol",
        terms: "Şərtlər",
        privacy: "Məxfilik",
      },
    },
    schema: {
      articleName: "Elmify 50+ ölkə üzrə təqaüdlü magistratura uyğunluğunu necə yoxlayır",
      faqName: "Elmify Magistratura və Təqaüd Müraciətləri üzrə Tez-tez Verilən Suallar (50+ Ölkə)",
      educationalUse: "Xaricdə magistratura və təqaüd müraciətlərinin hazırlanması",
      audienceType: "Azərbaycandan və dünyadan magistratura namizədləri",
      offerDescription: "Erkən giriş dövründə proqram seçimi və sənəd hazırlığı tələbələr üçün pulsuzdur.",
      featureList: [
        "Rəsmi universitet və təqaüd səhifələrinin cümlə səviyyəsində mənbə keçidləri ilə oxunması",
        "Dövlət Proqramı (2022–2028), HTP / Stipendium Hungaricum, Erasmus Mundus, DAAD, Chevening, Swedish Institute, Türkiye Bursları və NL Scholarship üzrə uyğunluq yoxlaması",
        "GPA, bakalavr AKTS kreditləri, IELTS/TOEFL/TestDaF balları, vətəndaşlıq və AZN/EUR/USD büdcəsi üzrə yoxlama (bakalavr dəstəyi tezliklə)",
        "Uydurma fakt olmadan akademik CV, motivasiya məktubu, təqaüd essesi və tövsiyəçi brifinqlərinin hazırlanması",
      ],
    },  },
  ru: {
    locale: "ru",
    ogLocale: "ru_RU",
    langLabel: "RU",
    metaTitle: "Elmify — Магистратура и стипендии в 50+ странах мира (Персонализированные заявки с ИИ)",
    metaDescription:
      "Elmify читает официальные регламенты университетов и стипендий в 50+ странах для магистратуры (MSc, MA, LLM, MRes — бакалавриат скоро), сверяет GPA, кредиты ECTS и баллы IELTS/TOEFL с правилами Госпрограммы (Dövlət Proqramı), HTP, Erasmus Mundus, DAAD, Chevening, скидками вузов и позициями RA/TA, и готовит адаптированные под каждую программу CV и мотивационные письма.",
    keywords: [
      "стипендии на обучение за рубежом Азербайджан",
      "Госпрограмма обучения за рубежом Dövlət Proqramı магистратура",
      "стипендия HTP Stipendium Hungaricum Азербайджан",
      "магистратура за рубежом со стипендией 50+ стран",
      "стипендия Erasmus Mundus Азербайджан",
      "стипендия DAAD Азербайджан",
      "стипендия Chevening Азербайджан",
      "Swedish Institute SISGP Азербайджан",
      "персонализированное мотивационное письмо и академическое резюме CV",
    ],
    skipToMain: "Перейти к основному содержанию",
    nav: {
      how: "Как это работает",
      product: "Продукт",
      faq: "Вопросы",
      login: "Войти",
      signup: "Регистрация",
      homeAria: "Главная страница Elmify",
      langAria: "Выбор языка",
    },
    hero: {
      h1: "Поступи в магистратуру за рубежом со стипендией",
      body: "Elmify находит подходящие вам программы и стипендии и готовит ваши документы.",
      ctaPrimary: "Регистрация",
      ctaSecondary: "Войти",
      example: "Пример",
      profileName: "Айсель, Баку",
      profileFacts: ["Бакалавр химии", "GPA 88/100", "IELTS 7.0"],
      matchesLabel: "Вам подходит",
      chanceLabel: "шанс",
      matches: [
        { country: "Германия", programme: "MSc Химия", funding: "DAAD · полная", chance: 72 },
        { country: "Венгрия", programme: "MSc Прикладная химия", funding: "HTP · полная", chance: 81 },
        { country: "Швеция", programme: "MSc Молекулярные науки", funding: "Swedish Institute", chance: 58 },
      ],
      shotAlt: "Пример: профиль студента и три магистерские программы со стипендией и шансами",
    },
    stats: [
      { value: 1400, suffix: "+", label: "стипендий и грантов проверяется" },
      { value: 53, suffix: "", label: "стран в поиске" },
      { value: 10, suffix: " мин", label: "на ваш профиль" },
      { value: 0, suffix: "", label: "паролей от порталов хранится" },
    ],
    scholarshipsLabel: "Стипендии, которые мы проверяем, — по их официальным страницам",
    booking: { cta: "Записаться на бесплатный звонок, 20 мин", note: "В Google Meet, в удобное вам время" },
    how: {
      h2: "Как это работает",
      stages: [
        { title: "Расскажите о себе", body: "Диплом, оценки, языки и бюджет." },
        { title: "Получите подборку", body: "Программы и стипендии, которые реально получить." },
        { title: "Подготовьте документы", body: "CV, мотивационные письма и брифы для рекомендателей." },
        { title: "Подайте сами", body: "Мы заполняем портал. Кнопку «Отправить» нажимаете вы." },
      ],
    },
    extensionPreview: {
      h2: "Мы заполняем портал. «Отправить» нажимаете вы.",
      body: "Расширение Elmify вписывает одобренные вами ответы в официальный портал и останавливается перед отправкой.",
      points: ["Заполняет все поля", "Прикрепляет PDF", "Отмечает новые вопросы", "Никогда не нажимает «Отправить»"],
    },
    product: {
      h2: "Всё в одном месте",
      cells: [
        { title: "Программы и стипендия, которая их оплатит", alt: "Программы, сгруппированные по стипендии" },
        { title: "Все дедлайны на одной доске", alt: "Доска заявок со всеми дедлайнами" },
        { title: "Транскрипт, CV и письма", alt: "Страница документов: транскрипт, CV и письма" },
        { title: "Ваш консультант рядом с заявками", alt: "Переписка с консультантом рядом с заявкой" },
      ],
    },
    faq: {
      h2: "Вопросы",
      items: [
        [
          "Что такое Elmify?",
          "ИИ-помощник для поступления в магистратуру за рубежом. Он находит программы и стипендии под ваш профиль, готовит CV и письма и держит все дедлайны в одном месте.",
        ],
        [
          "Для кого это?",
          "Для студентов из Азербайджана и региона, поступающих в магистратуру (MSc, MA, LLM, MRes); поддержка бакалавриата будет добавлена совсем скоро. Докторантура (PhD) не поддерживается.",
        ],
        [
          "Это бесплатно?",
          "Да. В период раннего доступа создание аккаунта, профиль и подборка программ бесплатны.",
        ],
        [
          "Какие стипендии и страны?",
          "Университеты Европы и Великобритании, а также Госпрограмма Азербайджана (dp.edu.az), HTP / Stipendium Hungaricum (htp.edu.az), Erasmus Mundus, DAAD, Chevening, Swedish Institute и стипендии университетов.",
        ],
        [
          "Как он понимает, что мне подходит?",
          "Он читает официальные страницы университетов и стипендий и сверяет ваши оценки, кредиты, языковые баллы, гражданство и бюджет с каждым правилом. Каждое правило ссылается на предложение-источник.",
        ],
        [
          "Elmify подаёт заявки за меня?",
          "Нет. Вы подаёте сами в своём браузере. Наше расширение заполняет одобренные вами ответы и останавливается перед отправкой.",
        ],
        [
          "Что происходит с моими данными?",
          "Они используются только для ваших заявок. Документы можно скачать, а аккаунт — удалить в любой момент в Настройках.",
        ],
      ],
    },
    closing: {
      h2: "Профиль — за десять минут",
      body: "Первая подборка готова, как только вы закончите.",
      ctaPrimary: "Регистрация",
      ctaSecondary: "Войти",
    },
    footer: {
      updatedLabel: "Обновлено",
      updatedDateText: "Ноябрь 2026",
      links: {
        how: "Как это работает",
        faq: "Вопросы",
        studentDemo: "Демо для студента",
        login: "Войти",
        terms: "Условия",
        privacy: "Конфиденциальность",
      },
    },
    schema: {
      articleName: "Как Elmify проверяет соответствие требованиям магистратуры и стипендий в 50+ странах мира",
      faqName: "Частые вопросы о поступлении в магистратуру и стипендиях с Elmify (50+ стран мира)",
      educationalUse: "Подготовка заявок на программы магистратуры и международные стипендии",
      audienceType: "Кандидаты в магистратуру из Азербайджана и со всего мира",
      offerDescription: "Бесплатно в период раннего доступа для подбора программ и подготовки документов.",
      featureList: [
        "Чтение официальных страниц вузов и стипендий со ссылками на каждое предложение-источник",
        "Проверка критериев Госпрограммы Азербайджана (Dövlət Proqramı 2022–2028), HTP / Stipendium Hungaricum, Erasmus Mundus, DAAD, Chevening, Swedish Institute, Türkiye Bursları и NL Scholarship",
        "Сверка GPA, кредитов ECTS бакалавра, баллов IELTS/TOEFL/TestDaF, гражданства и бюджета в AZN/EUR/USD (поддержка бакалавриата скоро)",
        "Подготовка академического CV, мотивационных писем, эссе и брифов для рекомендателей без выдуманных фактов",
      ],
    },  },
};
