# Supervisor talk (10 minutes, plain words)

`talk.pdf` is the deck: 13 slides plus one backup (the POMDP view), one picture each: the problem, background (runtime
monitoring, LTL), the idea (stages), the method, the test bed, Experiments 1 and 2, the
deadline and unanticipated-fault results, what we learned, and what is left to do.

Rebuild (needs TeX Live with Beamer and TikZ; on Ubuntu: `texlive-latex-recommended
texlive-latex-extra texlive-fonts-recommended lmodern`):

    cd docs/talk && pdflatex talk.tex && pdflatex talk.tex

The two bar charts come from `tools/charts.py` (values from `docs/e1b_ros/results.md`,
produced by `sim/e1/summarize_e1.py`); the screenshots are from the live demo page
(`python3 run.py`). Slide 9's times are one demo run, and it says so.
