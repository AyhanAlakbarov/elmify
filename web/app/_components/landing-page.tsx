import type { Metadata } from "next";
import { GeistSans } from "geist/font/sans";
import { SITE_URL, appLinks } from "./app-links";
import {
  COPY,
  type Locale,
  localeUrl,
  localizedAppLinks,
} from "./i18n";
import { Nav } from "./nav";
import { Hero } from "./hero";
import { Agencies, Closing, Faq, Footer, HowItWorks, Product } from "./sections";

const sameAsUrls = (process.env.NEXT_PUBLIC_SAME_AS_URLS ?? "")
  .split(",")
  .map((u) => u.trim())
  .filter(Boolean);

const ALL_OG_LOCALES = ["en_US", "az_AZ", "ru_RU"] as const;

export function buildLocaleMetadata(locale: Locale): Metadata {
  const copy = COPY[locale];
  const url = localeUrl(locale);

  return {
    metadataBase: new URL(SITE_URL),
    title: copy.metaTitle,
    description: copy.metaDescription,
    applicationName: "Elmify",
    authors: [{ name: "Elmify", url: SITE_URL }],
    creator: "Elmify",
    publisher: "Elmify",
    alternates: {
      canonical: url,
      languages: {
        en: SITE_URL,
        az: `${SITE_URL}/az`,
        ru: `${SITE_URL}/ru`,
        "x-default": SITE_URL,
      },
      types: {
        "application/rss+xml": `${SITE_URL}/feed.xml`,
      },
    },
    keywords: copy.keywords,
    openGraph: {
      title: copy.metaTitle,
      description: copy.metaDescription,
      url,
      type: "website",
      locale: copy.ogLocale,
      alternateLocale: ALL_OG_LOCALES.filter((l) => l !== copy.ogLocale),
      siteName: "Elmify",
      images: [
        {
          url: "/screens/home.png",
          width: 1440,
          height: 900,
          alt: copy.hero.shotAlt,
        },
      ],
    },
    twitter: {
      card: "summary_large_image",
      title: copy.metaTitle,
      description: copy.metaDescription,
      images: ["/screens/home.png"],
    },
    robots: {
      index: true,
      follow: true,
      googleBot: {
        index: true,
        follow: true,
        "max-snippet": -1,
        "max-image-preview": "large",
        "max-video-preview": -1,
      },
    },
  };
}

export function buildLocaleJsonLd(locale: Locale) {
  const copy = COPY[locale];
  const url = localeUrl(locale);
  const app = localizedAppLinks(locale);

  return {
    "@context": "https://schema.org",
    "@graph": [
      {
        "@type": "Organization",
        "@id": `${SITE_URL}/#organization`,
        name: "Elmify",
        url: SITE_URL,
        description: copy.metaDescription,
        email: "hello@elmify.com",
        areaServed: [
          {
            "@type": "Country",
            name: "Azerbaijan",
            identifier: "AZ",
          },
          "Europe",
          "United Kingdom",
          "Worldwide",
        ],
        foundingDate: "2025",
        logo: {
          "@type": "ImageObject",
          url: `${SITE_URL}/screens/home.png`,
        },
        contactPoint: {
          "@type": "ContactPoint",
          contactType: "customer support",
          email: "hello@elmify.com",
          url: appLinks.demo,
          areaServed: "AZ",
          availableLanguage: ["en", "az", "ru"],
        },
        ...(sameAsUrls.length > 0 ? { sameAs: sameAsUrls } : {}),
      },
      {
        "@type": "WebSite",
        "@id": `${url}#website`,
        url,
        name: "Elmify",
        description: copy.metaDescription,
        publisher: { "@id": `${SITE_URL}/#organization` },
        inLanguage: locale,
        availableLanguage: ["en", "az", "ru"],
        datePublished: "2026-10-15",
        dateModified: "2026-11-01",
        potentialAction: {
          "@type": "SearchAction",
          target: {
            "@type": "EntryPoint",
            urlTemplate: `${app.signup}&q={search_term_string}`,
          },
          "query-input": "required name=search_term_string",
        },
      },
      {
        "@type": "SoftwareApplication",
        "@id": `${url}#software`,
        name: "Elmify",
        applicationCategory: "EducationalApplication",
        operatingSystem: "Web",
        url,
        installUrl: app.signup,
        description: copy.metaDescription,
        inLanguage: locale,
        availableLanguage: ["en", "az", "ru"],
        datePublished: "2026-10-15",
        dateModified: "2026-11-01",
        author: {
          "@type": "Organization",
          "@id": `${SITE_URL}/#organization`,
          name: "Elmify",
        },
        publisher: { "@id": `${SITE_URL}/#organization` },
        educationalUse: copy.schema.educationalUse,
        audience: {
          "@type": "EducationalAudience",
          educationalRole: "student",
          audienceType: copy.schema.audienceType,
        },
        offers: {
          "@type": "Offer",
          price: "0",
          priceCurrency: "AZN",
          availability: "https://schema.org/InStock",
          eligibleRegion: {
            "@type": "Country",
            name: "Azerbaijan",
            identifier: "AZ",
          },
          description: copy.schema.offerDescription,
        },
        featureList: copy.schema.featureList,
      },
      {
        "@type": "TechArticle",
        "@id": `${url}#guide`,
        headline: copy.how.h2,
        name: copy.schema.articleName,
        description: copy.metaDescription,
        url: `${url}#how`,
        inLanguage: locale,
        datePublished: "2026-10-15",
        dateModified: "2026-11-01",
        author: {
          "@type": "Organization",
          "@id": `${SITE_URL}/#organization`,
          name: "Elmify",
        },
        publisher: {
          "@type": "Organization",
          "@id": `${SITE_URL}/#organization`,
          name: "Elmify",
        },
        image: `${SITE_URL}/screens/home.png`,
      },
      {
        "@type": "FAQPage",
        "@id": `${url}#faq`,
        name: copy.schema.faqName,
        url: `${url}#faq`,
        description: copy.metaDescription,
        inLanguage: locale,
        datePublished: "2026-10-15",
        dateModified: "2026-11-01",
        author: {
          "@type": "Organization",
          "@id": `${SITE_URL}/#organization`,
          name: "Elmify",
        },
        mainEntity: copy.faq.items.map(([question, answer]) => ({
          "@type": "Question",
          name: question,
          acceptedAnswer: {
            "@type": "Answer",
            text: answer,
          },
        })),
      },
    ],
  };
}

export function LocaleHtmlShell({
  locale,
  children,
}: {
  locale: Locale;
  children: React.ReactNode;
}) {
  const copy = COPY[locale];
  return (
    <html lang={locale} className={GeistSans.variable}>
      <body className="min-h-dvh bg-background text-foreground">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-brand focus:px-4 focus:py-2 focus:text-on-brand"
        >
          {copy.skipToMain}
        </a>
        {children}
      </body>
    </html>
  );
}

export function LandingPage({ locale }: { locale: Locale }) {
  const jsonLd = buildLocaleJsonLd(locale);
  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{
          __html: JSON.stringify(jsonLd).replace(/</g, "\\u003c"),
        }}
      />
      <Nav locale={locale} />
      <main id="main">
        <Hero locale={locale} />
        <HowItWorks locale={locale} />
        <Product locale={locale} />
        <Agencies locale={locale} />
        <Faq locale={locale} />
        <Closing locale={locale} />
      </main>
      <Footer locale={locale} />
    </>
  );
}
