"""Etapa 2 — transforma o que está desenhado no PDF numa estrutura de documento.

Saída: estilos (a escala tipográfica), cores, marcadores, cabeçalho e, por página,
QUADROS de conteúdo que flui (colunas) e espaços de imagem em posição fixa.

Modelo vertical de um bloco de texto (o mesmo que diagramacao.sty usa):
    topo  = 1ª linha de base - 0,7 x entrelinha
    fundo = última linha de base + 0,3 x entrelinha
Os espaços entre elementos são medidos com esse modelo; como o LaTeX monta os blocos
com a mesma regra, cada linha de base volta para onde estava no original.
"""
from __future__ import annotations

import colorsys
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from extrair import Forma, Imagem, Linha, MedidorDeTexto, Pagina, Trecho

_MARCADORES_GLIFO = {"•", "▪", "■", "●", "◦", "‣", "–", "·"}
_ALTO = 0.7    # fração da entrelinha acima da linha de base
_BAIXO = 0.3   # fração abaixo
_FOLGA = 0.75  # bp que uma linha pode passar da largura (igual a \dg@folga em diagramacao.sty)


# =====================================================================
#  Modelo de saída
# =====================================================================
@dataclass
class Estilo:
    nome: str
    tamanho: float
    entrelinha: float
    peso: int
    italico: bool
    cor: str = "000000"
    espaco: float = 0.0
    espacejamento: float = 0.0   # bp por letra (negativo = letras mais juntas)


@dataclass
class Elemento:
    topo: float
    fundo: float


@dataclass
class Bloco(Elemento):
    estilo: Estilo
    cor: str
    latex: str
    linhas: list
    marcador: str | None = None
    recuo: float = 0.0
    espacejamento: float | None = None   # só quando difere do estilo
    entrelinha: float | None = None      # só quando difere do estilo


@dataclass
class ListaEl(Elemento):
    estilo: Estilo
    cor: str
    marcador: str
    recuo: float
    espaco: float
    itens: list
    entrelinha: float | None = None


@dataclass
class FioEl(Elemento):
    cor: str
    espessura: float
    dx: float
    largura: float | None


@dataclass
class ImagemEl(Elemento):
    nome: str
    dx: float
    largura: float
    altura: float


@dataclass
class TabelaEl(Elemento):
    estilo: Estilo
    larguras: list
    recuo_um: float
    recuo: float
    recuo_dir: float
    sequencia: list      # ("fio", cor, espessura) | ("linha", acima, abaixo, [latex])
    entrelinha: float | None = None


@dataclass
class FaixaEl(Elemento):
    altura: float
    celulas: list        # (dx, dy, largura, [elementos])


@dataclass
class CaixaEl(Elemento):
    cor: str
    acima: float
    abaixo: float
    esquerda: float
    direita: float
    elementos: list


@dataclass
class ChamadaEl(Elemento):
    cor: str
    espessura: float
    recuo: float
    elementos: list


@dataclass
class Quadro:
    x: float
    y: float
    largura: float
    ancora: str
    elementos: list


@dataclass
class Livre:
    nome: str
    x: float
    y: float
    largura: float
    altura: float


@dataclass
class PaginaModelo:
    numero: int
    quadros: list
    livres: list


@dataclass
class EspacoImagem:
    nome: str
    pagina: int
    x0: float
    y0: float
    x1: float
    y1: float
    tipo: str


@dataclass
class Documento:
    largura: float
    altura: float
    estilos: list
    cores: dict          # hex -> nome
    marcadores: dict     # nome -> definição LaTeX
    cabecalho: Quadro | None
    numero_pagina: dict | None
    paginas: list
    sobrescrito: dict | None
    espacos_imagem: list
    avisos: list
    familia: str = ""
    faces_extras: dict = field(default_factory=dict)   # nome do comando -> arquivo da fonte


# =====================================================================
#  Utilidades
# =====================================================================
def _sobrepoe(a0, a1, b0, b1, folga=0.0):
    return min(a1, b1) - max(a0, b0) > folga


def _moda(valores, passo=0.25):
    if not valores:
        return None
    arred = [round(v / passo) * passo for v in valores]
    return Counter(arred).most_common(1)[0][0]


def _nome_cor(hexa: str) -> str:
    r, g, b = (int(hexa[i:i + 2], 16) / 255 for i in (0, 2, 4))
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    if s < 0.15 or v < 0.15:
        if v >= 0.95:
            return "branco"
        if v <= 0.2:
            return "preto"
        return "cinza" if v <= 0.55 else "cinzaclaro"
    graus = h * 360
    for limite, nome in ((15, "vermelho"), (45, "laranja"), (70, "amarelo"), (160, "verde"),
                         (200, "turquesa"), (260, "azul"), (300, "roxo"), (345, "magenta"),
                         (361, "vermelho")):
        if graus < limite:
            return nome
    return "cor"


def _batizar_cores(hexas) -> dict:
    por_nome = defaultdict(list)
    for h in set(hexas):
        por_nome[_nome_cor(h)].append(h)
    nomes = {}
    for base, lista in por_nome.items():
        # a mais escura fica com o nome; as outras viram "claro", "claro2"...
        lista.sort(key=lambda h: sum(int(h[i:i + 2], 16) for i in (0, 2, 4)))
        for i, h in enumerate(lista):
            nomes[h] = base if i == 0 else base + ("claro" if i == 1 else f"claro{i}")
    return nomes


class _UniaoBusca:
    def __init__(self, n):
        self.pai = list(range(n))

    def achar(self, i):
        while self.pai[i] != i:
            self.pai[i] = self.pai[self.pai[i]]
            i = self.pai[i]
        return i

    def unir(self, a, b):
        self.pai[self.achar(a)] = self.achar(b)


# =====================================================================
#  Itens que participam do corte da página em quadros
# =====================================================================
@dataclass
class _Item:
    tipo: str            # linha | fio | barra | caixa | figura | imagem
    x0: float
    y0: float
    x1: float
    y1: float
    obj: object = None
    filhos: list = field(default_factory=list)   # linhas internas (caixa)
    nome: str = ""


def _item_linha(ln: Linha) -> _Item:
    x0 = ln.marcador["x"] if ln.marcador else ln.x0
    return _Item("linha", x0, ln.y0, ln.x1, ln.y1, ln)


# =====================================================================
#  Análise
# =====================================================================
class Analisador:
    def __init__(self, paginas: list[Pagina], medidor: MedidorDeTexto):
        self.paginas = paginas
        self.medidor = medidor
        self.avisos: list[str] = []
        self.espacos_imagem: list[EspacoImagem] = []
        self.marcadores: dict[tuple, str] = {}
        self.marcadores_def: dict[str, str] = {}
        self.cores_usadas: list[str] = []
        self.sobrescrito = None

    # -----------------------------------------------------------------
    def analisar(self) -> Documento:
        moveis = self._mobiliario()
        por_pagina = []
        for pg in self.paginas:
            por_pagina.append(self._classificar_pagina(pg, moveis))

        linhas_conteudo = [ln for itens, _l in por_pagina for it in itens for ln in self._linhas_do_item(it)]
        linhas_conteudo += moveis["linhas_cabecalho"]
        if moveis["numero"]:
            linhas_conteudo.append(moveis["numero"]["linha"])
        self._definir_estilos(linhas_conteudo)
        self._margens(por_pagina)

        paginas_modelo = []
        for pg, (itens, livres) in zip(self.paginas, por_pagina):
            folhas = self._cortar(itens)
            quadros = [self._quadro(f, folhas, pg) for f in folhas if f]
            paginas_modelo.append(PaginaModelo(pg.numero, quadros, livres))

        cabecalho = None
        if moveis["linhas_cabecalho"]:
            lns = moveis["linhas_cabecalho"]
            x0 = min(l.x0 for l in lns)
            largura = self.margem_dir - x0
            elementos = self._fluxo([_item_linha(l) for l in lns], x0, largura)
            cabecalho = Quadro(x0, elementos[0].topo, largura, "topo", elementos)
        numero = None
        if moveis["numero"]:
            ln = moveis["numero"]["linha"]
            t = ln.trechos[0]
            numero = {"x": ln.x1, "base": ln.base, "estilo": self._estilo_de(t).nome,
                      "cor": self._cor(t.cor), "primeira": moveis["numero"]["primeira"]}

        self._espaco_padrao(paginas_modelo)
        cores = _batizar_cores(self.cores_usadas)
        return Documento(
            largura=self.paginas[0].largura, altura=self.paginas[0].altura,
            estilos=self.estilos, cores=cores,
            marcadores=self.marcadores_def, cabecalho=cabecalho, numero_pagina=numero,
            paginas=paginas_modelo, sobrescrito=self.sobrescrito,
            espacos_imagem=self.espacos_imagem, avisos=self.avisos,
            familia=self.familia, faces_extras=self.faces_extras)

    def _cor(self, hexa):
        self.cores_usadas.append(hexa)
        return hexa

    # -----------------------------------------------------------------
    #  Cabeçalho, rodapé e número de página repetidos
    # -----------------------------------------------------------------
    def _mobiliario(self):
        moveis = {"chaves": set(), "linhas_cabecalho": [], "numero": None, "ids": set()}
        if len(self.paginas) < 2:
            return moveis
        contagem = Counter()
        for pg in self.paginas:
            for ln in {(ln.texto.strip(), round(ln.x0), round(ln.base)) for ln in pg.linhas}:
                contagem[ln] += 1
        repetidas = {k for k, n in contagem.items() if n >= 2 and k[0]}
        primeira_vez = {}
        for pg in self.paginas:
            for ln in pg.linhas:
                k = (ln.texto.strip(), round(ln.x0), round(ln.base))
                if k in repetidas:
                    moveis["ids"].add(id(ln))
                    primeira_vez.setdefault(k, ln)
        moveis["linhas_cabecalho"] = sorted(primeira_vez.values(), key=lambda l: (l.base, l.x0))
        # número de página: um número igual ao da página, sempre no mesmo lugar
        candidatos = defaultdict(list)
        for pg in self.paginas:
            for ln in pg.linhas:
                if ln.texto.strip() == str(pg.numero):
                    candidatos[(round(ln.x1), round(ln.base))].append((pg.numero, ln))
        for _pos, lista in candidatos.items():
            if len(lista) >= 2:
                for _n, ln in lista:
                    moveis["ids"].add(id(ln))
                moveis["numero"] = {"linha": lista[0][1], "primeira": min(n for n, _ in lista)}
                break
        # cabeçalho de topo só; o que se repete embaixo também é cabeçalho para nós
        return moveis

    # -----------------------------------------------------------------
    #  Formas: fios, barras, marcadores, caixas, figuras e grafismos
    # -----------------------------------------------------------------
    def _classificar_pagina(self, pg: Pagina, moveis):
        linhas = [ln for ln in pg.linhas if id(ln) not in moveis["ids"]]
        fios, barras, quadradinhos, graficos = [], [], [], []
        for f in pg.formas:
            cor = f.preenchimento or f.traco
            if cor and f.altura <= 2.0 and f.largura >= 8 and (f.retangulo_simples or len(f.itens) == 1):
                fios.append(f)
            elif f.preenchimento and f.retangulo_simples and f.largura <= 4 and f.altura >= 8:
                barras.append(f)
            elif f.preenchimento and f.retangulo_simples and f.largura <= 6 and f.altura <= 6:
                quadradinhos.append(f)
            else:
                graficos.append(f)

        # marcadores de lista: quadradinho à esquerda do início de uma linha
        for q in quadradinhos:
            cy = (q.y0 + q.y1) / 2
            alvo = None
            for ln in linhas:
                if ln.x0 - 14 <= q.x1 <= ln.x0 - 0.5 and ln.base - 0.9 * ln.tamanho <= cy <= ln.base + 0.1 * ln.tamanho:
                    alvo = ln
                    break
            if alvo and not alvo.marcador:
                alvo.marcador = {"tipo": "quadrado", "cor": self._cor(q.preenchimento), "lado": round(q.largura, 2),
                                 "x": q.x0, "subida": round(alvo.base - q.y1, 2)}
            else:
                graficos.append(q)
        # marcadores de lista: glifo sozinho (•) logo antes de uma linha
        restantes = []
        for ln in linhas:
            if ln.texto.strip() in _MARCADORES_GLIFO and len(ln.texto.strip()) == 1:
                dono = next((o for o in linhas if o is not ln and abs(o.base - ln.base) <= 0.6
                             and 0.5 <= o.x0 - ln.x1 <= 16), None)
                if dono:
                    t = ln.trechos[0]
                    dono.marcador = {"tipo": "glifo", "glifo": ln.texto.strip(), "cor": self._cor(t.cor), "x": ln.x0}
                    continue
            restantes.append(ln)
        linhas = restantes

        # agrupa os desenhos próximos: as partes de um diagrama ficam a menos de ~20bp umas das outras
        perto = 20.0
        uf = _UniaoBusca(len(graficos))
        for i, a in enumerate(graficos):
            for j in range(i + 1, len(graficos)):
                b = graficos[j]
                if _sobrepoe(a.x0 - perto, a.x1 + perto, b.x0, b.x1) and _sobrepoe(a.y0 - perto, a.y1 + perto, b.y0, b.y1):
                    uf.unir(i, j)
        grupos = defaultdict(list)
        for i, f in enumerate(graficos):
            grupos[uf.achar(i)].append(f)

        itens, livres = [], []
        usadas = set()
        cont = Counter()

        def nome(tipo):
            cont[tipo] += 1
            return f"p{pg.numero}-{tipo}-{cont[tipo]}"

        for grupo in sorted(grupos.values(), key=lambda g: min(f.y0 for f in g)):
            x0, y0 = min(f.x0 for f in grupo), min(f.y0 for f in grupo)
            x1, y1 = max(f.x1 for f in grupo), max(f.y1 for f in grupo)
            dentro = [ln for ln in linhas if id(ln) not in usadas
                      and x0 - 1 <= (ln.x0 + ln.x1) / 2 <= x1 + 1 and y0 - 1 <= (ln.y0 + ln.y1) / 2 <= y1 + 1]
            if len(grupo) == 1 and grupo[0].preenchimento and grupo[0].retangulo_simples and dentro:
                f = grupo[0]
                for ln in dentro:
                    usadas.add(id(ln))
                itens.append(_Item("caixa", x0, y0, x1, y1, f, dentro))
                continue
            vaza = x0 < -0.5 or y0 < -0.5 or x1 > pg.largura + 0.5 or y1 > pg.altura + 0.5
            if vaza or not dentro and len(grupo) >= 2 and (x1 - x0) * (y1 - y0) > 2000 and self._fora_do_texto(pg, x0, y0, x1, y1, linhas):
                cx0, cy0 = max(0.0, x0), max(0.0, y0)
                cx1, cy1 = min(pg.largura, x1), min(pg.altura, y1)
                n = nome("grafismo")
                livres.append(Livre(n, round(cx0, 2), round(cy0, 2), round(cx1 - cx0, 2), round(cy1 - cy0, 2)))
                self.espacos_imagem.append(EspacoImagem(n, pg.numero, cx0, cy0, cx1, cy1, "grafismo"))
                continue
            # figura: os desenhos e os rótulos dentro deles (e rótulos centrados logo abaixo/acima)
            capturadas = list(dentro)
            for ln in linhas:
                if id(ln) in usadas or ln in capturadas:
                    continue
                perto = (y1 <= ln.y0 <= y1 + 1.2 * ln.tamanho) or (y0 - 1.2 * ln.tamanho <= ln.y1 <= y0)
                if perto and ln.x0 > x0 + 3 and ln.x1 < x1 - 3:
                    capturadas.append(ln)
            for ln in capturadas:
                usadas.add(id(ln))
            fx0 = min([x0] + [l.x0 for l in capturadas]); fx1 = max([x1] + [l.x1 for l in capturadas])
            fy0 = min([y0] + [l.y0 for l in capturadas]); fy1 = max([y1] + [l.y1 for l in capturadas])
            n = nome("figura")
            itens.append(_Item("figura", fx0, fy0, fx1, fy1, nome=n))
            self.espacos_imagem.append(EspacoImagem(n, pg.numero, fx0, fy0, fx1, fy1, "figura"))

        for im in pg.imagens:
            if any(it.tipo == "figura" and it.x0 - 1 <= im.x0 and im.x1 <= it.x1 + 1 and it.y0 - 1 <= im.y0 and im.y1 <= it.y1 + 1
                   for it in itens):
                continue
            n = nome("imagem")
            itens.append(_Item("imagem", im.x0, im.y0, im.x1, im.y1, nome=n))
            self.espacos_imagem.append(EspacoImagem(n, pg.numero, im.x0, im.y0, im.x1, im.y1, "imagem"))

        for f in fios:
            itens.append(_Item("fio", f.x0, f.y0, f.x1, f.y1, f))
        for b in barras:
            itens.append(_Item("barra", b.x0, b.y0, b.x1, b.y1, b))
        for ln in linhas:
            if id(ln) not in usadas:
                itens.append(_item_linha(ln))
        return itens, livres

    def _fora_do_texto(self, pg, x0, y0, x1, y1, linhas):
        return not any(_sobrepoe(x0, x1, l.x0, l.x1) and _sobrepoe(y0, y1, l.y0, l.y1) for l in linhas)

    @staticmethod
    def _linhas_do_item(it: _Item):
        if it.tipo == "linha":
            return [it.obj]
        if it.tipo == "caixa":
            return it.filhos
        return []

    # -----------------------------------------------------------------
    #  Estilos: um por (tamanho, itálico); o peso da maioria é o do estilo
    # -----------------------------------------------------------------
    def _definir_estilos(self, linhas: list[Linha]):
        chars = defaultdict(Counter)
        cores = defaultdict(Counter)
        familias = Counter()
        for ln in linhas:
            for t in ln.trechos:
                if t.sobrescrito or not t.texto.strip():
                    continue
                k = (round(t.tamanho, 1), t.italico)
                chars[k][t.peso] += len(t.texto)
                cores[k][t.cor] += len(t.texto)
                familias[t.familia] += len(t.texto)
                if t.sobrescrito is False and self.sobrescrito is None:
                    pass
        self.familia = familias.most_common(1)[0][0] if familias else ""
        total = {k: sum(c.values()) for k, c in chars.items()}
        corpo_k = max(total, key=total.get)

        # entrelinha: passo médio entre linhas consecutivas do mesmo estilo e mesma margem
        passos = defaultdict(list)
        por_pag = defaultdict(list)
        for ln in linhas:
            por_pag[ln.pagina].append(ln)
        for lns in por_pag.values():
            lns = sorted(lns, key=lambda l: l.base)
            for i, a in enumerate(lns):
                ka = self._chave(a)
                for b in lns[i + 1:]:
                    d = b.base - a.base
                    if d > 1.8 * a.tamanho:
                        break
                    if self._chave(b) == ka and abs(b.x0 - a.x0) < 1 and 0.9 * a.tamanho <= d <= 1.75 * a.tamanho:
                        passos[ka].append(d)
                        break

        # mediana descarta o espaço entre parágrafos; a média em volta dela desfaz o
        # arredondamento de 0,75bp que o navegador aplica a cada linha de base
        for k, v in list(passos.items()):
            if v:
                med = statistics.median(v)
                passos[k] = [p for p in v if abs(p - med) <= 0.8]

        ordem = sorted(total, key=lambda k: (-k[0], k[1]))
        maior = ordem[0][0]
        # nomes de comando LaTeX só podem ter letras: nada de "micro2"
        nomes_menores = iter(["pequeno", "nota", "minimo", "micro", "legenda", "rodape", "detalhe",
                              "fino", "finissimo", "miudo", "miudinho"])
        secoes = iter(["secao", "subsecao", "subsubsecao", "intertitulo", "intertitulob", "intertituloc"])
        rotulos = iter(["rotulo", "rotulob", "rotuloc", "rotulod"])
        self.estilos, self._por_chave = [], {}
        usados = set()
        for k in ordem:
            tam, ital = k
            peso = chars[k].most_common(1)[0][0]
            if k == corpo_k:
                nome = "corpo"
            elif tam == corpo_k[0]:
                nome = "corpoitalico" if ital else "corpo2"
            elif tam == maior and not ital:
                nome = "titulo"
            elif tam > corpo_k[0]:
                nome = "subtitulo" if ital else (next(secoes) if peso >= 600 else next(rotulos))
            else:
                nome = next(nomes_menores) + ("italico" if ital else "")
            while nome in usados:
                nome += "x"
            usados.add(nome)
            if passos[k]:
                L = round(statistics.fmean(passos[k]), 2)
            else:
                irmaos = [statistics.fmean(v) for kk, v in passos.items() if kk[0] == tam and v]
                L = round(irmaos[0], 2) if irmaos else round(tam * 1.25, 2)
            cor = cores[k].most_common(1)[0][0]
            e = Estilo(nome, tam, L, peso, ital, self._cor(cor))
            self.estilos.append(e)
            self._por_chave[k] = e
        self._tam_corpo = corpo_k[0]
        # entrelinha final do estilo: mediana do passo médio de cada PARÁGRAFO (ponderada pelo
        # número de passos). O passo de um parágrafo inteiro desfaz o arredondamento de 0,75bp
        # do navegador; a mediana escolhe o valor que a maior parte do texto usa.
        votos = defaultdict(list)
        for lns in por_pag.values():
            for g in self._agrupar_linhas(lns):
                ls = g["linhas"]
                if len(ls) >= 2:
                    passo = (ls[-1].base - ls[0].base) / (len(ls) - 1)
                    votos[self._chave(ls[0])] += [passo] * (len(ls) - 1)
        for k, e in self._por_chave.items():
            if votos[k]:
                e.entrelinha = round(statistics.median(votos[k]), 2)
        # espacejamento do estilo: mediana do que sobra entre letras vizinhas, em todas as suas linhas
        residuos = defaultdict(list)
        for ln in linhas:
            residuos[self._chave(ln)] += self._residuos(ln)
        for k, e in self._por_chave.items():
            e.espacejamento = self._espacejamento_de(residuos[k], e.tamanho)
        # faces que não são regular/seminegrito (ex.: Light, Bold) viram comandos próprios
        self.faces_extras = {}
        for ln in linhas:
            for t in ln.trechos:
                if t.peso not in (400, 600) or (t.peso == 600 and t.italico):
                    nome = self._face(t.peso, t.italico)
                    if nome:
                        self.faces_extras[nome] = (t.peso, t.italico)

    def _face(self, peso, italico):
        if peso in (400, 600) and not (peso == 600 and italico):
            return None
        nomes = {200: "Extraleve", 300: "Leve", 500: "Medio", 600: "Seminegrito", 700: "Negrito", 900: "Preto"}
        return "fonte" + nomes.get(peso, f"Peso{peso}") + ("Italico" if italico else "")

    @staticmethod
    def _chave(ln: Linha):
        t = max((t for t in ln.trechos if not t.sobrescrito), key=lambda t: len(t.texto))
        return (round(ln.tamanho, 1), t.italico)

    def _estilo_de(self, t: Trecho) -> Estilo:
        k = (round(t.tamanho, 1), t.italico)
        if k in self._por_chave:
            return self._por_chave[k]
        return min(self.estilos, key=lambda e: abs(e.tamanho - t.tamanho) + (0 if e.italico == t.italico else 5))

    def _estilo_linha(self, ln: Linha) -> Estilo:
        return self._por_chave.get(self._chave(ln)) or self._estilo_de(ln.trechos[0])

    # -----------------------------------------------------------------
    def _margens(self, por_pagina):
        xs0, xs1 = [], []
        for itens, _ in por_pagina:
            for it in itens:
                if it.tipo in ("linha", "fio", "caixa"):
                    xs0.append(it.x0)
                    xs1.append(it.x1)
        self.margem_esq = min(xs0) if xs0 else 0
        fios = [it.x1 for itens, _ in por_pagina for it in itens if it.tipo in ("fio", "caixa")]
        self.margem_dir = max(fios) if fios else max(xs1)

    # -----------------------------------------------------------------
    #  Corte XY: colunas primeiro; corte horizontal só se liberar colunas
    # -----------------------------------------------------------------
    def _cortar(self, itens: list[_Item]) -> list[list[_Item]]:
        if not itens:
            return []
        v = self._corte_vertical(itens)
        if v:
            esq, dir_ = v
            return self._cortar(esq) + self._cortar(dir_)
        for y in self._vaos_horizontais(itens):
            cima = [it for it in itens if it.y1 <= y]
            baixo = [it for it in itens if it.y0 >= y]
            if self._corte_vertical(cima) or self._corte_vertical(baixo):
                return self._cortar(cima) + self._cortar(baixo)
        return [itens]

    @staticmethod
    def _corte_vertical(itens, minimo=10.0):
        if len(itens) < 2:
            return None
        ints = sorted((it.x0, it.x1) for it in itens)
        melhor, fim = None, ints[0][1]
        for a, b in ints[1:]:
            if a - fim >= minimo and (melhor is None or a - fim > melhor[1] - melhor[0]):
                melhor = (fim, a)
            fim = max(fim, b)
        if not melhor:
            return None
        meio = (melhor[0] + melhor[1]) / 2
        return [it for it in itens if it.x1 <= meio], [it for it in itens if it.x0 >= meio]

    @staticmethod
    def _vaos_horizontais(itens, minimo=6.0):
        ints = sorted((it.y0, it.y1) for it in itens)
        vaos, fim = [], ints[0][1]
        for a, b in ints[1:]:
            if a - fim >= minimo:
                vaos.append((a - fim, (fim + a) / 2))
            fim = max(fim, b)
        return [y for _, y in sorted(vaos, reverse=True)]

    # -----------------------------------------------------------------
    #  Quadro
    # -----------------------------------------------------------------
    def _quadro(self, itens: list[_Item], folhas, pg: Pagina) -> Quadro:
        x0 = min(it.x0 for it in itens)
        x1 = max(it.x1 for it in itens)
        y0 = min(it.y0 for it in itens)
        estruturais = [it for it in itens if it.tipo in ("fio", "caixa")]
        if estruturais:
            largura = max(it.x1 for it in estruturais) - x0
        elif x1 > self.margem_dir - 25:
            largura = self.margem_dir - x0
        else:
            largura = x1 - x0 + 1.5
        largura = round(largura, 2)
        elementos = self._fluxo(itens, x0, largura)
        ancora = "base" if y0 > 0.85 * pg.altura else "topo"
        y = elementos[-1].fundo if ancora == "base" else elementos[0].topo
        return Quadro(round(x0, 2), round(y, 2), largura, ancora, elementos)

    # -----------------------------------------------------------------
    #  Fluxo: transforma os itens de uma região em elementos ordenados
    # -----------------------------------------------------------------
    def _fluxo(self, itens: list[_Item], x0: float, largura: float) -> list[Elemento]:
        itens = list(itens)
        elementos: list[Elemento] = []

        # 1) tabelas (antes de tudo: as linhas dela formam colunas lado a lado)
        tab, itens = self._tabelas(itens, x0, largura)
        elementos += tab

        # 2) caixas com fundo
        for it in [i for i in itens if i.tipo == "caixa"]:
            itens.remove(it)
            f = it.obj
            internos = [_item_linha(l) for l in it.filhos]
            esq = min(i.x0 for i in internos) - f.x0
            internos_el = self._fluxo(internos, f.x0 + esq, f.largura - 2 * esq)
            elementos.append(CaixaEl(f.y0, f.y1, self._cor(f.preenchimento),
                                     round(internos_el[0].topo - f.y0, 2), round(f.y1 - internos_el[-1].fundo, 2),
                                     round(esq, 2), round(esq, 2), internos_el))

        # 3) chamadas: barra vertical + texto à direita
        for barra in [i for i in itens if i.tipo == "barra"]:
            itens.remove(barra)
            ao_lado = [i for i in itens if i.tipo == "linha" and barra.x1 <= i.x0 <= barra.x1 + 20
                       and barra.y0 - 2 <= i.obj.base <= barra.y1 + 2]
            if not ao_lado:
                elementos.append(FioEl(barra.y0, barra.y1, self._cor(barra.obj.preenchimento),
                                       round(barra.y1 - barra.y0, 2), round(barra.x0 - x0, 2), round(barra.x1 - barra.x0, 2)))
                continue
            for i in ao_lado:
                itens.remove(i)
            ix0 = min(i.x0 for i in ao_lado)
            internos = self._fluxo(ao_lado, ix0, x0 + largura - ix0)
            elementos.append(ChamadaEl(min(barra.y0, internos[0].topo), max(barra.y1, internos[-1].fundo),
                                       self._cor(barra.obj.preenchimento), round(barra.x1 - barra.x0, 2),
                                       round(ix0 - barra.x0, 2), internos))

        # 4) faixas: itens lado a lado
        faixas, itens = self._faixas(itens, x0, largura)
        elementos += faixas

        # 5) o resto: fios, imagens, figuras e texto
        linhas = []
        for it in itens:
            if it.tipo == "fio":
                f = it.obj
                larg = None if abs((it.x1 - it.x0) - (largura - (it.x0 - x0))) < 0.6 else round(it.x1 - it.x0, 2)
                elementos.append(FioEl(it.y0, it.y1, self._cor(f.preenchimento or f.traco),
                                       round(it.y1 - it.y0, 2), round(it.x0 - x0, 2), larg))
            elif it.tipo in ("imagem", "figura"):
                elementos.append(ImagemEl(it.y0, it.y1, it.nome, round(it.x0 - x0, 2),
                                          round(it.x1 - it.x0, 2), round(it.y1 - it.y0, 2)))
            elif it.tipo == "linha":
                linhas.append(it.obj)
        elementos += self._blocos(linhas, x0, largura)
        elementos.sort(key=lambda e: e.topo)
        return elementos

    # -----------------------------------------------------------------
    def _faixas(self, itens, x0, largura):
        # unidades: parágrafos inteiros (não linhas soltas) e imagens
        candidatos = [i for i in itens if i.tipo in ("imagem", "figura")]
        por_linha = {id(i.obj): i for i in itens if i.tipo == "linha"}
        for g in self._agrupar_linhas([i.obj for i in itens if i.tipo == "linha"]):
            candidatos.append(_Item("paragrafo", g["x0"], g["y0"], g["x1"], g["y1"],
                                    filhos=[por_linha[id(l)] for l in g["linhas"]]))
        uf = _UniaoBusca(len(candidatos))
        for a in range(len(candidatos)):
            for b in range(a + 1, len(candidatos)):
                A, B = candidatos[a], candidatos[b]
                if _sobrepoe(A.y0, A.y1, B.y0, B.y1, 1.0) and not _sobrepoe(A.x0, A.x1, B.x0, B.x1):
                    uf.unir(a, b)
        grupos = defaultdict(list)
        for i, c in enumerate(candidatos):
            grupos[uf.achar(i)].append(c)
        faixas, consumidos = [], set()
        for grupo in grupos.values():
            if len(grupo) < 2:
                continue
            # células: itens agrupados por faixa horizontal que não se sobrepõe
            grupo.sort(key=lambda i: i.x0)
            celulas = []
            for it in grupo:
                if celulas and _sobrepoe(celulas[-1]["x0"], celulas[-1]["x1"], it.x0, it.x1):
                    celulas[-1]["itens"].append(it)
                    celulas[-1]["x1"] = max(celulas[-1]["x1"], it.x1)
                else:
                    celulas.append({"x0": it.x0, "x1": it.x1, "itens": [it]})
            if len(celulas) < 2:
                continue
            def expandir(unidades):
                return [f for u in unidades for f in (u.filhos if u.tipo == "paragrafo" else [u])]

            montadas = []
            for k, c in enumerate(celulas):
                fim = celulas[k + 1]["x0"] if k + 1 < len(celulas) else x0 + largura
                larg = round(fim - c["x0"], 2)
                els = self._fluxo(expandir(c["itens"]), c["x0"], larg)
                montadas.append((c["x0"], els, larg))
            topo = min(els[0].topo for _, els, _ in montadas)
            fundo = max(els[-1].fundo for _, els, _ in montadas)
            cels = [(round(cx - x0, 2), round(els[0].topo - topo, 2), larg, els) for cx, els, larg in montadas]
            faixas.append(FaixaEl(topo, fundo, round(fundo - topo, 2), cels))
            consumidos.update(id(i) for i in expandir(grupo))
        return faixas, [i for i in itens if id(i) not in consumidos]

    # -----------------------------------------------------------------
    def _tabelas(self, itens, x0, largura):
        fios = sorted([i for i in itens if i.tipo == "fio"], key=lambda i: i.y0)
        # junta segmentos de fio na mesma altura (as bordas de cada célula)
        juntos = []
        for f in fios:
            if juntos and abs(juntos[-1]["y0"] - f.y0) < 0.4 and f.x0 - juntos[-1]["x1"] < 0.8:
                j = juntos[-1]
                j["cortes"].append(f.x0)
                j["x1"] = max(j["x1"], f.x1)
                j["partes"].append(f)
            else:
                juntos.append({"y0": f.y0, "y1": f.y1, "x0": f.x0, "x1": f.x1, "cortes": [], "partes": [f]})
        linhas = [i for i in itens if i.tipo == "linha"]

        def faixa_de_tabela(a, b):
            dentro = [l for l in linhas if a["y1"] < l.obj.base < b["y0"]]
            xs = sorted({round(l.obj.x0) for l in dentro})
            colunas = []
            for x in xs:
                if not colunas or x - colunas[-1] > 3:
                    colunas.append(x)
            return dentro if len(colunas) >= 2 else None

        tabelas, consumidos = [], set()
        i = 0
        while i < len(juntos) - 1:
            j = i
            faixas = []
            while j < len(juntos) - 1:
                d = faixa_de_tabela(juntos[j], juntos[j + 1])
                if d is None:
                    break
                faixas.append(d)
                j += 1
            if len(faixas) >= 2:
                tabelas.append(self._montar_tabela(juntos[i:j + 1], faixas, x0, largura))
                for f in juntos[i:j + 1]:
                    consumidos.update(id(p) for p in f["partes"])
                for d in faixas:
                    consumidos.update(id(l) for l in d)
                i = j
            else:
                i += 1
        return tabelas, [it for it in itens if id(it) not in consumidos]

    def _montar_tabela(self, fios, faixas, x0, largura):
        tx0, tx1 = fios[0]["x0"], max(f["x1"] for f in fios)
        todas = [l.obj for d in faixas for l in d]
        xs = sorted(l.x0 for l in todas)
        colunas = []
        for x in xs:
            if not colunas or x - colunas[-1][-1] > 3:
                colunas.append([x])
            else:
                colunas[-1].append(x)
        inicios = [min(c) for c in colunas]
        cortes = next((f["cortes"] for f in fios if len(f["cortes"]) == len(inicios) - 1), None)
        if not cortes:
            cortes = [(inicios[k] + inicios[k - 1]) / 2 for k in range(1, len(inicios))]
            self.avisos.append("tabela sem bordas por célula: limites de coluna estimados")
        limites = [tx0] + list(cortes) + [tx1]
        larguras = [round(limites[k + 1] - limites[k], 2) for k in range(len(inicios))]
        recuo_um = round(inicios[0] - limites[0], 2)
        recuos = [inicios[k] - limites[k] for k in range(1, len(inicios))]
        recuo = round(statistics.median(recuos), 2) if recuos else 0.0
        estilo = self._estilo_linha(todas[0])
        Lt = self._passo_proprio([[l.obj for l in d if inicios[c] - 3 <= l.obj.x0 < limites[c + 1]]
                                  for d in faixas for c in range(len(inicios))], estilo)
        L = Lt or estilo.entrelinha
        seq = []
        for k, d in enumerate(faixas):
            topo_fio = fios[k]
            seq.append(("fio", self._cor(topo_fio["partes"][0].obj.preenchimento or topo_fio["partes"][0].obj.traco),
                        round(topo_fio["y1"] - topo_fio["y0"], 2)))
            celulas = []
            for c in range(len(inicios)):
                fim = limites[c + 1]
                da_coluna = [l.obj for l in d if inicios[c] - 3 <= l.obj.x0 < fim]
                if da_coluna:
                    W = larguras[c] - (recuo_um if c == 0 else recuo) - recuo
                    b = self._bloco_de(sorted(da_coluna, key=lambda l: l.base), W, estilo_forcado=estilo,
                                       L_forcada=L)
                    celulas.append(b)
                else:
                    celulas.append(None)
            primeiras = [b.linhas[0].base for b in celulas if b]
            # última linha onde o LaTeX vai pô-la (ver _bloco_de)
            ultimas = [b.linhas[0].base + (len(b.linhas) - 1) * L for b in celulas if b]
            acima = min(primeiras) - _ALTO * L - topo_fio["y1"]
            abaixo = fios[k + 1]["y0"] - (max(ultimas) + _BAIXO * L)
            seq.append(("linha", round(acima, 2), round(abaixo, 2), [b.latex if b else "" for b in celulas]))
        ult = fios[len(faixas)]
        seq.append(("fio", self._cor(ult["partes"][0].obj.preenchimento or ult["partes"][0].obj.traco),
                    round(ult["y1"] - ult["y0"], 2)))
        return TabelaEl(fios[0]["y0"], ult["y1"], estilo, larguras, recuo_um, recuo, recuo, seq, Lt)

    def _passo_proprio(self, grupos_de_linhas, estilo) -> float | None:
        """Entrelinha medida num conjunto de parágrafos; None se for a do estilo."""
        soma, passos = 0.0, 0
        for ls in grupos_de_linhas:
            if len(ls) >= 2:
                ls = sorted(ls, key=lambda l: l.base)
                soma += ls[-1].base - ls[0].base
                passos += len(ls) - 1
        if not passos:
            return None
        p = soma / passos
        return round(p, 2) if abs(p - estilo.entrelinha) > 0.15 else None

    # -----------------------------------------------------------------
    #  Texto: linhas -> blocos e listas
    # -----------------------------------------------------------------
    def _agrupar_linhas(self, linhas: list[Linha]) -> list[dict]:
        """Linhas -> parágrafos: mesmo estilo, mesma margem, mesma cor, passo de uma entrelinha."""
        linhas = sorted(linhas, key=lambda l: (l.base, l.x0))
        grupos = []
        for ln in linhas:
            est = self._estilo_linha(ln)
            cor = self._cor_dominante(ln)
            dono = None
            if not ln.marcador:
                for g in reversed(grupos):
                    ult = g["linhas"][-1]
                    passo = ln.base - ult.base
                    L = est.entrelinha
                    if g["estilo"] is est and abs(ln.x0 - g["x_texto"]) < 1.5 and g["cor"] == cor \
                            and 0.5 * L <= passo <= L + max(1.0, 0.12 * L):
                        dono = g
                        break
                    if passo > 3 * L:
                        break
            if dono:
                dono["linhas"].append(ln)
            else:
                grupos.append({"estilo": est, "linhas": [ln], "x_texto": ln.x0, "marcador": ln.marcador,
                               "cor": cor})
        for g in grupos:
            ls = g["linhas"]
            g["x0"] = min(l.marcador["x"] if l.marcador else l.x0 for l in ls)
            g["x1"] = max(l.x1 for l in ls)
            g["y0"] = min(l.y0 for l in ls)
            g["y1"] = max(l.y1 for l in ls)
        return grupos

    def _blocos(self, linhas: list[Linha], x0: float, largura: float) -> list[Elemento]:
        grupos = self._agrupar_linhas(linhas)
        blocos = []
        for g in grupos:
            recuo = g["x_texto"] - x0 if g["marcador"] else 0.0
            W = largura - recuo
            b = self._bloco_de(g["linhas"], W)
            if g["marcador"]:
                b.marcador = self._registrar_marcador(g["marcador"], x0)
                b.recuo = round(recuo, 2)
            elif g["x_texto"] - x0 > 1.5:
                self.avisos.append(f"bloco recuado {g['x_texto'] - x0:.1f}bp não suportado: "
                                   f"'{g['linhas'][0].texto[:30]}'")
            blocos.append(b)

        # itens seguidos com o mesmo marcador e estilo viram uma lista
        saida, i = [], 0
        while i < len(blocos):
            b = blocos[i]
            if not b.marcador:
                saida.append(b)
                i += 1
                continue
            j = i
            while j + 1 < len(blocos) and blocos[j + 1].marcador == b.marcador and blocos[j + 1].estilo is b.estilo \
                    and blocos[j + 1].recuo == b.recuo:
                j += 1
            itens = blocos[i:j + 1]
            # entrelinha própria da lista: vale para todos os itens, inclusive os de uma linha
            Lp = self._passo_proprio([it.linhas for it in itens], b.estilo)
            if Lp or any(it.entrelinha for it in itens):
                refeitos = []
                for it in itens:
                    nb = self._bloco_de(it.linhas, largura - it.recuo, L_forcada=Lp or b.estilo.entrelinha)
                    nb.marcador, nb.recuo = it.marcador, it.recuo
                    refeitos.append(nb)
                itens = refeitos
            vaos = [itens[k + 1].topo - itens[k].fundo for k in range(len(itens) - 1)]
            esp = round(statistics.fmean(vaos) / 0.05) * 0.05 if vaos else 0.0
            if vaos and max(vaos) - min(vaos) > 0.6:
                self.avisos.append(f"lista com espaçamento irregular ({min(vaos):.1f}–{max(vaos):.1f}bp): usado {esp}")
            saida.append(ListaEl(itens[0].topo, itens[-1].fundo, b.estilo, b.cor, b.marcador, b.recuo,
                                 round(esp, 2), itens, Lp))
            i = j + 1
        return saida

    def _cor_dominante(self, ln: Linha) -> str:
        c = Counter()
        for t in ln.trechos:
            if t.texto.strip():
                c[t.cor] += len(t.texto)
        return c.most_common(1)[0][0]

    def _registrar_marcador(self, m, x0) -> str:
        desloc = round(m["x"] - x0, 2)
        if m["tipo"] == "quadrado":
            chave = ("quadrado", m["cor"], m["lado"], m["subida"], desloc)
            base_nome = "quadrado"
            desenho = (f"\\textcolor{{{{COR:{m['cor']}}}}}{{\\rule[{m['subida']}bp]{{{m['lado']}bp}}{{{m['lado']}bp}}}}")
        else:
            chave = ("glifo", m["glifo"], m["cor"], desloc)
            base_nome = "ponto" if m["glifo"] in "•●·" else "traco"
            desenho = f"\\textcolor{{{{COR:{m['cor']}}}}}{{{m['glifo']}}}"
        if chave in self.marcadores:
            return self.marcadores[chave]
        nome = base_nome
        k = 0
        while nome in self.marcadores_def:      # sufixo em letra: quadradob, quadradoc...
            nome = base_nome + "bcdefghijklmnopqrstuvwxyz"[k]
            k += 1
        self.marcadores[chave] = nome
        self.marcadores_def[nome] = (desloc, desenho)
        return nome

    # -----------------------------------------------------------------
    def _bloco_de(self, linhas: list[Linha], W: float, estilo_forcado: Estilo | None = None,
                  L_forcada: float | None = None) -> Bloco:
        est = estilo_forcado or self._estilo_linha(linhas[0])
        cor_bloco = self._cor_dominante(linhas[0])
        # títulos e seções: o designer escolhe onde quebrar; a quebra do original é mantida
        titulo = est.tamanho > self._tam_corpo + 0.1
        partes = []        # (formato, texto)
        for k, ln in enumerate(linhas):
            trechos = [t for t in ln.trechos]
            # tira espaços das pontas da linha
            while trechos and not trechos[0].texto.strip():
                trechos.pop(0)
            while trechos and not trechos[-1].texto.strip():
                trechos.pop()
            if not trechos:
                continue
            textos = [t.texto for t in trechos]
            textos[0] = textos[0].lstrip()
            textos[-1] = textos[-1].rstrip()
            for t, txt in zip(trechos, textos):
                partes.append((self._formato(t, est, cor_bloco, ln), txt))
            if k < len(linhas) - 1:
                quebra = self._quebra(ln, linhas[k + 1], W)
                if quebra == "forcada":
                    partes.append((None, "\\newline "))
                elif quebra == "limite" or titulo:
                    partes.append((None, "\\quebra "))
                elif ln.texto.rstrip().endswith("-"):
                    partes.append((None, ""))
                else:
                    partes.append((None, " "))
        latex = self._compor(partes)
        # só vale para o bloco o espacejamento que difere do estilo (o do estilo vem em \definirestilo)
        res = [r for ln in linhas for r in self._residuos(ln)]
        espacej = None
        if len(res) >= 10:
            v = statistics.median(res)
            if abs(v - est.espacejamento) > max(0.004 * est.tamanho, 0.02):
                espacej = round(v, 3)
        if L_forcada is not None:
            L, propria = L_forcada, None          # quem chamou (lista, tabela) declara a entrelinha
        else:
            propria = self._passo_proprio([linhas], est)
            L = propria or est.entrelinha
        # o fundo é onde o LaTeX vai pôr a última linha (1ª + n entrelinhas), não onde ela estava:
        # assim o erro de fração de ponto dentro de um parágrafo não empurra o que vem depois
        fundo = linhas[0].base + (len(linhas) - 1) * L + _BAIXO * L
        return Bloco(linhas[0].base - _ALTO * L, fundo, est, self._cor(cor_bloco),
                     latex, linhas, espacejamento=espacej, entrelinha=propria)

    def _formato(self, t: Trecho, est: Estilo, cor_bloco: str, ln: Linha):
        f = []
        if t.sobrescrito:
            if self.sobrescrito is None:
                self.sobrescrito = {"subida": round(ln.base - t.base, 2), "tamanho": t.tamanho}
            f.append("sup")
        if t.peso != est.peso or (t.italico != est.italico and t.peso == 600):
            face = self._face(t.peso, t.italico)
            if t.peso == 600 and not t.italico:
                f.append("bf")
            elif t.peso == 400 and est.peso != 400:
                f.append("md")
            elif face:
                f.append("face:" + face)
        if t.italico != est.italico and not any(x.startswith("face:") for x in f):
            f.append("it" if t.italico else "up")
        if t.cor != cor_bloco:
            f.append("cor:" + self._cor(t.cor))
        return tuple(f)

    @staticmethod
    def _escapar(s: str) -> str:
        troca = {"\\": "\\textbackslash{}", "&": "\\&", "%": "\\%", "$": "\\$", "#": "\\#",
                 "_": "\\_", "{": "\\{", "}": "\\}", "~": "\\textasciitilde{}", "^": "\\textasciicircum{}"}
        return "".join(troca.get(c, c) for c in s)

    def _compor(self, partes) -> str:
        # junta trechos vizinhos de mesmo formato (o separador entra junto)
        runs = []
        for fmt, txt in partes:
            if fmt is None:
                if runs:
                    runs[-1][1].append(("sep", txt))
                continue
            if runs and runs[-1][0] == fmt:
                runs[-1][1].append(("txt", txt))
            else:
                runs.append([fmt, [("txt", txt)]])
        # separador no fim de um run pertence ao espaço entre runs
        saida = []
        for fmt, pedacos in runs:
            final = ""
            while pedacos and pedacos[-1][0] == "sep":
                final = pedacos.pop()[1] + final
            corpo = "".join(self._escapar(t) if k == "txt" else t for k, t in pedacos)
            saida.append(self._envolver(fmt, corpo) + final)
        return "".join(saida).strip()

    @staticmethod
    def _envolver(fmt, s):
        for f in fmt:
            if f == "bf":
                s = f"\\textbf{{{s}}}"
            elif f == "md":
                s = f"\\textmd{{{s}}}"
            elif f == "it":
                s = f"\\textit{{{s}}}"
            elif f == "up":
                s = f"\\textup{{{s}}}"
            elif f == "sup":
                s = f"\\sobrescrito{{{s}}}"
            elif f.startswith("face:"):
                s = f"{{\\{f[5:]} {s}}}"
            elif f.startswith("cor:"):
                s = f"\\textcolor{{{{COR:{f[4:]}}}}}{{{s}}}"
        return s

    def _quebra(self, ln: Linha, prox: Linha, W: float) -> str | None:
        """'forcada': a próxima palavra cabia com folga (quebra do designer).
        'limite': cabia por um fio — o LaTeX poderia decidir diferente, então a quebra é fixada.
        None: quebra natural, o LaTeX refaz igual."""
        txt = prox.texto.strip()
        if not txt:
            return None
        palavra = txt.split()[0]
        t0 = next(t for t in prox.trechos if t.texto.strip())
        lp = self.medidor.largura(palavra, t0.fonte, t0.tamanho)
        le = self.medidor.largura(" ", t0.fonte, t0.tamanho)
        if lp is None or le is None:
            return None
        total = (ln.x1 - ln.x0) + le + lp
        if total <= W - 1.0:
            return "forcada"
        if total <= W + _FOLGA + 0.5:
            return "limite"
        return None

    def _residuos(self, ln: Linha) -> list[float]:
        """Para cada par de letras vizinhas: distância real entre as origens menos a largura
        da primeira letra. O kerning mexe em poucos pares; o espacejamento, em todos — então a
        mediana dos resíduos é o espacejamento."""
        saida = []
        for t in ln.trechos:
            if t.sobrescrito:
                continue
            for (c, x), (c2, x2) in zip(t.chars, t.chars[1:]):
                if c.isspace() or c2.isspace():
                    continue
                w = self.medidor.largura(c, t.fonte, t.tamanho)
                if w is not None:
                    saida.append(x2 - x - w)
        return saida

    @staticmethod
    def _espacejamento_de(residuos, tamanho) -> float:
        if len(residuos) < 10:
            return 0.0
        v = statistics.median(residuos)
        return round(v, 3) if abs(v) > 0.004 * tamanho else 0.0

    def _espacejamento(self, linhas: list[Linha]) -> float:
        res = [r for ln in linhas for r in self._residuos(ln)]
        return self._espacejamento_de(res, linhas[0].tamanho)

    # -----------------------------------------------------------------
    #  Espaço padrão entre blocos do mesmo estilo (vai para \definirestilo)
    # -----------------------------------------------------------------
    def _espaco_padrao(self, paginas):
        vaos = defaultdict(list)

        def percorrer(elementos):
            for a, b in zip(elementos, elementos[1:]):
                if isinstance(a, Bloco) and isinstance(b, Bloco) and a.estilo is b.estilo:
                    vaos[b.estilo.nome].append(b.topo - a.fundo)
            for e in elementos:
                for filhos in self._filhos(e):
                    percorrer(filhos)

        for p in paginas:
            for q in p.quadros:
                percorrer(q.elementos)
        for e in self.estilos:
            m = _moda(vaos.get(e.nome, []), 0.05)
            e.espaco = round(m, 2) if m is not None else 0.0

    @staticmethod
    def _filhos(e):
        if isinstance(e, (CaixaEl, ChamadaEl)):
            return [e.elementos]
        if isinstance(e, FaixaEl):
            return [els for *_r, els in e.celulas]
        return []


def analisar(paginas, medidor) -> Documento:
    return Analisador(paginas, medidor).analisar()
