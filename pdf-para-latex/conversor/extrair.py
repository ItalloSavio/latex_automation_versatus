"""Etapa 1 — lê o PDF e devolve o que está desenhado em cada página.

Só lê PDF digital (com texto de verdade). Todas as medidas em pontos PostScript (bp),
origem no canto superior esquerdo, y crescendo para baixo — o sistema do PyMuPDF.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import fitz  # PyMuPDF

_PESOS = {"extralight": 200, "light": 300, "regular": 400, "medium": 500,
          "semibold": 600, "bold": 700, "black": 900}
_ESTILO_FONTE = re.compile(r"(extralight|light|regular|medium|semibold|bold|black)?(italic|it)?$")


def _hex(cor) -> str | None:
    if cor is None:
        return None
    if isinstance(cor, int):
        return "%06X" % cor
    return "%02X%02X%02X" % tuple(int(round(v * 255)) for v in cor[:3])


def familia_peso_italico(nome_fonte: str) -> tuple[str, int, bool]:
    """'ABCDEF+SourceSans3-SemiBoldIt' -> ('SourceSans3', 600, True)."""
    nome = nome_fonte.split("+")[-1]
    familia, _, estilo = nome.partition("-")
    m = _ESTILO_FONTE.match(estilo.lower()) if estilo else None
    if not m:
        return familia, 400, "italic" in estilo.lower()
    return familia, _PESOS.get(m.group(1) or "regular", 400), bool(m.group(2))


@dataclass
class Trecho:
    texto: str
    fonte: str          # nome completo da fonte no PDF
    familia: str
    peso: int
    italico: bool
    tamanho: float
    cor: str            # hex sem '#'
    x0: float
    x1: float
    base: float         # linha de base (y da origem)
    sobrescrito: bool = False
    chars: list = field(default_factory=list)   # (caractere, x da origem)


@dataclass
class Linha:
    trechos: list[Trecho]
    x0: float
    y0: float
    x1: float
    y1: float
    base: float
    tamanho: float
    pagina: int
    marcador: dict | None = None   # preenchido na análise

    @property
    def texto(self) -> str:
        return "".join(t.texto for t in self.trechos)


@dataclass
class Forma:
    x0: float
    y0: float
    x1: float
    y1: float
    preenchimento: str | None
    traco: str | None
    espessura: float | None
    itens: list = field(default_factory=list)
    opacidade: float = 1.0

    @property
    def largura(self):
        return self.x1 - self.x0

    @property
    def altura(self):
        return self.y1 - self.y0

    @property
    def retangulo_simples(self) -> bool:
        return len(self.itens) == 1 and self.itens[0][0] in ("re", "qu")


@dataclass
class Imagem:
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass
class Pagina:
    numero: int
    largura: float
    altura: float
    linhas: list[Linha]
    formas: list[Forma]
    imagens: list[Imagem]


class MedidorDeTexto:
    """Mede a largura natural de um texto com a própria fonte embutida no PDF."""

    def __init__(self, doc: fitz.Document):
        self._fontes: dict[str, fitz.Font] = {}
        for pagina in doc:
            for xref, _ext, _tipo, nome, *_ in pagina.get_fonts(full=True):
                chave = nome.split("+")[-1]
                if chave in self._fontes:
                    continue
                try:
                    buf = doc.extract_font(xref)[3]
                    if buf:
                        self._fontes[chave] = fitz.Font(fontbuffer=buf)
                except Exception:
                    pass

        self._cache: dict = {}

    def largura(self, texto: str, fonte: str, tamanho: float) -> float | None:
        chave = (texto, fonte, tamanho)
        if chave in self._cache:
            return self._cache[chave]
        f = self._fontes.get(fonte.split("+")[-1])
        valor = None
        if f is not None:
            try:
                valor = f.text_length(texto, fontsize=tamanho)
            except Exception:
                valor = None
        self._cache[chave] = valor
        return valor


def _linha(spans_brutos, numero_pagina, bbox) -> Linha | None:
    trechos = []
    for s in spans_brutos:
        texto = "".join(c["c"] for c in s["chars"])
        if not texto:
            continue
        familia, peso, italico = familia_peso_italico(s["font"])
        if s["flags"] & 2:
            italico = True
        trechos.append(Trecho(
            texto=texto, fonte=s["font"], familia=familia, peso=peso, italico=italico,
            tamanho=round(s["size"], 2), cor=_hex(s["color"]),
            x0=s["bbox"][0], x1=s["bbox"][2], base=s["origin"][1],
            chars=[(c["c"], c["origin"][0]) for c in s["chars"]]))
    if not trechos or not "".join(t.texto for t in trechos).strip():
        return None
    # corpo dominante: o tamanho com mais caracteres entre os trechos grandes
    maior = max(t.tamanho for t in trechos)
    dominantes = [t for t in trechos if t.tamanho >= 0.8 * maior and t.texto.strip()] or trechos
    contagem: dict[float, int] = {}
    for t in dominantes:
        contagem[t.tamanho] = contagem.get(t.tamanho, 0) + len(t.texto)
    tamanho = max(contagem, key=contagem.get)
    base = max(t.base for t in trechos if t.tamanho == tamanho)
    for t in trechos:
        if t.tamanho < 0.8 * tamanho and t.base < base - 0.15 * tamanho:
            t.sobrescrito = True
    # espaços nas pontas não contam para a extensão da linha
    visiveis = [t for t in trechos if t.texto.strip()] or trechos
    return Linha(trechos=trechos, x0=min(t.x0 for t in visiveis), x1=max(t.x1 for t in visiveis),
                 y0=bbox[1], y1=bbox[3], base=base, tamanho=tamanho, pagina=numero_pagina)


def extrair(caminho: str) -> tuple[list[Pagina], MedidorDeTexto, fitz.Document]:
    doc = fitz.open(caminho)
    paginas = []
    for i, pg in enumerate(doc):
        numero = i + 1
        linhas = []
        for bloco in pg.get_text("rawdict")["blocks"]:
            for ln in bloco.get("lines", []):
                linha = _linha(ln["spans"], numero, ln["bbox"])
                if linha:
                    linhas.append(linha)
        formas = []
        for d in pg.get_drawings():
            r = d["rect"]
            # fundo branco da página inteira não é desenho
            if r.width >= pg.rect.width - 1 and r.height >= pg.rect.height - 1:
                continue
            if r.width < 0.2 and r.height < 0.2:
                continue
            formas.append(Forma(r.x0, r.y0, r.x1, r.y1, _hex(d.get("fill")), _hex(d.get("color")),
                                d.get("width"), d.get("items", []), d.get("fill_opacity") or 1.0))
        imagens = [Imagem(*info["bbox"]) for info in pg.get_image_info()]
        paginas.append(Pagina(numero, pg.rect.width, pg.rect.height, linhas, formas, imagens))
    return paginas, MedidorDeTexto(doc), doc
