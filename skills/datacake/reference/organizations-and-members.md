# Organizations, workspaces, members, invites and white label sites

Everything needed for admin tooling: an internal admin console, a white label "customer admin" portal, bulk onboarding scripts, access audits. Reads first, then mutations, then recipes that combine them. All documents validate against `reference/schema.graphql`; use them as-is.

## Contents

- Model: who is what
- Who can see what
- Reads: organizations and their admins
- Reads: workspaces and members
- Reads: white label users, audit log, SSO
- Mutations: organization admins
- Mutations: workspace members, invites, permissions, API users
- Mutations: workspaces and branding
- Recipes
- Caveats and safety

## Model: who is what

| Kind | Type | Scope | Rights | Created by |
|---|---|---|---|---|
| Organization admin | `UserOrganizationRelationshipType` (`user`, `permissions: [UserOrganizationPermissions]`) | organization | `create_workspaces`, `members` (manage admins), `billing`, `whitelabel`, `manage_workspaces`; exactly one `owner` | `createUserOrganizationRelationships` |
| Workspace member | `UserWorkspaceRelationshipType` (`user`, `permissions: [WorkspacePermissions]`, `deviceRelationships`, `allDevicesPermissionExists`, `allDevicePermissions`, `isOrganizationOwner`) | one workspace | workspace permissions (`devices`, `rules`, `members`, …) plus per-device permissions (`edit_basics`, `edit_product`, `record_measurements`) | `addUserToWorkspace` |
| API user | `ApiUserWorkspaceRelationshipType` (`user { id name apiKey created }`, `permissions`, `deviceRelationships`) | one workspace | same permission model as a member, token only, no login | `addApiUser` |
| Pending invite | `UserWorkspaceInviteType` (`email`, `permissions`, `deviceInvites { device permissions }`) | one workspace | becomes a member when the invitee signs up with that email | `addUserToWorkspace` for an unknown email |
| White label user | `WhitelabelUserType` (`firstName`, `lastName`, `email`, `dateJoined`, `lastVisit`) | one white label site | an account that signed up on, or was invited through, that site; not a permission | signup / invite with `brand` |

Rules that follow from the model:

- Organization admins are not workspace members. An org admin with `manage_workspaces` sees every workspace of the organization in `organization.workspaces`, but reading a workspace's members or devices still requires being a member of that workspace with the respective permission (see caveats).
- The organization owner is an admin with all permissions; `isOrganizationOwner` on a workspace relationship marks that person, and the owner cannot be removed from workspaces of the organization.
- A user can be admin of several organizations and member of any number of workspaces across organizations.
- `organization.permissions` and `workspace.myPermissions` always describe the caller, never another user.

## Who can see what

| Query | Returns | Requirement |
|---|---|---|
| `user` | the caller (`isApiuser`, `whitelabelSites`, `primaryWorkspace`) | any token |
| `allWorkspaces` | workspaces the caller is a member of | any token |
| `organizations(permissionFilter:)` | organizations the caller administers, optionally only those where they hold one permission | user token (API users have no organization relationships) |
| `organization(id) { permissions }` | the caller's own organization permissions | admin of that organization |
| `organization.workspaces` | every workspace of the organization, whether or not the caller is a member | organization admin |
| `organization.userRelationships` | the organization admins | organization admin |
| `workspace.userRelationships`, `invitedUsers`, `apiUserRelationships`, `member(id)` | members of one workspace | workspace `members` permission |
| `device.relationshipsInfo(workspace)` | users with explicit permissions on one device | workspace `members` |
| `whitelabelSite(id) { users auditLogEntries ssoDomains }` | white label users, audit log, SSO domains | organization `whitelabel`; users and log additionally need `organization.entitlementWhitelabelShowUsersAndLogs` |

Gate an admin UI the way the portal does: show the organization section when `organization.permissions` contains `billing`, `members`, `manage_workspaces` or `whitelabel`; show the workspace members page when `workspace.myPermissions` contains `members`.

## Reads: organizations and their admins

```graphql
query MyOrganizations($permission: UserOrganizationPermissions) {
  user { id email isApiuser }
  organizations(permissionFilter: $permission, orderBy: NAME_ASC, first: 50) {
    totalCount
    pageInfo { hasNextPage endCursor }
    edges {
      node {
        id
        name
        permissions
        owner { id user { id email fullName } }
        totalDevices
        entitlementDeviceQuota
        entitlementRemainingDeviceQuota
        entitlementWorkspacesQuota
        entitlementRemainingWorkspacesQuota
        subscriptionUnpaid
        workspaces { totalCount }
        userRelationships { totalCount }
        whitelabelSites { totalCount }
      }
    }
  }
}
```

`permissionFilter: members` narrows to organizations where the caller may manage admins; omit it for "every organization I administer". Page with `after: endCursor`. Organization ids are Relay global ids but work as UUID strings in `organization(id:)`.

Organization admins with search, sorting and pagination (the portal's admin list):

```graphql
query OrganizationAdmins($id: UUID!, $query: String, $first: Int = 50, $offset: Int = 0, $orderBy: OrganizationUserRelationshipsOrder = USER_EMAIL_ASC) {
  organization(id: $id) {
    id
    name
    permissions
    owner { id user { id } }
    userRelationships(
      first: $first
      offset: $offset
      orderBy: $orderBy
      filter: { or: [
        { user: { firstName: { icontains: $query } } }
        { user: { lastName: { icontains: $query } } }
        { user: { email: { icontains: $query } } }
      ] }
    ) {
      totalCount
      edges { node { id permissions user { id email fullName firstName lastName } } }
    }
  }
}
```

With `$query` null the filter matches everyone. Filter operators are `exact`, `contains`, `icontains` on `firstName`, `lastName`, `email`, combinable with `and`, `or`, `not`. The relationship `id` (not the user id) is what update, delete and ownership transfer need.

Workspaces of an organization:

```graphql
query OrganizationWorkspaces($id: UUID!, $after: String, $name: String) {
  organization(id: $id) {
    id
    deviceQuotaDistributionMode
    workspaces(first: 100, after: $after, orderBy: NAME_ASC, filter: { name: { icontains: $name } }) {
      totalCount
      pageInfo { hasNextPage endCursor }
      edges {
        node {
          id
          name
          slug
          deviceCount
          memberCount
          myPermissions
          features
          whitelabelSite { id title }
          entitlementDeviceQuota
          entitlementDeviceQuotaRemaining
        }
      }
    }
  }
}
```

`myPermissions` is empty for workspaces the caller is not a member of; `memberCount` and `deviceCount` still resolve for organization admins. Use this list to decide which workspaces a members query can be run against.

## Reads: workspaces and members

Members, pending invites and API users of one workspace (the portal's members page):

```graphql
query WorkspaceMembers($workspaceId: String!) {
  workspace(id: $workspaceId) {
    id
    name
    myPermissions
    organization { id name }
    userRelationships {
      id
      permissions
      allDevicesPermissionExists
      allDevicePermissions
      isOrganizationOwner
      user { id email fullName firstName lastName language }
      deviceRelationships { id permissions device { id verboseName serialNumber } }
    }
    invitedUsers {
      id
      email
      permissions
      deviceInvites { id permissions device { id verboseName } }
    }
    apiUserRelationships {
      id
      permissions
      user { id name created }
      deviceRelationships { id permissions device { id verboseName } }
    }
  }
}
```

`userRelationships(includeApiUsers: true)` merges API users into the same list (their `user.isApiuser` is true); the separate `apiUserRelationships` is clearer for admin screens. `allDevicesPermissionExists` means the member has a workspace-wide device permission set (`allDevicePermissions`) instead of per-device entries. Never select `apiUser.apiKey` in a list screen; it is the token.

One member with everything they may do:

```graphql
query MemberDetail($workspaceId: String!, $userId: String!) {
  workspace(id: $workspaceId) {
    id
    member(id: $userId) {
      id
      email
      fullName
      isApiuser
      workspaceRelationship(workspace: $workspaceId) {
        id
        permissions
        isOrganizationOwner
        allDevicesPermissionExists
        allDevicePermissions
      }
      deviceRelationships(workspace: $workspaceId) {
        id
        permissions
        emailOffline
        device { id verboseName serialNumber online product { id name } }
      }
    }
  }
}
```

Who has access to one device:

```graphql
query DeviceAccess($workspaceId: String!, $deviceId: String!) {
  device(deviceId: $deviceId) {
    id
    verboseName
    myPermissions(workspace: $workspaceId)
    relationshipsInfo(workspace: $workspaceId) {
      id
      permissions
      user { id email fullName isApiuser }
    }
    usersWithAccess(workspace: $workspaceId) { id accessType user { id email fullName } }
  }
}
```

`relationshipsInfo` lists explicit per-device grants; `usersWithAccess` also includes members who see the device through a workspace-wide grant (`accessType`).

Organization-wide member directory (no single query exists; nest and deduplicate):

```graphql
query OrganizationMemberDirectory($id: UUID!, $after: String) {
  organization(id: $id) {
    id
    workspaces(first: 50, after: $after, orderBy: NAME_ASC) {
      pageInfo { hasNextPage endCursor }
      edges {
        node {
          id
          name
          slug
          myPermissions
          userRelationships { id permissions isOrganizationOwner user { id email fullName } }
          invitedUsers { id email permissions }
        }
      }
    }
  }
}
```

`userRelationships` is `null` (with a `NOT_AUTHORIZED` error entry) for workspaces where the caller lacks `members`; keep the workspace row and mark it unreadable rather than failing the whole page. Deduplicate by `user.id` in code and keep the list of workspaces per user. `scripts/members.py org-list <orgId>` implements exactly this.

## Reads: white label users, audit log, SSO

White label sites the caller may administer, and the site behind a workspace:

```graphql
query MyWhitelabelSites($workspaceId: String!) {
  user { id whitelabelSites { id title domain brand allowSignup restrictLoginToWhitelabelSite autoAssignSignupsToOrganization ssoEnabled emailVerified organization { id name } } }
  workspace(id: $workspaceId) { id whitelabelSite { id title } }
}
```

`brand` is the value to pass as `brand:` on `signup`, `addUserToWorkspace`, `addWorkspace` and `requestPasswordReset` so that emails and links carry that site's branding; the portal passes the site `id` and the API accepts it too. `branding` (current host) and `brandingForDomain(domain:)` return the site for a login page without a token.

Users of a white label site (needs `organization.entitlementWhitelabelShowUsersAndLogs`):

```graphql
query WhitelabelUsers($siteId: UUID!, $query: String, $first: Int = 50, $offset: Int = 0, $orderBy: WhitelabelUserOrder = LAST_VISIT_DESC) {
  whitelabelSite(id: $siteId) {
    id
    title
    organization { id entitlementWhitelabelShowUsersAndLogs entitlementEnterpriseSsoEnabled }
    users(first: $first, offset: $offset, orderBy: $orderBy, filter: { or: [
      { email: { contains: $query } }
      { firstName: { contains: $query } }
      { lastName: { contains: $query } }
    ] }) {
      totalCount
      pageInfo { hasNextPage endCursor }
      edges { node { id firstName lastName email dateJoined lastVisit } }
    }
  }
}
```

White label user filters offer `exact` and `contains` only (case-sensitive). Sorting: `FIRST_NAME`, `LAST_NAME`, `EMAIL`, `LAST_VISIT`, `DATE_JOINED`, `ID` with `_ASC`/`_DESC`. White label user ids are Relay ids of that connection, not `UserType.id`; to act on such a user (permissions, removal) look them up by email in the workspace members list.

Audit log of a white label site:

```graphql
query WhitelabelAuditLog($siteId: UUID!, $action: String, $email: String, $first: Int = 50, $offset: Int = 0) {
  whitelabelSite(id: $siteId) {
    id
    auditLogEntries(first: $first, offset: $offset, orderBy: CREATED_DESC, filter: {
      action: { exact: $action }
      user: { email: { contains: $email } }
    }) {
      totalCount
      pageInfo { hasNextPage endCursor }
      edges { node { id created action details targetContentType targetObjectId user { id email fullName } } }
    }
  }
}
```

User and detail filters offer `exact` and `contains` (case-sensitive). `action` values (`AuditLogEntryAction`): `LOGIN`, `PASSWORD_RESET`, `PASSWORD_CHANGE`, `USER_INVITE`, `USER_REMOVE`, `USER_WORKSPACE_PERMISSIONS`, `USER_DEVICE_PERMISSIONS`, `ORGANIZATION_MEMBER_ADD`, `ORGANIZATION_MEMBER_REMOVE`, `ORGANIZATION_MEMBER_PERMISSIONS`, `ORGANIZATION_TRANSFER_OWNERSHIP`, `CONFIG_CHANGE`, `DEVICE_CONFIG_CHANGED`, `DEVICE_DELETED`, `DEVICE_REMOVED`, `DEVICE_DATA_DELETED`, `PRODUCT_DELETED`, `DOWNLINK_SEND`, `SUBSCRIPTION_CANCELLED`. The action filter takes the enum name as a string (`exact: "USER_INVITE"`). `details` is free text; `targetContentType` and `targetObjectId` identify the affected object (workspace, device, user). The log covers actions performed by users of that site; there is no organization-level audit log outside white label.

SSO domains of a white label site (WorkOS enterprise SSO, needs `entitlementEnterpriseSsoEnabled`):

```graphql
query WhitelabelSso($siteId: UUID!) {
  whitelabelSite(id: $siteId) {
    id
    ssoEnabled
    allowPasswordLogin
    passwordLoginEnabled
    ssoDomains { domain verified ssoVerificationRecordName ssoVerificationRecordValue }
  }
}
```

## Mutations: organization admins

All take `organizationId` and need the organization `members` permission; the owner can do everything. Invitees who have no account yet cannot be organization admins: `createUserOrganizationRelationships` needs an existing user (`email` or `id`). Results echo the relationships; errors arrive as top-level `errors` with `extensions.code`.

```graphql
mutation AddOrgAdmins($input: CreateUserOrganizationRelationshipsInputType!) {
  createUserOrganizationRelationships(input: $input) { ok userRelationships { id permissions user { id email } } }
}
```

`input`: `{ organizationId, relationships: [{ user: { email: "ops@example.com" }, permissions: [members, manage_workspaces] }, { user: { id: "<user uuid>" }, permissions: [billing] }] }`. One call handles any number of users. Permissions: `create_workspaces`, `members`, `billing`, `whitelabel`, `manage_workspaces`.

```graphql
mutation UpdateOrgAdmins($input: UpdateUserOrganizationRelationshipsInputType!) {
  updateUserOrganizationRelationships(input: $input) { ok userRelationships { id permissions } }
}
```

`input`: `{ organizationId, relationships: [{ id: "<relationship id>", permissions: { set: [members, billing] } }] }`, or `permissions: { add: [...] }` / `{ remove: [...] }` for incremental changes.

```graphql
mutation RemoveOrgAdmins($input: DeleteUserOrganizationRelationshipsInputType!) {
  deleteUserOrganizationRelationships(input: $input) { ok userRelationships { id } }
}
```

`input`: `{ organizationId, relationships: [{ id }] }`. Removing an admin does not touch their workspace memberships.

```graphql
mutation TransferOwnership($input: TransferOrganizationOwnershipInputType!) {
  transferOrganizationOwnership(input: $input) { ok organization { id owner { id user { id email } } } }
}
```

`input`: `{ organizationId, userRelationshipId }`; only the current owner may call it. Confirm with the user, it is irreversible without the new owner's cooperation.

## Mutations: workspace members, invites, permissions, API users

Need the workspace `members` permission. `workspace` arguments take the workspace UUID as a string.

Invite or add a user:

```graphql
mutation Invite($input: AddUserToWorkspaceInputType!) {
  addUserToWorkspace(input: $input) {
    ok
    invited
    workspace { id invitedUsers { id email permissions } userRelationships { id user { id email } permissions } }
  }
}
```

`input`: `{ workspace, email, wsPermissions: [devices, rules], deviceRelationships: [{ device: "<device uuid>", permissions: [edit_basics] }], brand: "<white label site id>" }`.

- `invited: false` means the email already had an account and the user is a member now. `invited: true` means an invitation email was sent and the address appears in `invitedUsers` until the person signs up with that email; then the pending workspace and device permissions are applied automatically. There is no accept mutation.
- `deviceRelationships: []` gives an observer without device access; devices they should see must be listed, or granted later with `setUserDevicePermissions`.
- `brand` selects the white label site whose name, logo, sender address and domain appear in the email; omit it for Datacake branding. Take the value from `workspace.whitelabelSite.id` or `user.whitelabelSites`.
- One email per call. For many addresses loop (recipe below).

Change workspace permissions of a member (changeset, replaces the deprecated `setWorkspaceUserPermissions`):

```graphql
mutation SetWorkspacePermissions($input: UpdateWorkspacePermissionsInputType!) {
  updateWorkspacePermissions(input: $input) { ok relationship { id permissions } }
}
```

`input`: `{ workspaceId, userId, changeset: [{ permission: rules, permitted: true }, { permission: members, permitted: false }] }`. Permissions not mentioned stay as they are. Works for API users too (`userId` = API user id).

Device permissions of a member, whole set at once (replaces existing entries for the listed devices):

```graphql
mutation SetDevicePermissions($input: SetUserDevicePermissionsInputType!) {
  setUserDevicePermissions(input: $input) {
    ok
    workspace { id member(id: "USER-ID") { id deviceRelationships(workspace: "WORKSPACE-ID") { id permissions device { id } } } }
  }
}
```

`input`: `{ workspace, user, permissions: [{ device, permissions: [edit_basics, record_measurements] }] }`. An empty `permissions` list on a device removes the grant; `permissions: []` at the top level removes every device from the user.

Per device, for several users (the device permissions dialog):

```graphql
mutation GrantOnDevice($input: AddDevicePermissionsInputType!) {
  addDevicePermissions(input: $input) { ok device { id relationshipsInfo(workspace: "WORKSPACE-ID") { user { id email } permissions } } }
}
```

`input`: `{ workspace, device, permissions: [{ user, permissions: [] }] }` (empty permissions = view only). `removeDevicePermissions` has the same input shape and revokes the listed users.

Remove a member or a pending invite:

```graphql
mutation RemoveMember($userId: String!, $workspaceId: String!) {
  removeUserFromWorkspace(userId: $userId, workspaceId: $workspaceId) { ok }
}
```

```graphql
mutation CancelInvite($email: String!, $workspaceId: String!) {
  deleteUserInvite(email: $email, workspace: $workspaceId) { ok }
}
```

The organization owner cannot be removed. Removing a user deletes their device relationships in that workspace; their account and other memberships stay.

API users:

```graphql
mutation NewApiUser($input: ApiUserInput!) {
  addApiUser(input: $input) { ok apiUser { id name apiKey created } }
}
```

`input`: `{ workspace, name, wsPermissions: [], deviceRelationships: [{ device, permissions: [] }] }`. `apiKey` is the token; show it once and never store it in the app. `updateApiUser(id, name)` renames, `deleteApiUser(id)` revokes the token immediately, `updateWorkspacePermissions` and `setUserDevicePermissions` change what it may do.

## Mutations: workspaces and branding

```graphql
mutation NewWorkspace($name: String!, $organizationId: BlankableUUID, $brand: String) {
  addWorkspace(name: $name, organizationId: $organizationId, brand: $brand) { ok workspace { id slug name organization { id } } }
}
```

`organizationId` set: the workspace joins that organization (caller needs `create_workspaces`, quota `entitlementRemainingWorkspacesQuota`). Empty or omitted: a new organization with its own billing is created, owned by the caller. `brand` marks the workspace as belonging to a white label site (welcome emails, default branding). The caller becomes a member with all permissions.

```graphql
mutation BrandWorkspace($id: UUID!, $siteId: BlankableUUID, $name: String) {
  updateWorkspace(id: $id, whitelabelSiteId: $siteId, name: $name) { ok workspace { id name whitelabelSite { id title } } }
}
```

`whitelabelSiteId: ""` detaches the site. `deleteWorkspace(id)` needs no active subscriptions (`workspace.deletePreventCause` explains a refusal) and is irreversible: confirm first.

Enterprise SSO on a white label site (organization `whitelabel` permission, `entitlementEnterpriseSsoEnabled`):

```graphql
mutation SsoDomain($input: AttachSsoDomainInputType!) {
  attachSsoDomain(input: $input) { ok error { code details } }
}
```

`input`: `{ whitelabelSite, domain }`; afterwards `ssoDomains` carries the DNS TXT record to publish, `verified` flips once WorkOS confirms it. `detachSsoDomain(input: { whitelabelSite, domain })` removes it. `generateWorkosAdminPortalLink(input: { whitelabelSite, returnUrl })` returns a one-time `link` to the WorkOS admin portal where the customer's IT connects their identity provider; `updateWhitelabelSite(input: { whitelabelSite, allowPasswordLogin: false })` enforces SSO-only sign-in. White label site configuration beyond this (domains, email DKIM, banner, feature hiding) is indexed in `schema-map.md` under "White label".

## Recipes

**Mass invite.** Read `WorkspaceMembers` once; skip emails already in `userRelationships` or `invitedUsers`; call `Invite` per remaining email with at most 5 in flight; collect `invited` per address and report "added instantly" vs "invitation sent" vs error (`VALIDATION_ERROR` for malformed emails, `NOT_AUTHORIZED` without `members`). Use one `brand` for the batch. `scripts/members.py invite <workspace> --file emails.txt --permissions devices --brand <siteId>` does this with a dry run by default.

**Move a member between workspaces.** No move mutation exists; compose it and keep the source until the target is verified:

1. `MemberDetail` in the source workspace: `permissions`, `allDevicesPermissionExists`/`allDevicePermissions`, `deviceRelationships`.
2. Map device relationships to the target: devices that were moved keep their `serialNumber`, so resolve `workspace(id: target) { device(serialNumber:) { id } }`; devices that do not exist in the target are reported and skipped.
3. `Invite` on the target with the same `wsPermissions` and the mapped `deviceRelationships` (`invited` is false because the account exists). If the source had a workspace-wide device grant, there is no input for that on invite: grant per device, or ask an admin to set it in the portal.
4. Re-read `MemberDetail` on the target and compare.
5. `RemoveMember` on the source, unless the user should keep both memberships.

API users are workspace-bound: create a new one in the target (`NewApiUser`), hand over the new key, then `deleteApiUser` in the source. The organization owner cannot be removed from a source workspace; moving the owner means "add to target" only.

**Copy a permission profile.** Take `permissions` and `deviceRelationships` from a reference member and apply them to a list of users with `SetWorkspacePermissions` (build the changeset as every `WorkspacePermissions` value with `permitted` true or false, so the result is exact) and `SetDevicePermissions`.

**Offboard a user from an organization.** `OrganizationMemberDirectory` to find every workspace where `user.email` matches, `RemoveMember` in each, `CancelInvite` for pending invites, `RemoveOrgAdmins` if they are an admin (find the relationship id via `OrganizationAdmins` with `$query` = email). Report workspaces that were unreadable (missing `members`), they need a workspace admin.

**Find a user across an organization.** `OrganizationAdmins` with `$query` for admins, `OrganizationMemberDirectory` for memberships, `WhitelabelUsers` with `$query` for sign-up date and last visit. Match on email; user ids are the same object across workspaces but white label user ids are not.

**Gate admin pages.** After login fetch `user { id whitelabelSites { id } }`, `organizations { edges { node { id name permissions } } }`, `allWorkspaces { id name myPermissions }`. Organization menu when any permission of `billing`, `members`, `manage_workspaces`, `whitelabel` is present (billing only when the deployment supports it); workspace members page when `myPermissions` contains `members`; white label users and audit log when `whitelabel` is present and `entitlementWhitelabelShowUsersAndLogs` is true.

**Branded invitations from a white label admin tool.** Resolve the site once (`workspace.whitelabelSite.id`, or the site the admin is operating from via `brandingForDomain(domain:)`), pass it as `brand` on every `addUserToWorkspace` and `addWorkspace`; new workspaces created for customers get `updateWorkspace(whitelabelSiteId:)` if they were created without `brand`.

## Caveats and safety

- Reading members of a workspace needs the `members` permission in that workspace; organization permissions do not substitute. An admin console that must see every member needs its operator invited into each workspace with `members`, or the tool is scoped to the workspaces the operator belongs to. Verify with `tools/smoke_test.py` (organizations section) on the deployment at hand.
- API users cannot administer organizations: `organizations` is empty for them and organization mutations fail with `NOT_AUTHORIZED`. Admin tools use a real user login (frontend model A).
- No bulk workspace invite and no move mutation exist; both are loops in your code. Keep concurrency low (5) and expect per-item failures.
- Invitations resolve at signup with the exact email; there is no accept, resend or expiry mutation. To "resend", delete and re-create the invite.
- Removal is immediate and not undoable; ownership transfer is one-way. Confirm both with the user and show the affected workspaces first.
- `invited`, `ok` and top-level `errors` must all be checked; a mutation can return `ok: true` for one alias and errors for another in the same document.
- Relay connections (`organizations`, `organization.workspaces`, `userRelationships`, white label `users`, `auditLogEntries`) page with `first`/`after` or `first`/`offset`; workspace members are plain lists (no paging).
- White label user lists and audit logs are entitlement-gated (`entitlementWhitelabelShowUsersAndLogs`); SSO needs `entitlementEnterpriseSsoEnabled`. Absent entitlement returns `NOT_AUTHORIZED`, not an empty list.
- Never expose `apiKey`, `accessToken` or personal tokens in an admin UI beyond the one-time display after creation.
