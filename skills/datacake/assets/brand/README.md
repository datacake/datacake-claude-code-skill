# Datacake brand assets

Static files the skill copies into generated projects when no customer branding is supplied. How they are used, the colour tokens and the runtime white label fallback are described in `../../reference/branding.md`.

Expected files (names are referenced by the skill; keep them exact):

| File | Purpose |
|---|---|
| `datacake-logo-black.svg` | wordmark for light backgrounds |
| `datacake-logo-white.svg` | wordmark for dark backgrounds |
| `datacake-mark-black.svg` | square icon mark for light backgrounds (collapsed sidebar, splash, app icon source) |
| `datacake-mark-white.svg` | square icon mark for dark backgrounds |
| `favicon.png` | 48×48 favicon (`app/icon.png` in Next.js, `web.favicon` in Expo) |
| `icon-1024.png` | 1024×1024 opaque app icon (Expo `icon`) |
| `adaptive-icon.png` | 1024×1024 transparent Android foreground (mark inside the centre 66 %) |
| `splash-icon.png` | splash image (Expo), mark on transparent background |

Run `python3 tools/check_assets.py` from the repository root to list which files are present.

## Licence

The Datacake name, wordmark and icon mark are trademarks of Datacake GmbH. They are provided here so that tools, portals and apps built on the Datacake platform can carry Datacake branding by default. They are **not** covered by the MIT licence of this repository. Permitted: unmodified use in products built on Datacake. Not permitted: altering proportions or colours (beyond the provided black/white variants), using the marks to imply endorsement of unrelated products, or redistributing them as a standalone asset pack.
