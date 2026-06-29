$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force -Path "build/pdf" | Out-Null
latexmk -lualatex -interaction=nonstopmode -halt-on-error -outdir=build/pdf main-standard.tex
latexmk -lualatex -interaction=nonstopmode -halt-on-error -outdir=build/pdf main-print.tex
latexmk -lualatex -interaction=nonstopmode -halt-on-error -outdir=build/pdf main-longread.tex
latexmk -lualatex -interaction=nonstopmode -halt-on-error -outdir=build/pdf main-longread-mono.tex
