"""Vetoriza um logo de duas tintas (vermelho + preto sobre fundo claro) com o potrace.

uso: python vetorizar_logo.py entrada.png saida_sem_extensao [escala] [limiar_vermelho] [suavizacao_vermelho]
Gera saida.svg (vetor) e saida.pdf (o mesmo vetor, para o LaTeX) e saida_previa.png.
Precisa de: pip install potracer pillow pymupdf numpy

O logo da OpenSFS (p3-imagem-1) foi feito assim, a partir do print-logo.png do site deles:
    python vetorizar_logo.py print-logo.png p3-imagem-1 8 0.30 0.6
(limiar 0,30 e suavização 0,6 no vermelho: as pontas das elipses são um degradê fino e,
com os valores padrão, saíam picotadas.)
"""
import sys

import fitz
import numpy as np
import potrace
from PIL import Image, ImageFilter

entrada, saida = sys.argv[1], sys.argv[2]
escala = int(sys.argv[3]) if len(sys.argv) > 3 else 8

img = Image.open(entrada).convert("RGBA")
fundo = Image.new("RGBA", img.size, (255, 255, 255, 255))
rgb = np.asarray(Image.alpha_composite(fundo, img).convert("RGB")).astype(float)

# recorta na tinta
tinta = rgb.min(axis=2) < 235
ys, xs = np.where(tinta)
m = 2
y0, y1, x0, x1 = max(ys.min() - m, 0), ys.max() + m + 1, max(xs.min() - m, 0), xs.max() + m + 1
rgb = rgb[y0:y1, x0:x1]
R, G, B = rgb[..., 0], rgb[..., 1], rgb[..., 2]

# as duas tintas, medidas nos pixels mais "puros" de cada uma
eh_verm = (R > 150) & (G < 90) & (B < 90)
eh_preto = (R < 70) & (G < 70) & (B < 70)
verm = np.median(rgb[eh_verm], axis=0)
preto = np.median(rgb[eh_preto], axis=0)
print("vermelho", "#%02X%02X%02X" % tuple(int(v) for v in verm), "preto", "#%02X%02X%02X" % tuple(int(v) for v in preto))

# cobertura de cada tinta por pixel (0..1). Vermelho: R alto e G baixo. Preto: R baixo.
cob_verm = np.clip((R - G) / max(verm[0] - verm[1], 1), 0, 1)
cob_preto = np.clip((255 - R) / max(255 - preto[0], 1), 0, 1)


def ampliar(c, limiar=0.5, suave=0.35):
    im = Image.fromarray((c * 255).astype(np.uint8))
    im = im.resize((im.width * escala, im.height * escala), Image.LANCZOS)
    im = im.filter(ImageFilter.GaussianBlur(escala * suave))
    return np.asarray(im) > 255 * limiar


def tracar(mascara):
    caminhos = ~mascara.astype(bool)   # o potracer traça o que é False
    plist = potrace.Bitmap(caminhos).trace(turdsize=escala * escala // 2, alphamax=1.0,
                                           opticurve=True, opttolerance=0.2)
    d = []
    for curva in plist:
        p = curva.start_point
        d.append(f"M{p.x:.2f},{p.y:.2f}")
        for s in curva.segments:
            if s.is_corner:
                d.append(f"L{s.c.x:.2f},{s.c.y:.2f}L{s.end_point.x:.2f},{s.end_point.y:.2f}")
            else:
                d.append(f"C{s.c1.x:.2f},{s.c1.y:.2f} {s.c2.x:.2f},{s.c2.y:.2f} {s.end_point.x:.2f},{s.end_point.y:.2f}")
        d.append("Z")
    return "".join(d), len(plist)


LV, SV = float(sys.argv[4]) if len(sys.argv) > 4 else 0.5, float(sys.argv[5]) if len(sys.argv) > 5 else 0.35
# as pontas das elipses são um degradê fino: limiar mais baixo e mais suavização para não picotar
mv, mp = ampliar(cob_verm, LV, SV), ampliar(cob_preto)
dv, nv = tracar(mv)
dp, np_ = tracar(mp)
print(f"curvas: vermelho {nv}, preto {np_}")
H, W = mv.shape
hexa = lambda c: "#%02X%02X%02X" % tuple(int(v) for v in c)
svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
       f'width="{W / escala:.2f}pt" height="{H / escala:.2f}pt">\n'
       f'  <path fill="{hexa(verm)}" fill-rule="evenodd" d="{dv}"/>\n'
       f'  <path fill="{hexa(preto)}" fill-rule="evenodd" d="{dp}"/>\n</svg>\n')
open(saida + ".svg", "w", encoding="utf-8").write(svg)

doc = fitz.open(saida + ".svg")
pdf = fitz.open("pdf", doc.convert_to_pdf())
pdf.save(saida + ".pdf")
pg = pdf[0]
print("PDF:", round(pg.rect.width, 1), "x", round(pg.rect.height, 1), "pt · imagens raster:", len(pg.get_images()),
      "· desenhos vetoriais:", len(pg.get_drawings()))
pg.get_pixmap(matrix=fitz.Matrix(6, 6)).save(saida + "_previa.png")
