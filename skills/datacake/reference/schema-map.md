# Schema map

A curated index of the Datacake GraphQL schema. The full SDL is `reference/schema.graphql` (~230 KB): grep it for exact argument and field lists instead of reading it whole. The blocks marked "generated" are rewritten by `python3 scripts/fetch_schema.py`; edit only the curated sections by hand.

## Contents

- How to look things up
- Root queries (generated)
- Key object types (curated)
- Enums (generated)
- Mutations by theme (generated)
- Input types worth knowing

## How to look things up

```bash
grep -n "^type DeviceType" -A 100 reference/schema.graphql          # a type and its fields
grep -n "^input CreateLoraDevicesInputType" -A 20 reference/schema.graphql
grep -n "^enum FieldSemantic" -A 45 reference/schema.graphql
grep -n "  devicesFiltered(" -A 60 reference/schema.graphql            # a field with its arguments
grep -n "^  [a-zA-Z]*Rule[a-zA-Z]*(" reference/schema.graphql          # every root field mentioning Rule
grep -n "^union\|^interface" reference/schema.graphql
```

Conventions: `Query` is the query root, `Mutations` the mutation root, there is no subscription root. `!` = non-null, `[X]` = list. Most mutations take a single `input` object named `<Mutation>InputType` and return `{ ok, <object>, error }`.

## Root queries (generated)

<!-- generated:start:query-roots -->
- `export(id: UUID!) -> ExportType`
- `exportRun(id: UUID!) -> ExportRunType`
- `reportBuilderReport(id: UUID!) -> ReportBuilderReportType`
- `reportBuilderReportRun(id: UUID!) -> ReportBuilderReportRunType`
- `reportBuilderReportPreview(workspaceId: UUID!, reportId: UUID!, schema: ReportBuilderSchema!, schedule: ReportBuilderCronExpression!, timezone: String!, deviceFilterName: String!, deviceFilterTags: [String!]!, deviceFilterTagsConjunction: ReportBuilderDeviceTagsFilterConjunction!) -> ReportBuilderReportPreviewType`
- `reportBuilderPublicReportRun(id: UUID!, secretToken: String!) -> ReportBuilderPublicReportRunType`
- `reportBuilderLink(id: UUID!, password: String!) -> ReportBuilderReportRunLinkType`
- `organization(id: UUID!) -> OrganizationType`
- `organizations(permissionFilter: UserOrganizationPermissions, offset: Int, before: String, after: String, first: Int, last: Int, filter: OrganizationFilterInputType, orderBy: OrganizationOrder) -> OrganizationTypeConnection`
- `parseDate(date: String!, timezone: String!) -> DateTime`
- `apiTemplates -> [ApiTemplateType]`
- `draginonbiotTemplates -> [DraginoNBIoTTemplateType]`
- `draginoDeviceIdAvailable(deviceId: String!) -> Boolean`
- `cellular1nceTemplates -> [Cellular1nceTemplateType!]!`
- `particleTemplates -> [ParticleTemplateType]`
- `particleIdAvailable(particleId: String!) -> Boolean`
- `loraDevices -> [LoraDeviceType]`
- `devEuiAvailable(devEui: String!) -> Boolean`
- `ruleNG(id: UUID!) -> RuleNGType`
- `webhookLogs(webhookId: String!) -> [WebhookLogType]`
- `rule(rule: String!) -> CloudRuleType`
- `gateway(id: UUID!) -> GatewayType`
- `gatewayEuiAvailable(eui: String!) -> Boolean!`
- `branding -> WhitelabelSiteType`
- `brandingForDomain(domain: String!) -> WhitelabelSiteType`
- `whitelabelSite(id: UUID!) -> WhitelabelSiteType`
- `previewPlanSwitch(organizationId: UUID!, targetPlanSlug: String!) -> PlanSwitchPreviewType`
- `devicePlans(existingDevice: String) -> [DevicePlanType!]!`
- `stripePriceIds -> [StripePrice!]!`
- `billingPlans(organization: UUID!) -> [BillingPlanType!]!`
- `availableAddOnPackages(organization: UUID!) -> [AddOnPackageType!]!`
- `user -> UserType`
- `allWorkspaces -> [WorkspaceType]`
- `dashboard(id: String) -> DashboardType`
- `dashboardPublicLink(publicLink: DashboardPublicLinkAuthInputType) -> DashboardPublicLinkType`
- `workspace(id: String, slug: String) -> WorkspaceType`
- `view(id: String!) -> ViewType`
- `downlink(id: UUID!) -> DownlinkType`
- `alert(id: String!) -> AlertType`
- `product(id: String!) -> ProductType`
- `publicDevice(id: String!, token: String!) -> PublicDeviceType`
- `serialNumberAvailable(serialNumber: String!) -> Boolean`
- `dashboardMeta(id: String) -> DashboardMetaType`
- `dashboardMetaAll(ids: [String]) -> [DashboardMetaType]`
- `currentMeasurement(deviceId: String!, fieldName: String!) -> DeviceCurrentMeasurementType`
- `currentMeasurements(deviceId: String!, fieldNames: [String!]!) -> [DeviceCurrentMeasurementType]`
- `allProducts -> [ProductType]`
- `allDevices(idIn: [UUID!], inWorkspace: String, isProduct: String, isProductKind: String, online: Boolean, searchName: String, searchTag: String, searchTags: [String], searchTagsAnyAll: SearchTagsAnyAll) -> [DeviceType!]`
- `device(deviceId: String, particleId: String, dashboard: String) -> DeviceType`
<!-- generated:end:query-roots -->

## Key object types (curated)

**UserType**: `id`, `email`, `firstName`, `lastName`, `fullName`, `language`, `phoneNumber`, `isApiuser`, `apiKey` (own token), `primaryWorkspace`, `workspaceRelationship(workspace)`, `deviceRelationships(workspace)`, `allDevices` (id + name only), `otpTotpDevices`, `features`, `whitelabelSites`.

**WorkspaceType**
- Identity: `id`, `name`, `slug`, `logo`, `organization`, `whitelabelSite`, `features`, `myPermissions`, `entitlement*` (device/rules/webhooks/exports quotas), `deletePreventCause`.
- Devices: `devices(page, search, pageSize, all)`, `devicesFiltered(...)` → `FilteredDeviceList`, `device(id | serialNumber)`, `deviceCount(search)`, `products(hardware, includeProductsFromClaimedDevices)`, `allTags`, `allMetadataKeys`, `semantics`, `deviceFolders` (JSON), `deviceSuggestions`, `incomingDeviceMoveRequests`, `outgoingDeviceMoveRequests`.
- People: `users`, `member(id)`, `userRelationships(includeApiUsers)`, `apiUserRelationships`, `invitedUsers`, `pushRecipientCandidates`.
- Automation: `rulesNG`, `rules` (legacy), `rule(rule)`, `hasLegacyRules`, `alerts`, `webhooks`, `webhook(id)`, `reports`, `report(id)`, `reportBuilderReports`, `reportBuilderReportRuns`, `exports`, `exportRuns`.
- Views: `dashboards`, `dashboard(id)`, `homeDashboard`, `views`, `sidebarConfig`.
- Location: `zones`, `zone(id)`, `devicesInZones`, `deviceZoneEvents`, `zoneTags`, `gateways`.
- Integrations: `mqttServers`, `mqttServer(id)`, `particleAccounts`, `cellular1nceConfigurations`, `managedttiConfigurations`, `lorawanActilityThingparkConfigs`, `cakeredServers`.
- Billing/SMS: `billingAddress`, `paymentMethods`, `taxId`, `canPurchase`, `devicesSubscription`, `activeAddOnSubscriptions`, `smsQuota`, `smsMode`, `smsMessages`, `smsMessageCount(start, end)`.

**DeviceType**
- Identity/state: `id`, `verboseName`, `serialNumber`, `claimSerialNumber`, `product`, `tags`, `metadata` (JSON), `location`, `icon`, `iconOverride`, `image`, `created`, `online`, `lastHeard`, `lastHeardThreshold`, `softwareVersion`, `features`, `internalId`, `active`, `activationProviders`.
- Data: `currentMeasurements(fieldNames, allActiveFields, fieldVerboseNames)`, `currentMeasurement(fieldName)`, `history(fields, timerangestart, timerangeend, resolution, nodatathreshold, locf)`, `historyNg(start, end, resolution)`, `historyStats(start, end)`, `dashboardData(dashboard, dashboardConfig, widgetIds)`, `roleFields`, `numericSemanticField(semantic, aggregation)`, `booleanSemanticField(semantic, aggregation)`, `currentConfigurationValues`, `measurements24h`.
- Location: `currentLocation { lat lng }`, `currentLocationVerbose`, `currentLocationLastUpdate`, `deviceInZones(workspaceId, ...)`.
- Access: `myPermissions(workspace)`, `relationships(workspace)`, `relationshipsInfo(workspace)`, `usersWithAccess(workspace)`, `notifyOffline(workspace)`, `inWorkspaces(currentWorkspace)`, `claimed`, `claimingEnabled`, `claimCode`, `claims`, `publicLinks`, `jwtToken`.
- Commercial: `plan(workspace)`, `isOverQuota`, `simDataUsage`, `cellularRssi`.
- Automation: `rules` (legacy), `cloudRules`, `dzeroRules`, `debugLog`.
- LoRaWAN: `ttnDevId`, `ttiDevId`, `ttiJoinEui`, `ttiAppKey`, `heliumDevId`, `lorawanDeviceClass`, `ttiFrequencyId`, `ttnMapping`.

**ProductType**: `id`, `name`, `slug`, `icon`, `hardware`, `workspace`, `deviceCount`, `lastHeardThreshold`, `measurementFields(active, includeRaw)`, `measurementField(id | fieldName)`, `measurementFieldSuggestions`, `configurationFields`, `configurationField(id | fieldName)`, `dashboards` (JSON), `dashboardConfig`, `dashboardChangelog`, `lorawanDevice`, `lorawanPayloadDecoder`, `lorawanDownlinks`, `lorawanDownlink(id)`, `lorawanDownlinkConfig`, `apiConfiguration { httpPayloadDecoder mqttServer mqttDecoders apiDownlinks mqttDownlinks logs }`, `particleConfiguration`, `draginonbiotConfiguration`, `cellular1nceConfiguration`, `functions`, `features`, `myRelationship`.

**ProductMeasurementFieldType**: `id`, `fieldName`, `verboseFieldName`, `description`, `fieldType`, `unit`, `displayUnit`, `displayUnitOverride`, `originUnit`, `floatDigits`, `color`, `active`, `role`, `semantic`, `formula`, `useFormula`, `formulaError`, `gauges`, `mappingProvider`, `mappingConsumer`, `product`.

**DeviceCurrentMeasurementType**: `value(timeRangeStart, timeRangeEnd)`, `valueString`, `valueCounterAbs`, `modified`, `field`, `sum/average/minimum/maximum/change(timeRangeStart!, timeRangeEnd!)`.

**FilteredDeviceList**: `total`, `devices`, `aggregatedNumericSemanticValue(semantic!, aggregation)`, `aggregatedBooleanSemanticCount(semantic!, countValue!)`.

**DeviceRoleFieldValue**: `role`, `value` (String), `datetime`, `chartData`, `field { id fieldName verboseFieldName fieldType unit }`.

**DeviceNumericSemanticFieldValue** / **DeviceBooleanSemanticFieldValue**: `value`, `fields { fieldName verboseFieldName value unit fieldType }`; boolean adds `count(countValue!)`.

**OrganizationType**: `id`, `name`, `billingPlan`, `billingPlanInterval`, `entitlement*`, `totalDevices`, `devicePlanCounts`, `workspaces(...)` (connection), `owner`, `userRelationships(...)`, `permissions`, `smsQuota*`, `deviceQuotaDistributionMode`, `activeAddOnPackages`, `whitelabelSites(...)`.

**DashboardType**: `id`, `name`, `type`, `icon`, `dashboards` (JSON), `metaJSON`, `sharingPolicy`, `sharedWith`, `publicLinks`, `dashboardData(...)`, `deviceInformation(...)`, `workspace` (public subset), colours/background, `dashboardChangelog`.

**RuleNGType**: `id`, `name`, `description`, `enabled`, `timezone`, `executionMode`, `productFilter`, `devicesFilter`, `tagsFilter`, `tagsFilterConjunction`, `triggerOn*` flags, `triggeringMeasurementFields`, `scheduleTriggerCrontab`, zone trigger fields, `conditions { conjunction kind leftOperand rightOperand }`, `actions` (union of `RuleNG*ActionType`), `whitelabelSite`, `executionLogEntries(after, first, filter)`.

**ExportType** / **ExportRunType**: export config (`name`, `kind`, `timezone`, device filters, `exportFieldSelection`, `exportSemantics`, `exportFieldNames`, `exportFormat`, `periodicEnabled`, `periodicInterval`, `nextRun`, `exportRuns`) and runs (`exportFrom`, `exportUntil`, `state`, `expiresAt`, `artifacts { filename downloadUrl compressedSize }`).

**ZoneType**: `id`, `name`, `description`, `center`, `radius`, `tags`, `devicesInZone(...)`, `deviceZoneEvents(...)`, `averageEnteredAt`.

**GatewayType** (Datacake LNS): `id`, `eui`, `name`, `kind`, `frequencyId`, `online`, `lastSeen`, `connectedAt`, `uplinkCount`, `downlinkCount`, `latitude`, `longitude`, `altitude`, `gatewayServerAddress`.

**PublicDeviceType** (public dashboard viewers): `id`, `verboseName`, `serialNumber`, `online`, `lastHeard`, `tags`, `metadata`, `roleFields`, `numericSemanticField`, `booleanSemanticField`, `dashboards`, `dashboardData`, `dashboardDownlinksData`, `dashboardConfigFields`, `productHardware`, `image`, `publicLink`, `hasWriteScope`.

## Enums (generated)

<!-- generated:start:enums -->
- **FieldSemantic**: `AIR_POLLUTION`, `AMBIENT_LIGHT`, `BATTERY`, `CO2`, `ENERGY_CONSUMPTION`, `FILL_LEVEL`, `HOURS_UNTIL_MAINTENANCE`, `HUMIDITY`, `LOUDNESS`, `PEOPLE_COUNT`, `POWER`, `RUNTIME_HOURS`, `SIGNAL`, `SNR`, `SOIL_MOISTURE`, `TEMPERATURE`, `VOC`, `WATER_CONSUMPTION`, `WATER_DEPTH`, `LOCATION`, `BATTERY_LOW`, `BUTTON_PRESSED`, `DESK_OCCUPIED`, `DEVICE_POWERED`, `DOOR_OPENED`, `EMERGENCY_TRIGGERED`, `GAS_LEAK_DETECTED`, `HVAC_ACTIVE`, `LIGHT_ON`, `MAINTENANCE_REQUIRED`, `MOTION_DETECTED`, `PARKING_OCCUPIED`, `POWER_OUTAGE_DETECTED`, `RAIN_DETECTED`, `ROOM_OCCUPIED`, `SMOKE_DETECTED`, `TAMPER_DETECTED`, `VALVE_OPENED`, `WATER_LEAK_DETECTED`, `WINDOW_OPENED`
- **NumericSemanticFieldAggregation**: `AVG`, `SUM`, `MAX`, `MIN`
- **BooleanSemanticFieldAggregation**: `AVG`, `MAX`, `MIN`
- **WorkspacePermissions**: `basics`, `members`, `billing`, `devices`, `rules`, `cakered`, `whitelabel`, `gateways`, `reports`, `dashboards`, `zones`, `exports`
- **DevicePermissions**: `edit_basics`, `edit_product`, `record_measurements`
- **UserOrganizationPermissions**: `create_workspaces`, `members`, `billing`, `whitelabel`, `manage_workspaces`
- **ErrorCode**: `NOT_AUTHENTICATED`, `NOT_AUTHORIZED`, `NOT_FOUND`, `VALIDATION_ERROR`, `CANNOT_PERFORM_OPERATION`, `INVALID_BILLING_INFORMATION`, `DEVICE_NOT_FOUND`, `FIELD_DOES_NOT_EXIST`, `INSUFFICIENT_QUOTA`, `INVALID_AUTHENTICATION_CODE`, `GATEWAY_ALREADY_CLAIMED`, `ADDON_TRANSITION_REQUIRED`, `INSUFFICIENT_REPLACEMENT_QUOTA`, `NO_REPLACEMENT_AVAILABLE`, `QUOTA_SHORTFALL_NOT_COVERED`, `ADDON_NOT_AVAILABLE`
- **FieldType**: `FLOAT`, `INT`, `NUMERIC`, `BOOL`, `STRING`, `COUNTER`, `GEO`
- **ProductMeasurementFieldFieldType**: `FLOAT`, `INT`, `NUMERIC`, `STRING`, `BOOL`, `COUNTER`, `OUTPUT`, `GEO`
- **RoleChoices**: `PRIMARY`, `SECONDARY`, `DEVICE_LOCATION`, `DEVICE_SIGNAL`, `DEVICE_BATTERY`
- **DeviceKind**: `DZERO`, `DZEROLTE`, `API`, `KEMPER`, `PINCODE`
- **SearchTagsAnyAll**: `any`, `all`
- **DashboardSharingPolicy**: `public`, `workspace`, `restricted`
- **DevicePublicLinkMode**: `READ`, `WRITE`
- **DashboardPublicLinkMode**: `READ`, `WRITE`
- **RuleExecutionMode**: `DEVICE_LEVEL`, `SYSTEM_LEVEL`, `GATEWAY_LEVEL`
- **ExportKind**: `PERIODIC`, `MANUAL`
- **ExportFormat**: `CSV`, `XLSX`
- **ExportFieldSelection**: `SEMANTICS`, `FIELD_NAMES`, `ALL`
- **ExportPeriodicInterval**: `DAILY`, `WEEKLY`, `MONTHLY`
- **WorkspaceFeatures**: `RULE_ENGINE`, `ZONES`, `WHITELABEL_USERS`, `MANAGED_HELIUM`, `LIVE_CHAT`
<!-- generated:end:enums -->

## Mutations by theme (generated)

<!-- generated:start:mutations -->
### Auth & account (15)

- `changePassword(email: String!, passwordNew: String!, passwordNewCheck: String!, passwordOld: String!) -> ChangePassword`
- `closeAccount(input: CloseAccountInputType!) -> CloseAccount`
- `createOtpTotpDevice(name: String!) -> CreateOTPTOTPDevice`
- `disableOtp(password: String) -> DisableOtp`
- `login(email: String!, otpToken: String, password: String!) -> Login`
- `passwordReset(password: String!, token: String!, userid: String!) -> PasswordReset`
- `registerPushToken(token: String!) -> RegisterPushToken`
- `requestPasswordReset(brand: String, email: String!) -> RequestPasswordReset`
- `signup(agreeToSubscribeToNewsletter: Boolean, brand: String, captchaToken: String!, email: String!, firstName: String!, firstWorkspaceName: String, language: String, lastName: String!, password: String!, projectType: UserProjectType, useCases: [String!]) -> Signup`
- `tryDraginonbiotPayloadDecoder(input: TryDraginoNBIoTPayloadDecoderInputType!) -> TryDraginoNBIoTPayloadDecoder`
- `unregisterPushTokens(token: String) -> UnregisterPushTokens`
- `updateDraginonbiotProductConfiguration(input: UpdateDraginoNBIoTProductConfigurationInputType!) -> UpdateDraginoNBIoTProductConfiguration`
- `updateUser(firstName: String, language: UserLanguage, lastName: String, phoneNumber: String) -> UpdateUser`
- `updateUserOrganizationRelationships(input: UpdateUserOrganizationRelationshipsInputType!) -> UpdateUserOrganizationRelationships`
- `verifyOtpTotpDevice(deviceId: ID!, token: String!) -> VerifyOTPTOTPDevice`

### Members & permissions (14)

- `addApiUser(input: ApiUserInput!) -> AddApiUser`
- `addDevicePermissions(input: AddDevicePermissionsInputType!) -> AddDevicePermissions`
- `addUserToWorkspace(input: AddUserToWorkspaceInputType!) -> AddUserToWorkspace`
- `createUserOrganizationRelationships(input: CreateUserOrganizationRelationshipsInputType!) -> CreateUserOrganizationRelationships`
- `deleteApiUser(id: String!) -> DeleteApiUser`
- `deleteUserInvite(email: String!, workspace: String!) -> DeleteUserInvite`
- `deleteUserOrganizationRelationships(input: DeleteUserOrganizationRelationshipsInputType!) -> DeleteUserOrganizationRelationships`
- `removeDevicePermissions(input: RemoveDevicePermissionsInputType!) -> RemoveDevicePermissions`
- `removeUserFromWorkspace(userId: String!, workspaceId: String!) -> RemoveUserFromWorkspace`
- `setUserDevicePermissions(input: SetUserDevicePermissionsInputType!) -> SetUserDevicePermissions`
- `setWorkspaceUserPermissions(input: SetWorkspaceUserPermissionsInputType!) -> SetWorkspaceUserPermissions` - DEPRECATED: Please use the `updateWorkspacePermissions` and `removeUserFromWorkspace` mutations instead. Mutation will be removed in the next release.. 
- `transferOrganizationOwnership(input: TransferOrganizationOwnershipInputType!) -> TransferOrganizationOwnership`
- `updateApiUser(id: String!, name: String!) -> UpdateApiUser`
- `updateWorkspacePermissions(input: UpdateWorkspacePermissionsInputType!) -> UpdateWorkspacePermissions`

### Workspaces & organization (15)

- `addWorkspace(brand: String, name: String!, organizationId: BlankableUUID) -> AddWorkspace`
- `assignWorkspaceQuota(input: AssignWorkspaceQuotaInputType!) -> AssignWorkspaceQuota`
- `attachSsoDomain(input: AttachSsoDomainInputType!) -> AttachSsoDomainMutation`
- `claimDeviceIntoWorkspace(deviceId: String, deviceSerialNumber: String, workspaceId: String!) -> ClaimDeviceIntoWorkspace`
- `deleteWorkspace(id: String!) -> DeleteWorkspace`
- `detachSsoDomain(input: DetachSsoDomainInputType!) -> DetachSsoDomainMutation`
- `generateWorkosAdminPortalLink(input: GenerateWorkosAdminPortalLinkInputType!) -> GenerateWorkosAdminPortalLink`
- `setWorkspaceSmsMode(mode: SmsMode!, workspace: String!) -> SetWorkspaceSmsModeMutation`
- `setWorkspaceSmsReplaceNonGsm7Characters(input: SetWorkspaceSmsReplaceNonGsm7CharactersInput!) -> SetWorkspaceSmsReplaceNonGsm7CharactersMutation`
- `updateOrganization(input: UpdateOrganizationInputType!) -> UpdateOrganization`
- `updateOrganizationQuotaDistributionMode(input: UpdateOrganizationQuotaDistributionModeInputType!) -> UpdateOrganizationQuotaDistributionMode`
- `updateOrganizationSmsQuotaDistributionMode(input: UpdateOrganizationSmsQuotaDistributionModeInputType!) -> UpdateOrganizationSmsQuotaDistributionMode`
- `updateWorkspace(homeDashboardId: BlankableUUID, id: UUID!, logo: Upload, name: String, resetLogo: Boolean, whitelabelSiteId: BlankableUUID) -> UpdateWorkspace`
- `updateWorkspaceBilling(input: UpdateWorkspaceBillingInputType!) -> UpdateWorkspaceBilling`
- `updateWorkspaceSidebarConfig(id: String!, sidebarConfig: JSONString!) -> UpdateWorkspaceSidebarConfig`

### Rules & alerts (29)

- `addAlert(input: AlertInputType!, workspaceId: String!) -> AddAlert`
- `addCondition(alert: String!, input: ConditionInputType!) -> AddCondition`
- `addEmailSettings(alert: String!, input: EMailNotificationSettingsInputType!) -> AddEmailSettings`
- `addFunctionSettings(alert: String!, input: FunctionSettingsInputType!) -> AddFunctionSettings`
- `addSetOutputSettings(alert: String!, input: SetOutputSettingsInputType!) -> AddSetOutputSettings`
- `addSmsSettings(alert: String!, input: SMSNotificationSettingsInputType!) -> AddSMSSettings`
- `createRule(input: CloudRuleInputType!, workspace: String!) -> CreateRuleMutation`
- `createRuleNG(input: CreateRuleNGInputType!, workspaceId: UUID!) -> CreateRuleNG`
- `deleteAlert(id: String!) -> DeleteAlert`
- `deleteCondition(id: String!) -> DeleteCondition`
- `deleteEmailSettings(id: String!) -> DeleteEmailSettings`
- `deleteFunctionSettings(id: String!) -> DeleteFunctionSettings`
- `deleteRule(rule: String!, workspace: String!) -> DeleteRuleMutation`
- `deleteRuleNG(id: UUID!) -> DeleteRuleNG`
- `deleteSetOutputSettings(id: String!) -> DeleteSetOutputSettings`
- `deleteSmsSettings(id: String!) -> DeleteSMSSettings`
- `dzeroOsActivateRule(input: SingleRuleInputType!) -> ActivateRule`
- `dzeroOsCreateRule(input: RuleInputType!) -> CreateRule`
- `dzeroOsDeactivateRule(input: SingleRuleInputType!) -> DeactivateRule`
- `dzeroOsDeleteRule(input: SingleRuleInputType!) -> DeleteRule`
- `dzeroOsUpdateRule(input: RuleUpdateInputType!) -> UpdateRule`
- `updateAlert(id: String!, input: AlertInputType!) -> UpdateAlert`
- `updateCondition(id: String!, input: ConditionInputType!) -> UpdateCondition`
- `updateEmailSettings(id: String!, input: EMailNotificationSettingsInputType!) -> UpdateEmailSettings`
- `updateFunctionSettings(id: String!, input: FunctionSettingsInputType!) -> UpdateFunctionSettings`
- `updateRule(input: CloudRuleInputType!, rule: String!, workspace: String!) -> UpdateRuleMutation`
- `updateRuleNG(id: UUID!, input: UpdateRuleNGInputType!) -> UpdateRuleNG`
- `updateSetOutputSettings(id: String!, input: SetOutputSettingsInputType!) -> UpdateSetOutputSettings`
- `updateSmsSettings(id: String!, input: SMSNotificationSettingsInputType!) -> UpdateSMSSettings`

### Dashboards & views (14)

- `addDashboard(input: AddDashboardInputType!) -> AddDashboard`
- `addView(icon: String!, name: String!, workspaceId: String!) -> AddView`
- `checkDashboardPublicLinkToken(input: CheckDashboardPublicLinkTokenInputType!) -> CheckDashboardPublicLinkToken`
- `createDashboardPublicLink(input: CreateDashboardPublicLinkInputType!) -> CreateDashboardPublicLink`
- `deleteDashboard(dashboard: String!, workspace: String!) -> DeleteDashboard`
- `deleteDashboardPublicLink(input: DeleteDashboardPublicLinkInputType!) -> DeleteDashboardPublicLink`
- `deleteView(id: String!) -> DeleteView`
- `requestDashboardMetaId -> RequestDashboardMetaId`
- `updateDashboard(input: UpdateDashboardInputType!) -> UpdateDashboard`
- `updateDashboardMeta(data: JSONString!, id: String!) -> UpdateDashboardMeta`
- `updateDashboardPublicLink(input: UpdateDashboardPublicLinkInputType!) -> UpdateDashboardPublicLink`
- `updateProductDashboard(config: JSONString, id: String) -> UpdateProductDashboard`
- `updateView(config: JSONString, icon: String, id: String!, name: String) -> UpdateView`
- `uploadDashboardImage(input: UploadDashboardImageInputType!) -> UploadDashboardImage` - Used to upload images that are shown on dashboards. Should only be used

### Reports & exports (14)

- `createManualExport(input: CreateManualExportInputType!) -> CreateManualExport`
- `createPeriodicExport(input: CreatePeriodicExportInputType!) -> CreatePeriodicExport`
- `createReport(input: CreateReportInputType!) -> CreateReport`
- `createReportBuilderReport(input: CreateReportBuilderReportInputType!) -> CreateReportBuilderReport`
- `deleteExport(input: DeleteExportInputType!) -> DeleteExport`
- `deleteReport(report: String!) -> DeleteReport`
- `deleteReportBuilderReport(input: DeleteReportBuilderReportInputType!) -> DeleteReportBuilderReport`
- `runReport(report: String!) -> RunReport`
- `runReportBuilderReport(input: RunReportBuilderReportInputType!) -> RunReportBuilderReport`
- `updateEnergyReport(input: UpdateEnergyReportInputType!, report: String!) -> UpdateEnergyReport`
- `updatePeriodicExport(input: UpdatePeriodicExportInputType!) -> UpdatePeriodicExport`
- `updateReport(input: UpdateReportInputType!, report: String!) -> UpdateReport`
- `updateReportBuilderReport(input: UpdateReportBuilderReportInputType!) -> UpdateReportBuilderReport`
- `updateSimpleCsvReport(input: UpdateSimpleCsvReportInputType!, report: String!) -> UpdateSimpleCsvReport`

### Zones (3)

- `createZones(input: CreateZonesInputType!) -> CreateZones`
- `deleteZones(input: DeleteZonesInputType!) -> DeleteZones`
- `updateZone(input: UpdateZoneInputType!) -> UpdateZone`

### Webhooks (4)

- `createWebhook(input: CreateWebhookInputType!) -> CreateWebhook`
- `deleteWebhook(input: DeleteWebhookInputType!) -> DeleteWebhook`
- `tryWebhook(action: JSONString!, rule: String!, workspace: String!) -> TryWebhookMutation`
- `updateWebhook(input: UpdateWebhookInputType!) -> UpdateWebhook`

### Billing, plans & add-ons (19)

- `cancelAddOn(input: CancelAddOnInput!) -> CancelAddOn`
- `cancelAddOnPackage(input: CancelAddOnPackageInput!) -> CancelAddOnPackage`
- `cancelAllSubscriptions(input: CancelAllSubscriptionsInputType!) -> CancelAllSubscriptions`
- `changeDevicePlan(id: String!, plan: String!, planCode: String!) -> ChangeDevicePlan`
- `checkCoupon(id: String!) -> CheckCoupon`
- `checkTaxId(country: String, taxId: String!, taxIdType: TaxIdType!) -> CheckTaxId`
- `getDevicePlanForCode(code: String!, workspace: String!) -> GetDevicePlanForCode`
- `getQuoteForPrices(organizationId: UUID, prices: [QuoteInputType]!) -> GetQuoteForPrices`
- `getStripeCustomerPortal(workspace: String!) -> GetStripeCustomerPortal`
- `getStripeResubscribeUrl(input: GetStripeResubscribeUrlInput!) -> GetStripeResubscribeUrl`
- `getStripeSetupIntent(workspace: String!) -> GetStripeSetupIntent`
- `purchaseCakered(input: PurchaseCakeredInputType!) -> PurchaseCakered`
- `purchasePlan(input: PurchasePlanInput!) -> PurchasePlan`
- `purchaseSmsCredits(package: SmsPackage!, workspace: String!) -> PurchaseSmsCredits`
- `purchaseWhitelabelSite(input: PurchaseWhitelabelSiteInputType!) -> PurchaseWhitelabelSiteMutation` - DEPRECATED: Please use the `createWhitelabelSite` mutation instead. 
- `purchaseWirelessIotHub(input: PurchaseWirelessIotHubInputType!) -> PurchaseWirelessIotHub`
- `subscribeToAddOnPackage(input: SubscribeToAddOnPackageInput!) -> SubscribeToAddOnPackage`
- `transferSmsQuota(input: TransferSmsQuotaInputType!) -> TransferSmsQuota`
- `updateSmsAutoTopupConfig(input: UpdateSmsAutoTopupConfigInputType!) -> UpdateSmsAutoTopupConfig`

### Gateways & LoRaWAN (22)

- `addLoraEncoder(encoder: LoRaEncoder!, product: String!) -> AddLoRaEncoder`
- `addTtnMapping(device: String!, fieldMapping: JSONString!, ttnDevId: String!) -> AddTtnMapping`
- `claimGateway(input: ClaimGatewayInputType!) -> ClaimGateway`
- `createActilityThingparkDxConfig(asId: String!, asKey: String!, hostname: String!, timespec: TimespecEnum!, token: String!, useDxApi: Boolean!, workspace: String!) -> CreateActilityThingparkDxConfig`
- `createGateway(input: CreateGatewayInputType!) -> CreateGateway`
- `createLoraDevice(input: CreateLoraDeviceInputType!) -> CreateLoraDevice` - DEPRECATED: Please use `createLoraDevices` (plural) instead. This mutation will be removed in a future release.. 
- `createLoraDevices(input: CreateLoraDevicesInputType!) -> CreateLoraDevices`
- `createManagedTtiApplication(input: CreateManagedTtiApplicationInputType!) -> CreateManagedTtiApplication` - This mutation creates an instance of a TTI application and creates the corresponding downlink key and webhook.
- `createManagedTtiConfiguration(input: CreateManagedTtiConfigurationInputType!) -> CreateManagedTtiConfiguration`
- `deleteActilityThingparkDxConfig(id: String!) -> DeleteActilityThingparkDxConfig`
- `deleteGateway(input: DeleteGatewayInputType!) -> DeleteGateway`
- `deleteLoraEncoder(encoder: String!, product: String!) -> DeleteLoRaEncoder`
- `deleteManagedTtiConfiguration(id: String!) -> DeleteManagedTtiConfiguration`
- `getGatewayClaimInfo(eui: String!) -> GetGatewayClaimInfo`
- `requestLoraDevice(device: String!) -> RequestLoraDevice`
- `resetDatacakeLNSDevNonces(input: ResetDatacakeLNSDevNoncesInputType!) -> ResetDatacakeLNSDevNonces`
- `setLoraEncoders(encoders: [LoRaEncoder]!, product: String!) -> SetLoRaEncoders`
- `tryManagedTtiToken(input: TryManagedTtiTokenInputType!) -> TryManagedTtiToken`
- `updateActilityThingparkDxConfig(asId: String!, asKey: String!, hostname: String!, id: String!, timespec: TimespecEnum!, token: String!, useDxApi: Boolean!) -> UpdateActilityThingparkDxConfig`
- `updateGateway(input: UpdateGatewayInputType!) -> UpdateGateway`
- `updateLoraEncoder(encoder: LoRaEncoder!, product: String!) -> UpdateLoRaEncoder`
- `updateTtnMapping(fieldMapping: JSONString!, id: String!, ttnDevId: String!) -> UpdateTTNDeviceMapping`

### Devices (32)

- `acceptDeviceMoveRequest(input: AcceptDeviceMoveRequestInputType!) -> AcceptDeviceMoveRequest`
- `addDevice(brand: String, copyCloudRules: [String], copyConfigFrom: String, copyDashboard: Boolean, copyDzeroFunctions: [String], copyDzeroRules: [String], copyFields: [String], copyMetadata: Boolean, copyTags: Boolean, kind: DeviceKind!, name: String, pin: String, plan: String, planCode: String, serialNumber: String, workspaceId: String!) -> AddDevice` - DEPRECATED: Please use `create[Api|Lora|Cellular1nce|Draginonbiot]Devices` instead. This mutation will be removed in a future release.. 
- `addKemperDevice(input: AddKemperDeviceInputType!) -> AddKemperDevice` - DEPRECATED: Please use `addPincodeDevice` instead. This mutation will be removed in a future release.. 
- `addPincodeDevice(input: AddPincodeDeviceInputType!) -> AddPincodeDevice`
- `cancelDeviceMoveRequest(input: CancelDeviceMoveRequestInputType!) -> CancelDeviceMoveRequest`
- `changeDeviceSerial(id: String!, serial: String!) -> ChangeDeviceSerial`
- `checkPublicDeviceToken(link: String!, token: String!) -> CheckPublicDeviceToken`
- `createApiDevices(input: CreateApiDevicesInputType!) -> CreateApiDevices`
- `createCellular1nceDevices(input: CreateCellular1nceDevicesInputType!) -> CreateCellular1nceDevices`
- `createDeviceMoveRequest(input: CreateDeviceMoveRequestInputType!) -> CreateDeviceMoveRequest`
- `createDevicePublicLink(device: String!, input: DevicePublicLinkInputType!) -> CreateDevicePublicLink`
- `createDraginonbiotDevices(input: CreateDraginoNBIoTDevicesInputType!) -> CreateDraginoNBIoTDevices`
- `createParticleDeviceMapping(device: String!, particleId: String!) -> CreateParticleDeviceMapping`
- `createParticleDevices(input: CreateParticleDevicesInputType!) -> CreateParticleDevices`
- `deleteDeviceData(input: DeleteDeviceDataInput!) -> DeleteDeviceData`
- `deleteDevicePublicLink(device: String!, link: String!) -> DeleteDevicePublicLink`
- `deleteParticleDeviceMapping(id: String!) -> DeleteParticleDeviceMapping`
- `deleteProductMeasurementFieldSuggestion(id: UUID!) -> DeleteProductMeasurementFieldSuggestion`
- `deleteProductMeasurementFieldSuggestions(productId: UUID!) -> DeleteProductMeasurementFieldSuggestions`
- `ignoreDeviceSuggestion(input: IgnoreDeviceSuggestionInputType!) -> IgnoreDeviceSuggestion`
- `kemperDeviceValid(pinCode: String!, serialNumber: String!) -> KemperDeviceValid` - DEPRECATED: Please use `addPincodeDevice` instead. This mutation will be removed in a future release.. 
- `rejectDeviceMoveRequest(input: RejectDeviceMoveRequestInputType!) -> RejectDeviceMoveRequest`
- `removeDevice(input: RemoveDeviceInput!) -> RemoveDevice`
- `removeDeviceActivationProvider(input: RemoveDeviceActivationProviderInputType!) -> RemoveDeviceActivationProvider`
- `revokeDeviceClaims(input: RevokeDeviceClaimsInput!) -> RevokeDeviceClaims`
- `setDeviceActivationProvider(input: SetDeviceActivationProviderInputType!) -> SetDeviceActivationProvider`
- `setDeviceConfigurationValue(input: SetDeviceConfigurationValueInputType!) -> SetDeviceConfigurationValue`
- `setNotifyOffline(input: SetNotifyOfflineInputType!) -> SetNotifyOffline`
- `updateDevice(deviceId: String!, input: UpdateDeviceInputType) -> UpdateDevice`
- `updateDeviceFolders(input: UpdateDeviceFoldersInput) -> UpdateDeviceFolders`
- `updateDevicePublicLink(device: String!, input: DevicePublicLinkInputType!, link: String!) -> UpdateDevicePublicLink`
- `updateParticleDeviceMapping(id: String!, particleId: String!) -> UpdateParticleDeviceMapping`

### Products & fields (36)

- `addFieldMapping(input: AddFieldMappingInputType!) -> AddFieldMapping`
- `addLookupTableItem(input: LookupTableItemInputType!) -> AddLookupTableItem`
- `addProductFunction(description: TranslatedString!, fieldStates: [FieldState], fields: [String], function: FunctionKind!, name: TranslatedString!, productId: String!) -> AddProductFunction`
- `addProductMeasurementField(displayUnit: String, displayUnitOverride: String, fieldName: String!, fieldType: FieldType!, floatDigits: Int, formula: String, productId: String!, role: RoleChoices, semantic: FieldSemantic, unit: String, useFormula: Boolean, verboseFieldName: String!) -> AddProductMeasurementField`
- `addProductMeasurementFieldGauge(color: String!, eventName: String!, fieldId: String!, valuesFrom: Float!, valuesTo: Float!) -> AddProductMeasurementFieldGauge`
- `callProductFunction(deviceId: String!, functionId: String!) -> CallProductFunction`
- `cloneProduct(input: CloneProductInputType!) -> CloneProduct`
- `createConfigurationField(input: CreateConfigurationFieldInputType!) -> CreateConfigurationField`
- `createMqttDecoder(input: CreateMqttDecoderInputType!) -> CreateMqttDecoder`
- `deleteConfigurationField(field: String!) -> DeleteConfigurationField`
- `deleteLookupTableItem(fieldMapping: String!, lutItem: String!) -> DeleteLookupTableItem`
- `deleteMqttDecoder(input: DeleteMqttDecoderInputType!) -> DeleteMqttDecoder`
- `deleteProduct(input: DeleteProductInputType!) -> DeleteProduct` - Allows deleting products without any devices. Requires workspace devices permission.
- `deleteProductFunction(functionId: String!) -> DeleteProductFunction`
- `deleteProductMeasurementField(id: String!) -> DeleteProductMeasurementField`
- `deleteProductMeasurementFieldGauge(eventId: String!) -> DeleteProductMeasurementFieldGauge`
- `tryApiPayloadDecoder(input: TryApiPayloadDecoderInputType!) -> TryApiPayloadDecoder`
- `tryCellular1ncePayloadDecoder(input: TryCellular1ncePayloadDecoderInputType!) -> TryCellular1ncePayloadDecoder`
- `tryCellular1ncePayloadEncoder(input: TryCellular1ncePayloadEncoderInputType!) -> TryCellular1ncePayloadEncoder`
- `tryFormula(input: TryFormulaInputType!) -> TryFormula`
- `tryHttpPayloadEncoder(input: TryHttpPayloadEncoderInputType!) -> TryHttpPayloadEncoder`
- `tryMqttPayloadDecoder(input: TryMqttPayloadDecoderInputType!) -> TryMqttPayloadDecoder`
- `tryMqttPayloadEncoder(input: TryMqttPayloadEncoderInputType!) -> TryMqttPayloadEncoder`
- `tryParticlePayloadDecoder(input: TryParticlePayloadDecoderInputType!) -> TryParticlePayloadDecoder`
- `tryParticlePayloadEncoder(input: TryParticlePayloadEncoderInputType!) -> TryParticlePayloadEncoder`
- `tryPayloadDecoder(input: TryPayloadDecoderInputType!) -> TryPayloadDecoder`
- `tryPayloadEncoder(input: TryPayloadEncoderInputType!) -> TryPayloadEncoder`
- `updateCellular1nceProductConfiguration(input: UpdateCellular1nceProductConfigurationInputType!) -> UpdateCellular1nceProductConfiguration`
- `updateConfigurationField(input: UpdateConfigurationFieldInputType!) -> UpdateConfigurationField`
- `updateFieldMapping(id: String!, input: FieldMappingInputType!) -> UpdateFieldMapping`
- `updateLookupTableItem(input: LookupTableItemInputType!) -> UpdateLookupTableItem`
- `updateMqttDecoder(input: UpdateMqttDecoderInputType!) -> UpdateMqttDecoder`
- `updateProduct(input: UpdateProductInputType!) -> UpdateProduct`
- `updateProductFunction(description: TranslatedString!, fieldStates: [FieldState], fields: [String], function: FunctionKind!, functionId: String!, name: TranslatedString!) -> UpdateProductFunction`
- `updateProductMeasurementField(active: Boolean, color: String, displayUnit: String, displayUnitOverride: String, fieldId: String!, floatDigits: Int, formula: String, role: RoleChoices, semantic: FieldSemantic, unit: String, useFormula: Boolean, verboseFieldName: String) -> UpdateProductMeasurementField`
- `updateProductMeasurementFieldGauge(color: String!, eventId: String!, eventName: String!, valuesFrom: Float!, valuesTo: Float!) -> UpdateProductMeasurementFieldGauge`

### Data & downlinks (23)

- `createApiDownlink(input: CreateApiDownlinkInputType!) -> CreateApiDownlink`
- `createCellular1nceDownlink(input: CreateCellular1nceDownlinkInputType!) -> CreateCellular1nceDownlink`
- `createMqttDownlink(input: CreateMqttDownlinkInputType!) -> CreateMqttDownlink`
- `createParticleDownlink(input: CreateParticleDownlinkInputType!) -> CreateParticleDownlink`
- `deleteApiDownlink(input: DeleteApiDownlinkInputType!) -> DeleteApiDownlink`
- `deleteCellular1nceDownlink(input: DeleteCellular1nceDownlinkInputType!) -> DeleteCellular1nceDownlink`
- `deleteMqttDownlink(input: DeleteMqttDownlinkInputType!) -> DeleteMqttDownlink`
- `deleteParticleDownlink(input: DeleteParticleDownlinkInputType!) -> DeleteParticleDownlink`
- `dzeroOsSetPublishQueues(input: PublishQueueInputType!) -> SetPublishQueues`
- `dzeroOsSetValueFilter(input: ValueFilterInputType!) -> SetValueFilter`
- `dzeroOsSetValueWatcher(input: ValueWatcherInputType!) -> SetValueWatcher`
- `internalAddMeasurement(input: InternalAddMeasurementInputType!) -> InternalAddMeasurement` - For internal use only.
- `sendApiDownlink(device: String!, downlink: String!, publicDashboardAuth: DashboardPublicLinkAuthInputType, publicDeviceAuth: PublicDeviceAuthType) -> SendApiDownlink`
- `sendAw3CommandFrame(commandIndex: AW3CommandIndex!, deviceId: String!, value: String!) -> SendAW3CommandFrame`
- `sendCellular1nceDownlink(input: SendCellular1nceDownlinkInputType!) -> SendCellular1nceDownlink`
- `sendDownlink(device: String!, downlink: String!, publicDashboardAuth: DashboardPublicLinkAuthInputType, publicDeviceAuth: PublicDeviceAuthType) -> SendDownlink`
- `sendMqttDownlink(device: String!, downlink: String!, publicDeviceAuth: PublicDeviceAuthType) -> SendMqttDownlink`
- `sendParticleDownlink(device: String!, downlink: String!, publicDashboardAuth: DashboardPublicLinkAuthInputType, publicDeviceAuth: PublicDeviceAuthType) -> SendParticleDownlink`
- `setValue(input: SetValueInputType!) -> SetValue` - For internal use only.
- `updateApiDownlink(input: UpdateApiDownlinkInputType!) -> UpdateApiDownlink`
- `updateCellular1nceDownlink(input: UpdateCellular1nceDownlinkInputType!) -> UpdateCellular1nceDownlink`
- `updateMqttDownlink(input: UpdateMqttDownlinkInputType!) -> UpdateMqttDownlink`
- `updateParticleDownlink(input: UpdateParticleDownlinkInputType!) -> UpdateParticleDownlink`

### Integrations (18)

- `addParticleAccount(accessToken: String!, name: String, workspace: String!) -> AddParticleAccount`
- `cakeredUpdateWhitelistUrls(input: UpdateWhitelistUrlsInputType!) -> UpdateWhitelistUrlsMutation`
- `cancelCakered(input: CancelCakeredInputType!) -> CancelCakered`
- `createCellular1nceConfiguration(input: CreateCellular1nceConfigurationInput!) -> CreateCellular1nceConfiguration`
- `createMqttServer(server: MqttServerInputType!, workspace: String!) -> CreateMqttServer`
- `createParticleEventMapping(eventName: String!, fields: [String!], productId: String!) -> CreateParticleEventMapping`
- `deleteCellular1nceConfiguration(input: DeleteCellular1nceConfigurationInput!) -> DeleteCellular1nceConfiguration`
- `deleteMqttServer(input: DeleteMqttServerInputType!) -> DeleteMqttServer`
- `deleteParticleEventMapping(id: String!) -> DeleteParticleEventMapping`
- `dzeroOsSetEdgeCounterConfig(input: EdgeCounterInputType!) -> SetEdgeCounterConfig`
- `dzeroOsSetOutputs(input: SetOutputsInputType!) -> SetOutputs`
- `restartCakeredInstance(input: RestartCakeredInstanceInputType!) -> RestartCakeredInstanceMutation`
- `retryMqttServerConnection(input: RetryMqttServerConnectionInputType!) -> RetryMqttServerConnection`
- `testMqttServerConnection(server: MqttServerInputType!) -> TestMqttServerConnection`
- `updateApiConfiguration(input: UpdateApiConfigurationInputType!) -> UpdateApiConfiguration`
- `updateMqttServer(input: UpdateMqttServerInputType!) -> UpdateMqttServer`
- `updateParticleConfiguration(input: UpdateParticleConfigurationInputType!) -> UpdateParticleProductConfiguration`
- `updateParticleEventMapping(eventName: String, fields: [String!], id: String!) -> UpdateParticleEventMapping`

### White label (8)

- `cancelWhitelabelSite(whitelabelSite: String!) -> CancelWhitelabelSiteMutation`
- `createWhitelabelSite(input: CreateWhitelabelSiteInputType!) -> CreateWhitelabelSite`
- `deleteWhitelabelSite(input: DeleteWhitelabelSiteInputType!) -> DeleteWhitelabelSite`
- `generateHereToken -> GenerateHereToken`
- `reactivateWhitelabelSite(whitelabelSite: String!) -> ReactivateWhitelabelSiteMutation`
- `updateWhitelabelSite(input: UpdateWhitelabelSiteInputType!) -> UpdateWhitelabelSiteMutation`
- `verifyWhitelabelDomain(whitelabelSite: String!) -> VerifyWhitelabelDomainMutation`
- `verifyWhitelabelEmail(whitelabelSite: String!) -> VerifyWhitelabelEmailMutation`
<!-- generated:end:mutations -->

## Input types worth knowing

Grep these in `schema.graphql` before building a mutation:

| Purpose | Input type |
|---|---|
| Device list filters | `FilteredDeviceListTagsFilterInput`, `FilteredDeviceListDateTimeFilterInput`, `FilteredDeviceListNumericSemanticFieldFilterInput`, `FilteredDeviceListBooleanSemanticFieldFilterInput`, `DeviceListOrderByInputType`, `SemanticFieldOrderBy` |
| Create devices | `CreateLoraDevicesInputType` + `CreateLoraDevicesDevice`, `CreateApiDevicesInputType` + `CreateApiDevicesDevice`, `AddPincodeDeviceInputType` |
| Edit devices | `UpdateDeviceInputType`, `RemoveDeviceInput`, `DeleteDeviceDataInput`, `CreateDeviceMoveRequestInputType`, `AcceptDeviceMoveRequestInputType`, `DevicePublicLinkInputType` |
| Products and fields | `UpdateProductInputType`, `CloneProductInputType`, `DeleteProductInputType`, `CreateConfigurationFieldInputType`, `SetDeviceConfigurationValueInputType`, `AddFieldMappingInputType`, `TryPayloadDecoderInputType`, `TryFormulaInputType` |
| Members | `AddUserToWorkspaceInputType`, `ApiUserInput`, `DeviceRelationshipInputType`, `SetWorkspaceUserPermissionsInputType`, `SetUserDevicePermissionsInputType`, `AddDevicePermissionsInputType` |
| Rules | `CreateRuleNGInputType`, `UpdateRuleNGInputType`, `RuleNGConditionInputType`, `RuleNGLeftOperandInputType`, `RuleNGRightOperandInputType`, `RuleNGTimerangeOperationInputType`, `CreateRuleNGActionInputType`, `UpdateRuleNGActionInputType`, `NormalizedTimeRestrictionsInputType` |
| Dashboards | `AddDashboardInputType`, `UpdateDashboardInputType`, `CreateDashboardPublicLinkInputType`, `DashboardPublicLinkAuthInputType`, `PublicDeviceAuthType` |
| Exports and reports | `CreateManualExportInputType`, `CreatePeriodicExportInputType`, `UpdatePeriodicExportInputType`, `CreateReportInputType`, `CreateReportBuilderReportInputType` |
| Zones, webhooks, folders | `CreateZonesInputType` + `CreateZoneInputType`, `UpdateZoneInputType`, `CreateWebhookInputType` + `WebhookRequestHeader`, `UpdateDeviceFoldersInput` |
