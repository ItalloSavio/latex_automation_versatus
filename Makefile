LATEXMK=latexmk
ENGINE=-lualatex
OUTDIR=build/pdf

.PHONY: all standard print longread longread-mono clean distclean

all: standard print longread longread-mono

$(OUTDIR):
	mkdir -p $(OUTDIR)

standard: $(OUTDIR)
	$(LATEXMK) $(ENGINE) -interaction=nonstopmode -halt-on-error -outdir=$(OUTDIR) main-standard.tex

print: $(OUTDIR)
	$(LATEXMK) $(ENGINE) -interaction=nonstopmode -halt-on-error -outdir=$(OUTDIR) main-print.tex

longread: $(OUTDIR)
	$(LATEXMK) $(ENGINE) -interaction=nonstopmode -halt-on-error -outdir=$(OUTDIR) main-longread.tex

longread-mono: $(OUTDIR)
	$(LATEXMK) $(ENGINE) -interaction=nonstopmode -halt-on-error -outdir=$(OUTDIR) main-longread-mono.tex

clean:
	$(LATEXMK) -c -outdir=$(OUTDIR) main-standard.tex main-print.tex main-longread.tex main-longread-mono.tex || true

# Removes generated PDFs as well.
distclean: clean
	rm -rf $(OUTDIR)
