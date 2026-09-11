# Branding: Datacake default look, assets and white label fallback

## Contents

- Rule of thumb
- Assets (`assets/brand/`)
- Design tokens (light and dark)
- Look and feel (2026 interpretation of the portal)
- Next.js setup
- Expo setup
- Runtime branding for white label portals
- Checklist

## Rule of thumb

Every frontend built with this skill has a brand from the first commit. Decide it in the intake and state the assumption:

| User says | Do |
|---|---|
| Nothing about branding, or "just make it look good" | **Datacake default**: assets from `assets/brand/`, tokens below, look and feel below. Say so in one sentence ("Using Datacake branding; send me a logo and colours to swap"). |
| Provides logo, colours, fonts | **Customer branding**: use it fully. Keep the neutral surfaces and the state colours below, replace `--primary`/`--brand`/`--ring`/`--chart-1` with the customer colour, replace logo and favicon, set the app title. No "Powered by Datacake" mark unless asked. |
| Tool runs on a white label domain (portal for their customers) | **Runtime branding**: resolve the site with `branding` / `brandingForDomain`, use its title, logo and favicon, fall back to the bundled Datacake assets when the query returns `null` (see below). |

Never ask twice: if the user did not answer the branding part of the intake, build with the Datacake default and mention the swap in the hand-over.

## Assets (`assets/brand/`)

Location: `${CLAUDE_SKILL_DIR}/assets/brand/` (next to `reference/` and `scripts/`). Copy files into the project; never link to the skill directory from app code.

| File | Use | Required |
|---|---|---|
| `datacake-logo-black.svg` | wordmark on light backgrounds (header, login card, emails) | yes |
| `datacake-logo-white.svg` | wordmark on dark backgrounds (dark mode, dark sidebar) | yes |
| `datacake-mark-black.svg` | square icon mark for light backgrounds: collapsed sidebar, avatar fallback, splash | yes |
| `datacake-mark-white.svg` | square icon mark for dark backgrounds | yes |
| `favicon.png` | 48×48 PNG: `app/icon.png` in Next.js (becomes the favicon), `web.favicon` in Expo | yes |
| `icon-1024.png` | Expo `icon` (iOS app icon, opaque, square) | for mobile |
| `adaptive-icon.png` | Expo `android.adaptiveIcon.foregroundImage` (transparent, mark in the centre 66 % safe zone) | for mobile |
| `splash-icon.png` | Expo splash (`expo-splash-screen` `image`, mark on brand or white background) | for mobile |

Copy commands (run from the project root):

```bash
mkdir -p public/brand
cp "${CLAUDE_SKILL_DIR}/assets/brand/"datacake-{logo,mark}-{black,white}.svg public/brand/
cp "${CLAUDE_SKILL_DIR}/assets/brand/favicon.png" app/icon.png
```

If a file is missing from the skill folder, say so, use the ones that exist and derive the rest (the SVGs carry one fill each: black `#0d0000` on the wordmark, `#1d1d1b` on the mark, `#fff` on the white variants, so a colour swap is a one-line edit; a missing `icon-1024.png` is the black mark rendered on white at 1024 px). `python3 tools/check_assets.py` in the skill repo lists what is present.

Licence: the files in `assets/brand/` are Datacake trademarks. They may be used in tools, portals and apps built on the Datacake platform; they are not covered by the skill's MIT licence and must not be altered in proportion or colour beyond the black/white variants (see `assets/brand/README.md`).

## Design tokens (light and dark)

Source: the official Datacake palette as used on datacake.co (brand magenta `#FF0097`, slate neutrals, Geist typeface). Values are hex so they drop into Tailwind v4 / shadcn "new-york" `globals.css` without conversion.

| Token | Light | Dark | Notes |
|---|---|---|---|
| `--background` | `#fafafa` | `#0b0f17` | page |
| `--foreground` | `#0f172a` | `#f8fafc` | text |
| `--card` / `--popover` | `#ffffff` | `#111827` | surfaces |
| `--card-foreground` / `--popover-foreground` | `#0f172a` | `#f8fafc` | |
| `--primary` / `--brand` | `#ff0097` | `#ff0097` | buttons, active nav, focus ring, chart-1 |
| `--primary-foreground` | `#ffffff` | `#ffffff` | |
| `--brand-hover` | `#e60088` | `#ff2fb0` | hover on primary |
| `--secondary` / `--accent` | `#f1f5f9` | `#1e293b` | |
| `--secondary-foreground` / `--accent-foreground` | `#0f172a` | `#f8fafc` | |
| `--muted` | `#f1f5f9` | `#0f172a` | table stripes, skeletons |
| `--muted-foreground` | `#475569` | `#94a3b8` | labels, units, timestamps |
| `--destructive` | `#ef4444` | `#ef4444` | also "critical" |
| `--border` / `--input` | `#e2e8f0` | `#1f2937` | |
| `--ring` | `#ff0097` | `#ff0097` | |
| `--sidebar` | `#fafafa` | `#111827` | shadcn sidebar |
| `--sidebar-border` | `#e2e8f0` | `#1f2937` | |
| `--sidebar-accent` | `#f1f5f9` | `#1e293b` | hover/active row |
| `--sidebar-primary` | `#ff0097` | `#ff0097` | |
| `--chart-1` … `--chart-5` | `#ff0097 #475569 #0f172a #94a3b8 #e2e8f0` | `#ff0097 #94a3b8 #f8fafc #475569 #1f2937` | one brand series, then neutrals |
| `--gradient-start/mid/end` | `#ff0097 #ff2fb0 #ff6ad5` | `#ff0097 #ff4dc4 #ffa3e6` | hero/login accents only |
| logo/mark ink | `#0d0000` / `#1d1d1b` (the black SVGs) | `#ffffff` (the white SVGs) | never recolour the marks in the brand colour |
| `--radius` | `0.625rem` | | shadcn default sizes derive from it |

State colours for IoT data (not brand, keep them under customer branding too):

| State | Token | Light | Dark |
|---|---|---|---|
| online / ok / success | `--success` | `#00bb7f` | `#00d294` |
| warning / stale / low battery | `--warning` | `#fcbb00` | `#fcbb00` |
| critical / alarm | `--destructive` | `#ef4444` | `#ef4444` |
| offline / unknown | `--muted-foreground` | | |

Typography: `Geist` (sans) and `Geist Mono` (numbers, identifiers, serial numbers). Fallback stack `ui-sans-serif, system-ui, sans-serif`. Tabular figures (`font-variant-numeric: tabular-nums`) on every KPI, table and chart axis.

`globals.css` for Tailwind v4 + shadcn (paste as is; add tokens to `@theme inline` only when you use them):

```css
@import "tailwindcss";
@import "tw-animate-css";
@custom-variant dark (&:is(.dark *));

:root {
  --background: #fafafa; --foreground: #0f172a;
  --card: #ffffff; --card-foreground: #0f172a;
  --popover: #ffffff; --popover-foreground: #0f172a;
  --primary: #ff0097; --primary-foreground: #ffffff;
  --brand: #ff0097; --brand-hover: #e60088; --brand-foreground: #ffffff;
  --secondary: #f1f5f9; --secondary-foreground: #0f172a;
  --muted: #f1f5f9; --muted-foreground: #475569;
  --accent: #f1f5f9; --accent-foreground: #0f172a;
  --destructive: #ef4444; --success: #00bb7f; --warning: #fcbb00;
  --border: #e2e8f0; --input: #e2e8f0; --ring: #ff0097;
  --chart-1: #ff0097; --chart-2: #475569; --chart-3: #0f172a; --chart-4: #94a3b8; --chart-5: #e2e8f0;
  --sidebar: #fafafa; --sidebar-foreground: #0f172a; --sidebar-primary: #ff0097; --sidebar-primary-foreground: #ffffff;
  --sidebar-accent: #f1f5f9; --sidebar-accent-foreground: #0f172a; --sidebar-border: #e2e8f0; --sidebar-ring: #ff0097;
  --radius: 0.625rem;
}

.dark {
  --background: #0b0f17; --foreground: #f8fafc;
  --card: #111827; --card-foreground: #f8fafc;
  --popover: #111827; --popover-foreground: #f8fafc;
  --primary: #ff0097; --primary-foreground: #ffffff;
  --brand: #ff0097; --brand-hover: #ff2fb0; --brand-foreground: #ffffff;
  --secondary: #1e293b; --secondary-foreground: #f8fafc;
  --muted: #0f172a; --muted-foreground: #94a3b8;
  --accent: #1e293b; --accent-foreground: #f8fafc;
  --destructive: #ef4444; --success: #00d294; --warning: #fcbb00;
  --border: #1f2937; --input: #1f2937; --ring: #ff0097;
  --chart-1: #ff0097; --chart-2: #94a3b8; --chart-3: #f8fafc; --chart-4: #475569; --chart-5: #1f2937;
  --sidebar: #111827; --sidebar-foreground: #f8fafc; --sidebar-primary: #ff0097; --sidebar-primary-foreground: #ffffff;
  --sidebar-accent: #1e293b; --sidebar-accent-foreground: #f8fafc; --sidebar-border: #1f2937; --sidebar-ring: #ff0097;
}

@theme inline {
  --color-background: var(--background); --color-foreground: var(--foreground);
  --color-card: var(--card); --color-card-foreground: var(--card-foreground);
  --color-popover: var(--popover); --color-popover-foreground: var(--popover-foreground);
  --color-primary: var(--primary); --color-primary-foreground: var(--primary-foreground);
  --color-brand: var(--brand); --color-brand-hover: var(--brand-hover); --color-brand-foreground: var(--brand-foreground);
  --color-secondary: var(--secondary); --color-secondary-foreground: var(--secondary-foreground);
  --color-muted: var(--muted); --color-muted-foreground: var(--muted-foreground);
  --color-accent: var(--accent); --color-accent-foreground: var(--accent-foreground);
  --color-destructive: var(--destructive); --color-success: var(--success); --color-warning: var(--warning);
  --color-border: var(--border); --color-input: var(--input); --color-ring: var(--ring);
  --color-chart-1: var(--chart-1); --color-chart-2: var(--chart-2); --color-chart-3: var(--chart-3); --color-chart-4: var(--chart-4); --color-chart-5: var(--chart-5);
  --color-sidebar: var(--sidebar); --color-sidebar-foreground: var(--sidebar-foreground); --color-sidebar-primary: var(--sidebar-primary);
  --color-sidebar-primary-foreground: var(--sidebar-primary-foreground); --color-sidebar-accent: var(--sidebar-accent);
  --color-sidebar-accent-foreground: var(--sidebar-accent-foreground); --color-sidebar-border: var(--sidebar-border); --color-sidebar-ring: var(--sidebar-ring);
  --radius-sm: calc(var(--radius) - 4px); --radius-md: calc(var(--radius) - 2px); --radius-lg: var(--radius); --radius-xl: calc(var(--radius) + 4px);
  --font-sans: var(--font-geist-sans), ui-sans-serif, system-ui, sans-serif;
  --font-mono: var(--font-geist-mono), ui-monospace, monospace;
}

@layer base {
  * { @apply border-border outline-ring/50; }
  body { @apply bg-background text-foreground antialiased; }
  .tabular { font-variant-numeric: tabular-nums; }
}
```

`components.json` for shadcn: `"style": "new-york"`, `"baseColor": "slate"`, `"cssVariables": true`, `"iconLibrary": "lucide"`. Then `npx shadcn@latest add sidebar card table badge tabs sheet dialog command skeleton sonner dropdown-menu tooltip separator`.

## Look and feel (2026 interpretation of the portal)

The Datacake portal is a left-navigation, workspace-centred B2B app. Keep its structure and information density, render it as a current shadcn "new-york" product:

- **Shell**: collapsible `Sidebar` (icon rail when collapsed) with the mark at the top, a workspace switcher (`DropdownMenu` on `allWorkspaces`), navigation groups (Overview, Devices, Dashboards, Rules, Reports, Members, Settings; show only what the tool implements), user menu with theme toggle and sign-out at the bottom. Main area: breadcrumb header, page title, primary action right-aligned.
- **Theme**: dark mode is first-class, not optional. `next-themes` with `attribute="class"`, default `system`, toggle in the user menu, `color-scheme` set on `html`. Test every page in both.
- **Brand colour discipline**: magenta only on primary buttons, active navigation item, focus rings, links on hover, the first chart series and the login gradient. Everything else is slate. Never use the brand colour for status.
- **Status language**: `Badge` variants `online` (success), `stale`/`warning` (warning), `alarm` (destructive), `offline` (muted outline); a 2 px dot plus text, never colour alone. `lastHeard` as relative time with the absolute stamp in a `Tooltip`.
- **Data density**: KPI `Card` grid (value in `text-3xl font-semibold tabular`, unit `text-muted-foreground`, delta vs previous period, 7-day sparkline), dense `Table` rows (`h-10`), sticky header, column toggles, `Command` palette for device search (`⌘K`). Charts: `recharts` line/area with `--chart-*` colours, gridlines `--border`, no chart fills darker than `--muted`.
- **Login**: centred card on `--background`, wordmark on top (`datacake-logo-black.svg` / `-white.svg` per theme), email + password, optional OTP step, error inline; gradient accent stripe or right-hand panel using `--gradient-*` when there is room.
- **Empty and error states**: icon from `lucide-react`, one sentence, one action. Skeletons match the final layout.
- **Motion and radius**: `--radius` 0.625rem, subtle `tw-animate-css` fades, no bouncing.
- **Marketing site language**: matches datacake.co (Geist, magenta on slate), so a customer moving from the website to the tool sees one brand.

## Next.js setup

Fonts and metadata (`app/layout.tsx`):

```tsx
import { Geist, Geist_Mono } from "next/font/google";
import { ThemeProvider } from "next-themes";
import type { Metadata } from "next";
import "./globals.css";

const sans = Geist({ subsets: ["latin"], variable: "--font-geist-sans" });
const mono = Geist_Mono({ subsets: ["latin"], variable: "--font-geist-mono" });

export const metadata: Metadata = {
  title: { default: "Datacake", template: "%s · Datacake" },
  description: "IoT operations on Datacake",
  // app/icon.png (copied from assets/brand/favicon.png) is picked up automatically; add apple-icon.png (180×180) only if you have a larger source
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning className={`${sans.variable} ${mono.variable}`}>
      <body>
        <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>{children}</ThemeProvider>
      </body>
    </html>
  );
}
```

Brand config and logo (`lib/brand.ts`, `components/brand-logo.tsx`): one module holds title and asset paths so customer branding is a one-file change.

```tsx
// lib/brand.ts
export const brand = {
  name: "Datacake",
  logoLight: "/brand/datacake-logo-black.svg",
  logoDark: "/brand/datacake-logo-white.svg",
  markLight: "/brand/datacake-mark-black.svg",
  markDark: "/brand/datacake-mark-white.svg",
} as const;

// components/brand-logo.tsx
import Image from "next/image";
import { brand } from "@/lib/brand";

export function BrandLogo({ variant = "logo", className }: { variant?: "logo" | "mark"; className?: string }) {
  const light = variant === "mark" ? brand.markLight : brand.logoLight;
  const dark = variant === "mark" ? brand.markDark : brand.logoDark;
  const size = variant === "mark" ? { width: 32, height: 32 } : { width: 160, height: 40 }; // wordmark ratio ≈ 4:1, mark ≈ 1:1
  const cls = className ?? (variant === "mark" ? "h-8 w-8" : "h-7 w-auto");
  return (
    <>
      <Image src={light} alt={brand.name} {...size} className={`${cls} dark:hidden`} priority />
      <Image src={dark} alt={brand.name} {...size} className={`${cls} hidden dark:block`} priority />
    </>
  );
}
```

Customer branding: replace the four SVGs in `public/brand/`, `app/icon.png`, the `brand` object and the `--primary`/`--brand*`/`--ring`/`--sidebar-primary`/`--chart-1` values in `globals.css`. Nothing else changes.

## Expo setup

`app.json` (Datacake default):

```json
{
  "expo": {
    "name": "Datacake",
    "slug": "datacake-app",
    "scheme": "datacake",
    "icon": "./assets/brand/icon-1024.png",
    "userInterfaceStyle": "automatic",
    "splash": { "image": "./assets/brand/splash-icon.png", "resizeMode": "contain", "backgroundColor": "#fafafa", "dark": { "backgroundColor": "#0b0f17" } },
    "android": { "adaptiveIcon": { "foregroundImage": "./assets/brand/adaptive-icon.png", "backgroundColor": "#ff0097" } },
    "web": { "favicon": "./assets/brand/favicon.png" }
  }
}
```

NativeWind: put the same hex values into `tailwind.config.js` `theme.extend.colors` (`background`, `foreground`, `card`, `primary`, `muted`, `border`, `success`, `warning`, `destructive`) with `darkMode: "class"` and a `useColorScheme` driven root class; `Geist` via `@expo-google-fonts/geist` (fall back to the system font if the package is unavailable). Wordmark: `react-native-svg` + `react-native-svg-transformer` to import the SVGs, pick black/white by colour scheme.

## Runtime branding for white label portals

A white label site brands the portal for the customers of a Datacake customer. When the tool is served on such a domain (sign-in model A), take title, logo and favicon from the API and keep the Datacake assets as the fallback, exactly like the portal does. No token is needed for this query.

```graphql
query SiteBranding($domain: String!) {
  brandingForDomain(domain: $domain) {
    id title brand domain logo favicon bannerLogo
    allowSignup passwordLoginEnabled ssoEnabled authenticationScreenLayout apiUrl mqttServer
  }
}
```

- `branding` (no argument) resolves the site for the request's host when the tool is deployed on the site domain itself; `brandingForDomain(domain:)` works from anywhere (pass the host header on the server).
- `logo` and `favicon` are absolute URLs or `null`. Resolve once per host on the server (cache for an hour), pass `{ title, logo, favicon, brand }` into `lib/brand.ts` at request time, fall back per field to the Datacake default when `null`.
- `brand` is the value to pass as `brand:` on `signup`, `addUserToWorkspace`, `addWorkspace` and `requestPasswordReset` so emails carry the site branding (`organizations-and-members.md`).
- `passwordLoginEnabled: false` means SSO only: hide the password form. `apiUrl` may differ from `api.datacake.co` for dedicated sites; use it for that site's requests.
- Workspace-scoped tools without a domain: `workspace { whitelabelSite { id title logo favicon } }` gives the default branding of that workspace; `null` means Datacake.

## Checklist

- [ ] Brand decided in intake: Datacake default, customer branding, or runtime white label; assumption stated in the hand-over
- [ ] Assets copied from `assets/brand/` (or customer files) into `public/brand/` and `app/icon.png`; nothing references `${CLAUDE_SKILL_DIR}` at runtime
- [ ] `globals.css` tokens above (light + dark), `components.json` new-york/slate, Geist fonts loaded
- [ ] Dark mode via `next-themes` (`class`, system default, toggle); every page checked in both themes
- [ ] Brand colour only on primary actions, active nav, focus, chart-1; status colours from the state table
- [ ] Wordmark and mark swap with theme (`BrandLogo`, `variant="mark"` in the collapsed sidebar); title template set; `brand` object is the single place for names and paths
- [ ] Customer branding: no "Powered by Datacake" unless requested
