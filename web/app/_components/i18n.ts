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
    demo: `${appLinks.agencyDemo}&lang=${locale}`,
    studentDemo: `${appLinks.studentDemo}&lang=${locale}`,
    agencyDemo: `${appLinks.agencyDemo}&lang=${locale}`,
    terms: `${appLinks.terms}?lang=${locale}`,
    privacy: `${appLinks.privacy}?lang=${locale}`,
  };
}

export interface ScholarshipRow {
  funder: string;
  url: string;
  scope: string;
  funding: string;
  rules: string;
}

export interface HiddenFundingLayer {
  badge: string;
  title: string;
  examples: string;
  howFound: string;
}

export interface ExtensionPreviewCopy {
  badge: string;
  heading: string;
  sub: string;
  portalTitle: string;
  portalUrl: string;
  portalFields: ReadonlyArray<{
    label: string;
    value: string;
    status: string;
    tone: "ok" | "warn";
  }>;
  submitLabel: string;
  submitGuard: string;
  sidePanelTitle: string;
  sidePanelStatus: string;
  sidePanelItems: ReadonlyArray<string>;
  sidePanelNote: string;
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
    agencies: string;
    faq: string;
    login: string;
    signup: string;
    homeAria: string;
    langAria: string;
  };
  hero: {
    eyebrow: string;
    h1: string;
    body: string;
    ctaPrimary: string;
    ctaStudentDemo: string;
    ctaSecondary: string;
    shotAlt: string;
    shotCaption: string;
  };
  how: {
    h2: string;
    intro: string;
    stages: ReadonlyArray<{ title: string; body: string }>;
    tableHeading: string;
    tableSub: string;
    tableIntro: string;
    tableHeaders: readonly [string, string, string, string];
    rows: ReadonlyArray<ScholarshipRow>;
    hiddenHeading: string;
    hiddenSub: string;
    hiddenIntro: string;
    hiddenLayers: ReadonlyArray<HiddenFundingLayer>;
    extensionPreview: ExtensionPreviewCopy;
    closingNote: string;
  };
  product: {
    h2: string;
    intro: string;
    cells: ReadonlyArray<{
      title: string;
      body: string;
      alt: string;
    }>;
  };
  agencies: {
    h2: string;
    body: string;
    cta: string;
    points: ReadonlyArray<readonly [string, string]>;
  };
  faq: {
    h2: string;
    intro: string;
    items: ReadonlyArray<readonly [string, string]>;
  };
  closing: {
    h2: string;
    body: string;
    ctaPrimary: string;
    ctaStudentDemo: string;
    ctaSecondary: string;
  };
  footer: {
    updatedLabel: string;
    updatedDateText: string;
    links: {
      how: string;
      about: string;
      agencies: string;
      studentDemo: string;
      demo: string;
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
    metaTitle: "Elmify — Funded Master's Programmes & Scholarships Abroad (Azerbaijan, Europe & UK)",
    metaDescription:
      "Launching first in Azerbaijan: Elmify's AI reads official university and scholarship pages for master's degrees (MSc, MA, LLM, MRes — Bachelor's coming soon), checks your GPA, ECTS credits, and IELTS or TOEFL scores against State Program (Dövlət Proqramı), HTP, Erasmus Mundus, DAAD, and Chevening rules, and prepares your CV, motivation letters, and referee briefs.",
    keywords: [
      "study abroad scholarships Azerbaijan",
      "Dövlət Proqramı xaricdə təhsil magistratura",
      "HTP Stipendium Hungaricum Azerbaijan",
      "funded master's programmes in Europe",
      "Erasmus Mundus Joint Masters",
      "DAAD scholarship Azerbaijan",
      "Chevening scholarship Azerbaijan",
      "Swedish Institute SISGP Azerbaijan",
      "master's eligibility checker and motivation letter",
    ],
    skipToMain: "Skip to main content",
    nav: {
      how: "How it works",
      product: "Product",
      agencies: "For agencies",
      faq: "FAQ",
      login: "Log in",
      signup: "Sign up free",
      homeAria: "Elmify home",
      langAria: "Language switcher",
    },
    hero: {
      eyebrow:
        "Launching first in Azerbaijan · Master's degrees & scholarships (MSc, MA, LLM, MRes) · Bachelor's coming soon",
      h1: "Get into a funded master’s abroad",
      body:
        "Elmify’s AI reads official university and scholarship pages across Europe and the UK, checks your grades, ECTS credits, IELTS or TOEFL scores, and budget against every admission rule (including Azerbaijan’s State Program, HTP, and 5 layers of low-competition funding), prepares your CV, motivation letters, and referee briefs, and autofills portals in your browser while you stay in charge.",
      ctaPrimary: "Sign up free",
      ctaStudentDemo: "Book a student walkthrough",
      ctaSecondary: "See how it works",
      shotAlt: "The Elmify student dashboard showing progress, matched programmes, scholarships, and deadlines",
      shotCaption: "The student dashboard, shown with a sample applicant from Baku.",
    },
    how: {
      h2: "What the AI does, and what you decide",
      intro:
        "The slow part of applying for a funded postgraduate degree is reading hundreds of university and scholarship pages — including non-English regional grants and faculty PDF calls. Elmify does the reading, shows 100% of its sources, and helps you fill the portal without ever taking over your account.",
      stages: [
        {
          title: "Reads official university & niche funder pages",
          body: "It reads each university's and scholarship's own website and PDF calls in local languages for MSc, MA, LLM, and MRes degrees, keeping the exact sentence behind every requirement with a source link.",
        },
        {
          title: "Checks flagship & hidden funding against your profile",
          body: "Your GPA, Bachelor's ECTS credits, IELTS or TOEFL scores, citizenship, and fee budget (in AZN, EUR, GBP, or USD) are checked across national treaties and 5 layers of low-competition waivers and grants.",
        },
        {
          title: "Prepares your CV, letters, and referee briefs",
          body: "Your academic CV, motivation letters, scholarship essays, and distinct referee briefs are written strictly from facts you confirmed. Nothing is used until you approve it.",
        },
        {
          title: "Autofills the portal in your browser — you press Submit",
          body: "Our glass-box browser extension opens beside DreamApply, uni-assist, or Studielink, fills your approved answers and PDFs, flags any new question, and stops before the Submit button.",
        },
      ],
      tableHeading: "Tier 1 — Flagship Azerbaijan, European & UK national scholarships",
      tableSub: "100% of eligibility rules linked to official funder and university pages",
      tableIntro:
        "Elmify launches first in Azerbaijan and covers postgraduate degrees (MSc, MA, LLM, MRes) today, with Bachelor's degree support coming soon. Doctoral (PhD) and postdoctoral calls are excluded so credit, GPA, and work-hour checks match your exact level.",
      tableHeaders: [
        "Scholarship / Funder",
        "Degree Scope",
        "Typical Award Value",
        "Key Eligibility Rules Checked",
      ],
      rows: [
        {
          funder: "Azerbaijan State Program (Dövlət Proqramı 2022–2028)",
          url: "https://dp.edu.gov.az/",
          scope: "Priority postgraduate degrees at top global, European & UK universities",
          funding: "100% tuition + monthly living stipend + return flights + medical insurance + visa",
          rules: "Azerbaijani citizenship, unconditional admission offer from listed priority university/field",
        },
        {
          funder: "HTP & Stipendium Hungaricum (Hungary / Bilateral)",
          url: "https://htp.edu.az/",
          scope: "Full-time second-cycle degree in Hungary, China, Romania & partner states (1.5–2 years)",
          funding: "100% tuition exemption + dormitory or HUF 40,000/mo housing + HUF 43,700/mo stipend",
          rules: "Dual application on htp.edu.az & DreamApply, 200 AZ quota for Hungary, B2/C1 language",
        },
        {
          funder: "Erasmus Mundus Joint Masters",
          url: "https://erasmus-plus.ec.europa.eu/opportunities/opportunities-for-individuals/students/erasmus-mundus-joint-masters",
          scope: "Joint MSc / MA across 2–4 European universities (120 ECTS)",
          funding: "100% tuition waiver + €1,400/month stipend for up to 24 months",
          rules: "180 ECTS Bachelor's, IELTS 6.5–7.0, 12-month Partner Country residency rule",
        },
        {
          funder: "DAAD Study Scholarships",
          url: "https://www.daad.de/en/Studying-in-Germany/scholarships/",
          scope: "Full-time postgraduate degree in Germany (1–2 years)",
          funding: "€934/month stipend + health insurance + travel allowance from Azerbaijan",
          rules: "Bachelor's degree ≤ 6 years old, IELTS 6.5 or TestDaF TDN 4",
        },
        {
          funder: "Swedish Institute (SISGP)",
          url: "https://si.se/en/apply/scholarships/swedish-institute-scholarships-for-global-professionals/",
          scope: "English-taught 1- or 2-year MSc / MA in Sweden",
          funding: "100% tuition paid to university + SEK 12,000/month + SEK 15,000 travel grant",
          rules: "Azerbaijan eligible citizenship, 3,000 hours verified work & leadership experience",
        },
        {
          funder: "Chevening Scholarships",
          url: "https://www.chevening.org/scholarships/",
          scope: "1-year taught postgraduate degree at any UK university",
          funding: "100% UK tuition + £1,378–£1,690/month stipend + return flights from Baku",
          rules: "2,800 hours (2 years) work experience, 3 eligible UK course choices",
        },
        {
          funder: "NL Scholarship",
          url: "https://www.studyinnl.org/finances/nl-scholarship",
          scope: "Research or applied MSc / MA in the Netherlands",
          funding: "€5,000 first-year grant (combinable with faculty tuition waivers)",
          rules: "Non-EEA nationality, first-time enrolment at a Dutch university",
        },
      ],
      hiddenHeading: "Tier 2 — Beyond the famous names: 5 low-competition funding layers unlocked in your pack",
      hiddenSub: "Queried across 53 countries in native local languages and official university PDF regulations",
      hiddenIntro:
        "Every applicant in Baku applies to the same 6 famous scholarships above. Elmify's research engine unlocks 1,400+ verified awards across five deeper funding layers where competition is a fraction as high — matched directly to your transcript credits and household profile.",
      hiddenLayers: [
        {
          badge: "Route · Automatic on admission",
          title: "1. Automatic-on-admission & faculty tuition waivers",
          examples:
            "€5,000–€16,500/yr university tuition waivers and €8,000–€12,000/yr faculty excellence fellowships triggered automatically by your master's admission offer — requiring zero extra scholarship essays.",
          howFound:
            "Unlocked in your pack by matching your Bachelor's ECTS subject credits against faculty fee-waiver regulations.",
        },
        {
          badge: "Layer · Regional & municipal grants",
          title: "2. Regional & household-income right-to-study grants",
          examples:
            "100% tuition exemption + free university residence hall + daily campus canteen meals + €6,000–€7,000/yr cash stipend across European regional authorities.",
          howFound:
            "Calculated from your family income bracket and target city, where Azerbaijani households typically qualify for the maximum regional stipend tier.",
        },
        {
          badge: "Layer · Regional bloc & bank funds",
          title: "3. Multi-country bloc & development-bank scholarships",
          examples:
            "Full tuition + €3,000/semester living stipends + travel grants reserved under multilateral treaties for citizens of Eastern Partnership and developing member states.",
          howFound:
            "Matched exclusively to accredited master's tracks and partner-country quotas where Azerbaijani citizenship is eligible.",
        },
        {
          badge: "Layer · Local-language foundations",
          title: "4. Non-English private, civic & charitable foundations",
          examples:
            "€934/month living stipends + health insurance + family allowances from European and regional foundations that publish calls only in German, French, Italian, Dutch, or Turkish.",
          howFound:
            "Surfaced by our native-language research crawler and matched to your academic discipline, GPA, and civic or research profile.",
        },
        {
          badge: "Layer · Inside university PDF calls",
          title: "5. Departmental RA/TA assistantships & relocation supplements",
          examples:
            "Paid Graduate Research & Teaching Assistantships (monthly salary + tuition remission), application-fee waivers, and €500–€1,500 relocation and housing grants buried inside 40-page departmental PDF regulations.",
          howFound:
            "Extracted sentence-by-sentence from official faculty PDF bylaws and attached directly to your matched programme card.",
        },
      ],
      extensionPreview: {
        badge: "Step 04 · Glass-box browser extension co-pilot",
        heading: "See how our browser extension fills the portal — while stopping at Submit",
        sub: "No black-box bot ever logs in as you. You open the official university or scholarship portal in your own browser, and the Elmify side-panel fills verified fields right in front of you.",
        portalTitle: "Official University Admission Portal (DreamApply / uni-assist / Studielink)",
        portalUrl: "https://apply.university-portal.eu/masters/application/step-3",
        portalFields: [
          {
            label: "Prior Bachelor's degree & ECTS credits",
            value: "Baku State University · BSc Chemistry · 240 ECTS · GPA 91.4 / 100",
            status: "Auto-filled from verified transcript",
            tone: "ok",
          },
          {
            label: "English proficiency certificate",
            value: "IELTS Academic · Overall 7.0 (Listening 7.5, Reading 7.0, Writing 6.5, Speaking 7.0)",
            status: "Auto-filled from verified certificate",
            tone: "ok",
          },
          {
            label: "Required PDF attachments",
            value: "CV_Aysel_MSc_Chemistry.pdf · Motivation_Letter_IdEx_Approved.pdf",
            status: "2 approved PDFs attached from your kit",
            tone: "ok",
          },
          {
            label: "Portal-specific question: Preferred laboratory rotation track",
            value: "Waiting for your selection: Heterogeneous Catalysis vs. Polymer Synthesis",
            status: "Flagged by extension — needs your choice",
            tone: "warn",
          },
        ],
        submitLabel: "Submit final application to university",
        submitGuard: "Extension stops here — only you can click Submit in your browser",
        sidePanelTitle: "Elmify Browser Extension",
        sidePanelStatus: "Connected to your MSc Chemistry application kit",
        sidePanelItems: [
          "14 portal fields matched & filled from your confirmed profile",
          "2 counsellor-approved PDFs attached (CV & Motivation Letter)",
          "1 unmapped portal question highlighted in amber for your decision",
          "Zero portal passwords stored · Full audit log in your workspace",
        ],
        sidePanelNote: "You review every field on screen and click Submit yourself.",
      },
      closingNote: "You press submit in your own browser. Elmify never applies anywhere without you.",
    },
    product: {
      h2: "Everything for your applications, in one place",
      intro: "These are screens from the product itself.",
      cells: [
        {
          title: "Programmes grouped by the scholarship that pays",
          body: "Dövlət Proqramı, HTP / Stipendium Hungaricum, Erasmus Mundus, DAAD, Chevening, Swedish Institute, and university awards, with tuition coverage, monthly stipends, and deadlines.",
          alt: "Postgraduate programme match cards grouped under the scholarship that funds them",
        },
        {
          title: "One board for every application",
          body: "Track every university and scholarship deadline from To start to Decision, with gates that flag early.",
          alt: "The My applications board with columns for each stage",
        },
        {
          title: "Transcripts, CV, and letters in one place",
          body: "Upload your Bachelor's transcript, diploma supplement, CV, and IELTS or TOEFL certificate once. See what each admission portal still needs.",
          alt: "The documents page with an upload area and document cards",
        },
        {
          title: "Your counsellor, beside your applications",
          body: "If you work with a study-abroad agency in Baku or online, messages and document reviews sit right next to the application.",
          alt: "A conversation between a student and their counsellor",
        },
      ],
    },
    agencies: {
      h2: "Run your agency on Elmify",
      body: "Built for study-abroad agencies in Azerbaijan and across the region. Counsellors work on each student’s board under your own domain, and students always know what is next.",
      cta: "Book an agency demo",
      points: [
        ["Your address", "Students sign up and log in on your agency’s own web address."],
        ["Your team", "Assign each student to a counsellor and see who is waiting on whom."],
        ["Your leads", "Agency demo requests and student walkthroughs arrive separated on your owner page."],
        ["30-day pilot", "Start with a 30-day 10-student white-label pilot (100% credited to your annual plan)."],
      ],
    },
    faq: {
      h2: "Questions",
      intro: "Anything else? Ask us during a demo.",
      items: [
        [
          "Is Elmify available in Azerbaijan, and is it free for students?",
          "Yes. Elmify is launching first in Azerbaijan in English, Azerbaijani, and Russian, with local application-fee budgeting in AZN, EUR, GBP, and USD. Creating an account, uploading your transcript and CV, and getting your matched postgraduate programmes and scholarships is free during early access.",
        ],
        [
          "Which countries, scholarships, and degrees do you cover?",
          "We cover English-taught and local-language postgraduate degrees across Europe and the UK, paired with Azerbaijan's State Program (Dövlət Proqramı 2022–2028), Intergovernmental Scholarship Programs (HTP / Stipendium Hungaricum), Erasmus Mundus Joint Masters, DAAD, Swedish Institute (SISGP), Chevening, Türkiye Bursları, NL Scholarship, plus 5 layers of low-competition funding (automatic faculty waivers, regional household-income grants, multilateral bloc funds, local-language foundations, and departmental RA/TA stipends).",
        ],
        [
          "Does Elmify cover Bachelor's or PhD programmes?",
          "Master's degrees (MSc, MA, LLM, MRes) and second-cycle scholarships are live today, and Bachelor's degree support will be done soon. Doctoral (PhD) and postdoctoral calls are not covered so every credit rule, deadline, and funding check stays accurate for your degree level.",
        ],
        [
          "Does the AI make things up?",
          "Every admission or scholarship requirement links directly to the exact sentence on the official university or funder webpage it was read from. Your CV, motivation letters, and essays use only facts you have confirmed from your transcript and profile. When an official page does not state a rule, Elmify flags it as unstated instead of guessing.",
        ],
        [
          "How does Elmify prepare my CV, motivation letter, and reference briefs?",
          "Once you confirm your academic facts, Elmify builds a tailored academic CV, a programme-specific motivation letter, scholarship essays, and distinct talking-point briefs for each of your referees so two recommenders never repeat the same story.",
        ],
        [
          "Do you submit applications for me?",
          "No. You stay in your own browser and press submit yourself on the official university or scholarship portal. Our glass-box browser extension opens beside DreamApply, uni-assist, or Studielink, autofills your verified profile answers and approved PDFs, flags any portal-specific question, and stops before the Submit button.",
        ],
        [
          "What happens to my data?",
          "Your transcripts, CV, and profile answers are used solely to match postgraduate programmes and prepare your application documents. You can export your documents or permanently delete your account and files from Settings at any time.",
        ],
      ],
    },
    closing: {
      h2: "Your profile takes ten minutes",
      body: "Your first matches across flagship and hidden scholarships are ready as soon as you finish.",
      ctaPrimary: "Sign up free",
      ctaStudentDemo: "Book a student walkthrough",
      ctaSecondary: "Log in",
    },
    footer: {
      updatedLabel: "Updated",
      updatedDateText: "November 2026",
      links: {
        how: "How it works",
        about: "About & sources",
        agencies: "For agencies",
        studentDemo: "Student walkthrough",
        demo: "Agency demo",
        login: "Log in",
        terms: "Terms",
        privacy: "Privacy",
      },
    },
    schema: {
      articleName: "How Elmify Evaluates Funded Master's & Scholarship Eligibility for Applicants in Azerbaijan",
      faqName: "Elmify Postgraduate & Scholarship Application FAQ (Azerbaijan, Europe & UK)",
      educationalUse: "Postgraduate degree and scholarship application preparation",
      audienceType: "Master's degree applicants and study-abroad agencies in Azerbaijan and worldwide",
      offerDescription: "Free during early access for postgraduate programme matching and document preparation.",
      featureList: [
        "Official university and scholarship page reading with sentence-level source links",
        "Eligibility matching for Azerbaijan State Program (Dövlət Proqramı 2022–2028), HTP / Stipendium Hungaricum, Erasmus Mundus, DAAD, Chevening, Swedish Institute, Türkiye Bursları, and NL Scholarship",
        "Postgraduate eligibility checks across GPA, Bachelor's ECTS credits, IELTS/TOEFL/TestDaF scores, citizenship, and AZN/EUR/USD budgets (Bachelor's support coming soon)",
        "Zero-fabrication academic CV, motivation letter, scholarship essay, and referee briefing preparation",
        "White-label multi-counsellor workspace for study-abroad agencies in Azerbaijan and abroad",
      ],
    },
  },
  az: {
    locale: "az",
    ogLocale: "az_AZ",
    langLabel: "AZ",
    metaTitle: "Elmify — Xaricdə Təqaüdlü Magistratura Proqramları (Azərbaycan, Avropa və Böyük Britaniya)",
    metaDescription:
      "Azərbaycanda ilk buraxılış: Elmify-ın süni intellekti magistratura dərəcələri (MSc, MA, LLM, MRes — bakalavr dəstəyi tezliklə) üçün rəsmi universitet və təqaüd səhifələrini oxuyur, GPA, AKTS (ECTS) kreditləri və IELTS/TOEFL ballarınızı Dövlət Proqramı, HTP, Erasmus Mundus, DAAD və Chevening qaydaları ilə yoxlayır, CV və motivasiya məktublarınızı hazırlayır.",
    keywords: [
      "xaricdə təhsil təqaüd proqramları",
      "Dövlət Proqramı 2022-2028 magistratura",
      "HTP təqaüd proqramı Macarıstan",
      "Avropada təqaüdlü magistratura",
      "Erasmus Mundus təqaüdü Azərbaycan",
      "DAAD təqaüdü Azərbaycan",
      "Chevening təqaüdü Azərbaycan",
      "Swedish Institute SISGP Azərbaycan",
      "motivasiya məktubu və akademik CV hazırlanması",
    ],
    skipToMain: "Əsas məzmuna keç",
    nav: {
      how: "Necə işləyir",
      product: "Məhsul",
      agencies: "Agentliklər üçün",
      faq: "Suallar",
      login: "Daxil ol",
      signup: "Pulsuz qeydiyyat",
      homeAria: "Elmify ana səhifə",
      langAria: "Dil seçimi",
    },
    hero: {
      eyebrow:
        "Azərbaycanda ilk buraxılış · Magistratura və təqaüdlər (MSc, MA, LLM, MRes) · Bakalavr tezliklə",
      h1: "Xaricdə təqaüdlü magistraturaya qəbul ol",
      body:
        "Elmify-ın süni intellekti Avropa və Böyük Britaniyanın rəsmi universitet və təqaüd səhifələrini oxuyur, qiymətlərinizi, AKTS (ECTS) kreditlərinizi, IELTS və ya TOEFL ballarınızı və büdcənizi hər bir qəbul qaydası (Dövlət Proqramı, HTP və 5 aşağı rəqabətli gizli təqaüd qatı daxil olmaqla) ilə yoxlayır, CV, motivasiya məktubu və tövsiyə xülasələrinizi hazırlayır və portalları öz brauzerinizdə doldurmağa kömək edir.",
      ctaPrimary: "Pulsuz qeydiyyat",
      ctaStudentDemo: "Tələbə nümayişi sifariş et",
      ctaSecondary: "Necə işlədiyinə bax",
      shotAlt: "Elmify tələbə paneli: müraciət gedişatı, növbəti addımlar və son tarixlər",
      shotCaption: "Tələbə paneli — Bakıdan olan nümunə namizəd profili ilə.",
    },
    how: {
      h2: "Süni intellekt nə edir və siz nəyə qərar verirsiniz",
      intro:
        "Xaricdə təqaüdlü təhsilə müraciət zamanı ən çox vaxt aparan hissə yüzlərlə universitet və fond səhifəsini — o cümlədən yerli dillərdəki regional qrantları və PDF əsasnamələri oxumaqdır. Elmify bütün rəsmi səhifələri oxuyur, mənbələrin 100%-ni göstərir və hesabınızı ələ keçirmədən portalı doldurmağa kömək edir.",
      stages: [
        {
          title: "Rəsmi universitet və niş təqaüd səhifələrini oxuyur",
          body: "MSc, MA, LLM və MRes proqramları üçün hər bir universitetin və təqaüd fondunun öz rəsmi saytını və PDF elanlarını yerli dillərdə oxuyur, hər tələbin arxasındakı dəqiq cümləni mənbə keçidi ilə saxlayır.",
        },
        {
          title: "Əsas və gizli təqaüdləri profilinizlə yoxlayır",
          body: "GPA ortalamanız, bakalavr AKTS (ECTS) kreditləriniz, IELTS və ya TOEFL nəticələriniz, vətəndaşlığınız və müraciət büdcəniz (AZN, EUR, GBP və ya USD ilə) həm dövlət təqaüdləri, həm də 5 aşağı rəqabətli maliyyə qatı üzrə yoxlanılır.",
        },
        {
          title: "CV, məktub və tövsiyə xülasələrinizi hazırlayır",
          body: "Akademik CV, motivasiya məktubları, təqaüd esseləri və tövsiyəçi (referee) brifinqləri yalnız sizin təsdiqlədiyiniz faktlar əsasında yazılır. Siz təsdiqləmədən heç nə istifadə olunmur.",
        },
        {
          title: "Öz brauzerinizdə portalı doldurur — göndər düyməsini siz sıxırsınız",
          body: "Şəffaf brauzer əlavəmiz DreamApply, uni-assist və ya Studielink-in yanında açılır, təsdiqlənmiş cavablarınızı və PDF sənədlərinizi yerləşdirir və Göndər düyməsindən əvvəl dayanır.",
        },
      ],
      tableHeading: "1-ci Səviyyə — Azərbaycan, Avropa və Böyük Britaniyanın əsas milli təqaüdləri",
      tableSub: "Uyğunluq qaydalarının 100%-i rəsmi fond və universitet səhifələrinə istinad edir",
      tableIntro:
        "Elmify ilk olaraq Azərbaycanda istifadəyə verilir və hazırda magistratura dərəcələrini (MSc, MA, LLM, MRes) əhatə edir; bakalavr proqramları üzrə dəstək tezliklə əlavə olunacaq. Doktorantura (PhD) müraciətləri daxil edilmir ki, kredit və GPA yoxlamaları dəqiq səviyyənizə uyğun olsun.",
      tableHeaders: [
        "Təqaüd / Fond",
        "Dərəcə əhatəsi",
        "Tipik maliyyə dəyəri",
        "Yoxlanılan əsas uyğunluq qaydaları",
      ],
      rows: [
        {
          funder: "Dövlət Proqramı (2022–2028 Xaricdə Təhsil)",
          url: "https://dp.edu.gov.az/",
          scope: "Prioritet ixtisaslar üzrə dünyanın aparıcı universitetlərində magistratura",
          funding: "100% təhsil haqqı + aylıq yaşayış təqaüdü + aviabilet + tibbi sığorta + viza",
          rules: "Azərbaycan vətəndaşlığı, siyahıdakı nüfuzlu universitetdən qəbul məktubu (offer)",
        },
        {
          funder: "HTP və Stipendium Hungaricum (Macarıstan / İkitərəfli)",
          url: "https://htp.edu.az/",
          scope: "Macarıstan, Çin, Rumıniya və tərəfdaş ölkələrdə əyani ikinci pillə təhsil (1.5–2 il)",
          funding: "100% təhsil haqqından azad + yataqxana və ya 40,000 HUF/ay + 43,700 HUF/ay təqaüd",
          rules: "htp.edu.az və DreamApply üzərindən ikili qeydiyyat, 200 yerlik Azərbaycan kvotası, B2/C1 dil",
        },
        {
          funder: "Erasmus Mundus Joint Masters",
          url: "https://erasmus-plus.ec.europa.eu/opportunities/opportunities-for-individuals/students/erasmus-mundus-joint-masters",
          scope: "2–4 Avropa universitetində birgə MSc / MA proqramı (120 ECTS)",
          funding: "100% təhsil haqqı + 24 ayadək ayda €1,400 təqaüd",
          rules: "180 ECTS bakalavr diplomu, IELTS 6.5–7.0, 12 aylıq ölkə qaydası",
        },
        {
          funder: "DAAD Təhsil Təqaüdləri",
          url: "https://www.daad.de/en/Studying-in-Germany/scholarships/",
          scope: "Almaniyada əyani magistratura təhsili (1–2 il)",
          funding: "Ayda €934 təqaüd + tibbi sığorta + Azərbaycandan yol xərci",
          rules: "Bakalavr diplomunun yaşı ≤ 6 il, IELTS 6.5 və ya TestDaF TDN 4",
        },
        {
          funder: "Swedish Institute (SISGP)",
          url: "https://si.se/en/apply/scholarships/swedish-institute-scholarships-for-global-professionals/",
          scope: "İsveçdə ingilisdilli 1 və ya 2 illik MSc / MA proqramları",
          funding: "100% təhsil haqqı + ayda 12,000 SEK təqaüd + 15,000 SEK səyahət qrantı",
          rules: "Azərbaycan vətəndaşlığı, 3,000 saat təsdiqlənmiş iş və liderlik təcrübəsi",
        },
        {
          funder: "Chevening Təqaüdü",
          url: "https://www.chevening.org/scholarships/",
          scope: "Böyük Britaniyanın istənilən universitetində 1 illik magistratura",
          funding: "100% UK təhsil haqqı + ayda £1,378–£1,690 təqaüd + Bakıdan gediş-dönüş bileti",
          rules: "2,800 saat (2 il) iş təcrübəsi, 3 Britaniya universiteti seçimi",
        },
        {
          funder: "NL Scholarship",
          url: "https://www.studyinnl.org/finances/nl-scholarship",
          scope: "Niderlandda tədqiqat və ya tətbiqi MSc / MA proqramları",
          funding: "Birinci il üçün €5,000 qrant (fakültə güzəştləri ilə birləşdirilə bilər)",
          rules: "Aİ/AİZ xarici vətəndaşlıq, Niderland universitetində ilk qeydiyyat",
        },
      ],
      hiddenHeading: "2-ci Səviyyə — Məşhur adlardan kənarda: paketinizdə açılan 5 aşağı rəqabətli təqaüd qatı",
      hiddenSub: "53 ölkədə yerli dillərdə və universitetlərin rəsmi PDF əsasnamələrində axtarılır",
      hiddenIntro:
        "Bakıdakı namizədlərin əksəriyyəti yalnız yuxarıdakı 6 məşhur proqrama müraciət edir. Elmify-ın tədqiqat mühərriki rəqabətin dəfələrlə aşağı olduğu 5 dərin maliyyə qatı üzrə 1,400+ təsdiqlənmiş təqaüdü birbaşa transkript kreditlərinizə və profilinizə uyğunlaşdırır.",
      hiddenLayers: [
        {
          badge: "Marşrut · Qəbul zamanı avtomatik",
          title: "1. Qəbul zamanı avtomatik verilən və fakültə təhsil haqqı güzəştləri",
          examples:
            "Magistr qəbul təklifi (offer) ilə avtomatik aktivləşən ildə €5,000–€16,500 təhsil haqqı güzəştləri və €8,000–€12,000 fakültə təqaüdləri — əlavə təqaüd essesi tələb etmir.",
          howFound:
            "Bakalavr AKTS (ECTS) fənn kreditlərinizin fakültənin daxili güzəşt qaydaları ilə uyğunlaşdırılması nəticəsində şəxsi paketinizdə açılır.",
        },
        {
          badge: "Qat · Regional və bələdiyyə qrantları",
          title: "2. Ailə gəlirinə əsaslanan regional təhsil qrantları",
          examples:
            "Avropanın regional təhsil qurumları tərəfindən verilən 100% təhsil haqqından azadolma + pulsuz universitet yataqxanası + gündəlik yeməkxana + ildə €6,000–€7,000 nağd təqaüd.",
          howFound:
            "Ailə gəlirinizə və seçilmiş şəhərə əsasən hesablanır; Azərbaycandan olan ailə büdcəsi adətən ən yüksək təqaüd dərəcəsinə uyğun gəlir.",
        },
        {
          badge: "Qat · Regional blok və bank fondları",
          title: "3. Çoxtərəfli regional blok və inkişaf bankı təqaüdləri",
          examples:
            "Şərq Tərəfdaşlığı və inkişaf etməkdə olan üzv ölkələrin vətəndaşları üçün beynəlxalq müqavilələr üzrə ayrılan tam təhsil haqqı + semestrdə €3,000 yaşayış təqaüdü.",
          howFound:
            "Azərbaycan vətəndaşlarının birbaşa kvotaya malik olduğu akkreditə olunmuş magistr proqramları ilə uyğunlaşdırılır.",
        },
        {
          badge: "Qat · Yerli dildə fondlar",
          title: "4. Qeyri-ingilisdilli özəl, ictimai və xeyriyyə fondları",
          examples:
            "Elanlarını yalnız alman, fransız, italyan, niderland və ya türk dillərində dərc edən Avropa və regional fondlardan ayda €934 yaşayış təqaüdü + tibbi sığorta.",
          howFound:
            "İngilisdilli axtarışlarda görünməyən yerli fond nizamnamələrindən oxunur və ixtisasınıza, GPA balınıza və profilinizə görə seçilir.",
        },
        {
          badge: "Qat · Universitet PDF elanları",
          title: "5. Kafedradaxili RA/TA assistentlikləri və köçmə qrantları",
          examples:
            "Ödənişli tədqiqat və tədris assistentlikləri (RA/TA — aylıq maaş + təhsil haqqı güzəşti), müraciət rüsumundan azadolmalar və 40 səhifəlik PDF əsasnamələrdə gizlənən €500–€1,500 yol/yataqxana qrantları.",
          howFound:
            "Kafedraların rəsmi PDF əsasnamələrindən cümlə-cümlə çıxarılır və birbaşa uyğun proqram kartınıza bağlanır.",
        },
      ],
      extensionPreview: {
        badge: "Addım 04 · Şəffaf brauzer əlavəsi (Co-Pilot)",
        heading: "Brauzer əlavəmizin portalı necə doldurduğuna baxın — Göndər düyməsində dayanır",
        sub: "Heç bir qapalı bot sizin adınızdan sistemə girmir. Siz rəsmi universitet və ya təqaüd portalını öz brauzerinizdə açırsınız, Elmify yan paneli isə təsdiqlənmiş məlumatları gözünüzün önündə xanalara yerləşdirir.",
        portalTitle: "Rəsmi Universitet Qəbul Portalı (DreamApply / uni-assist / Studielink)",
        portalUrl: "https://apply.university-portal.eu/masters/application/step-3",
        portalFields: [
          {
            label: "Bakalavr dərəcəsi və AKTS (ECTS) kreditləri",
            value: "Bakı Dövlət Universiteti · BSc Kimya · 240 ECTS · ÜOMG 91.4 / 100",
            status: "Təsdiqlənmiş transkriptdən avtomatik dolduruldu",
            tone: "ok",
          },
          {
            label: "İngilis dili sertifikatı",
            value: "IELTS Academic · Ümumi 7.0 (Listening 7.5, Reading 7.0, Writing 6.5, Speaking 7.0)",
            status: "Təsdiqlənmiş sertifikatdan avtomatik dolduruldu",
            tone: "ok",
          },
          {
            label: "Tələb olunan PDF sənədlər",
            value: "CV_Aysel_MSc_Chemistry.pdf · Motivation_Letter_IdEx_Approved.pdf",
            status: "Sənəd paketinizdən 2 təsdiqlənmiş PDF əlavə olundu",
            tone: "ok",
          },
          {
            label: "Portala aid əlavə sual: Seçilən laboratoriya istiqaməti",
            value: "Seçiminiz gözlənilir: Heterogen Kataliz yoxsa Polimer Sintezi",
            status: "Əlavə tərəfindən işarələndi — sizin qərarınız lazımdır",
            tone: "warn",
          },
        ],
        submitLabel: "Yekun müraciəti universitetə göndər",
        submitGuard: "Əlavə burada dayanır — Göndər düyməsini yalnız özünüz sıxa bilərsiniz",
        sidePanelTitle: "Elmify Brauzer Əlavəsi",
        sidePanelStatus: "MSc Chemistry müraciət paketinizə qoşulub",
        sidePanelItems: [
          "Təsdiqlənmiş profilinizdən 14 portal xanası uyğunlaşdırıldı və dolduruldu",
          "Məsləhətçi tərəfindən təsdiqlənmiş 2 PDF (CV və Motivasiya məktubu) əlavə edildi",
          "1 yeni portal sualı sizin seçiminiz üçün sarı rənglə işarələndi",
          "Portal şifrələri saxlanılmır · Tam audit tarixçəsi kabinetinizdədir",
        ],
        sidePanelNote: "Ekrandakı hər xananı özünüz yoxlayır və Göndər düyməsini özünüz sıxırsınız.",
      },
      closingNote: "Müraciəti öz brauzerinizdə özünüz göndərirsiniz. Elmify sizin xəbəriniz olmadan heç yerə müraciət etmir.",
    },
    product: {
      h2: "Bütün müraciətləriniz üçün hər şey bir məkanda",
      intro: "Bu ekran görüntüləri birbaşa məhsulun özündəndir.",
      cells: [
        {
          title: "Xərcləri qarşılayan təqaüdə görə qruplaşdırılmış proqramlar",
          body: "Dövlət Proqramı, HTP / Stipendium Hungaricum, Erasmus Mundus, DAAD, Chevening, Swedish Institute və universitet təqaüdləri — təhsil haqqı, aylıq təqaüd və son tarixlərlə.",
          alt: "Maliyyələşdirən təqaüd fonduna görə qruplaşdırılmış proqram kartları",
        },
        {
          title: "Bütün müraciətlər üçün vahid lövhə",
          body: "Hər bir universitet və təqaüd son tarixini «Başlanacaq» mərhələsindən «Qərar» mərhələsinədək izləyin.",
          alt: "Mərhələlər üzrə sütunları olan Müraciətlərim lövhəsi",
        },
        {
          title: "Transkript, CV və məktublar bir yerdə",
          body: "Bakalavr transkriptinizi, diplom əlavəsini, CV və dil sertifikatlarınızı bir dəfə yükləyin. Hər portalın daha nə tələb etdiyini görün.",
          alt: "Yükləmə sahəsi və sənəd kartları olan Sənədlər səhifəsi",
        },
        {
          title: "Məsləhətçiniz müraciətlərinizin yanında",
          body: "Xaricdə təhsil agentliyi ilə işləyirsinizsə, mesajlar və sənəd rəyləri birbaşa müraciətin yanında yerləşir.",
          alt: "Tələbə ilə məsləhətçi arasında yazışma",
        },
      ],
    },
    agencies: {
      h2: "Agentliyinizi Elmify üzərində idarə edin",
      body: "Azərbaycandakı və regiondakı xaricdə təhsil şirkətləri üçün hazırlanıb. Məsləhətçilər öz domeniniz üzərində hər tələbənin lövhəsində işləyir, tələbələr isə növbəti addımı həmişə bilir.",
      cta: "Agentlik demosu sifariş et",
      points: [
        ["Öz ünvanınız", "Tələbələr agentliyinizin öz veb ünvanında qeydiyyatdan keçir və daxil olur."],
        ["Öz komandanız", "Hər tələbəni məsləhətçiyə təyin edin və kimin kimi gözlədiyini dərhal görün."],
        ["Öz müraciətləriniz", "Agentlik demoları və tələbə müraciətləri rəhbər səhifəsində ayrı-ayrı görünür."],
        ["30 günlük pilot", "Öz domeninizdə 10 tələbəlik 30 günlük pilotla başlayın (illik plana 100% hesablanır)."],
      ],
    },
    faq: {
      h2: "Tez-tez verilən suallar",
      intro: "Başqa sualınız var? Demo zamanı bizdən soruşun.",
      items: [
        [
          "Elmify Azərbaycanda əlçatandırmı və tələbələr üçün pulsuzdurmu?",
          "Bəli. Elmify ilk olaraq Azərbaycanda Azərbaycan, ingilis və rus dillərində, həmçinin AZN, EUR, GBP və USD ilə müraciət büdcəsi hesablaması ilə istifadəyə verilir. Erkən giriş dövründə hesab yaratmaq, transkript və CV yükləmək və uyğun proqramları görmək pulsuzdur.",
        ],
        [
          "Hansı ölkələri, təqaüdləri və proqramları əhatə edirsiniz?",
          "Avropa və Böyük Britaniyada ingilis və yerli dillərdə tədris olunan proqramları, Dövlət Proqramı (2022–2028), HTP / Stipendium Hungaricum, Erasmus Mundus, DAAD, Swedish Institute (SISGP), Chevening, Türkiye Bursları, NL Scholarship fondlarını, eləcə də 5 aşağı rəqabətli maliyyə qatını (qəbul zamanı avtomatik fakültə güzəştləri, ailə gəlirinə əsaslanan regional qrantlar, çoxtərəfli regional fondlar, yerli dildə özəl fondlar və kafedradaxili RA/TA təqaüdləri) əhatə edirik.",
        ],
        [
          "Elmify bakalavr və ya doktorantura (PhD) proqramlarını əhatə edirmi?",
          "Magistratura dərəcələri (MSc, MA, LLM, MRes) və magistr təqaüdləri hazırda tam aktivdir; bakalavr proqramları üzrə dəstək isə tezliklə əlavə olunacaq. Doktorantura (PhD) və postdoktorantura proqramları əhatə olunmur.",
        ],
        [
          "Süni intellekt faktları özündən uydururmu?",
          "Xeyr. Hər bir qəbul və ya təqaüd tələbi rəsmi universitet və ya fond səhifəsindəki dəqiq cümləyə birbaşa keçid verir. CV, motivasiya məktubları və esselərinizdə yalnız transkript və profilinizdən təsdiqlədiyiniz faktlar istifadə olunur.",
        ],
        [
          "Elmify CV, motivasiya məktubu və tövsiyə xülasələrini necə hazırlayır?",
          "Akademik faktlarınızı təsdiqlədikdən sonra Elmify hər proqram üçün uyğunlaşdırılmış akademik CV, motivasiya məktubu, təqaüd esseləri və hər tövsiyəçi (referee) üçün fərqli danışıq nöqtələri hazırlayır ki, iki müəllim eyni mətni təkrarlamasın.",
        ],
        [
          "Müraciətləri mənim əvəzimə siz göndərirsiniz?",
          "Xeyr. Siz öz brauzerinizdə rəsmi universitet və ya təqaüd portalında təsdiq düyməsini özünüz sıxırsınız. Şəffaf brauzer əlavəmiz DreamApply, uni-assist və ya Studielink-in yanında açılır, təsdiqlənmiş məlumatları və PDF sənədlərinizi doldurur və Göndər düyməsindən əvvəl dayanır.",
        ],
        [
          "Məlumatlarımla nə baş verir?",
          "Transkript, CV və profil cavablarınız yalnız uyğun proqramları tapmaq və müraciət sənədlərinizi hazırlamaq üçün istifadə olunur. İstənilən vaxt Ayarlar bölməsindən sənədlərinizi ixrac edə və ya hesabınızı həmişəlik silə bilərsiniz.",
        ],
      ],
    },
    closing: {
      h2: "Profilinizi tamamlamaq on dəqiqə çəkir",
      body: "Tamamladığınız anda həm əsas dövlət təqaüdləri, həm də gizli universitet fondları üzrə siyahınız hazır olur.",
      ctaPrimary: "Pulsuz qeydiyyat",
      ctaStudentDemo: "Tələbə nümayişi sifariş et",
      ctaSecondary: "Daxil ol",
    },
    footer: {
      updatedLabel: "Yenilənib",
      updatedDateText: "Noyabr 2026",
      links: {
        how: "Necə işləyir",
        about: "Haqqımızda və mənbələr",
        agencies: "Agentliklər üçün",
        studentDemo: "Tələbə nümayişi",
        demo: "Agentlik demosu",
        login: "Daxil ol",
        terms: "Şərtlər",
        privacy: "Məxfilik",
      },
    },
    schema: {
      articleName: "Elmify Azərbaycandan olan namizədlər üçün təqaüdlü magistratura uyğunluğunu necə yoxlayır",
      faqName: "Elmify Magistratura və Təqaüd Müraciətləri üzrə Tez-tez Verilən Suallar (Azərbaycan)",
      educationalUse: "Xaricdə magistratura və təqaüd müraciətlərinin hazırlanması",
      audienceType: "Azərbaycandan və dünyadan magistratura namizədləri və xaricdə təhsil agentlikləri",
      offerDescription: "Erkən giriş dövründə proqram seçimi və sənəd hazırlığı tələbələr üçün pulsuzdur.",
      featureList: [
        "Rəsmi universitet və təqaüd səhifələrinin cümlə səviyyəsində mənbə keçidləri ilə oxunması",
        "Dövlət Proqramı (2022–2028), HTP / Stipendium Hungaricum, Erasmus Mundus, DAAD, Chevening, Swedish Institute, Türkiye Bursları və NL Scholarship üzrə uyğunluq yoxlaması",
        "GPA, bakalavr AKTS kreditləri, IELTS/TOEFL/TestDaF balları, vətəndaşlıq və AZN/EUR/USD büdcəsi üzrə yoxlama (bakalavr dəstəyi tezliklə)",
        "Uydurma fakt olmadan akademik CV, motivasiya məktubu, təqaüd essesi və tövsiyəçi brifinqlərinin hazırlanması",
        "Xaricdə təhsil agentlikləri üçün öz domeni üzərində çoxməsləhətçili iş mühiti",
      ],
    },
  },
  ru: {
    locale: "ru",
    ogLocale: "ru_RU",
    langLabel: "RU",
    metaTitle: "Elmify — Магистратура и стипендии за рубежом (Азербайджан, Европа и Великобритания)",
    metaDescription:
      "Первый запуск в Азербайджане: ИИ Elmify читает официальные страницы университетов и стипендий для магистратуры (MSc, MA, LLM, MRes — бакалавриат скоро), проверяет ваш GPA, кредиты ECTS и баллы IELTS/TOEFL по правилам Госпрограммы (Dövlət Proqramı), HTP, Erasmus Mundus, DAAD и Chevening, и готовит резюме (CV) и мотивационные письма.",
    keywords: [
      "стипендии на обучение за рубежом Азербайджан",
      "Госпрограмма обучения за рубежом Dövlət Proqramı магистратура",
      "стипендия HTP Stipendium Hungaricum Азербайджан",
      "магистратура в Европе со стипендией",
      "стипендия Erasmus Mundus Азербайджан",
      "стипендия DAAD Азербайджан",
      "стипендия Chevening Азербайджан",
      "Swedish Institute SISGP Азербайджан",
      "мотивационное письмо и академическое резюме CV",
    ],
    skipToMain: "Перейти к основному содержанию",
    nav: {
      how: "Как это работает",
      product: "Продукт",
      agencies: "Для агентств",
      faq: "Вопросы",
      login: "Войти",
      signup: "Регистрация",
      homeAria: "Главная страница Elmify",
      langAria: "Выбор языка",
    },
    hero: {
      eyebrow:
        "Запуск в Азербайджане · Магистратура и стипендии (MSc, MA, LLM, MRes) · Бакалавриат скоро",
      h1: "Поступите в магистратуру за рубежом со стипендией",
      body:
        "ИИ Elmify читает официальные страницы университетов и фондов Европы и Великобритании, сверяет ваши оценки, кредиты ECTS, сертификаты IELTS или TOEFL и бюджет с каждым правилом приёма (включая Госпрограмму Азербайджана, HTP и 5 уровней низкоконкурентных грантов), готовит академическое CV, мотивационные письма и брифы для рекомендателей и помогает заполнить портал вуза в вашем браузере.",
      ctaPrimary: "Начать бесплатно",
      ctaStudentDemo: "Демо для студентов",
      ctaSecondary: "Как это работает",
      shotAlt: "Панель студента Elmify: прогресс заявок, следующие шаги и дедлайны",
      shotCaption: "Панель студента на примере кандидата из Баку.",
    },
    how: {
      h2: "Что делает ИИ, а что решаете вы",
      intro:
        "Самая долгая часть поступления на финансируемую программу — чтение сотен страниц университетов и стипендиальных фондов, включая региональные гранты и PDF-регламенты на местных языках. Elmify берёт чтение на себя, показывает 100% официальных источников и помогает заполнить портал в вашем браузере.",
      stages: [
        {
          title: "Читает официальные страницы вузов и нишевых фондов",
          body: "Платформа читает официальные сайты университетов и PDF-регламенты стипендий для программ MSc, MA, LLM и MRes на местных языках и сохраняет точную цитату каждого требования со ссылкой на источник.",
        },
        {
          title: "Сверяет флагманские и скрытые гранты с профилем",
          body: "Ваш средний балл (GPA), кредиты ECTS диплома бакалавра, баллы IELTS или TOEFL, гражданство и бюджет (в AZN, EUR, GBP или USD) проверяются по государственным программам и 5 уровням низкоконкурентных фондов.",
        },
        {
          title: "Готовит CV, письма и тезисы рекомендателям",
          body: "Академическое CV, мотивационные письма, стипендиальные эссе и тезисы для рекомендателей составляются строго из подтверждённых вами фактов. Ничего не используется без вашего одобрения.",
        },
        {
          title: "Заполняет портал в вашем браузере — кнопку Submit жмёте вы",
          body: "Прозрачное браузерное расширение открывается рядом с DreamApply, uni-assist или Studielink, подставляет проверенные ответы и PDF-файлы и останавливается перед кнопкой отправки.",
        },
      ],
      tableHeading: "Уровень 1 — Флагманские государственные стипендии Азербайджана, Европы и Великобритании",
      tableSub: "100% правил отбора привязаны к официальным страницам фондов и университетов",
      tableIntro:
        "Elmify запускается в первую очередь в Азербайджане и сегодня охватывает программы магистратуры (MSc, MA, LLM, MRes), а поддержка бакалавриата появится совсем скоро. Докторантура (PhD) исключена, чтобы проверка кредитов, оценок и опыта работы точно соответствовала вашему уровню.",
      tableHeaders: [
        "Стипендия / Фонд",
        "Уровень программ",
        "Объём финансирования",
        "Проверяемые критерии отбора",
      ],
      rows: [
        {
          funder: "Госпрограмма Азербайджана (Dövlət Proqramı 2022–2028)",
          url: "https://dp.edu.gov.az/",
          scope: "Магистратура по приоритетным направлениям в ведущих вузах мира, Европы и Великобритании",
          funding: "100% стоимости обучения + ежемесячная стипендия + перелёт + медстраховка + виза",
          rules: "Гражданство Азербайджана, оффер (приглашение) от вуза из утверждённого перечня",
        },
        {
          funder: "HTP и Stipendium Hungaricum (Венгрия / Межправительственные)",
          url: "https://htp.edu.az/",
          scope: "Очная магистратура в Венгрии, Китае, Румынии и странах-партнёрах (1,5–2 года)",
          funding: "100% освобождение от оплаты + общежитие или 40 000 HUF/мес + стипендия 43 700 HUF/мес",
          rules: "Двойная подача через htp.edu.az и DreamApply, квота 200 мест для АР в Венгрии, уровень B2/C1",
        },
        {
          funder: "Erasmus Mundus Joint Masters",
          url: "https://erasmus-plus.ec.europa.eu/opportunities/opportunities-for-individuals/students/erasmus-mundus-joint-masters",
          scope: "Совместная магистратура MSc / MA в 2–4 вузах Европы (120 ECTS)",
          funding: "100% покрытие обучения + стипендия €1,400/мес до 24 месяцев",
          rules: "Диплом бакалавра 180 ECTS, IELTS 6.5–7.0, правило 12 месяцев проживания",
        },
        {
          funder: "Учебные стипендии DAAD",
          url: "https://www.daad.de/en/Studying-in-Germany/scholarships/",
          scope: "Очная магистратура в государственных вузах Германии (1–2 года)",
          funding: "€934/мес + медицинская страховка + дорожная субсидия из Азербайджана",
          rules: "Диплом бакалавра не старше 6 лет, IELTS 6.5 или TestDaF TDN 4",
        },
        {
          funder: "Swedish Institute (SISGP)",
          url: "https://si.se/en/apply/scholarships/swedish-institute-scholarships-for-global-professionals/",
          scope: "Англоязычная магистратура MSc / MA в Швеции (1 или 2 года)",
          funding: "100% оплаты вузу + 12 000 SEK/мес + 15 000 SEK грант на перелёт",
          rules: "Гражданство Азербайджана (в списке SISGP), от 3 000 часов опыта работы и лидерства",
        },
        {
          funder: "Стипендии Chevening",
          url: "https://www.chevening.org/scholarships/",
          scope: "Годичная магистратура в любом университете Великобритании",
          funding: "100% обучения в UK + £1,378–£1,690/мес + перелёт туда-обратно из Баку",
          rules: "От 2 800 часов (2 лет) опыта работы, выбор 3 подходящих программ в UK",
        },
        {
          funder: "NL Scholarship",
          url: "https://www.studyinnl.org/finances/nl-scholarship",
          scope: "Исследовательская или прикладная магистратура в Нидерландах",
          funding: "Грант €5,000 на первый год (совмещается со скидками факультетов)",
          rules: "Гражданство вне ЕЭЗ, первое зачисление в нидерландский университет",
        },
      ],
      hiddenHeading: "Уровень 2 — За пределами известных названий: 5 низкоконкурентных слоёв финансирования в вашей подборке",
      hiddenSub: "Поиск в 53 странах на национальных языках и в официальных PDF-регламентах вузов",
      hiddenIntro:
        "Большинство абитуриентов в Баку подают только на 6 известных программ выше. Поисковое ядро Elmify открывает 1 400+ проверенных грантов в пяти глубинных слоях финансирования, где конкурс в разы ниже — напрямую сверяя их с вашим транскриптом и профилем.",
      hiddenLayers: [
        {
          badge: "Маршрут · Автоматически при зачислении",
          title: "1. Автоматические стипендии и факультетские скидки (tuition waivers)",
          examples:
            "Скидки на обучение €5,000–€16,500/год и факультетские стипендии €8,000–€12,000/год, которые присуждаются автоматически вместе с оффером в магистратуру — без отдельного стипендиального эссе.",
          howFound:
            "Открываются в вашей персональной подборке после сверки дисциплин и кредитов ECTS вашего диплома с регламентами факультетов.",
        },
        {
          badge: "Слой · Региональные гранты",
          title: "2. Региональные и социальные гранты по доходу семьи",
          examples:
            "100% освобождение от оплаты обучения + бесплатное общежитие + ежедневное питание в кампусе + €6,000–€7,000/год наличными от региональных ведомств Европы.",
          howFound:
            "Рассчитываются по доходу вашей семьи и городу обучения, где семьи из Азербайджана обычно проходят по максимальной категории выплат.",
        },
        {
          badge: "Слой · Региональные блоки и банки",
          title: "3. Стипендии региональных блоков и банков развития",
          examples:
            "Полное покрытие обучения + стипендия €3,000/семестр + оплата перелёта по международным квотам для граждан стран Восточного партнёрства и развивающихся государств.",
          howFound:
            "Подбираются строго под аккредитованные магистерские программы, где гражданство Азербайджана входит в целевую квоту.",
        },
        {
          badge: "Слой · Фонды на местных языках",
          title: "4. Неанглоязычные частные, общественные и благотворительные фонды",
          examples:
            "Ежемесячные стипендии €934/мес + медицинская страховка + семейные надбавки от европейских и региональных фондов, публикующих конкурсы только на немецком, французском, итальянском, нидерландском или турецком языках.",
          howFound:
            "Находятся нашим многоязычным поисковым ядром и сопоставляются с вашей специальностью, средним баллом и профилем.",
        },
        {
          badge: "Слой · PDF-регламенты кафедр",
          title: "5. Оплачиваемые позиции ассистентов (RA/TA) и гранты на переезд",
          examples:
            "Оплачиваемые позиции исследовательских и учебных ассистентов (RA/TA с ежемесячной зарплатой и снятием оплаты за обучение), освобождение от пошлин и субсидии €500–€1,500 на переезд внутри 40-страничных PDF-приказов.",
          howFound:
            "Извлекаются построчно из официальных PDF-положений кафедр и привязываются напрямую к карточке подходящей программы.",
        },
      ],
      extensionPreview: {
        badge: "Шаг 04 · Прозрачное браузерное расширение (Co-Pilot)",
        heading: "Как наше расширение заполняет портал вуза — останавливаясь перед кнопкой Submit",
        sub: "Никакой закрытый бот не входит в порталы от вашего имени. Вы сами открываете официальный портал университета в своём браузере, а боковая панель Elmify подставляет проверенные данные прямо у вас на глазах.",
        portalTitle: "Официальный портал приёмной комиссии (DreamApply / uni-assist / Studielink)",
        portalUrl: "https://apply.university-portal.eu/masters/application/step-3",
        portalFields: [
          {
            label: "Диплом бакалавра и кредиты ECTS",
            value: "Бакинский государственный университет · BSc Химия · 240 ECTS · GPA 91.4 / 100",
            status: "Заполнено из проверенного транскрипта",
            tone: "ok",
          },
          {
            label: "Сертификат владения английским языком",
            value: "IELTS Academic · Общий балл 7.0 (Listening 7.5, Reading 7.0, Writing 6.5, Speaking 7.0)",
            status: "Заполнено из проверенного сертификата",
            tone: "ok",
          },
          {
            label: "Прикреплённые PDF-документы",
            value: "CV_Aysel_MSc_Chemistry.pdf · Motivation_Letter_IdEx_Approved.pdf",
            status: "Прикреплены 2 одобренных PDF из вашего пакета",
            tone: "ok",
          },
          {
            label: "Специальный вопрос портала: Приоритетная лабораторная ротация",
            value: "Ожидает вашего выбора: Гетерогенный катализ или Синтез полимеров",
            status: "Отмечено расширением — требуется ваше решение",
            tone: "warn",
          },
        ],
        submitLabel: "Отправить итоговую заявку в университет",
        submitGuard: "Расширение останавливается здесь — нажать Submit можете только вы",
        sidePanelTitle: "Браузерное расширение Elmify",
        sidePanelStatus: "Подключено к вашему пакету MSc Chemistry",
        sidePanelItems: [
          "14 полей портала сопоставлены и заполнены из подтверждённого профиля",
          "2 одобренных консультантом PDF-файла прикреплены (CV и мотивационное письмо)",
          "1 нестандартный вопрос портала выделен жёлтым для вашего ответа",
          "Пароли от порталов не сохраняются · Полный журнал действий в кабинете",
        ],
        sidePanelNote: "Вы проверяете каждое поле на экране и сами нажимаете кнопку отправки.",
      },
      closingNote: "Кнопку отправки в портале вуза нажимаете вы сами в своём браузере. Elmify никогда не отправляет заявки без вас.",
    },
    product: {
      h2: "Всё для ваших заявок — в одном месте",
      intro: "Это реальные экраны самого продукта.",
      cells: [
        {
          title: "Программы, сгруппированные по финансирующей стипендии",
          body: "Dövlət Proqramı, HTP / Stipendium Hungaricum, Erasmus Mundus, DAAD, Chevening, Swedish Institute и гранты вузов — с покрытием обучения, ежемесячной стипендией и дедлайнами.",
          alt: "Карточки подходящих программ, сгруппированные по финансирующему фонду",
        },
        {
          title: "Единая доска для всех заявок",
          body: "Отслеживайте каждый дедлайн университета и стипендии от этапа «К старту» до «Решения».",
          alt: "Доска Мои заявки с колонками по этапам поступления",
        },
        {
          title: "Транскрипт, CV и письма в одном месте",
          body: "Загрузите транскрипт бакалавра, приложение к диплому, CV и языковые сертификаты один раз. Сразу видно, чего ещё не хватает для каждого портала.",
          alt: "Страница документов с областью загрузки и карточками файлов",
        },
        {
          title: "Ваш консультант — рядом с каждой заявкой",
          body: "Если вы работаете с образовательным агентством в Баку или онлайн, переписка и проверка документов находятся прямо внутри карточки заявки.",
          alt: "Переписка студента с консультантом по документам",
        },
      ],
    },
    agencies: {
      h2: "Управляйте образовательным агентством на Elmify",
      body: "Создано для образовательных агентств в Азербайджане и регионе. Консультанты ведут доску каждого студента на вашем домене, а студенты всегда видят следующий шаг.",
      cta: "Запросить демо для агентства",
      points: [
        ["Ваш домен", "Студенты регистрируются и входят на собственном веб-адресе вашего агентства."],
        ["Ваша команда", "Назначайте консультантов и сразу видьте, кто кого ждёт по документам."],
        ["Ваши заявки", "Запросы от агентств и записи студентов разделены на странице руководителя."],
        ["Пилот 30 дней", "Запустите 30-дневный white-label пилот на 10 студентов (100% зачитывается в годовой тариф)."],
      ],
    },
    faq: {
      h2: "Частые вопросы",
      intro: "Остались вопросы? Задайте их на демо-встрече.",
      items: [
        [
          "Доступен ли Elmify в Азербайджане и бесплатна ли платформа для студентов?",
          "Да. Elmify в первую очередь запускается в Азербайджане на азербайджанском, английском и русском языках с поддержкой расчёта бюджета пошлин в AZN, EUR, GBP и USD. Создание аккаунта, загрузка транскрипта и CV, а также подбор программ и стипендий бесплатны в период раннего доступа.",
        ],
        [
          "Какие страны, стипендии и программы вы охватываете?",
          "Мы охватываем англоязычные и национальные программы магистратуры в Европе и Великобритании в связке с Госпрограммой Азербайджана (Dövlət Proqramı 2022–2028), межправительственными стипендиями (HTP / Stipendium Hungaricum), Erasmus Mundus Joint Masters, DAAD, Swedish Institute (SISGP), Chevening, Türkiye Bursları, NL Scholarship, а также 5 слоями низкоконкурентного финансирования (автоматические скидки факультетов, региональные гранты по доходу семьи, фонды региональных блоков, неанглоязычные частные фонды и позиции RA/TA).",
        ],
        [
          "Поддерживает ли Elmify программы бакалавриата или PhD?",
          "Программы магистратуры (MSc, MA, LLM, MRes) и магистерские стипендии полностью работают уже сегодня, а поддержка бакалавриата будет добавлена совсем скоро. Докторантура (PhD) и постдокторские программы не поддерживаются.",
        ],
        [
          "Выдумывает ли ИИ правила или факты?",
          "Нет. Каждое требование вуза или стипендии ведёт по прямой ссылке на точное предложение на официальном сайте университета или фонда. Ваше CV, мотивационные письма и эссе строятся исключительно на фактах, подтверждённых вами из транскрипта и анкеты.",
        ],
        [
          "Как Elmify готовит CV, мотивационное письмо и брифы для рекомендателей?",
          "После подтверждения ваших академических фактов Elmify формирует академическое CV, адаптированное под программу мотивационное письмо, стипендиальные эссе и отдельные тезисы для каждого рекомендателя, чтобы письма преподавателей не повторяли друг друга.",
        ],
        [
          "Отправляете ли вы заявки вместо меня?",
          "Нет. Вы остаётесь в своём браузере и сами нажимаете кнопку отправки на официальном портале вуза или стипендии. Наше прозрачное браузерное расширение открывается рядом с DreamApply, uni-assist или Studielink, заполняет проверенные поля и прикрепляет одобренные PDF-файлы, останавливаясь перед кнопкой Submit.",
        ],
        [
          "Что происходит с моими данными?",
          "Ваши транскрипты, CV и ответы анкеты используются исключительно для подбора программ и подготовки ваших документов. Вы можете экспортировать файлы или полностью удалить аккаунт и документы в разделе Настройки в любой момент.",
        ],
      ],
    },
    closing: {
      h2: "Заполнение профиля занимает десять минут",
      body: "Первая подборка по флагманским и низкоконкурентным стипендиям будет готова сразу после завершения.",
      ctaPrimary: "Начать бесплатно",
      ctaStudentDemo: "Демо для студентов",
      ctaSecondary: "Войти",
    },
    footer: {
      updatedLabel: "Обновлено",
      updatedDateText: "Ноябрь 2026",
      links: {
        how: "Как это работает",
        about: "О платформе и источники",
        agencies: "Для агентств",
        studentDemo: "Демо для студентов",
        demo: "Демо для агентств",
        login: "Войти",
        terms: "Условия",
        privacy: "Конфиденциальность",
      },
    },
    schema: {
      articleName: "Как Elmify проверяет соответствие требованиям магистратуры и стипендий для кандидатов из Азербайджана",
      faqName: "Частые вопросы о поступлении в магистратуру и стипендиях с Elmify (Азербайджан, Европа и UK)",
      educationalUse: "Подготовка заявок на программы магистратуры и международные стипендии",
      audienceType: "Кандидаты в магистратуру и образовательные агентства в Азербайджане и по всему миру",
      offerDescription: "Бесплатно в период раннего доступа для подбора программ и подготовки документов.",
      featureList: [
        "Чтение официальных страниц вузов и стипендий со ссылками на каждое предложение-источник",
        "Проверка критериев Госпрограммы Азербайджана (Dövlət Proqramı 2022–2028), HTP / Stipendium Hungaricum, Erasmus Mundus, DAAD, Chevening, Swedish Institute, Türkiye Bursları и NL Scholarship",
        "Сверка GPA, кредитов ECTS бакалавра, баллов IELTS/TOEFL/TestDaF, гражданства и бюджета в AZN/EUR/USD (поддержка бакалавриата скоро)",
        "Подготовка академического CV, мотивационных писем, эссе и брифов для рекомендателей без выдуманных фактов",
        "White-label рабочее пространство для образовательных агентств в Азербайджане и за рубежом",
      ],
    },
  },
};
