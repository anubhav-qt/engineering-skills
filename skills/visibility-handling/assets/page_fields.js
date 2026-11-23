// Read the crawler-facing fields of this page as the browser rendered it.
// Run it with the built-in browser's javascript_tool on each page, put the
// results in one JSON list in a file, and pass that file to
// check_pages.py --rendered. It only reads the page.
(() => {
  const collapse = (text) => (text || "").replace(/\s+/g, " ").trim();

  const canonicals = [];
  for (const link of document.querySelectorAll("link[rel]")) {
    const rels = link.getAttribute("rel").toLowerCase().split(/\s+/);
    if (rels.includes("canonical")) {
      canonicals.push((link.getAttribute("href") || "").trim());
    }
  }

  const robots = [];
  for (const meta of document.querySelectorAll("meta[name]")) {
    const name = meta.getAttribute("name").toLowerCase();
    if (name === "robots" || name === "googlebot") {
      robots.push(meta.getAttribute("content") || "");
    }
  }

  let title = "";
  const titleElement = document.querySelector("head title") || document.querySelector("title");
  if (titleElement) {
    title = collapse(titleElement.textContent);
  }

  let textLength = 0;
  if (document.body) {
    textLength = collapse(document.body.innerText).length;
  }

  return {
    url: location.href,
    title: title,
    canonicals: canonicals,
    robots: robots,
    h1Count: document.querySelectorAll("h1").length,
    textLength: textLength,
    lang: document.documentElement.getAttribute("lang") || "",
  };
})();
