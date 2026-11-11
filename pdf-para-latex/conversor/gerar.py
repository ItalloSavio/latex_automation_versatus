"""Etapa 3 — escreve o LaTeX: estilo.sty (o desenho do documento) e <nome>.tex (o conteúdo)."""
from __future__ import annotations

import datetime
import re

from analisar import (Bloco, CaixaEl, ChamadaEl, Documento, FaixaEl, FioEl, ImagemEl, ListaEl,
                      TabelaEl)

# família da fonte no PDF -> como carregar no LaTeX
_FAMILIAS = {
    # default: vira a fonte do documento inteiro; semibold: \textbf é o SemiBold
    "SourceSans3": ("\\RequirePackage[default,semibold]{sourcesanspro}", "SourceSans3"),
    "SourceSansPro": ("\\RequirePackage[default,semibold]{sourcesanspro}", "SourceSans3"),
}
_ARQ_PESO = {200: "ExtraLight", 300: "Light", 400: "Regular", 500: "Medium", 600: "Semibold",
             700: "Bold", 900: "Black"}


def _letterspace(bp_por_letra: float, tamanho: float) -> float:
    """LetterSpace do fontspec é em % do corpo (medido: LetterSpace=10 a 10bp soma 1bp por letra)."""
    return bp_por_letra / tamanho * 100


def n(x: float) -> str:
    """Número curto: 43.50 -> 43.5, 15.00 -> 15."""
    s = f"{x:.2f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


class Gerador:
    def __init__(self, doc: Documento, nome_pdf: str):
        self.doc = doc
        self.nome_pdf = nome_pdf
        self.cores = doc.cores

    def _c(self, texto: str) -> str:
        return re.sub(r"\{COR:([0-9A-F]{6})\}", lambda m: self.cores[m.group(1)], texto)

    def cor(self, hexa: str) -> str:
        return self.cores[hexa]

    # =================================================================
    def estilo_sty(self) -> str:
        d = self.doc
        hoje = datetime.date.today().isoformat()
        out = [
            "% =====================================================================",
            f"%  estilo.sty — o desenho de '{self.nome_pdf}'",
            "%  Gerado pelo conversor pdf-para-latex. Pode editar à vontade: todos os",
            "%  valores foram medidos no PDF original (em bp, a unidade do PDF).",
            "% =====================================================================",
            "\\NeedsTeXFormat{LaTeX2e}",
            f"\\ProvidesPackage{{estilo}}[{hoje.replace('-', '/')} gerado de {self.nome_pdf}]",
            "",
            "% --- Página -----------------------------------------------------------",
            f"\\RequirePackage[paperwidth={n(d.largura)}bp,paperheight={n(d.altura)}bp,margin=0pt,nohead,nofoot]{{geometry}}",
            "",
            "% --- Fonte ------------------------------------------------------------",
        ]
        carga, arquivo_base = _FAMILIAS.get(d.familia, (None, None))
        if carga:
            out.append(carga)
        else:
            out += ["\\RequirePackage{fontspec}", f"\\setmainfont{{{d.familia}}}  % família lida no PDF; confira se está instalada"]
            arquivo_base = d.familia
        out.append("\\RequirePackage{diagramacao}")
        for nome, (peso, italico) in sorted(d.faces_extras.items()):
            arq = f"{arquivo_base}-{_ARQ_PESO.get(peso, 'Regular')}{'It' if italico else ''}.otf"
            out.append(f"\\newfontface\\{nome}{{{arq}}}")
        out += ["", "% --- Cores ------------------------------------------------------------"]
        for hexa, nome in sorted(self.cores.items(), key=lambda kv: kv[1]):
            out.append(f"\\definecolor{{{nome}}}{{HTML}}{{{hexa}}}")

        out += ["", "% --- Escala tipográfica ----------------------------------------------",
                "%  \\definirestilo[espacejamento]{nome}{tamanho}{entrelinha}{peso}{itálico}{cor}{espaço entre dois blocos seguidos}",
                "%  espacejamento: em % do corpo (negativo = letras mais juntas), como o LetterSpace do fontspec.",
                "%  Cada estilo vira um comando: \\corpo{...}, \\secao{...}. Cor diferente: \\secao[branco]{...}"]
        for e in d.estilos:
            peso = {400: "regular", 600: "seminegrito"}.get(e.peso)
            if peso is None:
                peso = "fonte" + {200: "Extraleve", 300: "Leve", 500: "Medio", 700: "Negrito", 900: "Preto"}.get(e.peso, "")
                if e.italico:
                    peso += "Italico"
            esp = f"[{n(_letterspace(e.espacejamento, e.tamanho))}]" if e.espacejamento else ""
            # uma face própria (ex.: fonteLeveItalico) já é itálica: não pede \itshape de novo
            italico = "sim" if e.italico and peso in ("regular", "seminegrito") else "nao"
            out.append(f"\\definirestilo{esp}{{{e.nome}}}{{{n(e.tamanho)}}}{{{n(e.entrelinha)}}}{{{peso}}}"
                       f"{{{italico}}}{{{self.cor(e.cor)}}}{{{n(e.espaco)}}}")

        if d.marcadores:
            out += ["", "% --- Marcadores de lista ----------------------------------------------",
                    "%  \\definirmarcador{nome}{deslocamento a partir da margem}{desenho}"]
            for nome, (desloc, desenho) in d.marcadores.items():
                out.append(f"\\definirmarcador{{{nome}}}{{{n(desloc)}}}{{{self._c(desenho)}}}")
        if d.sobrescrito:
            s = d.sobrescrito
            out += ["", "% --- Sobrescrito (chamada de nota) -----------------------------------",
                    f"\\newcommand\\sobrescrito[1]{{\\raisebox{{{n(s['subida'])}bp}}"
                    f"{{\\fontsize{{{n(s['tamanho'])}bp}}{{{n(s['tamanho'])}bp}}\\selectfont #1}}}}"]
        if d.cabecalho or d.numero_pagina:
            out += ["", "% --- Cabeçalho e número de página (aparecem em todas as páginas) ------"]
        if d.cabecalho:
            q = d.cabecalho
            out.append(f"\\definircabecalho{{{n(q.x)}}}{{{n(q.y)}}}{{{n(q.largura)}}}{{%")
            out += self.elementos(q.elementos, "  ")
            out.append("}")
        if d.numero_pagina:
            p = d.numero_pagina
            out.append(f"\\definirnumeropagina{{{n(p['x'])}}}{{{n(p['base'])}}}{{{p['estilo']}}}"
                       f"{{{self.cor(p['cor'])}}}{{{p['primeira']}}}")
        out += ["", "% --- Imagens -----------------------------------------------------------",
                "%  Coloque o arquivo com o nome do espaço (pdf, png ou jpg) nesta pasta.",
                "\\pastaimagens{../../imagens/}", "", "\\endinput", ""]
        return "\n".join(out)

    # =================================================================
    def documento_tex(self) -> str:
        d = self.doc
        out = [
            "% =====================================================================",
            f"%  Conteúdo de '{self.nome_pdf}' — gerado pelo conversor pdf-para-latex",
            "%  O desenho (fontes, tamanhos, cores) está em estilo.sty.",
            "%  Cada \\begin{coluna}{x}{y}{largura} é um quadro: o texto dentro dele flui",
            "%  e você pode editar à vontade. \\espaco{bp} é a distância até o elemento",
            "%  anterior, medida no original. \\quebra é uma quebra de linha mantida só",
            "%  para ficar idêntico ao original (pode apagar ao reescrever o trecho).",
            "%  \\entrelinha{bp} antes de um elemento troca a entrelinha só dele.",
            "%  Depois de editar, recompile com:",
            "%    python pdf-para-latex/conversor/pdf_para_latex.py <pdf de entrada> --so-compilar",
            "% =====================================================================",
            "\\documentclass{article}",
            "\\usepackage{estilo}",
            "",
            "\\begin{document}",
        ]
        for p in d.paginas:
            out += ["", "%% " + "=" * 68, f"%%  Página {p.numero}", "%% " + "=" * 68, "\\begin{pagina}"]
            for lv in p.livres:
                out.append(f"  \\imagemlivre{{{lv.nome}}}{{{n(lv.x)}}}{{{n(lv.y)}}}{{{n(lv.largura)}}}{{{n(lv.altura)}}}")
            for i, q in enumerate(p.quadros, 1):
                ancora = "[base]" if q.ancora == "base" else ""
                out.append("")
                out.append(f"  % quadro {i}: {self._resumo(q.elementos)}")
                out.append(f"  \\begin{{coluna}}{ancora}{{{n(q.x)}}}{{{n(q.y)}}}{{{n(q.largura)}}}")
                out += self.elementos(q.elementos, "    ")
                out.append("  \\end{coluna}")
            out.append("\\end{pagina}")
        out += ["", "\\end{document}", ""]
        return "\n".join(out)

    @staticmethod
    def _resumo(elementos):
        for e in elementos:
            if isinstance(e, Bloco):
                t = e.linhas[0].texto.strip()
                return f"começa em \"{t[:40]}{'…' if len(t) > 40 else ''}\""
            if isinstance(e, ListaEl):
                return "começa com uma lista"
        tipos = {ImagemEl: "imagem", FioEl: "fio", TabelaEl: "tabela", FaixaEl: "faixa", CaixaEl: "caixa"}
        return "começa com " + tipos.get(type(elementos[0]), "elemento")

    # -----------------------------------------------------------------
    def elementos(self, elementos, ind) -> list[str]:
        out, ant = [], None
        for e in elementos:
            if ant is not None:
                vao = e.topo - ant.fundo
                padrao = ant.estilo.espaco if isinstance(ant, Bloco) and isinstance(e, Bloco) \
                    and ant.estilo is e.estilo else 0.0
                if abs(vao - padrao) >= 0.05:
                    out.append(f"{ind}\\espaco{{{n(vao)}}}")
            out += self.elemento(e, ind)
            ant = e
        return out

    def _texto(self, b: Bloco) -> str:
        t = self._c(b.latex)
        if b.espacejamento is not None:
            t = f"\\espacejado{{{n(_letterspace(b.espacejamento, b.estilo.tamanho))}}}{{{t}}}"
        return t

    def elemento(self, e, ind) -> list[str]:
        L = getattr(e, "entrelinha", None)
        prefixo = [f"{ind}\\entrelinha{{{n(L)}}}"] if L else []
        return prefixo + self._elemento(e, ind)

    def _elemento(self, e, ind) -> list[str]:
        if isinstance(e, Bloco):
            cor = "" if e.cor == e.estilo.cor else f"[{self.cor(e.cor)}]"
            return [f"{ind}\\{e.estilo.nome}{cor}{{{self._texto(e)}}}"]
        if isinstance(e, ListaEl):
            cor = "" if e.cor == e.estilo.cor else f"[{self.cor(e.cor)}]"
            out = [f"{ind}\\begin{{lista}}{cor}{{{e.estilo.nome}}}{{{e.marcador}}}{{{n(e.recuo)}}}{{{n(e.espaco)}}}"]
            out += [f"{ind}  \\item {self._texto(it)}" for it in e.itens]
            out.append(f"{ind}\\end{{lista}}")
            return out
        if isinstance(e, FioEl):
            dx = f"[{n(e.dx)}]" if abs(e.dx) >= 0.05 else ""
            larg = f"[{n(e.largura)}]" if e.largura is not None else ""
            return [f"{ind}\\fio{dx}{{{self.cor(e.cor)}}}{{{n(e.espessura)}}}{larg}"]
        if isinstance(e, ImagemEl):
            dx = f"[{n(e.dx)}]" if abs(e.dx) >= 0.05 else ""
            return [f"{ind}\\imagem{dx}{{{e.nome}}}{{{n(e.largura)}}}{{{n(e.altura)}}}"]
        if isinstance(e, TabelaEl):
            out = [f"{ind}\\begin{{tabela}}{{{e.estilo.nome}}}{{{','.join(n(w) for w in e.larguras)}}}"
                   f"{{{n(e.recuo_um)}}}{{{n(e.recuo)}}}{{{n(e.recuo_dir)}}}"]
            for item in e.sequencia:
                if item[0] == "fio":
                    out.append(f"{ind}  \\fiotabela{{{self.cor(item[1])}}}{{{n(item[2])}}}")
                else:
                    _, acima, abaixo, cels = item
                    out.append(f"{ind}  \\linha{{{n(acima)}}}{{{n(abaixo)}}}{{{' & '.join(self._c(c) for c in cels)}}}")
            out.append(f"{ind}\\end{{tabela}}")
            return out
        if isinstance(e, FaixaEl):
            out = [f"{ind}\\begin{{faixa}}{{{n(e.altura)}}}"]
            for dx, dy, larg, els in e.celulas:
                out.append(f"{ind}  \\celula{{{n(dx)}}}{{{n(dy)}}}{{{n(larg)}}}{{%")
                out += self.elementos(els, ind + "    ")
                out.append(f"{ind}  }}")
            out.append(f"{ind}\\end{{faixa}}")
            return out
        if isinstance(e, CaixaEl):
            out = [f"{ind}\\begin{{caixa}}{{{self.cor(e.cor)}}}{{{n(e.acima)}}}{{{n(e.abaixo)}}}"
                   f"{{{n(e.esquerda)}}}{{{n(e.direita)}}}"]
            out += self.elementos(e.elementos, ind + "  ")
            out.append(f"{ind}\\end{{caixa}}")
            return out
        if isinstance(e, ChamadaEl):
            out = [f"{ind}\\begin{{chamada}}{{{self.cor(e.cor)}}}{{{n(e.espessura)}}}{{{n(e.recuo)}}}"]
            out += self.elementos(e.elementos, ind + "  ")
            out.append(f"{ind}\\end{{chamada}}")
            return out
        raise TypeError(type(e))
