# LoadPilot landing page

## Appended circle section

`circle.css` and `circle.js` style and animate only `#loadpilot-circle`, appended
after the original page. The tilted ellipse, equal-distance spacing, depth
scaling, foreground/background layering, and scroll acceleration are adapted
from `SectionPartner` in the supplied `kononenkogroup.com.zip`. Capability labels
replace the reference's customer logos. Motion pauses outside the viewport and
honors reduced-motion preferences. The reference's font was absent from the ZIP
and its host returned 403; this section uses a local Times serif fallback.

The original portrait-gallery section is removed. Other existing landing markup
is retained. The workspace uses a separate `workspace-theme.css` layer matching
the existing landing page's black surfaces, white type, mint accent, and pill
buttons; its test execution flow and layout are retained.

This page adapts the HTML, CSS, artwork, and animation bundle in the user-supplied
`hobro.digital.zip`. It is not a new design or a React recreation. The original
section layout and animation selectors are retained; branding, text, metadata,
and navigation are adapted for LoadPilot.

The Python server serves this page at `/`, its assets at `/landing/`, and the
existing React testing workspace at `/app`. Vite's development middleware also
serves this page at `/`. Build with `npm run build` in `web`, then start the
Python server as usual. No model key is needed for the landing page.

## Export repairs

- Removed captured browser-extension scripts, analytics, reCAPTCHA, and forms.
- Replaced the original router bootstrap, which expected absent page fragments.
- Restored asset paths and removed captured SplitText and pinning state.
- Kept original GSAP animation code, with LoadPilot rotating words.
- Added a bounded loading fallback so unavailable remote media cannot trap users.
- Workspace links use `/app`; documentation uses `/docs`.

## External assets

The supplied ZIP omits fonts, videos, and Lottie animation files. Their original
URLs remain in the page and font stylesheet. The Lottie player also needs CDN
modules absent from the export, so it loads from the original versioned CDN.
Some remote files return 403 or fail cross-origin requests locally. Videos that
load still play; failed decorative animations are hidden. Fonts fall back to the
original stylesheet's fallback families. Exact typography and every decorative
animation require the missing original assets. The landing page is therefore
not fully offline, although the testing backend supports offline model mode.

Gallery artwork and portraits are retained from the supplied reference. They are
not LoadPilot customers, staff, or benchmark evidence. Scenario descriptions are
illustrative and do not claim actual performance results. Original third-party
asset and library licensing continues to apply; the repository's license does
not relicense these imported files.
