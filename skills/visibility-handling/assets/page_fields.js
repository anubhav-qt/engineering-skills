// Read the crawler-facing fields of this page as the browser rendered it.
// Run it with the built-in browser's javascript_tool on each page, put the
// results in one JSON list in a file, and pass that file to
// check_pages.py --rendered. It only reads the page. It first waits for a
// client-rendered app to draw: until the page shows some text and then
// stops changing for half a second, at most 5 seconds.
(async () => {
  const QUIET_MS = 500;
  const MOST_MS = 5000;

  function waitUntilDrawn() {
    return new Promise((resolve) => {
      let quietTimer = null;
      const finish = () => {
        watcher.disconnect();
        clearTimeout(quietTimer);
        clearTimeout(mostTimer);
        resolve();
      };
      // An app still fetching shows an empty root: keep waiting for words.
      const doneIfDrawn = () => {
        if (document.body && document.body.innerText.trim() !== "") {
          finish();
        }
      };
      const restartQuiet = () => {
        clearTimeout(quietTimer);
        quietTimer = setTimeout(doneIfDrawn, QUIET_MS);
      };
      const watcher = new MutationObserver(restartQuiet);
      watcher.observe(document.documentElement, { childList: true, subtree: true, characterData: true, attributes: true });
      const mostTimer = setTimeout(finish, MOST_MS);
      restartQuiet();
    });
  }

  if (document.readyState !== "complete") {
    await new Promise((resolve) => window.addEventListener("load", resolve, { once: true }));
  }
  await waitUntilDrawn();

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
