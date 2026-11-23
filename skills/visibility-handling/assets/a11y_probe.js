// Accessibility and page-speed probe for the built-in browser.
// Run it with javascript_tool on each page. It finds what axe-core skips
// or what needs computed styles, plus a few axe basics so it still helps
// when a Content-Security-Policy blocks axe. It moves focus to each
// control to read its focus style, then puts focus back; nothing else
// on the page changes.
//
// Every finding is a lead for the agent to confirm in the browser, not a
// verdict: a heuristic can be wrong, and a clean result is not
// "accessible" (keyboard, names, zoom and screen reader passes remain).
(async () => {
  const MAX_ELEMENTS = 3000;
  const MAX_FOCUS_CHECKS = 200;
  const MAX_EXAMPLES = 3;
  const MIN_TARGET_PX = 24;
  const NATIVE_CONTROLS = "a[href], button, input, select, textarea, summary, label, details, audio[controls], video[controls]";
  const FOCUSABLE = "a[href], button, input:not([type=hidden]), select, textarea, summary, [tabindex], [contenteditable=true]";
  const PERSONAL_FIELD = /(^|[-_ ])(e-?mail|phone|tel|mobile|name|first-?name|last-?name|address|street|city|zip|postal|postcode|country)($|[-_ ])/i;

  const findings = [];

  function describe(element) {
    let text = element.tagName.toLowerCase();
    if (element.id) {
      text += "#" + element.id;
    } else if (element.classList.length > 0) {
      text += "." + element.classList[0];
    }
    const words = (element.textContent || "").replace(/\s+/g, " ").trim().slice(0, 40);
    if (words) {
      text += ` "${words}"`;
    }
    return text;
  }

  function report(rule, wcag, level, what, elements) {
    if (elements.length === 0) {
      return;
    }
    findings.push({
      rule: rule,
      wcag: wcag,
      level: level,
      what: what,
      count: elements.length,
      examples: elements.slice(0, MAX_EXAMPLES).map(describe),
    });
  }

  function isHidden(element) {
    if (element.closest("[aria-hidden=true], [hidden]")) {
      return true;
    }
    // Inside a display:none parent the element's own style looks shown.
    if (element.checkVisibility && !element.checkVisibility()) {
      return true;
    }
    const style = getComputedStyle(element);
    return style.display === "none" || style.visibility === "hidden";
  }

  function visible(selector) {
    const found = [];
    for (const element of document.querySelectorAll(selector)) {
      if (!isHidden(element)) {
        found.push(element);
      }
    }
    return found;
  }

  function textOfIds(ids) {
    let text = "";
    for (const id of ids.split(/\s+/)) {
      const target = document.getElementById(id);
      if (target) {
        text += " " + target.textContent;
      }
    }
    return text.trim();
  }

  // A rough accessible name: enough to spot controls that have none.
  function accessibleName(element) {
    const labelledBy = element.getAttribute("aria-labelledby");
    if (labelledBy && textOfIds(labelledBy)) {
      return textOfIds(labelledBy);
    }
    const ariaLabel = (element.getAttribute("aria-label") || "").trim();
    if (ariaLabel) {
      return ariaLabel;
    }
    if (element.labels && element.labels.length > 0) {
      for (const label of element.labels) {
        if (label.textContent.trim()) {
          return label.textContent.trim();
        }
      }
    }
    const tag = element.tagName.toLowerCase();
    const type = (element.getAttribute("type") || "").toLowerCase();
    if (tag === "input" && ["submit", "button", "reset"].includes(type)) {
      return (element.value || "").trim();
    }
    if (tag === "input" && type === "image") {
      return (element.getAttribute("alt") || "").trim();
    }
    if (!["input", "select", "textarea"].includes(tag)) {
      let text = (element.textContent || "").trim();
      for (const image of element.querySelectorAll("img[alt]")) {
        text += " " + image.getAttribute("alt");
      }
      if (text.trim()) {
        return text.trim();
      }
    }
    return (element.getAttribute("title") || "").trim();
  }

  function hasLabel(field) {
    if (field.labels && field.labels.length > 0) {
      return true;
    }
    if (field.getAttribute("aria-label") || field.getAttribute("aria-labelledby")) {
      return true;
    }
    return false;
  }

  function isLinkInSentence(element) {
    if (element.tagName !== "A" || getComputedStyle(element).display !== "inline") {
      return false;
    }
    const parent = element.parentElement;
    if (!parent) {
      return false;
    }
    // In a sentence: the parent has its own words next to the link.
    for (const node of parent.childNodes) {
      if (node.nodeType === Node.TEXT_NODE && node.textContent.trim()) {
        return true;
      }
    }
    return false;
  }

  // 3.1.1 Language of Page
  if (!document.documentElement.getAttribute("lang")) {
    report("no-lang", "3.1.1", "major", "the <html> element has no lang", [document.documentElement]);
  }

  // 1.1.1 Non-text Content
  const imagesWithoutAlt = [];
  const imagesWithFileNameAlt = [];
  for (const image of visible("img")) {
    const role = image.getAttribute("role");
    if (role === "presentation" || role === "none") {
      continue;
    }
    const alt = image.getAttribute("alt");
    if (alt === null) {
      imagesWithoutAlt.push(image);
    } else if (/\.(png|jpe?g|gif|webp|svg|avif)$/i.test(alt.trim())) {
      imagesWithFileNameAlt.push(image);
    }
  }
  report("img-no-alt", "1.1.1", "major", "images with no alt attribute", imagesWithoutAlt);
  report("img-file-name-alt", "1.1.1", "minor", "alt text is a file name", imagesWithFileNameAlt);

  // 4.1.2 Name, Role, Value: controls with no name
  const nameless = [];
  const controls = visible("a[href], button, input:not([type=hidden]), select, textarea, [role=button], [role=link]");
  for (const control of controls) {
    // A field with only a placeholder is reported by its own rule below.
    if (control.hasAttribute("placeholder")) {
      continue;
    }
    if (!accessibleName(control)) {
      nameless.push(control);
    }
  }
  report("control-no-name", "4.1.2", "major", "controls a screen reader announces with no name", nameless);

  // 3.3.2 Labels or Instructions: a placeholder is not a label
  const placeholderOnly = [];
  for (const field of visible("input[placeholder], textarea[placeholder]")) {
    if (!hasLabel(field)) {
      placeholderOnly.push(field);
    }
  }
  report("placeholder-only-label", "3.3.2", "major", "fields whose only label is a placeholder", placeholderOnly);

  // 2.1.1 Keyboard and 4.1.2: things that look clickable but are not controls
  const fakeControls = [];
  let checked = 0;
  for (const element of document.body.querySelectorAll("*")) {
    checked += 1;
    if (checked > MAX_ELEMENTS) {
      break;
    }
    if (element.closest(NATIVE_CONTROLS) || element.hasAttribute("role") || element.hasAttribute("tabindex")) {
      continue;
    }
    const clickable = element.hasAttribute("onclick") || getComputedStyle(element).cursor === "pointer";
    if (!clickable || isHidden(element)) {
      continue;
    }
    // Report only the outermost element, not every child that inherits the cursor.
    const parent = element.parentElement;
    if (parent && !parent.hasAttribute("onclick") && getComputedStyle(parent).cursor === "pointer") {
      continue;
    }
    fakeControls.push(element);
  }
  report("fake-control", "2.1.1, 4.1.2", "major", "clickable elements that are not buttons or links (no keyboard, no role)", fakeControls);

  // 2.4.3 Focus Order
  const positiveTabindex = [];
  for (const element of document.querySelectorAll("[tabindex]")) {
    if (parseInt(element.getAttribute("tabindex"), 10) > 0) {
      positiveTabindex.push(element);
    }
  }
  report("positive-tabindex", "2.4.3", "minor", "positive tabindex breaks the natural focus order", positiveTabindex);

  // 2.4.7 Focus Visible: compare each control's style before and after focus
  const STYLE_KEYS = ["outlineStyle", "outlineWidth", "outlineColor", "boxShadow", "borderColor", "backgroundColor", "color", "textDecorationLine"];
  const noFocusStyle = [];
  let focusChecked = 0;
  let focusBlocked = 0;
  let focusRingOff = 0;
  const startFocus = document.activeElement;
  for (const element of visible(FOCUSABLE).slice(0, MAX_FOCUS_CHECKS)) {
    if (element.disabled || element.getAttribute("tabindex") === "-1") {
      continue;
    }
    const before = getComputedStyle(element);
    const saved = {};
    for (const key of STYLE_KEYS) {
      saved[key] = before[key];
    }
    element.focus({ preventScroll: true });
    // Without window focus, :focus styles never apply, so nothing can be judged.
    if (document.activeElement !== element) {
      continue;
    }
    if (!element.matches(":focus")) {
      focusBlocked += 1;
      element.blur();
      continue;
    }
    // After a mouse click the browser shows no :focus-visible style for
    // focus moved by script, so a missing ring here proves nothing.
    if (!element.matches(":focus-visible")) {
      focusRingOff += 1;
      element.blur();
      continue;
    }
    focusChecked += 1;
    const after = getComputedStyle(element);
    let changed = after.outlineStyle !== "none" && after.outlineWidth !== "0px";
    for (const key of STYLE_KEYS) {
      if (after[key] !== saved[key]) {
        changed = true;
      }
    }
    if (!changed) {
      noFocusStyle.push(element);
    }
    element.blur();
  }
  if (startFocus && startFocus.focus) {
    startFocus.focus({ preventScroll: true });
  }
  report("focus-not-visible", "2.4.7", "major", "controls that look the same when focused (confirm with Tab)", noFocusStyle);
  const notChecked = [];
  if (focusBlocked > 0 && focusChecked === 0) {
    notChecked.push("focus-not-visible: the page window has no focus; click the page and run again, or Tab through by hand");
  }
  if (focusRingOff > 0) {
    notChecked.push(`focus-not-visible: ${focusRingOff} control(s) skipped, the browser hides focus rings after a mouse click; press Tab once in the page and run again, or Tab through by hand`);
  }

  // 2.5.8 Target Size (Minimum). Exempt: links inside a sentence, and
  // fields and checkboxes the browser sizes itself, so they are skipped.
  const smallTargets = [];
  const TARGETS = "a[href], button, [role=button], [role=link], input[type=submit], input[type=button], input[type=image]";
  for (const element of visible(TARGETS)) {
    const box = element.getBoundingClientRect();
    if (box.width >= MIN_TARGET_PX && box.height >= MIN_TARGET_PX) {
      continue;
    }
    if (!isLinkInSentence(element)) {
      smallTargets.push(element);
    }
  }
  report("small-target", "2.5.8", "minor", `targets under ${MIN_TARGET_PX}x${MIN_TARGET_PX} px (fine if spaced 24 px apart)`, smallTargets);

  // 1.3.1 Info and Relationships: headings and landmarks
  const outline = [];
  const skipped = [];
  let lastLevel = 0;
  for (const heading of visible("h1, h2, h3, h4, h5, h6")) {
    const level = parseInt(heading.tagName.slice(1), 10);
    outline.push(`h${level} ${heading.textContent.replace(/\s+/g, " ").trim().slice(0, 60)}`);
    if (lastLevel > 0 && level > lastLevel + 1) {
      skipped.push(heading);
    }
    lastLevel = level;
  }
  report("heading-skip", "1.3.1", "minor", "heading levels skip (h2 then h4)", skipped);
  if (document.querySelectorAll("main, [role=main]").length === 0) {
    report("no-main", "1.3.1", "minor", "no <main> landmark; screen reader users cannot jump to the content", [document.body]);
  }

  // 1.3.5 Identify Input Purpose
  const noAutocomplete = [];
  for (const field of visible("input")) {
    const type = (field.getAttribute("type") || "text").toLowerCase();
    const hint = `${field.name || ""} ${field.id || ""}`;
    const personal = type === "email" || type === "tel" || PERSONAL_FIELD.test(hint);
    if (personal && !field.hasAttribute("autocomplete")) {
      noAutocomplete.push(field);
    }
  }
  report("no-autocomplete", "1.3.5", "minor", "personal fields with no autocomplete", noAutocomplete);

  // 3.3.8 Accessible Authentication: paste must work in password fields
  report("paste-blocked", "3.3.8", "major", "password fields that block paste", visible("input[type=password][onpaste]"));

  // 1.4.2 Audio Control and 2.2.2 Pause, Stop, Hide
  const autoplaySound = [];
  const autoplayMotion = [];
  for (const media of document.querySelectorAll("video[autoplay], audio[autoplay]")) {
    if (!media.muted) {
      autoplaySound.push(media);
    } else if (!media.hasAttribute("controls")) {
      autoplayMotion.push(media);
    }
  }
  report("autoplay-sound", "1.4.2", "major", "media that plays sound on its own", autoplaySound);
  report("autoplay-no-pause", "2.2.2", "minor", "autoplaying video with no controls (needs a pause if over 5 s)", autoplayMotion);

  // 2.3.3 / 2.2.2: animation with no prefers-reduced-motion rule
  let animated = 0;
  checked = 0;
  for (const element of document.querySelectorAll("*")) {
    checked += 1;
    if (checked > MAX_ELEMENTS) {
      break;
    }
    if (getComputedStyle(element).animationName !== "none") {
      animated += 1;
    }
  }
  let reducedMotionRule = false;
  let unreadableSheets = 0;
  for (const sheet of document.styleSheets) {
    let rules;
    try {
      rules = sheet.cssRules;
    } catch (error) {
      unreadableSheets += 1;
      continue;
    }
    for (const rule of rules) {
      if (rule.media && /prefers-reduced-motion/.test(rule.media.mediaText)) {
        reducedMotionRule = true;
      }
    }
  }
  if (animated > 0 && !reducedMotionRule) {
    report("no-reduced-motion", "2.3.3", "minor", `${animated} animated element(s) and no prefers-reduced-motion rule`, [document.body]);
  }

  // Core Web Vitals in the lab: LCP and CLS (INP needs real users)
  const vitals = { lcpMs: null, cls: null, note: "lab values on this machine; INP needs real users" };
  try {
    const lcpEntries = performance.getEntriesByType("largest-contentful-paint");
    if (lcpEntries.length > 0) {
      vitals.lcpMs = Math.round(lcpEntries[lcpEntries.length - 1].startTime);
    }
  } catch (error) {
    // Older browsers have no buffered LCP entries.
  }
  vitals.cls = await new Promise((resolve) => {
    let total = 0;
    try {
      const observer = new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) {
          if (!entry.hadRecentInput) {
            total += entry.value;
          }
        }
      });
      observer.observe({ type: "layout-shift", buffered: true });
      setTimeout(() => {
        observer.disconnect();
        resolve(Math.round(total * 1000) / 1000);
      }, 200);
    } catch (error) {
      resolve(null);
    }
  });
  if (vitals.lcpMs !== null && vitals.lcpMs > 2500) {
    report("slow-lcp", "CWV", "minor", `LCP ${vitals.lcpMs} ms is over 2500 ms`, [document.body]);
  }
  if (vitals.cls !== null && vitals.cls > 0.1) {
    report("layout-shift", "CWV", "minor", `CLS ${vitals.cls} is over 0.1`, [document.body]);
  }

  return {
    url: location.href,
    findings: findings,
    notChecked: notChecked,
    headings: outline,
    vitals: vitals,
    stylesheetsNotRead: unreadableSheets,
  };
})();
