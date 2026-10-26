# Supervisor talk (10 minutes, plain words)

`talk.pdf` is "Skill progress monitoring", a 10–12 minute talk: 13 main pages (Beamer, Madrid,
14pt, Noto Sans) in plain words. The main pages cover:
- the problem, and the research question and hypotheses;
- related work as **two streams**: skill description and skill monitoring;
- background (monitors, LTL) and the idea (stages);
- the formal model and the decision view (a POMDP);
- the method, and the fetch-and-deliver experiment;
- whether catching early matters, hypotheses and results, and what is next (MiniGrid → MuJoCo →
  Isaac Sim → real G1).

After the main talk come **backup slides** for questions (from PDF page 15): each related-work
stream in detail, the model's predictions, unplanned failures, one run second by second,
Experiment 1, the test beds, the demo, and the references. The footer counts only the 13 main
pages.

`talk.pptx` is the same talk as a PowerPoint file, to present from:
- **13 visible slides.**
- **Speaker notes** on every slide: short bullets, time checks, and "If asked" answers.
- **14 hidden slides** at the end, never shown unless you jump to them:
  - a divider;
  - related work in detail;
  - model predictions and unplanned failures;
  - one run, second by second;
  - Experiment 1, the test beds and the demo;
  - references;
  - a two-page committee Q&A cheat sheet.

Diagrams and charts are native PowerPoint shapes and charts, so they can be edited.
`make_pptx.js` builds it: `npm install pptxgenjs@3.12.0`, then `node make_pptx.js`.

`formal_model.md` is the mathematical core: research question and hypotheses, definitions
(labelling, spec, phase, monitor state and update, verdict), five properties with proofs and
the measured number each predicts, the POMDP view with the value-of-information argument, and
the assumptions.

`committee_qa.md` is the full committee question bank: how to answer, cards to memorise
(contribution, numbers, definitions), and ~70 likely questions across the whole work
(method, formal soundness, the LLM, experiments and statistics, results, MiniGrid, future,
curveballs) with short, honest answers.

`related_work_prep.md` is the committee prep sheet: every cited paper in more depth (method,
result, gap, how we differ), the platforms, all our numbers in one place, and likely
committee questions with short, honest answers.

`talk_notes.pdf` is the same deck with speaker notes: each page shows the slide on the left
and its notes on the right (more detail on every cited paper, what to say, where each
number comes from). Present from it with a two-screen viewer such as `pdfpc`, which shows
the left half to the audience; or just read it beforehand.

`phone_notes.md` is what to keep on a phone while presenting `talk.pdf`. It has:
- a card of rules and numbers up front;
- one to three bullets per main slide, with the same page numbers;
- time checks;
- the list of backup pages;
- the ten mock-defence questions, two lines each.

`python3 make_phone_notes.py` turns it into `phone_notes.html` (large text, a strip of page
numbers to jump, light and dark, a "Keep screen on" button).

Every citation reads `[article name, authors, year]` and the whole citation is a link to
the article (DOI, PMLR or arXiv). Citations come from the verified entries in `papers/<slug>/bibtex.md`, plus Kaelbling,
Littman & Cassandra 1998 (POMDPs) and Stoller et al. 2011 (monitoring with state
estimation), whose DOIs were confirmed by web search. FailSafe, Foresight and Embedding-TL are cited as arXiv preprints: no venue
is verified for them.

Rebuild with LuaLaTeX (the preamble uses fontspec and babel's `bidi`/`onchar`). On Ubuntu:
`texlive-latex-recommended texlive-latex-extra texlive-luatex texlive-lang-english
fonts-noto-core`.

    cd docs/talk && lualatex talk.tex && lualatex talk.tex                 # slides
    lualatex talk_notes.tex && lualatex talk_notes.tex                     # slides + notes

The two bar charts come from `tools/charts.py` (values from `docs/e1b_ros/results.md`,
produced by `sim/e1/summarize_e1.py`); the screenshots are from the live demo page
(`python3 run.py`). Slide 17's times ("One run, second by second") are one demo run, and it says so.
