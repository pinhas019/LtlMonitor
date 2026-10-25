# Supervisor talk (10 minutes, plain words)

`talk.pdf` is the deck: 15 slides (Beamer, Madrid, 14pt, Noto Sans), one picture each: the
problem, background (runtime monitoring, LTL), the idea (stages), the model behind it (a
POMDP, and what the monitor computes today), the method, the test bed, Experiments 1 and 2, the
deadline and unanticipated-fault results, what we learned, and what is left to do.

Rebuild with LuaLaTeX (the preamble uses fontspec and babel's `bidi`/`onchar`). On Ubuntu:
`texlive-latex-recommended texlive-latex-extra texlive-luatex texlive-lang-english
fonts-noto-core`.

    cd docs/talk && lualatex talk.tex && lualatex talk.tex

The two bar charts come from `tools/charts.py` (values from `docs/e1b_ros/results.md`,
produced by `sim/e1/summarize_e1.py`); the screenshots are from the live demo page
(`python3 run.py`). Slide 9's times are one demo run, and it says so.
