DSI MARKUP — APPLICATION ICON ASSETS
====================================

Concept: a revision cloud (the scalloped redline markup engineers/drafters
draw to flag a change) forms the icon's silhouette. Inside sits the DSI
lightbulb — the exact geometry from the DSI logo — with a check, the
engineer's flagged comment delivered to the drafter as a done-able task.

Brand colors
------------
Navy   #16233F
Orange #E8772E
White  #FFFFFF

The scalloped edge is the boundary: it separates the interior fill from
whatever background the icon sits on. The exterior is fully transparent.

Two themes
----------
light/  — white interior, navy bulb, orange check. Use on light surfaces.
dark/   — navy interior, orange bulb, white check. Use on dark surfaces.

.ico is a static format; Windows will not auto-swap by theme. Point your
build at the light or dark file to match your app's appearance.

Contents
--------
ico/
  dsi-markup-light.ico   multi-resolution (16,32,48,64,128,256)
  dsi-markup-dark.ico    multi-resolution (16,32,48,64,128,256)

png/light/  dsi-markup-light-{16,24,32,48,64,128,256,512,1024}.png
png/dark/   dsi-markup-dark-{16,24,32,48,64,128,256,512,1024}.png
            (transparent, square)

Where each goes
---------------
Windows app / .exe         ico/dsi-markup-*.ico
Windows installer / shortcut   ico/dsi-markup-*.ico
Taskbar / favicon          png 16, 32, 48
Desktop / Start tile       png 128, 256
Web app / PWA manifest     png 192-ish -> use 256; 512 for splash
macOS / Linux / app store  png 512, 1024 (or request a .icns and we'll add it)

Need anything else (macOS .icns, a monochrome/notification glyph, or a
single source SVG) — just ask.
