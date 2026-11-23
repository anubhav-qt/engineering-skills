// Run axe-core (Deque, MPL-2.0) on this page with the WCAG 2.0 to 2.2
// A and AA rules. Run it with the built-in browser's javascript_tool.
// It adds one script tag that loads a pinned axe-core from jsdelivr.
// If the page's Content-Security-Policy blocks that, it returns
// {blocked: true}: then report "axe: not checked yet", rely on
// a11y_probe.js, and ask the human before touching the CSP.
(async () => {
  const VERSION = "4.14.1";
  const SOURCE = `https://cdn.jsdelivr.net/npm/axe-core@${VERSION}/axe.min.js`;
  const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];
  const MAX_EXAMPLES = 3;

  function load() {
    return new Promise((resolve) => {
      const script = document.createElement("script");
      script.src = SOURCE;
      script.onload = () => resolve("");
      script.onerror = () => resolve("the script did not load (CSP or offline)");
      setTimeout(() => resolve("timed out after 15 s"), 15000);
      document.head.appendChild(script);
    });
  }

  if (!window.axe) {
    const problem = await load();
    if (problem) {
      return { blocked: true, reason: problem, source: SOURCE };
    }
    if (!window.axe) {
      return { blocked: true, reason: "axe is missing after the script loaded", source: SOURCE };
    }
  }

  const result = await window.axe.run(document, {
    runOnly: { type: "tag", values: TAGS },
    resultTypes: ["violations", "incomplete"],
  });

  function summarize(item) {
    return {
      id: item.id,
      impact: item.impact,
      help: item.help,
      count: item.nodes.length,
      examples: item.nodes.slice(0, MAX_EXAMPLES).map((node) => node.target.join(" ")),
    };
  }

  return {
    axe: window.axe.version,
    url: location.href,
    violations: result.violations.map(summarize),
    // Incomplete: axe could not decide. A human or the agent checks these.
    incomplete: result.incomplete.map(summarize),
  };
})();
