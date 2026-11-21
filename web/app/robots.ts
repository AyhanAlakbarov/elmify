import type { MetadataRoute } from "next";
import { SITE_URL } from "./_components/app-links";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: "/",
      },
      {
        userAgent: [
          "Googlebot",
          "Bingbot",
          "YandexBot",
          "OAI-SearchBot",
          "ChatGPT-User",
          "GPTBot",
          "PerplexityBot",
          "ClaudeBot",
          "Claude-SearchBot",
          "Applebot",
          "Google-Extended",
        ],
        allow: ["/", "/az", "/ru", "/llms.txt", "/llms-full.txt", "/.well-known/ai.txt", "/ai/"],
      },
    ],
    sitemap: `${SITE_URL}/sitemap.xml`,
    host: SITE_URL,
  };
}
