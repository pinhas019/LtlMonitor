# Supervisor talk (10 minutes, plain words)

`talk.pdf` is "Skill progress monitoring": 15 slides plus references (Beamer, Madrid, 14pt,
Noto Sans), one picture each, in plain words: the problem, related work (what each line of
work does and what it is missing), background (monitors, LTL), the idea (stages), the
mathematical model (a POMDP, and what the monitor computes today), the method, the test
bed, Experiments 1 and 2, one run second by second, the deadline and unplanned-failure
results, what we learned, and what is left to do.

Citations come from the verified entries in `papers/<slug>/bibtex.md`, plus Kaelbling,
Littman & Cassandra 1998 (POMDPs) and Stoller et al. 2011 (monitoring with state
estimation). FailSafe, Foresight and Embedding-TL are cited as arXiv preprints: no venue
is verified for them.

Rebuild with LuaLaTeX (the preamble uses fontspec and babel's `bidi`/`onchar`). On Ubuntu:
`texlive-latex-recommended texlive-latex-extra texlive-luatex texlive-lang-english
fonts-noto-core`.

    cd docs/talk && lualatex talk.tex && lualatex talk.tex

The two bar charts come from `tools/charts.py` (values from `docs/e1b_ros/results.md`,
produced by `sim/e1/summarize_e1.py`); the screenshots are from the live demo page
(`python3 run.py`). Slide 11's times ("One run, second by second") are one demo run, and it says so.
