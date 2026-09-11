# Building mobile apps on Datacake (Expo / React Native)

## Contents

- Ask before building
- Stack
- Authentication and token storage
- Screens
- Data, polling and offline
- Push notifications
- Snippets
- Checklist

Only start an Expo project when the user asked for a mobile app. Web dashboards with a responsive layout (see `frontend-nextjs.md`) cover many "app" requests.

## Ask before building

1. Platforms and distribution: iOS, Android, both; TestFlight/internal, app stores, Expo Go for demos?
2. Sign-in model: users with Datacake accounts (token per user) or a single scoped API user behind your own backend? Personal tokens must never ship inside the app binary.
3. Offline expectations: read-only cache of last values, or queued writes?
4. Notifications: are Datacake rule-engine pushes (Datacake app only) enough, or does this app need its own push pipeline?
5. Screens, products, identifiers (run `discover.py`), branding (customer files or the Datacake default: icon, splash and colours in `branding.md`, "Expo setup"). Without a token, follow "Generic mode" in `frontend-nextjs.md` (config module, semantics and role fields, mock provider, connect steps).
6. Admin features (members, invites, organizations) belong in a web tool (`frontend-nextjs.md`, "Admin and white label tools"); keep the mobile app to reading data and acknowledging alerts unless the user insists.

## Stack

| Concern | Default |
|---|---|
| Framework | Expo (managed workflow), Expo Router, TypeScript |
| UI | NativeWind (Tailwind for RN) or Tamagui; `expo-router` tabs; `@expo/vector-icons`; colours, fonts and app icons from `branding.md` |
| Data | TanStack Query with `refetchInterval`; persisted cache via `@tanstack/query-async-storage-persister` for offline reads |
| Secrets | `expo-secure-store` for the user's token; `EXPO_PUBLIC_*` only for non-secret config |
| Charts | `react-native-gifted-charts` or `victory-native` |
| Maps | `react-native-maps` |
| Dates | `date-fns` + `date-fns-tz` |

## Authentication and token storage

- Model A (users sign in): call the `login` mutation from the app, store `token` in `SecureStore`, attach `Authorization: Token …` to every GraphQL request. The token is the user's own, so device/workspace permissions apply. Provide logout (delete from SecureStore) and handle `NOT_AUTHENTICATED` by returning to login.
- Model B (shared API user): the token must live on your backend; the app talks to your backend (REST/GraphQL of your own) which calls Datacake. Do not put an API user token in `EXPO_PUBLIC_*` variables or the bundle.
- Public dashboards: `publicDevice(id:, token:)` needs no account and no secret.

## Screens

| Screen | Data |
|---|---|
| Login | `login` (email, password, optional OTP) |
| Workspace picker | `allWorkspaces` (skip when one workspace) |
| Device list | `devicesFiltered(page, pageSize: 25, search, tags, online, orderBy)`, `roleFields` per row, pull-to-refresh, infinite scroll by `page` |
| Device detail | `device(deviceId)`: current values (`currentMeasurements(fieldNames)`), sparkline/chart (`history`), tags/metadata, last heard |
| KPI / purpose dashboard | semantic aggregates via aliases (see `semantics-and-kpis.md`) |
| Map | devices with `currentLocation`, zones |
| Settings | workspace, units, refresh interval, sign out |

## Data, polling and offline

- Poll current values every 30–60 s while a screen is focused (`refetchInterval`, pause in background with `AppState`).
- Cache the last successful responses (persisted TanStack Query) so lists and last values render offline with an "as of" stamp.
- History: fetch per device with a resolution matched to the range (`queries-measurements.md`); cache per range.
- Writes (`setValue`, `sendDownlink`, `updateDevice`) only when the user has the permission; show optimistic UI carefully and refetch afterwards.

## Push notifications

- Datacake's rule engine `PUSH` action delivers only to the official Datacake mobile app. A custom app needs its own pipeline: Expo Push (`expo-notifications`) + a backend that receives rule-engine **webhook** actions or outgoing webhooks and forwards them to Expo's push service.
- Alternative without backend: in-app polling of alert queries (`devicesFiltered` with thresholds) plus local notifications while the app runs.

## Snippets

GraphQL helper with secure token:

```typescript
import * as SecureStore from "expo-secure-store";

const ENDPOINT = "https://api.datacake.co/graphql/";

export async function datacake<T>(query: string, variables: Record<string, unknown> = {}): Promise<T> {
  const token = await SecureStore.getItemAsync("dc_token");
  const res = await fetch(ENDPOINT, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Token ${token}` } : {}) },
    body: JSON.stringify({ query, variables }),
  });
  const json = await res.json();
  if (json.errors?.length) {
    const code = json.errors[0].extensions?.code;
    if (code === "NOT_AUTHENTICATED") await SecureStore.deleteItemAsync("dc_token");
    throw new Error(json.errors[0].message);
  }
  return json.data as T;
}

export async function signIn(email: string, password: string, otp?: string) {
  const data = await datacake<{ login: { ok: boolean; token?: string; error?: string } }>(
    `mutation Login($email: String!, $password: String!, $otp: String) {
       login(email: $email, password: $password, otpToken: $otp) { ok token error } }`,
    { email, password, otp });
  if (!data.login.ok || !data.login.token) throw new Error(data.login.error ?? "Login failed");
  await SecureStore.setItemAsync("dc_token", data.login.token);
}
```

Device list hook:

```typescript
import { useInfiniteQuery } from "@tanstack/react-query";
import { datacake } from "@/lib/datacake";

const LIST = `query List($workspaceId: String!, $page: Int!, $search: String) {
  workspace(id: $workspaceId) {
    devicesFiltered(page: $page, pageSize: 25, search: $search, orderBy: { verboseName: ASC }) {
      total
      devices { id verboseName online lastHeard roleFields { role value field { unit } } }
    }
  }
}`;

export function useDevices(workspaceId: string, search?: string) {
  return useInfiniteQuery({
    queryKey: ["devices", workspaceId, search],
    initialPageParam: 0,
    queryFn: ({ pageParam }) => datacake<any>(LIST, { workspaceId, page: pageParam, search: search || null })
      .then((d) => d.workspace.devicesFiltered),
    getNextPageParam: (last, pages) => (pages.length * 25 < last.total ? pages.length : undefined),
    refetchInterval: 60_000,
  });
}
```

## Checklist

- [ ] Sign-in model agreed; no API user token in the bundle
- [ ] Token in SecureStore; logout and `NOT_AUTHENTICATED` handling
- [ ] Lists paginated; KPIs via aggregates; history per device with proper resolution
- [ ] Offline cache with "as of" stamps; polling paused in background
- [ ] Push strategy decided (own pipeline vs none)
- [ ] Identifiers per product in one module (from `discover.py`)
- [ ] App icon, splash and colour scheme applied (`branding.md`); light and dark checked
