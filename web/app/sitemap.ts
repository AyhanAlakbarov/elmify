import type { MetadataRoute } from "next";
import { SITE_URL } from "./_components/app-links";

export default function sitemap(): MetadataRoute.Sitemap {
  const lastModified = new Date("2026-11-01T00:00:00.000Z");
  const languages = {
    en: SITE_URL,
    az: `${SITE_URL}/az`,
    ru: `${SITE_URL}/ru`,
  };
  return [
    {
      url: SITE_URL,
      lastModified,
      changeFrequency: "weekly",
      priority: 1,
      alternates: { languages },
    },
    {
      url: `${SITE_URL}/az`,
      lastModified,
      changeFrequency: "weekly",
      priority: 1,
      alternates: { languages },
    },
    {
      url: `${SITE_URL}/ru`,
      lastModified,
      changeFrequency: "weekly",
      priority: 1,
      alternates: { languages },
    },
    {
      url: `${SITE_URL}/llms.txt`,
      lastModified,
      changeFrequency: "weekly",
      priority: 0.8,
    },
    {
      url: `${SITE_URL}/llms-full.txt`,
      lastModified,
      changeFrequency: "weekly",
      priority: 0.8,
    },
  ];
}
