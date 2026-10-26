// Build talk.pptx: the 13-slide talk, short speaker notes, and hidden backup slides.
//
//   npm install pptxgenjs@3.12.0      (once, anywhere on NODE_PATH)
//   node make_pptx.js                 (run from docs/talk)
//
// Text markup in this file: **bold**, ++key++ (bold, accent colour).
const path = require("path");
const pptxgen = require("pptxgenjs");

const FIG = (f) => path.join(__dirname, "figures", f);
const COL = {
  ink: "1B2430", navy: "14243B", acc: "1F5FAE", bad: "B5503C", mut: "5B6472",
  soft: "EEF1F5", accSoft: "E3ECF8", badSoft: "F6E7E3", good: "E6F2E8", white: "FFFFFF", ice: "CADCFC",
};
const FONT = "Calibri";
const FOOT = "P. N. Aburmad · Skill progress monitoring";

const pres = new pptxgen();
pres.layout = "LAYOUT_16x9"; // 10 x 5.625 in
pres.author = "Pinhas Nehoray Aburmad";
pres.title = "Skill progress monitoring";
pres.theme = { headFontFace: FONT, bodyFontFace: FONT };

// ---------- layouts ----------
const titlePh = (color) => ({
  placeholder: { options: { name: "title", type: "title", x: 0.5, y: 0.28, w: 9, h: 0.7, fontFace: FONT, fontSize: 28, bold: true, color, valign: "middle", margin: 0 }, text: "" },
});
const footer = [
  { text: { text: FOOT, options: { x: 0.5, y: 5.2, w: 6, h: 0.3, fontFace: FONT, fontSize: 9, color: COL.mut, margin: 0 } } },
];
pres.defineSlideMaster({ title: "TITLE", background: { color: COL.navy }, objects: [] });
pres.defineSlideMaster({
  title: "CONTENT", background: { color: COL.white },
  objects: [titlePh(COL.navy), ...footer],
  slideNumber: { x: 9.0, y: 5.2, w: 0.5, h: 0.3, fontFace: FONT, fontSize: 9, color: COL.mut, align: "right" },
});
pres.defineSlideMaster({
  title: "BACKUP", background: { color: COL.white },
  objects: [
    titlePh(COL.navy), ...footer,
    { text: { text: "BACKUP", options: { x: 7.0, y: 5.2, w: 1.8, h: 0.3, fontFace: FONT, fontSize: 9, bold: true, color: COL.bad, align: "right", charSpacing: 2, margin: 0 } } },
  ],
  slideNumber: { x: 9.0, y: 5.2, w: 0.5, h: 0.3, fontFace: FONT, fontSize: 9, color: COL.mut, align: "right" },
});
pres.defineSlideMaster({
  title: "DIVIDER", background: { color: COL.navy },
  objects: [{ placeholder: { options: { name: "title", type: "title", x: 0.5, y: 2.0, w: 9, h: 1.0, fontFace: FONT, fontSize: 36, bold: true, color: COL.white, align: "left", margin: 0 }, text: "" } }],
});

// ---------- helpers ----------
function runs(str, base = {}) {
  // split **bold** and ++key++ into text runs; each "\n" ends a paragraph
  if (str.includes("\n")) {
    const lines = str.split("\n").map((l) => runs(l, base));
    lines.slice(0, -1).forEach((r) => (r[r.length - 1].options.breakLine = true));
    return lines.flat();
  }
  const out = [];
  const re = /(\*\*[^*]+\*\*|\+\+[^+]+\+\+)/g;
  let last = 0, m;
  while ((m = re.exec(str))) {
    if (m.index > last) out.push({ text: str.slice(last, m.index), options: { ...base } });
    const t = m[0];
    if (t.startsWith("**")) out.push({ text: t.slice(2, -2), options: { ...base, bold: true } });
    else out.push({ text: t.slice(2, -2), options: { ...base, bold: true, color: COL.acc } });
    last = m.index + t.length;
  }
  if (last < str.length) out.push({ text: str.slice(last), options: { ...base } });
  return out;
}
function bullets(slide, items, o) {
  const size = o.fontSize || 16;
  const all = [];
  items.forEach((it, i) => {
    // paragraph options (bullet, spacing) go on the text box: on a run they start a new paragraph
    const r = runs(it, { fontSize: size, color: COL.ink });
    if (i < items.length - 1) r[r.length - 1].options.breakLine = true;
    all.push(...r);
  });
  slide.addText(all, {
    x: o.x, y: o.y, w: o.w, h: o.h, fontFace: FONT, valign: o.valign || "top", margin: 0, isTextBox: true, objectName: o.plain ? "lines" : "bullets",
    bullet: o.plain ? false : { indent: 14 }, paraSpaceAfter: o.gap ?? 8,
  });
}
function text(slide, str, o) {
  slide.addText(runs(str, { fontSize: o.fontSize || 16, color: o.color || COL.ink, italic: o.italic }), {
    x: o.x, y: o.y, w: o.w, h: o.h, fontFace: o.fontFace || FONT, align: o.align || "left", valign: o.valign || "top", margin: o.margin ?? 0, isTextBox: true, objectName: o.name || "text",
  });
}
function caption(slide, str, o) { text(slide, str, { ...o, fontSize: 11, color: COL.mut }); }
function box(slide, str, o) {
  const kind = o.kind || "plain";
  const fill = { plain: COL.soft, key: COL.accSoft, bad: COL.badSoft, good: COL.good }[kind];
  const line = { plain: "C5CCD6", key: COL.acc, bad: COL.bad, good: "8DB596" }[kind];
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: o.x, y: o.y, w: o.w, h: o.h, rectRadius: 0.08, fill: { color: fill }, line: { color: line, width: kind === "key" ? 2 : 1 }, objectName: o.name || "box",
  });
  slide.addText(runs(str, { fontSize: o.fontSize || 14, color: o.color || COL.ink }), {
    x: o.x, y: o.y, w: o.w, h: o.h, fontFace: FONT, align: "center", valign: "middle", margin: 4, isTextBox: true, objectName: (o.name || "box") + " text",
  });
}
function arrow(slide, x1, y1, x2, y2, o = {}) {
  slide.addShape(pres.shapes.LINE, {
    x: Math.min(x1, x2), y: Math.min(y1, y2), w: Math.abs(x2 - x1), h: Math.abs(y2 - y1),
    flipH: x2 < x1, flipV: y2 < y1,
    line: { color: o.color || COL.mut, width: o.width || 1.5, dashType: o.dash ? "dash" : "solid", endArrowType: o.noHead ? undefined : "triangle" },
    objectName: o.name || "arrow",
  });
}
function img(slide, file, x, y, w, ratio, name) {
  slide.addImage({ path: FIG(file), x, y, w, h: w / ratio, altText: name, objectName: name });
}
function notes(slide, lines) { slide.addNotes(lines.join("\n")); }
function content(title, master = "CONTENT", section = "Talk") {
  const s = pres.addSlide({ masterName: master, sectionTitle: section });
  s.addText(title, { placeholder: "title" });
  return s;
}

// ================= MAIN TALK =================
pres.addSection({ title: "Talk" });

// 1. Title
{
  const s = pres.addSlide({ masterName: "TITLE", sectionTitle: "Talk" });
  text(s, "Skill progress monitoring", { x: 0.5, y: 1.3, w: 4.9, h: 1.2, fontSize: 36, color: COL.white, name: "title text", valign: "bottom" });
  s.addText("Catching robot failures while they happen", { x: 0.5, y: 2.55, w: 4.9, h: 0.5, fontFace: FONT, fontSize: 18, color: COL.ice, margin: 0, isTextBox: true, objectName: "subtitle" });
  s.addText([
    { text: "Pinhas Nehoray Aburmad", options: { bold: true, breakLine: true } },
    { text: "Ben-Gurion University of the Negev", options: { breakLine: true } },
    { text: "Supervisor: Prof. Ronen Brafman" },
  ], { x: 0.5, y: 3.4, w: 4.9, h: 1.0, fontFace: FONT, fontSize: 14, color: COL.white, margin: 0, isTextBox: true, objectName: "author" });
  img(s, "robot_title.png", 5.6, 1.2, 3.9, 1.597, "Humanoid robot carrying a box");
  notes(s, [
    "- Robots fail in the middle of a task and don't know it.",
    "- I build a watcher that catches the failure when it happens.",
    "- About 10 minutes. Backup slides are hidden at the end.",
  ]);
}

// 2. The problem
{
  const s = content("The problem");
  bullets(s, [
    "Robots often fail **in the middle** of a task.",
    "They often **do not notice**.",
    "They report \"done\" anyway.",
    "++Goal:++ notice the failure ++the moment it happens++.",
  ], { x: 0.5, y: 1.3, w: 4.2, h: 3.3, fontSize: 18, gap: 12 });
  img(s, "robot_false_success.png", 5.0, 1.2, 4.5, 1.6, "Robot reports done while the box is on the floor");
  caption(s, "The robot says \"done\" at the drop-off (blue). The box (yellow) is still on the floor.", { x: 5.0, y: 4.1, w: 4.5, h: 0.6 });
  notes(s, [
    "- Real run: the box slipped, the robot walked on and reported success.",
    "- The robot knows what it commanded, not what happened.",
    "- Finding out at the end is late: the time is gone.",
  ]);
}

// 3. Research question
{
  const s = content("Research question");
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.5, y: 1.15, w: 9, h: 0.75, rectRadius: 0.08, fill: { color: COL.accSoft }, line: { color: COL.accSoft }, objectName: "rq card" });
  text(s, "++RQ:++ Does giving the monitor the **stages** of a skill make it catch failures earlier, and does that improve success?", { x: 0.7, y: 1.15, w: 8.6, h: 0.75, fontSize: 16, valign: "middle", name: "rq" });
  bullets(s, [
    "**H1:** stage failures are caught **earlier**.",
    "**H2:** with a deadline, **more tasks succeed**; without one, no change.",
    "**H3:** it catches failures that **hand-written checks** miss.",
    "**H0:** falls (every stage checks them): **no change**.",
  ], { x: 0.5, y: 2.15, w: 4.5, h: 2.7, fontSize: 15, gap: 8 });
  // timeline
  const y0 = 3.7;
  arrow(s, 5.4, y0, 9.4, y0, { width: 2, name: "time axis" });
  text(s, "time", { x: 8.9, y: y0 + 0.05, w: 0.6, h: 0.3, fontSize: 11, color: COL.mut, align: "right" });
  arrow(s, 5.8, y0 - 0.18, 5.8, y0 + 0.18, { color: COL.bad, width: 3, noHead: true, name: "fault tick" });
  text(s, "fault", { x: 5.4, y: y0 + 0.22, w: 0.8, h: 0.3, fontSize: 12, color: COL.bad, align: "center" });
  arrow(s, 6.3, y0, 6.3, 2.75, { color: COL.acc, width: 3, noHead: true, name: "alarm with stages" });
  text(s, "alarm, with stages", { x: 5.6, y: 2.4, w: 1.6, h: 0.3, fontSize: 12, color: COL.acc, align: "center" });
  arrow(s, 8.0, 2.85, 8.0, 4.25, { dash: true, noHead: true, name: "deadline" });
  text(s, "deadline", { x: 7.5, y: 4.27, w: 1.0, h: 0.3, fontSize: 12, color: COL.mut, align: "center" });
  arrow(s, 9.0, y0, 9.0, 2.75, { color: COL.mut, width: 3, noHead: true, name: "alarm without stages" });
  text(s, "alarm, no stages", { x: 8.0, y: 2.4, w: 1.5, h: 0.3, fontSize: 12, color: COL.mut, align: "right" });
  caption(s, "Re-planning must finish before the deadline.", { x: 5.4, y: 4.6, w: 4.1, h: 0.3 });
  notes(s, [
    "- Do stages catch failures earlier, and does that improve success?",
    "- H1 earlier. H2 more success with a deadline. H3 beats hand-written checks.",
    "- H0, said in advance: falls show no change.",
  ]);
}

// 4. Related work: two streams
{
  const s = content("Related work: two streams");
  text(s, "1. Skill description", { x: 0.5, y: 1.1, w: 3.0, h: 0.35, fontSize: 16, color: COL.acc, align: "center", name: "stream 1 head" });
  text(s, "2. Skill monitoring", { x: 6.5, y: 1.1, w: 3.0, h: 0.35, fontSize: 16, color: COL.acc, align: "center", name: "stream 2 head" });
  const L = ["**Natural language**", "Formal logic (LTL, STL)", "Videos, demos", "Hand-written code"];
  const R = ["**State machines (automata)**", "LLM reasoning", "VLM / learned detectors", "Hybrid (logic + images)"];
  L.forEach((t, i) => box(s, t, { x: 0.5, y: 1.55 + i * 0.62, w: 3.0, h: 0.5, kind: i === 0 ? "key" : "plain", name: "describe " + i }));
  R.forEach((t, i) => box(s, t, { x: 6.5, y: 1.55 + i * 0.62, w: 3.0, h: 0.5, kind: i === 0 ? "key" : "plain", name: "monitor " + i }));
  box(s, "**Our bridge**\nan LLM writes\nLTL rules + stages", { x: 3.85, y: 2.35, w: 2.3, h: 1.05, kind: "key", name: "bridge" });
  arrow(s, 3.5, 1.8, 4.2, 2.35, { color: COL.acc, width: 2 });
  arrow(s, 5.8, 2.35, 6.5, 1.8, { color: COL.acc, width: 2 });
  text(s, "Most work improves **one** stream. ++Ours connects them: the description produces the monitor.++", { x: 0.5, y: 4.2, w: 9, h: 0.6, fontSize: 15 });
  notes(s, [
    "- Two streams: how to describe a skill, and how to watch it run.",
    "- Most work improves one stream.",
    "- Ours: words -> LLM writes stages + rules -> monitor on the robot's sensors.",
    "- Details per paper: hidden backup slides.",
    "TIME CHECK: about 3 minutes here.",
    "If asked \"nothing new\": nl2spec stops at a formula; ROSMonitoring needs hand-written rules. New = generated monitor with stages, on sensors.",
  ]);
}

// 5. Background
{
  const s = content("Background: what is a monitor?");
  bullets(s, [
    "A program that **watches** the robot's messages.",
    "It checks **rules over time**, written in ++LTL++ (a logic of time).",
    "Example: \"**always** stay upright\".",
    "Each rule becomes a small **state machine**.",
    "Problem: \"**eventually** deliver\" **never fails early**.",
  ], { x: 0.5, y: 1.25, w: 4.6, h: 3.6, fontSize: 17, gap: 10 });
  img(s, "aut_fell_over.png", 5.4, 1.6, 4.1, 2.119, "Automaton for always upright");
  caption(s, "\"Always upright\" as a state machine. One fall moves it to state 1 (red), forever.", { x: 5.4, y: 3.65, w: 4.1, h: 0.6 });
  notes(s, [
    "- LTL: G = always, F = eventually. Each rule becomes a small automaton.",
    "- \"Always upright\" fails the moment the robot falls.",
    "- \"Eventually deliver\" can never fail early. That's the gap.",
  ]);
}

// 6. Our idea: stages
{
  const s = content("Our idea: the stages of the task");
  text(s, "**Each stage has its own rules and its own time limit.**", { x: 0.5, y: 1.1, w: 9, h: 0.4, fontSize: 17 });
  const st = [["**Walk to box**\n≤ 45 s", "plain"], ["**Grasp**\n≤ 10 s", "plain"], ["**Carry**\n≤ 60 s\n++must hold box++", "key"], ["**Place**\n≤ 10 s", "plain"], ["**Done**", "good"]];
  const w = 1.55, g = 0.25, x0 = 0.625, y = 1.7, h = 1.05;
  st.forEach(([t, k], i) => {
    box(s, t, { x: x0 + i * (w + g), y, w, h, kind: k, fontSize: 14, name: "stage " + i });
    if (i < 4) arrow(s, x0 + i * (w + g) + w, y + h / 2, x0 + (i + 1) * (w + g), y + h / 2);
  });
  const fy = 3.35;
  box(s, "**Failure:** a rule broke, too slow, or stuck", { x: x0, y: fy, w: 4 * w + 3 * g, h: 0.55, kind: "bad", color: COL.bad, name: "failure" });
  for (let i = 0; i < 4; i++) arrow(s, x0 + i * (w + g) + w / 2, y + h, x0 + i * (w + g) + w / 2, fy, { color: COL.bad, dash: true });
  text(s, "While carrying, the robot **must hold the box**. A drop is caught ++at once++.", { x: 0.5, y: 4.3, w: 9, h: 0.45, fontSize: 16 });
  notes(s, [
    "- Each stage: must-hold rules, a time limit, progress.",
    "- Carry: \"holding\" must stay true, so a drop is caught the next second.",
    "- Without stages you can't say \"must hold\": it is false at the start.",
    "- Written by the LLM from plain words.",
  ]);
}

// 7. Formal model
{
  const s = content("Formal model: specification and monitor");
  bullets(s, [
    "**Labelling:** each tick, σₜ = L(oₜ) ⊆ AP (true facts from sensors).",
    "**Spec:** S = ⟨AP, Φ, M, Π, succ, fail⟩: LTL task rules Φ, safety rules M, phases Π.",
    "**Phase:** πᵢ = ⟨enterᵢ, invᵢ, progᵢ, exitᵢ, Tᵢ, kᵢ⟩.",
    "**Monitor state:** m = ⟨i, c, v, q₁…qₙ⟩ (phase, time in it, progress misses, rule states).",
    "**Update on σ:** every rule steps, qⱼ ← δⱼ(qⱼ, σ); ++fault++ if σ ⊭ invᵢ or c ≥ Tᵢ or v ≥ kᵢ; next phase if σ ⊨ exitᵢ.",
  ], { x: 0.5, y: 1.2, w: 5.4, h: 3.8, fontSize: 14, gap: 9, plain: true });
  const fl = [["robot messages oₜ", "plain"], ["labels σₜ = L(oₜ)", "plain"], ["phase check: invᵢ, Tᵢ, kᵢ\nrules: qⱼ ← δⱼ(qⱼ, σₜ)", "key"], ["verdict → action", "bad"]];
  fl.forEach(([t, k], i) => {
    box(s, t, { x: 6.3, y: 1.2 + i * 0.9, w: 3.2, h: i === 2 ? 0.68 : 0.55, kind: k, fontSize: 13, name: "tick step " + i });
  });
  arrow(s, 7.9, 1.75, 7.9, 2.1); arrow(s, 7.9, 2.65, 7.9, 3.0); arrow(s, 7.9, 3.68, 7.9, 3.9);
  caption(s, "One tick of the monitor (1 Hz).", { x: 6.3, y: 4.55, w: 3.2, h: 0.3, align: "center" });
  notes(s, [
    "- Each second: sensors -> facts -> every rule takes one step.",
    "- A stage fails if a must-hold rule breaks, time runs out, or no progress (3 misses).",
    "- This is exactly what the code does.",
    "If asked \"one automaton?\": no, one monitor: a stage machine beside separate small automata.",
    "If asked \"P1 is a tautology\": yes, by design. The rule exists only with stages. LTL alone 14 s, stages 1 s.",
  ]);
}

// 8. POMDP
{
  const s = content("The decision view: a POMDP");
  bullets(s, [
    "**Hidden s:** what really happens (stage, box held?).",
    "**Seen o:** the robot's messages.",
    "**Belief b:** our best guess of s.",
    "**Action a:** continue, stop, or re-plan.",
  ], { x: 0.5, y: 1.15, w: 5.2, h: 1.7, fontSize: 15, gap: 5 });
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.5, y: 2.95, w: 5.2, h: 0.55, rectRadius: 0.06, fill: { color: COL.soft }, line: { color: COL.soft }, objectName: "formula card" });
  text(s, "b′(s′) ∝ Z(o | s′) · Σₛ T(s′ | s, a) · b(s)", { x: 0.5, y: 2.95, w: 5.2, h: 0.55, fontSize: 17, align: "center", valign: "middle", fontFace: "Cambria", italic: true, name: "belief update" });
  bullets(s, [
    "++Today:++ a point belief (stage + rule states).",
    "++Value of information:++ on time only if latency + recovery ≤ time left.",
  ], { x: 0.5, y: 3.7, w: 5.2, h: 1.1, fontSize: 15, gap: 5, plain: true });
  const cy = [["**Hidden s**\ntrue stage, box held?", "bad"], ["**Seen o**\nnoisy robot messages", "plain"], ["**Belief b**\nstage + rule states", "key"], ["**Action a**\ncontinue / stop / re-plan", "plain"]];
  cy.forEach(([t, k], i) => box(s, t, { x: 6.5, y: 1.1 + i * 0.85, w: 3.0, h: 0.6, kind: k, fontSize: 12, name: "pomdp " + i }));
  ["Z", "update", "decide"].forEach((l, i) => {
    arrow(s, 8.0, 1.7 + i * 0.85, 8.0, 1.95 + i * 0.85);
    text(s, l, { x: 8.1, y: 1.68 + i * 0.85, w: 0.9, h: 0.27, fontSize: 10, color: COL.mut });
  });
  arrow(s, 6.5, 3.95, 6.2, 3.95, { noHead: true }); arrow(s, 6.2, 3.95, 6.2, 1.4, { noHead: true }); arrow(s, 6.2, 1.4, 6.5, 1.4);
  text(s, "T", { x: 5.95, y: 2.55, w: 0.22, h: 0.3, fontSize: 12, color: COL.mut });
  s.addText([{ text: "[Planning and Acting in Partially Observable Stochastic Domains, Kaelbling, Littman, Cassandra, 1998]", options: { hyperlink: { url: "https://doi.org/10.1016/S0004-3702(98)00023-X" }, color: COL.acc } }],
    { x: 6.0, y: 4.55, w: 3.5, h: 0.5, fontFace: FONT, fontSize: 9, margin: 0, isTextBox: true, objectName: "citation" });
  notes(s, [
    "- The stage is hidden state: \"not holding\" is normal while walking, a failure while carrying.",
    "- Early detection helps only with a deadline. Predicted, then measured: 64/36 with, 82/84 without.",
    "- Say first: today the belief is a single point.",
    "TIME CHECK: about 6 minutes here.",
    "If asked \"decorative?\": I don't solve it; it predicted the deadline effect, including no effect without one.",
  ]);
}

// 9. Method
{
  const s = content("Method: how the monitor is built and run");
  const steps = [["**Task in words**\n\"walk to the box, pick it up\"", "plain"], ["**An LLM**\nwrites the stages and rules", "plain"], ["**Spot** (a tool)\nrules → state machines", "plain"], ["**Monitor**\nchecks once a second", "key"], ["**Alarm**\nreport, stop or re-plan", "bad"]];
  const w = 1.62, g = 0.18, x0 = 0.59, y = 1.2, h = 1.1;
  steps.forEach(([t, k], i) => {
    box(s, t, { x: x0 + i * (w + g), y, w, h, kind: k, fontSize: 12, name: "method " + i });
    if (i < 4) arrow(s, x0 + i * (w + g) + w, y + h / 2, x0 + (i + 1) * (w + g), y + h / 2);
  });
  const mx = x0 + 3 * (w + g) + w / 2;
  box(s, "**Robot messages** (ROS 2): position, laser, box position", { x: mx - 1.9, y: 2.75, w: 3.8, h: 0.55, fontSize: 12, name: "robot messages" });
  arrow(s, mx, 2.75, mx, y + h);
  bullets(s, [
    "The rules are written **automatically**, from the task in words.",
    "The monitor uses **only sensors**. It never asks the planner.",
  ], { x: 0.5, y: 3.65, w: 9, h: 1.2, fontSize: 16, gap: 8 });
  notes(s, [
    "- The LLM writes the spec once; it is checked and frozen before any run.",
    "- Checks: it loads, and every fact maps to a real sensor.",
    "- The monitor reads only sensors, never the planner.",
    "If asked \"why trust the LLM?\": checked, readable, frozen. Gap: rules that run but are wrong (3 false alarms of 40). Fix: accept a spec only after clean runs.",
  ]);
}

// 10. Experiment
{
  const s = content("Experiment: fetch and deliver (3360 runs)");
  bullets(s, [
    "G1 humanoid in **MuJoCo**, over ROS 2.",
    "Box dropped: caught after ++1 s++ with stages, 14 s without.",
    "Grasp failed: ++4 s++ vs. 19 s.",
    "Earlier in **all 20** runs.",
  ], { x: 0.5, y: 1.25, w: 3.9, h: 3.4, fontSize: 17, gap: 12 });
  s.addChart(pres.charts.BAR, [
    { name: "with stages", labels: ["Dropped box", "Failed grasp"], values: [1, 4] },
    { name: "without stages", labels: ["Dropped box", "Failed grasp"], values: [14, 19] },
  ], {
    x: 4.6, y: 1.15, w: 4.9, h: 3.3, barDir: "bar", barGrouping: "clustered", barGapWidthPct: 60,
    chartColors: [COL.acc, "B8BFC9"], showValue: true, dataLabelPosition: "outEnd", dataLabelFormatCode: '0" s"',
    dataLabelColor: COL.ink, dataLabelFontSize: 11, dataLabelFontFace: FONT,
    catAxisLabelColor: COL.ink, catAxisLabelFontSize: 12, catAxisLabelFontFace: FONT, catAxisOrientation: "maxMin",
    valAxisHidden: true, valGridLine: { style: "none" }, catGridLine: { style: "none" },
    showLegend: true, legendPos: "b", legendFontSize: 11, legendFontFace: FONT, legendColor: COL.ink,
    showTitle: true, title: "Seconds until the monitor raises the alarm", titleFontSize: 12, titleColor: COL.mut, titleFontFace: FONT,
    objectName: "latency chart",
  });
  caption(s, "Middle value (median) of 20 runs for each failure.", { x: 4.6, y: 4.5, w: 4.9, h: 0.3, align: "center" });
  notes(s, [
    "- G1 in MuJoCo, ROS 2, failures caused on purpose.",
    "- Drop: 1 s vs 14 s, because Carry requires holding.",
    "- Grasp: 4 s vs 19 s. Earlier in all 20 runs.",
    "If asked \"flat is a straw man\": true, an expert could write it in LTL; flat is an ablation. The claim is who writes it: hand-written checks missed 40 of 40.",
    "If asked about statistics: the claim comes from the model; the runs confirm it, 20 of 20. No p-values.",
  ]);
}

// 11. Does catching early matter?
{
  const s = content("Does catching early matter?");
  bullets(s, [
    "No time limit: all monitors ≈ 82–84%.",
    "With a time limit: ++64%++ with stages, 36% without.",
    "Hand-written checks: 81%, but someone must **predict every failure**.",
  ], { x: 0.5, y: 1.25, w: 3.7, h: 3.4, fontSize: 17, gap: 12 });
  s.addChart(pres.charts.BAR, [
    { name: "Delivered on time", labels: ["No monitor", "No stages", "LTL only", "With stages", "Hand-written checks"], values: [34, 36, 36, 64, 81] },
  ], {
    x: 4.4, y: 1.15, w: 5.1, h: 3.3, barDir: "col", barGapWidthPct: 50,
    chartColors: ["B8BFC9", "B8BFC9", "B8BFC9", COL.acc, "3A404A"],
    showValue: true, dataLabelPosition: "outEnd", dataLabelFormatCode: '0"%"', dataLabelColor: COL.ink, dataLabelFontSize: 12, dataLabelFontFace: FONT, dataLabelFontBold: true,
    catAxisLabelColor: COL.ink, catAxisLabelFontSize: 10, catAxisLabelFontFace: FONT,
    valAxisHidden: true, valAxisMaxVal: 100, valAxisMinVal: 0, valGridLine: { style: "none" }, catGridLine: { style: "none" },
    showLegend: false, showTitle: true, title: "Delivered on time (deadline = 1.5 × normal time)", titleFontSize: 12, titleColor: COL.mut, titleFontFace: FONT,
    objectName: "deadline chart",
  });
  caption(s, "160 runs per bar. Early knowledge pays when time matters.", { x: 4.4, y: 4.5, w: 5.1, h: 0.3, align: "center" });
  notes(s, [
    "- No deadline: everyone about 83%, because a late re-plan still works.",
    "- Deadline: 64% vs 36%. LTL alone: 36%.",
    "- Hand-written checks 81%, but only for failures someone foresaw: they missed 40 of 40 unplanned ones.",
  ]);
}

// 12. Hypotheses and results
{
  const s = content("Hypotheses and results");
  const H = (t) => ({ text: t, options: { bold: true, color: COL.white, fill: { color: COL.navy } } });
  const ok = (t) => ({ text: t, options: { bold: true, color: COL.acc } });
  s.addTable([
    [H("Hypothesis"), H("Result"), H("Verdict")],
    ["H1: earlier detection", "drop 1 vs. 14 s; grasp 4 vs. 19 s; 20 of 20 runs", ok("supported")],
    ["H2: more on-time success", "64% vs. 36% with a deadline; 82% vs. 84% without", ok("supported")],
    ["H3: beyond hand-written checks", "40 of 40 missed → 0 of 40", ok("supported")],
    ["H0: falls unchanged", "1 s in every version", "as predicted"],
    ["Not caught", "too slow, detours, skipped pick-up", { text: "reported", options: { bold: true, color: COL.bad } }],
  ], {
    x: 0.5, y: 1.25, w: 9, colW: [2.9, 4.4, 1.7], fontFace: FONT, fontSize: 14, color: COL.ink,
    border: { type: "solid", pt: 0.75, color: "D5DBE3" }, rowH: 0.52, valign: "middle", margin: 0.08, objectName: "results table",
  });
  notes(s, [
    "- Each hypothesis was written down before the run.",
    "- H1, H2, H3 supported. H0 as predicted.",
    "- Missed: slowness, detours. I report them.",
    "TIME CHECK: about 9 minutes here.",
    "If asked \"circular?\": the spec came from words, not the faults; unplanned failures 40 -> 0; I report misses.",
  ]);
}

// 13. To be done
{
  const s = content("To be done");
  const p = [["**Continuous MiniGrid**\n+ MAAOS (done)", "good"], ["**MuJoCo G1**\n(now)", "key"], ["**Isaac Sim**\n(next)", "plain"], ["**Real G1**\n+ TRAV navigation", "plain"]];
  const w = 2.0, g = 0.33;
  p.forEach(([t, k], i) => {
    box(s, t, { x: 0.5 + i * (w + g), y: 1.2, w, h: 0.9, kind: k, fontSize: 14, name: "platform " + i });
    if (i < 3) arrow(s, 0.5 + i * (w + g) + w, 1.65, 0.5 + (i + 1) * (w + g), 1.65);
  });
  bullets(s, [
    "**Fix what we found:** better time limits; progress toward each stage's goal.",
    "**More tests:** more tasks, more rule sets, specs from several LLMs.",
    "**The full POMDP:** camera, real probabilities, best decisions.",
  ], { x: 0.5, y: 2.5, w: 9, h: 1.8, fontSize: 16, gap: 10 });
  caption(s, "**Limits today:** grasp and camera are simulated; thresholds not tuned.", { x: 0.5, y: 4.45, w: 9, h: 0.3 });
  notes(s, [
    "- MiniGrid + MAAOS (done) -> MuJoCo (now) -> Isaac Sim -> real G1.",
    "- Calibrate limits; specs from several LLMs; full POMDP with a camera.",
    "- Stop: \"Thank you. Questions?\"",
    "If asked \"weakest part?\": one spec per skill from one LLM; next, several LLMs. The stages work even if a person writes them.",
    "If asked \"1 Hz is too slow\": not reflex safety; the balance controller handles falls. Task decisions take seconds.",
    "If asked \"who chose 0.3/0.5?\": not the LLM; \"holding\" is in the robot dictionary, once per robot. The LLM's own thresholds aren't calibrated yet.",
  ]);
}

// ================= BACKUP (hidden) =================
pres.addSection({ title: "Backup" });
const backup = (title) => { const s = content(title, "BACKUP", "Backup"); s.hidden = true; return s; };
{
  const s = pres.addSlide({ masterName: "DIVIDER", sectionTitle: "Backup" });
  s.hidden = true;
  s.addText("Backup slides", { placeholder: "title" });
  text(s, "Hidden. Jump here only to answer a question.", { x: 0.5, y: 3.05, w: 9, h: 0.4, fontSize: 16, color: COL.ice });
  notes(s, ["Hidden slides: related work, model predictions, unplanned failures, one run, Experiment 1, test beds, demo, references, Q&A cheat sheet."]);
}

function cites(list) {
  const out = [];
  list.forEach(([label, url], i) => out.push({ text: label, options: url ? { hyperlink: { url }, color: COL.acc, breakLine: i < list.length - 1 } : { breakLine: i < list.length - 1 } }));
  return out;
}
function streamTable(s, rows, rowH) {
  const H = (t) => ({ text: t, options: { bold: true, color: COL.white, fill: { color: COL.navy }, fontSize: 12 } });
  s.addTable([
    [H("Way"), H("Examples"), H("What is missing")],
    ...rows.map(([way, list, gap]) => [{ text: way, options: { bold: true } }, { text: cites(list), options: { fontSize: 9 } }, { text: gap, options: { color: COL.bad } }]),
  ], { x: 0.5, y: 1.15, w: 9, colW: [1.4, 5.8, 1.8], rowH, fontFace: FONT, fontSize: 11, color: COL.ink, border: { type: "solid", pt: 0.75, color: "D5DBE3" }, valign: "middle", margin: 0.06, objectName: "stream table" });
}

// B1. Stream 1
{
  const s = backup("Stream 1: describing a skill");
  streamTable(s, [
    ["Natural language", [
      ["[Grounding Complex Natural Language Commands for Temporal Tasks in Unseen Environments, Liu et al., 2023]", "https://proceedings.mlr.press/v229/liu23d.html"],
      ["[nl2spec: Interactively Translating Unstructured Natural Language to Temporal Logics with LLMs, Cosler et al., 2023]", "https://doi.org/10.1007/978-3-031-37703-7_18"],
      ["[NL2TL: Transforming Natural Languages to Temporal Logics using LLMs, Chen et al., 2023]", "https://arxiv.org/abs/2305.07766"],
      ["[NL2LTL: A Python Package for Converting Natural Language Instructions to LTL Formulas, Fuggitti, Chakraborti, 2023]", "https://doi.org/10.1609/aaai.v37i13.27068"],
      ["[GinSign: Grounding Natural Language Into System Signatures for Temporal Logic Translation, English et al., 2025]", "https://arxiv.org/abs/2512.16770"],
    ], "Made for planning or writing specs; no stages; words must be tied to sensors"],
    ["Formal logic (LTL, STL)", [
      ["[Runtime Verification for LTL and TLTL, Bauer, Leucker, Schallhart, 2011]", "https://doi.org/10.1145/2000799.2000800"],
      ["[RTAMT: Runtime Robustness Monitors with Application to CPS and Robotics, Yamaguchi, Hoxha, Ničković, 2024]", "https://doi.org/10.1007/s10009-023-00720-3"],
    ], "An expert writes every rule; flat rules, no stages"],
    ["Videos / demos", [
      ["[Learning Task Specifications from Demonstrations, Vazquez-Chanlatte et al., 2018]", "https://proceedings.neurips.cc/paper_files/paper/2018/hash/74934548253bcab8490ebd74afed7031-Abstract.html"],
      ["[RoboCLIP: One Demonstration is Enough to Learn Robot Policies, Sontakke et al., 2023]", "https://arxiv.org/abs/2310.07899"],
    ], "Need examples; the result is hard to read or edit"],
    ["Hand-written code", [["Our baseline: checks written inside the robot program", null]], "Someone must foresee every failure"],
  ], [0.32, 1.55, 0.62, 0.62, 0.45]);
  notes(s, [
    "- Words to logic (Lang2LTL, nl2spec, NL2TL): stop at a formula, for planning or spec writing. No stages, nothing running on a robot.",
    "- nl2spec: 16 of 36 alone, 31 of 36 with a human fixing it.",
    "- Logic by experts: precise, but a person writes every rule, and the rules are flat.",
    "- Videos/demos: need examples; hard to read or edit.",
    "- Hand-written checks: 81% on foreseen failures, silent on unforeseen ones (40 of 40).",
  ]);
}

// B2. Stream 2
{
  const s = backup("Stream 2: monitoring a skill");
  streamTable(s, [
    ["State machines", [
      ["[Runtime Verification for LTL and TLTL, Bauer, Leucker, Schallhart, 2011]", "https://doi.org/10.1145/2000799.2000800"],
      ["[ROSMonitoring: A Runtime Verification Framework for ROS, Ferrando et al., 2020]", "https://doi.org/10.1007/978-3-030-63486-5_40"],
      ["[RTAMT: Runtime Robustness Monitors with Application to CPS and Robotics, Yamaguchi, Hoxha, Ničković, 2024]", "https://doi.org/10.1007/s10009-023-00720-3"],
      ["[Reelay: Online Temporal Logic Monitoring Framework, Ulus, 2026]", "https://arxiv.org/abs/2604.22384"],
      ["[Runtime Verification with State Estimation, Stoller et al., 2011]", "https://doi.org/10.1007/978-3-642-29860-8_15"],
    ], "No stages: \"eventually\" waits to the end; rules by hand"],
    ["LLM reasoning", [["[REFLECT: Summarizing Robot Experiences for Failure Explanation and Correction, Liu, Bahety, Song, 2023]", "https://proceedings.mlr.press/v229/liu23g.html"]], "Slow; can be wrong; says \"wrong\", not \"where\""],
    ["VLM / learned", [
      ["[AHA: A Vision-Language-Model for Detecting and Reasoning Over Failures in Robotic Manipulation, Duan et al., 2025]", "https://proceedings.iclr.cc/paper_files/paper/2025/hash/70a06501001e1820fd1eb9ee821302d2-Abstract-Conference.html"],
      ["[FailSafe: Reasoning and Recovery from Failures in VLA Models, Lin et al., 2025]", "https://arxiv.org/abs/2510.01642"],
      ["[Foresight: Failure Detection for Long-Horizon Robotic Manipulation, Zhang et al., 2026]", "https://arxiv.org/abs/2606.23085"],
    ], "Need training data; black box"],
    ["Hybrid", [["[Runtime Monitoring of Perception-Based Autonomous Systems via Embedding Temporal Logic, Kapoor et al., 2026]", "https://arxiv.org/abs/2605.12651"]], "Facts not human-readable"],
  ], [0.32, 1.55, 0.5, 0.9, 0.5]);
  notes(s, [
    "- Bauer 2011: LTL3 (true / false / ?), which we build on. ROSMonitoring, RTAMT: engines for hand-written rules. None knows the task's stages.",
    "- REFLECT explains a failure after the fact. In our MiniGrid pilot a free-text LLM judge gave +0.",
    "- AHA, FailSafe, Foresight: need failure data, give no readable reason.",
    "- Our gap: rules from plain words + task stages + only the robot's own sensors.",
  ]);
}

// B3. Model predictions
{
  const s = backup("Model predictions vs. measurements");
  const H = (t) => ({ text: t, options: { bold: true, color: COL.white, fill: { color: COL.navy } } });
  const k = (t) => ({ text: t, options: { bold: true, color: COL.acc } });
  s.addTable([
    [H("Property (from the model)"), H("Prediction"), H("Measured")],
    ["P1. A broken stage rule fails at the tick it is seen.", "Drop caught at once.", k("1 tick (20 of 20)")],
    ["P2. \"Eventually\" rules have no failing state.", "LTL alone misses the drop until the end.", "LTL only: 14 ticks"],
    ["P3. A stuck stage fails within its time limit.", "Failed grasp caught by Grasp's 10 s.", k("4 ticks vs. 19")],
    ["P4. \"Holding\" can't be a whole-task rule.", "Flat spec sees the drop only at the end.", "Flat: 14 ticks"],
    ["P5. Rules every stage shares are in the flat spec too.", "Falls: no difference.", "1 tick, all versions"],
  ], { x: 0.5, y: 1.15, w: 9, colW: [4.0, 3.0, 2.0], fontFace: FONT, fontSize: 13, color: COL.ink, border: { type: "solid", pt: 0.75, color: "D5DBE3" }, rowH: 0.5, valign: "middle", margin: 0.07, objectName: "predictions table" });
  text(s, "++The results follow from the model++; they are not a lucky outcome.", { x: 0.5, y: 4.4, w: 9, h: 0.4, fontSize: 15 });
  notes(s, [
    "- P1: the rule is checked every tick and fails on the first false tick.",
    "- P2: any unfinished run can still finish, so LTL3 says \"?\". Spot's automaton: 6 states, no rejecting state.",
    "- P3: the time counter grows each tick; the stage fails at its limit.",
    "- Say it yourself: stages add no expressiveness. G(grasped -> (holding U near_dropoff)) is LTL. The LLM writes it because stages ask \"what must stay true here?\"",
  ]);
}

// B4. Unplanned failures
{
  const s = backup("Failures nobody planned for");
  bullets(s, [
    "Box left at the wrong place; robot too close to a wall.",
    "Hand-written checks: **40 of 40** missed.",
    "With our monitor: ++0 of 40++ missed.",
    "Missed by all: too slow, or a long detour.",
  ], { x: 0.5, y: 1.25, w: 4.2, h: 3.4, fontSize: 17, gap: 12 });
  img(s, "robot_wrong_dropoff.png", 5.0, 1.2, 4.5, 1.6, "Box far from the drop-off");
  caption(s, "The box is far from the drop-off (blue), yet the robot says \"done\". Our monitor catches it.", { x: 5.0, y: 4.1, w: 4.5, h: 0.6 });
  notes(s, [
    "- New failures, not covered by the hand-written checks; predictions written before the run.",
    "- Wrong drop-off: the robot's own idea of the drop-off is wrong, so its own check passes.",
    "- 40 of 40 silent -> 0 of 40, no cost elsewhere.",
    "- Missed by everyone: slowness, detours. My \"slow\" prediction was wrong; say so.",
  ]);
}

// B5. One run
{
  const s = backup("One run, second by second");
  bullets(s, [
    "**21.6 s:** the box drops.",
    "**22 s:** the Carry rule breaks. Alarm.",
    "The plain LTL rule still waits: \"maybe later\".",
    "++The stage caught it.++",
  ], { x: 0.5, y: 1.25, w: 3.8, h: 3.4, fontSize: 17, gap: 12 });
  img(s, "automaton_card.png", 4.9, 1.1, 4.6 * 0.95, 1.258, "Live demo stage and automaton view");
  caption(s, "From the live demo (one run). The current stage and state are lit.", { x: 4.9, y: 4.65, w: 4.4, h: 0.3 });
  notes(s, [
    "- One run from the live demo page (seed 0).",
    "- Top: stages, Carry in red. Bottom: the 6-state automaton, still in state 3: it has no failing state.",
    "- The stage catches what LTL alone can't.",
  ]);
}

// B6. Experiment 1
{
  const s = backup("Experiment 1: a short walk (1800 runs)");
  bullets(s, [
    "Stages helped **little** here: 15 vs. 14 of 15 stalls caught.",
    "What mattered: measure progress ++from the robot's sensors++.",
    "Without that: only **1 of 15** caught.",
  ], { x: 0.5, y: 1.25, w: 3.9, h: 3.4, fontSize: 17, gap: 12 });
  img(s, "stall.png", 4.6, 1.3, 4.9, 1.897, "Planner says go while the robot has stopped");
  caption(s, "The planner still says \"go\". The robot has stopped. The monitor sees no progress.", { x: 4.6, y: 3.95, w: 4.9, h: 0.6 });
  notes(s, [
    "- 10 failure types x 20 seeds x 3 versions x 3 reactions = 1800 runs.",
    "- Falls caught in 1-7 s by every version.",
    "- Stalls: with progress check 15/15, flat 14/15, without progress 1/15.",
  ]);
}

// B7. Test bed
{
  const s = backup("Test bed: a humanoid robot in MuJoCo");
  bullets(s, [
    "Unitree **G1** robot in the **MuJoCo** physics simulator.",
    "We ++cause failures on purpose++: push, stall, drop, failed grasp.",
    "We compare the monitor ++with stages++ and ++without++.",
  ], { x: 0.5, y: 1.15, w: 9, h: 1.5, fontSize: 16, gap: 6 });
  ["frame_push_1_walking.png", "frame_push_2_pushed.png", "frame_push_3_down.png"].forEach((f, i) => img(s, f, 0.5 + i * 3.05, 2.75, 2.9, 1.778, "G1 frame " + (i + 1)));
  caption(s, "Walking → pushed → fallen. The simulator knows the truth; the monitor does not.", { x: 0.5, y: 4.45, w: 9, h: 0.3 });
  notes(s, [
    "- The G1 walks with Unitree's own controller.",
    "- \"Without stages\" = same spec, stages merged into one: same facts, same rules.",
    "- Success is judged by the simulator's truth, which the monitor never sees.",
  ]);
}

// B8. MiniGrid + MAAOS
{
  const s = backup("First test bed: continuous MiniGrid + MAAOS");
  bullets(s, [
    "Box pushing in a **continuous MiniGrid**, with **MAAOS** (Fouzi's multi-agent planner; I integrated it).",
    "One agent, or two agents pushing together.",
    "Wrong plan or deadlock: monitor + re-plan ++fixed every seed++.",
    "A free-text **LLM judge: no gain**. It says \"wrong\", not where.",
    "No false alarms on clean runs.",
  ], { x: 0.5, y: 1.2, w: 5.0, h: 3.7, fontSize: 15, gap: 8 });
  const gx = 5.9, gy = 1.4, c = 0.5;
  for (let i = 0; i < 7; i++) for (let j = 0; j < 5; j++) {
    const lava = [[2, 1], [3, 1], [5, 4], [6, 4]].some(([a, b]) => a === i && b === j);
    const goal = i === 6 && j === 0;
    s.addShape(pres.shapes.RECTANGLE, { x: gx + i * c, y: gy + j * c, w: c, h: c, fill: { color: lava ? "D98B78" : goal ? "8DB596" : COL.soft }, line: { color: "C5CCD6", width: 0.5 }, objectName: "cell" });
  }
  s.addShape(pres.shapes.RECTANGLE, { x: gx + 3 * c + 0.08, y: gy + 3 * c + 0.08, w: c - 0.16, h: c - 0.16, fill: { color: "9C7A54" }, line: { color: "9C7A54" }, objectName: "box" });
  [["A", 2], ["B", 4]].forEach(([l, j]) => {
    s.addShape(pres.shapes.OVAL, { x: gx + 1 * c + 0.08, y: gy + (j === 2 ? 3 : 4) * c + 0.08, w: c - 0.16, h: c - 0.16, fill: { color: COL.acc }, line: { color: COL.acc }, objectName: "agent " + l });
    text(s, l, { x: gx + 1 * c, y: gy + (j === 2 ? 3 : 4) * c, w: c, h: c, fontSize: 11, color: COL.white, align: "center", valign: "middle" });
  });
  arrow(s, gx + 2 * c - 0.05, gy + 3.5 * c, gx + 3 * c + 0.05, gy + 3.5 * c, { color: COL.acc, width: 2 });
  caption(s, "Two agents (A, B) push a heavy box to the goal (green) and avoid lava (red).", { x: 5.9, y: 4.0, w: 3.6, h: 0.6 });
  notes(s, [
    "- Pilot, now frozen. Continuous MiniGrid with MAAOS (Fouzi's multi-agent project).",
    "- Corrupted plan: re-plan fixes every seed (+1.00). Deadlock: LTL + re-plan recovers every seed (~45 steps).",
    "- Detect only: +0. Free-text LLM judge: +0. Clean runs: no false alarms.",
    "- Say it yourself: scripted plans, not the live MAAOS planner; one rule I wrote was too strict, and I fixed it.",
  ]);
}

// B9. Demo
{
  const s = backup("What we learned, and the live demo");
  bullets(s, [
    "++Stages catch failures when they happen.++",
    "Early alarms help **when time matters**.",
    "Rules come from words, so failures **nobody planned for** are caught too.",
    "Use the **robot's own sensors**, not the planner.",
  ], { x: 0.5, y: 1.25, w: 4.3, h: 3.4, fontSize: 16, gap: 10 });
  img(s, "demo_page.png", 5.0, 1.2, 4.5, 1.6, "Live demo page");
  caption(s, "Live demo, one command:\ndocker run -p 8080:8080 ghcr.io/pinhas019/ltlmonitor-demo", { x: 5.0, y: 4.1, w: 4.5, h: 0.6 });
  notes(s, [
    "- Demo: open localhost:8080, click \"Dropped object: full spec\", press Pause at 22 s.",
    "- The page draws the stages and the automaton live, from the monitor's own ROS 2 messages.",
  ]);
}

// B10-11. References
const REFS = [
  ["Runtime Verification for LTL and TLTL", "Bauer, Leucker, Schallhart", "2011", "https://doi.org/10.1145/2000799.2000800"],
  ["NL2TL: Transforming Natural Languages to Temporal Logics using Large Language Models", "Chen, Gandhi, Zhang, Fan", "2023", "https://arxiv.org/abs/2305.07766"],
  ["nl2spec: Interactively Translating Unstructured Natural Language to Temporal Logics with Large Language Models", "Cosler, Hahn, Mendoza, et al.", "2023", "https://doi.org/10.1007/978-3-031-37703-7_18"],
  ["AHA: A Vision-Language-Model for Detecting and Reasoning Over Failures in Robotic Manipulation", "Duan et al.", "2025", "https://proceedings.iclr.cc/paper_files/paper/2025/hash/70a06501001e1820fd1eb9ee821302d2-Abstract-Conference.html"],
  ["GinSign: Grounding Natural Language Into System Signatures for Temporal Logic Translation", "English, Walker, Simon, Ewetz", "2025", "https://arxiv.org/abs/2512.16770"],
  ["ROSMonitoring: A Runtime Verification Framework for ROS", "Ferrando, Cardoso, Fisher, Ancona, et al.", "2020", "https://doi.org/10.1007/978-3-030-63486-5_40"],
  ["NL2LTL: A Python Package for Converting Natural Language Instructions to LTL Formulas", "Fuggitti, Chakraborti", "2023", "https://doi.org/10.1609/aaai.v37i13.27068"],
  ["Planning and Acting in Partially Observable Stochastic Domains", "Kaelbling, Littman, Cassandra", "1998", "https://doi.org/10.1016/S0004-3702(98)00023-X"],
  ["Runtime Monitoring of Perception-Based Autonomous Systems via Embedding Temporal Logic", "Kapoor, Hammer, Kapoor, et al.", "2026", "https://arxiv.org/abs/2605.12651"],
  ["FailSafe: Reasoning and Recovery from Failures in Vision-Language-Action Models", "Lin, Duan, Fang, Fox, et al.", "2025", "https://arxiv.org/abs/2510.01642"],
  ["Grounding Complex Natural Language Commands for Temporal Tasks in Unseen Environments", "Liu, Yang, Idrees, Liang, et al.", "2023", "https://proceedings.mlr.press/v229/liu23d.html"],
  ["REFLECT: Summarizing Robot Experiences for Failure Explanation and Correction", "Liu, Bahety, Song", "2023", "https://proceedings.mlr.press/v229/liu23g.html"],
  ["RoboCLIP: One Demonstration is Enough to Learn Robot Policies", "Sontakke, Zhang, Arnold, et al.", "2023", "https://arxiv.org/abs/2310.07899"],
  ["Runtime Verification with State Estimation", "Stoller, Bartocci, Seyster, Grosu, Havelund, Smolka, Zadok", "2011", "https://doi.org/10.1007/978-3-642-29860-8_15"],
  ["Reelay: Online Temporal Logic Monitoring Framework", "Ulus", "2026", "https://arxiv.org/abs/2604.22384"],
  ["Learning Task Specifications from Demonstrations", "Vazquez-Chanlatte, Jha, Tiwari, Ho, Seshia", "2018", "https://proceedings.neurips.cc/paper_files/paper/2018/hash/74934548253bcab8490ebd74afed7031-Abstract.html"],
  ["RTAMT: Runtime Robustness Monitors with Application to CPS and Robotics", "Yamaguchi, Hoxha, Ničković", "2024", "https://doi.org/10.1007/s10009-023-00720-3"],
  ["Foresight: Failure Detection for Long-Horizon Robotic Manipulation with Action-Conditioned World Model Latents", "Zhang, Lu, Wang, Kang, et al.", "2026", "https://arxiv.org/abs/2606.23085"],
];
[REFS.slice(0, 9), REFS.slice(9)].forEach((part, n) => {
  const s = backup(n === 0 ? "References" : "References (cont.)");
  const t = [];
  part.forEach(([a, b, c, u], i) => t.push({ text: `[${a}, ${b}, ${c}]`, options: { hyperlink: { url: u }, color: COL.acc, breakLine: i < part.length - 1, paraSpaceAfter: 5 } }));
  s.addText(t, { x: 0.5, y: 1.1, w: 9, h: 3.9, fontFace: FONT, fontSize: 11, valign: "top", margin: 0, isTextBox: true, objectName: "references" });
  notes(s, ["Every entry is a link. Don't read them out."]);
});

// B12-13. Q&A cheat sheet
const QA = [
  ["\"P1 is a tautology\"", "Yes, by design: the rule exists only with stages. LTL alone 14 s, stages 1 s; deadline 64% vs 36%."],
  ["\"Flat is a straw man\"", "True, an expert could write it in LTL; flat is an ablation. The claim is who writes it: hand-written checks missed 40 of 40."],
  ["\"The POMDP is decorative\"", "I don't solve it. It predicted the deadline effect: 64/36 with a deadline, 82/84 without."],
  ["\"Why trust the LLM?\"", "Checked, readable, frozen before runs. Gap: rules that run but are wrong (3 false alarms of 40). Fix: accept only after clean runs."],
  ["\"Circular experiment?\"", "The spec came from words, not the faults. Unplanned failures 40 → 0. I report misses: slowness, detours."],
  ["\"Statistics?\"", "The claim comes from the model; the runs confirm it, 20 of 20. If pushed: \"clearly significant; it's in my backup notes.\""],
  ["\"Nothing new\"", "New: an LLM-generated monitor with stages, on the robot's sensors. nl2spec stops at a formula; ROSMonitoring needs hand-written rules."],
  ["\"Who chose 0.3 / 0.5?\"", "Not the LLM: \"holding\" is in the robot dictionary, once per robot. The LLM's own thresholds aren't calibrated yet."],
  ["\"1 Hz is too slow\"", "Not reflex safety: the balance controller handles falls. Task decisions take seconds."],
  ["\"Weakest part?\"", "One spec per skill from one LLM; next, several LLMs. The stages work even if a person writes them."],
];
[QA.slice(0, 5), QA.slice(5)].forEach((part, n) => {
  const s = backup(n === 0 ? "Committee questions (1 of 2)" : "Committee questions (2 of 2)");
  const t = [];
  part.forEach(([q, a], i) => {
    t.push({ text: `Q${n * 5 + i + 1}. ${q}`, options: { bold: true, color: COL.navy, breakLine: true } });
    t.push({ text: a, options: { color: COL.ink, breakLine: i < part.length - 1, paraSpaceAfter: 9 } });
  });
  s.addText(t, { x: 0.5, y: 1.1, w: 9, h: 3.95, fontFace: FONT, fontSize: 13, valign: "top", margin: 0, isTextBox: true, objectName: "qa" });
  notes(s, ["Cheat sheet. Hidden: never shown unless you choose to."]);
});

// pptxgenjs writes an <a:pPr> before every run of a rich-text paragraph (the later ones say
// "no bullet" and override the first), and bullets only the first paragraph of a box. Keep only
// each paragraph's first <a:pPr>, then give every paragraph of a "bullets" box its bullet.
const BULLET = (spc) => `<a:pPr marL="177800" indent="-177800">${spc}<a:buSzPct val="100000"/><a:buChar char="&#x2022;"/></a:pPr>`;
const fs = require("fs");
const JSZip = require("jszip");
(async () => {
  const zip = await JSZip.loadAsync(await pres.write({ outputType: "nodebuffer" }));
  for (const f of Object.keys(zip.files).filter((n) => /^ppt\/slides\/slide\d+\.xml$/.test(n))) {
    const xml = (await zip.file(f).async("string")).replace(/<a:p>([\s\S]*?)<\/a:p>/g, (m, inner) => {
      let seen = false;
      return "<a:p>" + inner.replace(/<a:pPr\b[^>]*?(?:\/>|>[\s\S]*?<\/a:pPr>)/g, (t) => (seen ? "" : ((seen = true), t))) + "</a:p>";
    }).replace(/<p:sp>[\s\S]*?<\/p:sp>/g, (sp) => (!sp.includes('name="bullets"') ? sp
      : sp.replace(/<a:pPr indent="0" marL="0">(<a:spcAft>[\s\S]*?<\/a:spcAft>)<a:buNone\/><\/a:pPr>/g, (m, spc) => BULLET(spc))));
    zip.file(f, xml);
  }
  const out = path.join(__dirname, "talk.pptx");
  fs.writeFileSync(out, await zip.generateAsync({ type: "nodebuffer", compression: "DEFLATE" }));
  console.log("wrote " + out);
})();
