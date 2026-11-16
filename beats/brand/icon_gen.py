"""The round Siansa Beats icon (the owner, 16 Nov): "Siansa Beats" in the middle of a black circle, between the
same echo arcs as the Siansa app's icon (its docs/brand/icon_gen.py: radius, width, the 44° ends and their frost).

The letters are the square icon's before it (0.47.1), read from the SVG given:
    python3 brand/icon_gen.py <old icon.svg> brand/siansa-beats-icon.svg [scale of the words, 0.70]
Then the 512 px PNG with see-through corners, and the page's tab icon (page.html, signin.html), from the new SVG.
"""
import math, re, sys
old = open(sys.argv[1]).read()
# The words' letters as the old icon had them: "Siansa" (amber S, frost) above "Beats" (frost), without the reflection.
words = [m.group(0) for m in re.finditer(r'<path d="[^"]+" fill="url\(#(amber|frost1|frost2)\)"/>', old)]
assert len(words) == 11, len(words)
defs = re.search(r'<linearGradient id="amber".*?</linearGradient><linearGradient id="frost1".*?</linearGradient><linearGradient id="frost2".*?</linearGradient>', old).group(0)
SCALE = 7.111  # Siansa's icon: viewBox 18..90 shown at 512
C = 256.0
def arc(r, side, width, alpha_end, alpha_mid, gid):
    half = math.radians(44.2)  # Siansa's arcs end 44° above and below the middle
    dx, dy = r * math.cos(half), r * math.sin(half)
    x = C - dx if side < 0 else C + dx
    sweep = 0 if side < 0 else 1
    grad = (f'<linearGradient id="{gid}" gradientUnits="userSpaceOnUse" x1="0" y1="{C - dy:.1f}" x2="0" y2="{C + dy:.1f}">'
            f'<stop offset="0" stop-color="#AFC2D3" stop-opacity="{alpha_end}"/><stop offset="0.5" stop-color="#AFC2D3" stop-opacity="{alpha_mid}"/>'
            f'<stop offset="1" stop-color="#AFC2D3" stop-opacity="{alpha_end}"/></linearGradient>')
    path = (f'<path d="M{x:.1f},{C - dy:.1f}A{r:.1f},{r:.1f} 0 0,{sweep} {x:.1f},{C + dy:.1f}" fill="none" stroke="url(#{gid})" '
            f'stroke-width="{width:.1f}" stroke-linecap="round"/>')
    return grad, path
arcs = [arc(24.42 * SCALE, -1, 2.6 * SCALE, 0.303, 0.550, "a0"), arc(24.42 * SCALE, 1, 2.6 * SCALE, 0.303, 0.550, "a1"),
        arc(32.56 * SCALE, -1, 2.2 * SCALE, 0.132, 0.240, "a2"), arc(32.56 * SCALE, 1, 2.2 * SCALE, 0.132, 0.240, "a3")]
# The words, 352 x 215 in the old icon (x 80..432, y 135..350), scaled to sit well inside the inner arcs.
s = float(sys.argv[3]) if len(sys.argv) > 3 else 0.74
group = f'<g transform="translate({C},{C}) scale({s}) translate(-256,-242.5)">' + "".join(words) + "</g>"
svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="512" height="512" role="img" aria-label="Siansa Beats">'
       '<title>Siansa Beats</title><defs>' + defs + "".join(g for g, _ in arcs) + '</defs>'
       f'<circle cx="{C}" cy="{C}" r="256" fill="#000000"/>' + "".join(p for _, p in arcs) + group + '</svg>')
open(sys.argv[2], "w").write(svg)
print(len(svg), "bytes")
