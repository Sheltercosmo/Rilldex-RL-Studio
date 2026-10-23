"""Render the owner-supplied Rilldex identity as portable vector assets."""
from pathlib import Path
from html import escape
import re

ROOT = Path(__file__).resolve().parents[1]
MARK = '''<defs>
 <linearGradient id="rd-base" x1="0" y1="1" x2="1" y2="0"><stop stop-color="#d2d9ff"/><stop offset=".43" stop-color="#147bff"/><stop offset="1" stop-color="#8ed9fc"/></linearGradient>
 <linearGradient id="rd-fold" x1=".2" y1="0" x2=".65" y2="1"><stop stop-color="#003fe9"/><stop offset=".4" stop-color="#0667ff"/><stop offset="1" stop-color="#d6d9ff"/></linearGradient>
 <linearGradient id="rd-core" x1=".1" y1=".5" x2="1" y2=".35"><stop stop-color="#1428c9"/><stop offset=".65" stop-color="#0759f5"/><stop offset="1" stop-color="#439fff"/></linearGradient>
 <linearGradient id="rd-stem" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#92b9ff"/><stop offset="1" stop-color="#c9effc"/></linearGradient>
 <linearGradient id="rd-dot" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#0055ff"/><stop offset="1" stop-color="#48a6ff"/></linearGradient>
 <clipPath id="rd-clip"><path d="M22 562Q0 562 0 540V254Q0 212 30 181L184 27Q211 0 256 0H472Q493 0 493 23V181Q493 204 472 204H332C269 204 219 255 219 319V540Q219 562 197 562Z"/></clipPath>
</defs>
<g transform="translate(19 19)">
 <g clip-path="url(#rd-clip)">
  <path d="M0 0H493V562H0Z" fill="url(#rd-base)"/>
  <path d="M219 257V562H0L0 540Z" fill="url(#rd-stem)"/>
  <path d="M0 194C93 130 150 98 229 98C316 98 369 136 418 204H332C293 204 260 224 235 251L0 532Z" fill="url(#rd-fold)"/>
  <path d="M214 98H247C327 98 381 146 418 204H332C290 204 262 220 233 254L148 355V238C148 178 171 129 214 98Z" fill="url(#rd-core)"/>
 </g>
 <rect x="417" y="287" width="144" height="141" rx="19" fill="url(#rd-dot)"/>
</g>'''

# Outlined lettering keeps the supplied geometric wordmark independent of fonts.
WORDMARK = '''<g fill="#05081d">
 <path d="M0 174V101C0 65 18 50 54 50H104V74H53Q30 74 30 101V174Z"/>
 <rect x="130" y="50" width="30" height="124" rx="2"/><rect x="130" width="30" height="30" rx="15"/>
 <rect x="194" width="30" height="174" rx="2"/><rect x="259" width="30" height="174" rx="2"/>
 <path fill-rule="evenodd" d="M469 0V174H400C351 174 321 167 321 123V100C321 64 343 50 385 50H440V0ZM440 75H391Q351 75 351 102V123Q351 148 390 148H440Z"/>
 <path fill-rule="evenodd" d="M530 121Q530 149 572 149H620V172Q599 176 570 176Q500 176 500 128V99Q500 50 567 50Q640 50 640 96V119H530ZM530 98H610V94Q610 72 569 72Q533 72 530 98Z"/>
 <path d="M657 50H691L728 96L765 50H800L746 110L800 174H765L728 128L691 174H657L710 110Z"/>
</g>'''


def svg(width, height, body, title='Rilldex'):
    label = escape(title, quote=True)
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{label}">\n<title>{label}</title>\n{body}\n</svg>\n'


def main():
    web=ROOT/'tracker/web'; assets=ROOT/'docs/assets'
    (web/'rilldex-mark.svg').write_text(svg(600,600,MARK),encoding='utf-8')
    horizontal=svg(340,80,f'<g transform="translate(0 2) scale(.126)">{MARK}</g><g transform="translate(94 13) scale(.30)">{WORDMARK}</g>')
    (web/'rilldex-logo.svg').write_text(horizontal,encoding='utf-8')
    # The public trace illustrations retain their original, source-backed content.
    # Refresh only their identity, with a marker for repeatable regeneration.
    lockup=f'<g id="rilldex-identity"><svg x="44" y="30" width="132" height="31" viewBox="0 0 340 80">{horizontal.split(chr(10),1)[1].rsplit("</svg>",1)[0]}</svg></g>'
    for name in ('unit-map.svg','plans-and-attempts.svg','training-signals.svg'):
        path=assets/'demo'/name
        content=path.read_text(encoding='utf-8')
        if '<g id="rilldex-identity">' in content:
            content=re.sub(r'<g id="rilldex-identity">.*?</svg></g>',lambda _:lockup,content,flags=re.S)
        else:
            content,count=re.subn(r'<rect x="44" y="34".*?>Rilldex</text>',lambda _:lockup,content,count=1,flags=re.S)
            if count!=1:raise ValueError(f'Expected legacy identity in {path}')
        path.write_text(content,encoding='utf-8')
    (assets/'rilldex-logo.svg').write_text(svg(960,960,f'<g transform="translate(180 28)">{MARK}</g><g transform="translate(80 714)">{WORDMARK}</g>'),encoding='utf-8')
    header=f'''<rect width="1280" height="430" rx="24" fill="#f8faff"/>
<rect x="1" y="1" width="1278" height="428" rx="23" fill="none" stroke="#e3e9f3"/>
<g transform="translate(58 45) scale(.15)">{MARK}</g>
<g transform="translate(166 67) scale(.34)">{WORDMARK}</g>
<g font-family="Segoe UI,Arial,sans-serif">
 <text x="471" y="115" font-size="17" fill="#536580" letter-spacing="2">RL STUDIO</text>
 <text x="64" y="211" font-size="42" font-weight="650" letter-spacing="-1.3" fill="#15243b">From training signals to agent behavior.</text>
 <text x="66" y="253" font-size="21" fill="#617089">Follow a run. Inspect a change. Return to the evidence.</text>
 <path d="M64 296H1216" stroke="#dce5f2"/>
 <text x="66" y="342" font-size="22" font-weight="600" fill="#15243b">Behavior maps</text>
 <text x="66" y="373" font-size="17" fill="#617089">Activities, plans &amp; repeated attempts</text>
 <text x="468" y="342" font-size="22" font-weight="600" fill="#15243b">Training &amp; execution</text>
 <text x="468" y="373" font-size="17" fill="#617089">Native signals, parallel workers &amp; logs</text>
 <text x="888" y="342" font-size="22" font-weight="600" fill="#15243b">Evidence &amp; diagnosis</text>
 <text x="888" y="373" font-size="17" fill="#617089">Saved comparisons, Python &amp; SQL</text>
</g>'''
    (assets/'rilldex-header.svg').write_text(svg(1280,430,header,'Rilldex RL Studio — behavior maps, training and evidence'),encoding='utf-8')


if __name__=='__main__':main()
