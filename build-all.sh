#!/usr/bin/env bash
set -euo pipefail
mkdir -p build/pdf
latexmk -lualatex -interaction=nonstopmode -halt-on-error -outdir=build/pdf main-standard.tex
latexmk -lualatex -interaction=nonstopmode -halt-on-error -outdir=build/pdf main-print.tex
latexmk -lualatex -interaction=nonstopmode -halt-on-error -outdir=build/pdf main-longread.tex
latexmk -lualatex -interaction=nonstopmode -halt-on-error -outdir=build/pdf main-longread-mono.tex
