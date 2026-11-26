"use strict";

// A SiteDocument (as served by GET /v1/projects/{id}/site) that exercises every section type.

const ph = (label, extra = {}) => ({ width: 1200, height: 600, bg_hex: "1d3557", text_hex: "f1faee", label, ...extra });
let n = 0;
const sec = (section_id, type, content, image_placeholder = null) =>
  ({ section_id, type, content, image_placeholder, image_prompts: [], content_hash: `hash${++n}` });

const cards = (...titles) => titles.map((t) => ({ title: t, description: `${t} described in a sentence or two.` }));

const LIGHT = { primary: "#1d3557", secondary: "#457b9d", accent: "#e76f51", background: "#ffffff", surface: "#f1f5f9", text: "#0f172a" };
const DARK = { primary: "#0B3D2E", secondary: "#1F5C47", accent: "#C9A227", background: "#0F1A15", surface: "#16251E", text: "#F4F1E8" };

const everySection = [
  sec("home-hero", "hero", {
    heading: "Travel, tailored.", subheading: "Private journeys designed around you.",
    primary_cta: { label: "Plan my trip", href: "/contact" },
  }, ph("Hero")),
  sec("home-features", "features", { heading: "Why Aurum", items: cards("Private", "Local", "Seamless") }),
  sec("home-services", "services", { heading: "Services", items: cards("Design", "Booking") }),
  sec("home-steps", "process_steps", { heading: "How it works", items: cards("Tell us", "We design", "You go", "We support") }),
  sec("home-stats", "stats", { items: [{ value: "120+", label: "Countries" }, { value: "4.9", label: "Rating" }, { value: "15", label: "Years" }] }),
  sec("home-testimonials", "testimonials", {
    heading: "Kind words",
    items: [{ quote: "Flawless from start to finish.", author: "Maya R.", role: "Honeymooner" }, { quote: "Felt like a local.", author: "Tom H." }],
  }),
  sec("home-gallery", "gallery", { heading: "Gallery", items: [{ label: "Alps", caption: "Winter" }, { label: "Kyoto" }, { label: "Lisbon" }] }, ph("Photo", { width: 800, height: 600 })),
  sec("home-pricing", "pricing", {
    heading: "Plans",
    items: [
      { title: "Essential", price: "$2,500", description: "Short breaks.", features: ["Itinerary", "Bookings"] },
      { title: "Signature", price: "$6,000", features: ["Everything in Essential", "Private guide"] },
    ],
  }),
  sec("home-faq", "faq", { heading: "FAQ", items: [{ question: "How far ahead?", answer: "Six weeks is ideal." }, { question: "Insurance?", answer: "We recommend it." }, { question: "Deposits?", answer: "20% to confirm." }] }),
  sec("home-team", "team", { heading: "Team", items: [{ title: "Ava Stone", description: "Founder" }, { title: "Noor Ali", description: "Designer" }] }),
  sec("home-catalog", "catalog", { heading: "Catalog", items: [{ title: "Safari", description: "7 nights", price: "from $4k" }, { title: "Alps", description: "5 nights" }] }),
  sec("home-about", "about", { heading: "Our story", body: "Founded by travellers.\n\nWe still plan every trip ourselves." }, ph("Studio", { width: 800, height: 600 })),
  sec("home-text", "rich_text", { body: "Plain paragraph without a heading." }),
  sec("home-blog", "blog_list", { heading: "Journal" }),
  sec("home-banner", "cta_banner", { heading: "Ready?", subheading: "Tell us where.", primary_cta: { label: "Start", href: "/contact" } }),
];

const site = (colors = LIGHT, overrides = {}) => ({
  version: 1,
  brand_name: "Aurum Escapes",
  tokens: { colors: { ...colors, rationale: "x" }, heading_font: "Playfair Display", body_font: "Inter", base_font_size_px: 16, radius: "md", spacing: "comfortable", style_notes: "", ...overrides },
  navigation: [
    { label: "Home", slug: "/" },
    { label: "About", slug: "/about", children: [{ label: "Team", slug: "/about" }] },
    { label: "Contact", slug: "/contact" },
  ],
  footer_links: ["/about", "/contact"],
  pages: [
    { slug: "/", title: "Home", meta: { title: "Aurum Escapes", description: "Luxury private travel." }, sections: everySection },
    { slug: "/about", title: "About", meta: { title: "About", description: "About us." }, sections: [sec("about-story", "about", { heading: "Story", body: "Hello." })] },
    {
      slug: "/contact", title: "Contact", meta: { title: "Contact", description: "Get in touch." },
      sections: [
        sec("contact-form", "contact_form", { heading: "Talk to us", fields: [{ label: "Name", required: true }, { label: "Email", type: "email" }, { label: "Message", type: "textarea" }, "Phone"] }),
        sec("contact-map", "map_location", { heading: "Visit", address: "1 Gold Street" }, ph("Map")),
      ],
    },
  ],
});

module.exports = { site, everySection, LIGHT, DARK };
