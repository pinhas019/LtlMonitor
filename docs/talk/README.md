# Supervisor talk (10 minutes, plain words)

`talk.pdf` is "Skill progress monitoring": 16 slides plus two pages of references (Beamer, Madrid, 14pt,
Noto Sans), one picture each, in plain words: the problem, related work on two slides (what each line of
work does and what it is missing), background (monitors, LTL), the idea (stages), the
mathematical model (a POMDP, and what the monitor computes today), the method, the test
bed, Experiments 1 and 2, one run second by second, the deadline and unplanned-failure
results, what we learned, and what is left to do.

`talk_notes.pdf` is the same deck with speaker notes: each page shows the slide on the left
and its notes on the right (more detail on every cited paper, what to say, where each
number comes from). Present from it with a two-screen viewer such as `pdfpc`, which shows
the left half to the audience; or just read it beforehand.

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
(`python3 run.py`). Slide 11's times ("One run, second by second") are one demo run, and it says so.
