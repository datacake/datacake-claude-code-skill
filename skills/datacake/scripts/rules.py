#!/usr/bin/env python3
"""Rule Engine NG helper: list, inspect, export, create, update, toggle and delete rules, read their logs.

Usage:
  python3 scripts/rules.py list <workspace> [--json]                 # every rule of the workspace, one line each
  python3 scripts/rules.py ids <workspace> [--product "Name"] [--tags a,b]
                                                                    # ids a rule needs: product, fields, configuration fields,
                                                                    # downlinks, devices, push recipients, white label site
  python3 scripts/rules.py get <rule-id> [--json]                    # full definition (conditions, actions, ids)
  python3 scripts/rules.py export <rule-id> [--file rule.json]       # CreateRuleNGInputType payload for re-creation / templates
  python3 scripts/rules.py create <workspace> --file rule.json [--execute]
  python3 scripts/rules.py update <rule-id> --file patch.json [--execute]   # UpdateRuleNGInputType (only the fields to change)
  python3 scripts/rules.py enable|disable <rule-id> [--execute]
  python3 scripts/rules.py delete <rule-id> [--execute]
  python3 scripts/rules.py logs <rule-id> [--since 24h] [--fired] [--device <uuid>] [--limit 50] [--trace] [--json]

<workspace> is a UUID or slug. Write commands print their plan; add --execute to run them.
`create` accepts the portal's copy/paste JSON too (productId, updateActions with ids are converted).
Condition ids are generated when missing, hysteresis is set to 0 on static number/range operands and removed
elsewhere (the API rejects it there), action firing flags get defaults, templates are checked for unsupported
filters and tags (the engine renders only {{ }} with round, datetime and json).
Token: $DATACAKE_TOKEN or ~/.datacake/token (or --token). Standard library only; reuses dc.py.
Reference: reference/rules-ng.md
"""
import argparse
import json
import os
import re
import sys
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dc import ENDPOINT, gql, report_errors, resolve_token  # noqa: E402

UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
ACTION_KINDS = ["EMAIL", "SMS", "PUSH", "WEBHOOK", "SINGLE_DEVICE_DOWNLINK", "MULTI_DEVICE_DOWNLINK", "SET_VALUE"]
TRIGGER_FLAGS = [("triggerOnMeasurement", "measurement"), ("triggerOnDeviceGoesOffline", "device-offline"),
                 ("triggerOnDeviceGoesOnline", "device-online"), ("triggerOnGatewayGoesOffline", "gateway-offline"),
                 ("triggerOnGatewayGoesOnline", "gateway-online"), ("triggerOnSchedule", "schedule"),
                 ("triggerOnZoneEntry", "zone-entry"), ("triggerOnZoneExit", "zone-exit"),
                 ("triggerOnZoneLengthOfStay", "zone-stay")]

ACTION_COMMON = ("id kind description fireWhenConditionsBecomeHot fireWhenConditionsStayHot fireWhenConditionsBecomeCold "
                 "minSecondsBetweenHotConditions maxConsecutiveActionExecutions "
                 "timeRestrictions { kind timeRestrictions { start { dayOfWeek time } end { dayOfWeek time } } }")
DOWNLINK = ("{ ... on LoRaWanDownlinkType { id name } ... on ApiDownlinkType { id name } ... on MqttDownlinkType { id name } "
            "... on Cellular1nceDownlinkType { id name } ... on ParticleDownlinkType { id name } ... on ProductFunctionType { id } }")
RULE_FIELDS = """
    id name description enabled timezone executionMode
    whitelabelSite { id title }
    productFilter { id name }
    devicesFilter { id verboseName }
    tagsFilter tagsFilterConjunction
    triggerOnMeasurement triggeringMeasurementFields { id fieldName }
    triggerOnDeviceGoesOffline triggerOnDeviceGoesOnline
    triggerOnGatewayGoesOffline triggerOnGatewayGoesOnline
    triggerOnSchedule scheduleTriggerCrontab
    triggerOnZoneEntry triggerOnZoneExit triggerOnZoneLengthOfStay
    zoneLengthOfStayTriggerMinutes zoneTagsFilter zoneTagsFilterConjunction
    conditions {
      id description conjunction kind
      leftOperand { kind fieldId deviceId timerangeOperation { kind start end } }
      rightOperand { kind numberValue rangeValue { start end includeBoundaries } hysteresis booleanValue stringValue geofenceValue fieldId deviceId }
    }
    actions {
      __typename
      ... on RuleNGEmailActionType { %(c)s emailReceivers emailSubject emailBody }
      ... on RuleNGSmsActionType { %(c)s smsReceivers smsBody }
      ... on RuleNGPushActionType { %(c)s pushTitle pushBody pushRecipients { id email } }
      ... on RuleNGWebhookActionType { %(c)s webhookUrl webhookHeaders { key value } webhookPayload }
      ... on RuleNGSingleDeviceDownlinkActionType { %(c)s singleDeviceDownlinkDevice { id verboseName } singleDeviceDownlink %(d)s }
      ... on RuleNGMultiDeviceDownlinkActionType { %(c)s multiDeviceDownlinkProduct { id name } multiDeviceDownlinkTagsFilter multiDeviceDownlinkTagsFilterConjunction multiDeviceDownlink %(d)s }
      ... on RuleNGSetValueActionType { %(c)s setValueDevice { id verboseName } setValueField { id fieldName } setValueNumeric setValueBool setValueString setValueGeo }
    }
""" % {"c": ACTION_COMMON, "d": DOWNLINK}

LIST_QUERY = """
query Rules($id: String, $slug: String) {
  workspace(id: $id, slug: $slug) {
    id name slug myPermissions features entitlementRulesQuota entitlementRulesQuotaRemaining
    rulesNG {
      id name enabled executionMode timezone
      productFilter { id name }
      devicesFilter { id }
      tagsFilter tagsFilterConjunction
      triggerOnMeasurement triggerOnDeviceGoesOffline triggerOnDeviceGoesOnline
      triggerOnGatewayGoesOffline triggerOnGatewayGoesOnline triggerOnSchedule scheduleTriggerCrontab
      triggerOnZoneEntry triggerOnZoneExit triggerOnZoneLengthOfStay
      conditions { id }
      actions { __typename }
    }
  }
}
"""

GET_QUERY = "query Rule($id: UUID!) { ruleNG(id: $id) { %s } }" % RULE_FIELDS

IDS_QUERY = """
query RuleIds($id: String, $slug: String, $tags: FilteredDeviceListTagsFilterInput, $pageSize: Int) {
  workspace(id: $id, slug: $slug) {
    id name slug myPermissions features entitlementRulesQuota entitlementRulesQuotaRemaining
    whitelabelSite { id title }
    pushRecipientCandidates { reachable user { id email firstName lastName } }
    products {
      id name slug deviceCount
      measurementFields(active: true) { id fieldName verboseFieldName fieldType unit }
      configurationFields { id fieldName fieldType unit }
      lorawanDownlinks { id name fport }
      apiConfiguration { apiDownlinks { id name kind } mqttDownlinks { id name } }
    }
    devicesFiltered(page: 0, pageSize: $pageSize, tags: $tags) {
      total
      devices { id verboseName serialNumber tags product { id } }
    }
  }
}
"""

LOGS_QUERY = """
query RuleLogs($id: UUID!, $first: Int, $after: String, $filter: RuleExecutionLogEntriesFilterInputType) {
  ruleNG(id: $id) {
    id name executionMode
    executionLogEntries(first: $first, after: $after, filter: $filter) {
      pageInfo { hasNextPage endCursor }
      edges {
        node {
          id initiator triggerTimestamp executionTimestamp completionTimestamp
          triggeringDevice { id verboseName }
          triggeringGateway { id name }
          conditionsResult conditionsPrettyEvaluationTrace actionFiringEvent anyActionFired
          actionExecutionVariables
          actionExecutionLogEntries { id kind isFired isFiredByEvent isWithinActiveTimePeriod prettyTrace }
        }
      }
    }
  }
}
"""

CREATE_MUTATION = """
mutation CreateRule($workspaceId: UUID!, $input: CreateRuleNGInputType!) {
  createRuleNG(workspaceId: $workspaceId, input: $input) { ok error { code details } ruleNG { id name enabled } }
}
"""

UPDATE_MUTATION = """
mutation UpdateRule($id: UUID!, $input: UpdateRuleNGInputType!) {
  updateRuleNG(id: $id, input: $input) { ok error { code details } ruleNG { id name enabled } }
}
"""

DELETE_MUTATION = """
mutation DeleteRule($id: UUID!) { deleteRuleNG(id: $id) { ok error { code details } } }
"""


class Api:
    def __init__(self, token, endpoint):
        self.token, self.endpoint = token, endpoint

    def run(self, query, variables=None):
        """Return (data, errors); GraphQL errors are printed to stderr."""
        resp = gql(query, variables, self.token, self.endpoint)
        report_errors(resp)
        return resp.get("data") or {}, resp.get("errors") or []

    def rule(self, rule_id):
        if not UUID_RE.match(rule_id):
            sys.exit("rule id must be a UUID (rules.py list <workspace> prints them): %s" % rule_id)
        data, _ = self.run(GET_QUERY, {"id": rule_id})
        rule = data.get("ruleNG")
        if not rule:
            sys.exit("rule not found or no access: %s" % rule_id)
        return rule


def workspace_vars(ref):
    return {"id" if UUID_RE.match(ref) else "slug": ref}


def table(rows, headers):
    rows = [[("" if c is None else str(c)) for c in r] for r in rows]
    widths = [max(len(h), *(len(r[i]) for r in rows)) if rows else len(h) for i, h in enumerate(headers)]
    out = ["  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)), "  ".join("-" * w for w in widths)]
    out.extend("  ".join(r[i].ljust(widths[i]) for i in range(len(headers))) for r in rows)
    return "\n".join(out)


def triggers_of(rule):
    names = [label for flag, label in TRIGGER_FLAGS if rule.get(flag)]
    if rule.get("triggerOnSchedule") and rule.get("scheduleTriggerCrontab"):
        names = [n if n != "schedule" else "schedule(%s)" % rule["scheduleTriggerCrontab"] for n in names]
    return ",".join(names) or "-"


def scope_of(rule):
    if rule.get("devicesFilter"):
        return "%d device%s" % (len(rule["devicesFilter"]), "" if len(rule["devicesFilter"]) == 1 else "s")
    if rule.get("tagsFilter"):
        return "tags %s: %s" % (rule.get("tagsFilterConjunction") or "?", ",".join(rule["tagsFilter"]))
    return "all devices"


def action_kind(action):
    kind = action.get("kind")
    if kind:
        return kind
    name = (action.get("__typename") or "").replace("RuleNG", "").replace("ActionType", "")
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).upper() or "?"


def actions_summary(actions):
    counts = {}
    for a in actions or []:
        counts[action_kind(a)] = counts.get(action_kind(a), 0) + 1
    return ", ".join("%s%s" % (k, " x%d" % n if n > 1 else "") for k, n in counts.items()) or "-"


def describe_operand(op, side):
    if not op:
        return "?"
    kind = op.get("kind", "?")
    if side == "left":
        text = "%s field %s" % ("triggering device" if kind == "TRIGGERING_DEVICE_FIELD_VALUE" else "device %s" % op.get("deviceId"), op.get("fieldId"))
        tr = op.get("timerangeOperation")
        if tr:
            text += " [%s from %s to %s]" % (tr.get("kind"), tr.get("start"), tr.get("end"))
        return text
    if kind == "STATIC_NUMBER_VALUE":
        return "%s (hysteresis %s)" % (op.get("numberValue"), op.get("hysteresis"))
    if kind == "STATIC_RANGE_VALUE":
        rv = op.get("rangeValue") or {}
        return "range %s..%s%s" % (rv.get("start"), rv.get("end"), " incl." if rv.get("includeBoundaries") else "")
    if kind == "STATIC_BOOLEAN_VALUE":
        return str(op.get("booleanValue"))
    if kind == "STATIC_STRING_VALUE":
        return json.dumps(op.get("stringValue"))
    if kind == "DYNAMIC_TRIGGERING_DEVICE_FIELD_VALUE":
        return "triggering device field %s" % op.get("fieldId")
    if kind == "DYNAMIC_DEVICE_FIELD_VALUE":
        return "device %s field %s" % (op.get("deviceId"), op.get("fieldId"))
    if kind == "DYNAMIC_CONFIGURATION_FIELD_VALUE":
        return "configuration field %s" % op.get("fieldId")
    return "%s %s" % (kind, op.get("geofenceValue") or "")


def print_rule(rule):
    print("RULE %s  (id: %s)  %s  mode: %s  timezone: %s" % (
        rule["name"], rule["id"], "ENABLED" if rule.get("enabled") else "disabled", rule.get("executionMode"), rule.get("timezone")))
    if rule.get("description"):
        print("  description: %s" % rule["description"])
    pf = rule.get("productFilter") or {}
    print("  product: %s (%s)   scope: %s   branding: %s" % (
        pf.get("name") or "-", pf.get("id") or "-", scope_of(rule),
        (rule.get("whitelabelSite") or {}).get("title") or "default"))
    if rule.get("devicesFilter"):
        for d in rule["devicesFilter"]:
            print("    device %s (%s)" % (d.get("verboseName"), d["id"]))
    print("  triggers: %s" % triggers_of(rule))
    if rule.get("triggeringMeasurementFields"):
        print("    on fields: %s" % ", ".join("%s (%s)" % (f.get("fieldName"), f["id"]) for f in rule["triggeringMeasurementFields"]))
    if any(rule.get(k) for k in ("triggerOnZoneEntry", "triggerOnZoneExit", "triggerOnZoneLengthOfStay")):
        print("    zones: tags %s %s, length of stay %s min" % (
            rule.get("zoneTagsFilterConjunction") or "", ",".join(rule.get("zoneTagsFilter") or []) or "(any)", rule.get("zoneLengthOfStayTriggerMinutes")))
    conds = rule.get("conditions") or []
    print("  conditions (%d):" % len(conds))
    for i, c in enumerate(conds):
        print("    %s%s %s %s   [id %s]%s" % (
            (c.get("conjunction") + " ") if i else "", describe_operand(c.get("leftOperand"), "left"), c.get("kind"),
            describe_operand(c.get("rightOperand"), "right"), c.get("id"), (" " + c["description"]) if c.get("description") else ""))
    actions = rule.get("actions") or []
    print("  actions (%d):" % len(actions))
    for a in actions:
        fires = [n for n, f in (("hot", "fireWhenConditionsBecomeHot"), ("stay-hot", "fireWhenConditionsStayHot"),
                                ("cold", "fireWhenConditionsBecomeCold")) if a.get(f)]
        extra = ""
        kind = action_kind(a)
        if kind == "EMAIL":
            extra = "to %s, subject %s" % (", ".join(a.get("emailReceivers") or []), json.dumps(a.get("emailSubject")))
        elif kind == "SMS":
            extra = "to %s" % ", ".join(a.get("smsReceivers") or [])
        elif kind == "PUSH":
            extra = "to %s, title %s" % (", ".join(r.get("email") for r in a.get("pushRecipients") or []), json.dumps(a.get("pushTitle")))
        elif kind == "WEBHOOK":
            extra = "POST %s" % a.get("webhookUrl")
        elif kind == "SINGLE_DEVICE_DOWNLINK":
            extra = "downlink %s to %s" % ((a.get("singleDeviceDownlink") or {}).get("name") or (a.get("singleDeviceDownlink") or {}).get("id"),
                                           (a.get("singleDeviceDownlinkDevice") or {}).get("verboseName") or "triggering device")
        elif kind == "MULTI_DEVICE_DOWNLINK":
            extra = "downlink %s to product %s tags %s %s" % (
                (a.get("multiDeviceDownlink") or {}).get("name"), (a.get("multiDeviceDownlinkProduct") or {}).get("name"),
                a.get("multiDeviceDownlinkTagsFilterConjunction") or "", ",".join(a.get("multiDeviceDownlinkTagsFilter") or []) or "(all)")
        elif kind == "SET_VALUE":
            value = next((a[k] for k in ("setValueNumeric", "setValueBool", "setValueGeo") if a.get(k) is not None), a.get("setValueString"))
            extra = "set %s = %r on %s" % ((a.get("setValueField") or {}).get("fieldName"), value,
                                          (a.get("setValueDevice") or {}).get("verboseName") or "triggering device")
        limits = "cooldown %ss, max %s" % (a.get("minSecondsBetweenHotConditions"), a.get("maxConsecutiveActionExecutions") or "unlimited")
        tr = a.get("timeRestrictions")
        if tr:
            limits += ", %s %d window(s)" % (tr.get("kind"), len(tr.get("timeRestrictions") or []))
        print("    %s %s  fires on %s  (%s)  [id %s]" % (kind, extra, "/".join(fires) or "nothing", limits, a.get("id")))


def strip_nulls(obj):
    if isinstance(obj, dict):
        return {k: strip_nulls(v) for k, v in obj.items() if v is not None and k != "__typename"}
    if isinstance(obj, list):
        return [strip_nulls(v) for v in obj]
    return obj


def normalize_condition(cond):
    cond = strip_nulls(cond)
    if not (isinstance(cond.get("id"), str) and UUID_RE.match(cond["id"])):
        cond["id"] = str(uuid.uuid4())
    cond.setdefault("description", "")
    cond.setdefault("conjunction", "AND")
    left = cond.get("leftOperand") or {}
    if left.get("kind") == "TRIGGERING_DEVICE_FIELD_VALUE":
        left.pop("deviceId", None)
    right = cond.get("rightOperand") or {}
    if right.get("kind") in ("STATIC_NUMBER_VALUE", "STATIC_RANGE_VALUE"):
        if right.get("hysteresis") is None:
            right["hysteresis"] = 0
    else:
        right.pop("hysteresis", None)  # only static number/range operands may carry it; the API rejects it elsewhere
    cond["leftOperand"], cond["rightOperand"] = left, right
    return cond


def normalize_action(action, keep_id, defaults):
    """Turn an action (input document, portal clipboard entry or RuleNG*ActionType output) into an input object."""
    action = strip_nulls(action)
    if not keep_id:
        action.pop("id", None)
    if "kind" not in action and action.get("__typename"):
        action["kind"] = action_kind(action)
    # output objects -> ids
    for src, dst, fn in (("pushRecipients", "pushRecipientIds", lambda v: [x["id"] for x in v]),
                         ("singleDeviceDownlinkDevice", "singleDeviceDownlinkDeviceId", lambda v: v["id"]),
                         ("singleDeviceDownlink", "singleDeviceDownlinkId", lambda v: v["id"]),
                         ("multiDeviceDownlinkProduct", "multiDeviceDownlinkProductId", lambda v: v["id"]),
                         ("multiDeviceDownlink", "multiDeviceDownlinkId", lambda v: v["id"]),
                         ("setValueDevice", "setValueDeviceId", lambda v: v["id"]),
                         ("setValueField", "setValueFieldId", lambda v: v["id"])):
        if src in action:
            value = action.pop(src)
            if value and dst not in action:
                action[dst] = fn(value)
    # aliases used by the portal's own AI tools
    for alias, real in (("to", "emailReceivers"), ("receivers", "emailReceivers"), ("subject", "emailSubject"),
                        ("body", "emailBody"), ("url", "webhookUrl"), ("headers", "webhookHeaders"), ("payload", "webhookPayload")):
        if alias in action and real not in action:
            action[real] = action.pop(alias)
    if action.get("kind") == "SET_VALUE":
        for deprecated in ("setValueFloat", "setValueInt"):
            if deprecated in action:
                value = action.pop(deprecated)
                action.setdefault("setValueNumeric", value)
        if any(action.get(k) is not None for k in ("setValueNumeric", "setValueBool", "setValueGeo")) and action.get("setValueString") == "":
            action.pop("setValueString")
    if defaults:
        action.setdefault("fireWhenConditionsBecomeHot", True)
        action.setdefault("fireWhenConditionsStayHot", False)
        action.setdefault("fireWhenConditionsBecomeCold", False)
        action.setdefault("minSecondsBetweenHotConditions", 0)
        action.setdefault("maxConsecutiveActionExecutions", 0)
    return action


TEMPLATE_FIELDS = ("emailSubject", "emailBody", "smsBody", "pushTitle", "pushBody", "webhookPayload")
KNOWN_FILTERS = {"round", "datetime", "json"}


def template_warnings(actions):
    """The rule engine renders only {{ }} expressions with the filters round, datetime and json (verified live):
    an unknown filter or a parse error leaves the whole text unrendered, {% %} tags are printed verbatim,
    webhook URLs and headers are never rendered."""
    out = []
    for a in actions or []:
        label_base = a.get("description") or a.get("kind") or "action"
        texts = [(f, a.get(f)) for f in TEMPLATE_FIELDS if isinstance(a.get(f), str)]
        for field, text in texts:
            label = "%s.%s" % (label_base, field)
            if "{%" in text:
                out.append("%s: {%% %%} tags are not interpreted by the rule engine (they stay in the text)" % label)
            for expr in re.findall(r"{{(.*?)}}", text, re.S):
                for filt in re.findall(r"\|\s*([A-Za-z_]+)", expr):
                    if filt not in KNOWN_FILTERS:
                        out.append("%s: unknown filter '%s' (only round, datetime, json exist); the whole text would be sent unrendered" % (label, filt))
                if '\\"' in expr:
                    out.append("%s: escaped double quotes inside {{ }} break the expression parser (whole text sent unrendered); use single quotes, e.g. datetime('%%H:%%M')" % label)
            if "['values']" in text or '["values"]' in text:
                out.append("%s: 'values' is not a template key (renders empty); use 'measurements'" % label)
        if a.get("kind") == "WEBHOOK" or a.get("webhookUrl") or a.get("webhookPayload"):
            headers = [h for h in a.get("webhookHeaders") or [] if isinstance(h, dict)]
            if "{{" in (a.get("webhookUrl") or ""):
                out.append("%s.webhookUrl: URLs are not templates (validation rejects {{ }}); put dynamic values into the payload" % label_base)
            if any("{{" in str(h.get("value", "")) for h in headers):
                out.append("%s.webhookHeaders: header values are sent verbatim, {{ }} is not rendered there" % label_base)
            payload = (a.get("webhookPayload") or "").strip()
            if payload.startswith(("{", "[")):
                if not any(str(h.get("key", "")).lower() == "content-type" for h in headers):
                    out.append("%s: JSON payload without a Content-Type header; Datacake adds none, so set Content-Type: application/json" % label_base)
                try:
                    json.loads(re.sub(r"{{.*?}}", "0", payload, flags=re.S))
                except ValueError as exc:
                    out.append("%s.webhookPayload: not valid JSON once expressions are substituted (%s); quote string expressions or use | json" % (label_base, exc))
    return out


def downlink_warnings(execution_mode, product_id, actions):
    """MULTI_DEVICE_DOWNLINK targets every device of a product on each execution; on a DEVICE_LEVEL rule that runs once per
    device, so a multi downlink to the rule's own product sends devices x devices downlinks (a frequent misunderstanding)."""
    out = []
    mode = execution_mode or "DEVICE_LEVEL"
    for a in actions or []:
        if a.get("kind") != "MULTI_DEVICE_DOWNLINK" or mode != "DEVICE_LEVEL":
            continue
        target = a.get("multiDeviceDownlinkProductId")
        label = a.get("description") or "MULTI_DEVICE_DOWNLINK"
        if target and product_id and target == product_id:
            out.append("%s: multi device downlink to the rule's own product in a DEVICE_LEVEL rule sends devices x devices downlinks; "
                       "use SINGLE_DEVICE_DOWNLINK without a device id (one downlink per device) or SYSTEM_LEVEL (one batch)" % label)
        else:
            out.append("%s: DEVICE_LEVEL runs once per device in scope and each run sends the multi downlink to every device of product %s; "
                       "intended only when the rule's devices are the triggers and product %s the receivers" % (label, target or "?", target or "?"))
    return out


def normalize_input(doc, for_update):
    """Accept CreateRuleNGInputType / UpdateRuleNGInputType documents and the portal's clipboard JSON."""
    doc = strip_nulls(doc)
    doc.pop("id", None)
    if "productId" in doc:
        doc.setdefault("productFilterId", doc.pop("productId"))
    if "whitelabelSite" in doc and isinstance(doc["whitelabelSite"], dict):
        doc["whitelabelSiteId"] = doc.pop("whitelabelSite").get("id", "")
    if not for_update:
        # portal clipboard and `export` output: everything becomes createActions without ids
        actions = list(doc.pop("createActions", None) or []) + list(doc.pop("updateActions", None) or [])
        doc.pop("deleteActions", None)
        doc["createActions"] = [normalize_action(a, keep_id=False, defaults=True) for a in actions]
        for key in ("devicesFilterIds", "triggeringMeasurementFields"):
            if isinstance(doc.get(key), dict):
                doc[key] = doc[key].get("set") or []
    else:
        if doc.get("createActions"):
            doc["createActions"] = [normalize_action(a, keep_id=False, defaults=True) for a in doc["createActions"]]
        if doc.get("updateActions"):
            doc["updateActions"] = [normalize_action(a, keep_id=True, defaults=False) for a in doc["updateActions"]]
            missing = [a for a in doc["updateActions"] if not UUID_RE.match(str(a.get("id", "")))]
            if missing:
                sys.exit("updateActions entries need the id of an existing action (rules.py get <rule-id>)")
        for key in ("devicesFilterIds", "triggeringMeasurementFields"):
            if isinstance(doc.get(key), list):
                doc[key] = {"set": doc[key]}
    if doc.get("conditions") is not None:
        doc["conditions"] = [normalize_condition(c) for c in doc["conditions"]]
    return doc


def export_input(rule):
    """RuleNGType -> CreateRuleNGInputType payload."""
    doc = {
        "name": rule.get("name"), "description": rule.get("description") or "", "timezone": rule.get("timezone"),
        "enabled": rule.get("enabled"), "executionMode": rule.get("executionMode"),
        "productFilterId": (rule.get("productFilter") or {}).get("id", ""),
        "devicesFilterIds": [d["id"] for d in rule.get("devicesFilter") or []],
        "tagsFilter": rule.get("tagsFilter") or [], "tagsFilterConjunction": rule.get("tagsFilterConjunction") or "",
        "triggeringMeasurementFields": [f["id"] for f in rule.get("triggeringMeasurementFields") or []],
        "scheduleTriggerCrontab": rule.get("scheduleTriggerCrontab") or "",
        "zoneLengthOfStayTriggerMinutes": rule.get("zoneLengthOfStayTriggerMinutes"),
        "zoneTagsFilter": rule.get("zoneTagsFilter") or [], "zoneTagsFilterConjunction": rule.get("zoneTagsFilterConjunction") or "",
        "whitelabelSiteId": (rule.get("whitelabelSite") or {}).get("id", ""),
        "conditions": rule.get("conditions") or [],
        "createActions": rule.get("actions") or [],
    }
    for flag, _ in TRIGGER_FLAGS:
        doc[flag] = bool(rule.get(flag))
    return normalize_input(doc, for_update=False)


def plan_summary(doc):
    lines = ["  name: %s   enabled: %s   mode: %s   timezone: %s" % (
        doc.get("name"), doc.get("enabled", True), doc.get("executionMode", "DEVICE_LEVEL (API default)"), doc.get("timezone", "UTC (API default)"))]
    scope = "all devices of the product"
    if doc.get("devicesFilterIds"):
        scope = "%d device ids" % len(doc["devicesFilterIds"] if isinstance(doc["devicesFilterIds"], list) else doc["devicesFilterIds"].get("set") or [])
    elif doc.get("tagsFilter"):
        scope = "tags %s: %s" % (doc.get("tagsFilterConjunction") or "?", ",".join(doc["tagsFilter"]))
    lines.append("  product: %s   scope: %s" % (doc.get("productFilterId") or "(none)", scope))
    lines.append("  triggers: %s" % triggers_of(doc))
    lines.append("  conditions: %d   actions: %s" % (len(doc.get("conditions") or []), actions_summary(doc.get("createActions"))))
    for a in doc.get("createActions") or []:
        targets = a.get("emailReceivers") or a.get("smsReceivers") or a.get("pushRecipientIds") or [a.get("webhookUrl")] if a.get("kind") in ("EMAIL", "SMS", "PUSH", "WEBHOOK") else []
        if targets:
            lines.append("    %s -> %s" % (a.get("kind"), ", ".join(str(t) for t in targets)))
    return "\n".join(lines)


def load_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        sys.exit("cannot read %s: %s" % (path, exc))


def parse_since(text):
    m = re.match(r"^(\d+)([mhd])$", text or "")
    if m:
        n, unit = int(m.group(1)), m.group(2)
        delta = timedelta(minutes=n) if unit == "m" else timedelta(hours=n) if unit == "h" else timedelta(days=n)
        return (datetime.now(timezone.utc) - delta).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        sys.exit("--since expects 30m, 24h, 7d or an ISO timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- commands

def cmd_list(api, args):
    data, errors = api.run(LIST_QUERY, workspace_vars(args.workspace))
    ws = data.get("workspace")
    if not ws:
        sys.exit("workspace not found or no access: %s" % args.workspace)
    rules = ws.get("rulesNG")
    if rules is None:
        sys.exit("rulesNG is not readable in %s (needs the 'rules' permission and the RULE_ENGINE feature; features: %s, myPermissions: %s)" % (
            ws["slug"], ",".join(ws.get("features") or []), ",".join(ws.get("myPermissions") or [])))
    if args.json:
        print(json.dumps(rules, indent=2, ensure_ascii=False))
        return
    print("WORKSPACE %s  (slug: %s, id: %s)  rules: %d  quota: %s remaining of %s  RULE_ENGINE: %s" % (
        ws["name"], ws["slug"], ws["id"], len(rules), ws.get("entitlementRulesQuotaRemaining"), ws.get("entitlementRulesQuota"),
        "yes" if "RULE_ENGINE" in (ws.get("features") or []) else "NO"))
    if rules:
        print(table([[r["id"], r["name"][:40], "on" if r["enabled"] else "off", (r.get("executionMode") or "-").replace("_LEVEL", ""),
                      ((r.get("productFilter") or {}).get("name") or "-")[:24], scope_of(r), triggers_of(r),
                      len(r.get("conditions") or []), actions_summary(r.get("actions"))] for r in rules],
                    ["id", "name", "state", "mode", "product", "scope", "triggers", "cond", "actions"]))
    print("\nNext: python3 scripts/rules.py get <rule-id>   or   logs <rule-id> --since 24h")


def cmd_ids(api, args):
    variables = workspace_vars(args.workspace)
    variables["pageSize"] = args.devices
    if args.tags:
        variables["tags"] = {"contains": [t.strip() for t in args.tags.split(",") if t.strip()]}
    data, _ = api.run(IDS_QUERY, variables)
    ws = data.get("workspace")
    if not ws:
        sys.exit("workspace not found or no access: %s" % args.workspace)
    products = ws.get("products") or []
    if args.product:
        needle = args.product.lower()
        products = [p for p in products if needle in (p.get("name") or "").lower()]
    if args.json:
        ws["products"] = products
        print(json.dumps(ws, indent=2, ensure_ascii=False))
        return
    print("WORKSPACE %s  (slug: %s, id: %s)  RULE_ENGINE: %s  rules permission: %s  rules quota remaining: %s" % (
        ws["name"], ws["slug"], ws["id"], "yes" if "RULE_ENGINE" in (ws.get("features") or []) else "NO",
        "yes" if "rules" in (ws.get("myPermissions") or []) else "NO", ws.get("entitlementRulesQuotaRemaining")))
    site = ws.get("whitelabelSite")
    print("whitelabelSiteId: %s" % ("%s (%s)" % (site["id"], site.get("title")) if site else "(none: Datacake branding)"))
    for p in products:
        print("\nPRODUCT %s  (productFilterId: %s, devices: %s)" % (p["name"], p["id"], p.get("deviceCount")))
        fields = p.get("measurementFields") or []
        if fields:
            print(table([[f["fieldName"], f["verboseFieldName"], f["fieldType"], f.get("unit") or "", f["id"]] for f in fields],
                        ["fieldName (template key)", "verboseFieldName", "type", "unit", "fieldId (conditions, triggers, set value)"]))
        cfg = p.get("configurationFields") or []
        if cfg:
            print("  configuration fields (DYNAMIC_CONFIGURATION_FIELD_VALUE): " + ", ".join(
                "%s %s (%s)" % (c["fieldName"], c["id"], c["fieldType"]) for c in cfg))
        downlinks = [("lorawan", d) for d in p.get("lorawanDownlinks") or []]
        api_cfg = p.get("apiConfiguration") or {}
        # apiDownlinks already lists MQTT-kind downlinks (ApiDownlinkType.kind); mqttDownlinks repeats them
        downlinks += [((d.get("kind") or "api").lower(), d) for d in api_cfg.get("apiDownlinks") or []]
        seen = {d["id"] for _, d in downlinks}
        downlinks += [("mqtt", d) for d in api_cfg.get("mqttDownlinks") or [] if d["id"] not in seen]
        if downlinks:
            print("  downlinks (singleDeviceDownlinkId / multiDeviceDownlinkId): " + ", ".join(
                "%s %s (%s%s)" % (d["name"], d["id"], kind, ", fport %s" % d["fport"] if d.get("fport") is not None else "") for kind, d in downlinks))
    recipients = ws.get("pushRecipientCandidates") or []
    print("\nPUSH RECIPIENTS (pushRecipientIds) %d" % len(recipients))
    if recipients:
        print(table([[r["user"]["id"], r["user"]["email"], ("%s %s" % (r["user"].get("firstName") or "", r["user"].get("lastName") or "")).strip(),
                      "reachable" if r.get("reachable") else "app not installed"] for r in recipients], ["userId", "email", "name", "state"]))
    dl = ws.get("devicesFiltered") or {}
    devices = dl.get("devices") or []
    product_ids = {p["id"] for p in products}
    if args.product:
        devices = [d for d in devices if (d.get("product") or {}).get("id") in product_ids]
    print("\nDEVICES (devicesFilterIds, setValueDeviceId, STATIC_DEVICE_FIELD_VALUE) %d of %s%s" % (
        len(devices), dl.get("total"), " matching tags %s" % args.tags if args.tags else ""))
    if devices:
        print(table([[d["id"], d.get("verboseName"), d.get("serialNumber"), ",".join(d.get("tags") or [])] for d in devices],
                    ["deviceId", "verboseName", "serialNumber", "tags"]))
    print("\nTemplates use fieldName keys: {{ triggering_device['measurements']['<fieldName>'] }}; inputs use the UUIDs above.")


def cmd_get(api, args):
    rule = api.rule(args.rule)
    if args.json:
        print(json.dumps(rule, indent=2, ensure_ascii=False))
        return
    print_rule(rule)


def cmd_export(api, args):
    rule = api.rule(args.rule)
    doc = export_input(rule)
    text = json.dumps(doc, indent=2, ensure_ascii=False)
    if args.file:
        with open(args.file, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print("wrote CreateRuleNGInputType payload for '%s' to %s" % (rule["name"], args.file))
    else:
        print(text)
    sys.stderr.write("note: product, field, device, downlink and recipient ids belong to workspace of rule %s; replace them before creating the rule elsewhere\n" % rule["id"])


def cmd_create(api, args):
    doc = normalize_input(load_json(args.file), for_update=False)
    if not doc.get("name"):
        sys.exit("the payload needs a name")
    data, _ = api.run(LIST_QUERY, workspace_vars(args.workspace))
    ws = data.get("workspace")
    if not ws:
        sys.exit("workspace not found or no access: %s" % args.workspace)
    print("PLAN: create rule in %s (%s)\n%s" % (ws["name"], ws["slug"], plan_summary(doc)))
    warnings = []
    if "rules" not in (ws.get("myPermissions") or []):
        warnings.append("token lacks the 'rules' permission in this workspace")
    if "RULE_ENGINE" not in (ws.get("features") or []):
        warnings.append("workspace has no RULE_ENGINE feature")
    if ws.get("entitlementRulesQuotaRemaining") == 0:
        warnings.append("rules quota exhausted")
    if doc.get("triggerOnMeasurement") and not doc.get("conditions"):
        warnings.append("measurement trigger without conditions runs every action on every uplink (fire flags, cooldown and limits are ignored)")
    warnings += template_warnings(doc.get("createActions"))
    if any(doc.get(f) for f in ("triggerOnMeasurement", "triggerOnDeviceGoesOffline", "triggerOnDeviceGoesOnline")) and not doc.get("productFilterId"):
        warnings.append("device-level triggers need productFilterId")
    if not any(doc.get(f) for f, _ in TRIGGER_FLAGS):
        warnings.append("no trigger enabled: the rule will never run")
    if not doc.get("createActions"):
        warnings.append("no actions: the rule does nothing")
    warnings += downlink_warnings(doc.get("executionMode"), doc.get("productFilterId"), doc.get("createActions"))
    for w in warnings:
        print("  WARNING: %s" % w)
    if not args.execute:
        print("dry run: add --execute to create the rule (payload below)")
        print(json.dumps(doc, indent=2, ensure_ascii=False))
        return
    data, errors = api.run(CREATE_MUTATION, {"workspaceId": ws["id"], "input": doc})
    result = data.get("createRuleNG") or {}
    if errors or not result.get("ok"):
        sys.exit("create failed: %s" % json.dumps(result.get("error") or errors)[:800])
    rule = result.get("ruleNG") or {}
    print("created rule %s (%s), enabled=%s" % (rule.get("name"), rule.get("id"), rule.get("enabled")))


def cmd_update(api, args):
    rule = api.rule(args.rule)
    doc = normalize_input(load_json(args.file), for_update=True)
    print("PLAN: update rule %s (%s) with:\n%s" % (rule["name"], rule["id"], json.dumps(doc, indent=2, ensure_ascii=False)))
    if doc.get("conditions") is not None:
        print("  note: 'conditions' replaces the complete condition list (%d -> %d)" % (len(rule.get("conditions") or []), len(doc["conditions"])))
    mode = doc.get("executionMode") or rule.get("executionMode")
    product = doc.get("productFilterId") if "productFilterId" in doc else (rule.get("productFilter") or {}).get("id")
    for w in template_warnings(list(doc.get("createActions") or []) + list(doc.get("updateActions") or [])) + \
            downlink_warnings(mode, product, list(doc.get("createActions") or []) + list(doc.get("updateActions") or [])):
        print("  WARNING: %s" % w)
    if not args.execute:
        print("dry run: add --execute to apply")
        return
    data, errors = api.run(UPDATE_MUTATION, {"id": rule["id"], "input": doc})
    result = data.get("updateRuleNG") or {}
    if errors or not result.get("ok"):
        sys.exit("update failed: %s" % json.dumps(result.get("error") or errors)[:800])
    print("updated rule %s (%s), enabled=%s" % (result["ruleNG"]["name"], result["ruleNG"]["id"], result["ruleNG"]["enabled"]))


def cmd_toggle(api, args):
    rule = api.rule(args.rule)
    enabled = args.command == "enable"
    if bool(rule.get("enabled")) == enabled:
        print("rule %s (%s) is already %s" % (rule["name"], rule["id"], "enabled" if enabled else "disabled"))
        return
    print("PLAN: %s rule %s (%s)" % (args.command, rule["name"], rule["id"]))
    if not args.execute:
        print("dry run: add --execute to apply")
        return
    data, errors = api.run(UPDATE_MUTATION, {"id": rule["id"], "input": {"enabled": enabled}})
    result = data.get("updateRuleNG") or {}
    if errors or not result.get("ok"):
        sys.exit("%s failed: %s" % (args.command, json.dumps(result.get("error") or errors)[:800]))
    print("rule %s is now %s" % (rule["name"], "enabled" if result["ruleNG"]["enabled"] else "disabled"))


def cmd_delete(api, args):
    rule = api.rule(args.rule)
    print("PLAN: delete rule %s (%s): %d conditions, %s; this cannot be undone" % (
        rule["name"], rule["id"], len(rule.get("conditions") or []), actions_summary(rule.get("actions"))))
    if not args.execute:
        print("dry run: add --execute to delete (consider 'disable' instead, or 'export' first)")
        return
    data, errors = api.run(DELETE_MUTATION, {"id": rule["id"]})
    result = data.get("deleteRuleNG") or {}
    if errors or not result.get("ok"):
        sys.exit("delete failed: %s" % json.dumps(result.get("error") or errors)[:800])
    print("deleted.")


def cmd_logs(api, args):
    if not UUID_RE.match(args.rule):
        sys.exit("rule id must be a UUID")
    filt = {}
    if args.since:
        filt["triggerTimestamp"] = {"gte": parse_since(args.since)}
    if args.fired:
        filt["anyActionFired"] = {"exact": True}
    if args.device:
        filt["triggeringDeviceId"] = {"exact": args.device}
    entries, after, name = [], None, None
    while len(entries) < args.limit:
        data, errors = api.run(LOGS_QUERY, {"id": args.rule, "first": min(50, args.limit - len(entries)), "after": after, "filter": filt or None})
        rule = data.get("ruleNG")
        if not rule:
            sys.exit("rule not found, no access, or logs not included in the plan: %s" % args.rule)
        name = rule["name"]
        conn = rule.get("executionLogEntries") or {}
        entries.extend(e["node"] for e in conn.get("edges") or [] if e and e.get("node"))
        if not (conn.get("pageInfo") or {}).get("hasNextPage"):
            break
        after = conn["pageInfo"]["endCursor"]
    if args.json:
        print(json.dumps(entries, indent=2, ensure_ascii=False))
        return
    print("RULE %s (%s): %d log entries%s%s" % (name, args.rule, len(entries), " since %s" % args.since if args.since else "",
                                                " with fired actions" if args.fired else ""))
    rows = []
    for e in entries:
        who = (e.get("triggeringDevice") or {}).get("verboseName") or (e.get("triggeringGateway") or {}).get("name") or "-"
        acts = ", ".join("%s:%s" % (a.get("kind"), "fired" if a.get("isFired") else "skipped") for a in e.get("actionExecutionLogEntries") or []) or "-"
        rows.append([(e.get("triggerTimestamp") or "")[:19], e.get("initiator"), who[:28],
                     {True: "true", False: "false"}.get(e.get("conditionsResult"), "-"), (e.get("actionFiringEvent") or "-").replace("CONDITIONS_", ""), acts])
    if rows:
        print(table(rows, ["trigger (UTC)", "initiator", "device/gateway", "conditions", "event", "actions"]))
    if args.trace:
        for e in entries:
            print("\n--- %s %s" % (e.get("triggerTimestamp"), (e.get("triggeringDevice") or {}).get("verboseName") or ""))
            print(e.get("conditionsPrettyEvaluationTrace") or "(no conditions)")
            variables = []
            for raw in e.get("actionExecutionVariables") or []:
                try:
                    variables.append(json.loads(raw) if isinstance(raw, str) else raw)
                except ValueError:
                    variables.append({})
            for i, a in enumerate(e.get("actionExecutionLogEntries") or []):
                rv = ((variables[i] if i < len(variables) else None) or {}).get("runtime_variables") or {}
                detail = {k: v for k, v in rv.items() if k not in ("email_body", "email_subject", "email_receivers", "push_body", "push_title",
                                                                    "is_fired_by_event", "is_within_active_time_period", "email_branding_title")}
                print("  [%s] fired=%s byEvent=%s inTimeWindow=%s%s\n  %s" % (
                    a.get("kind"), a.get("isFired"), a.get("isFiredByEvent"), a.get("isWithinActiveTimePeriod"),
                    (" " + json.dumps(detail, ensure_ascii=False)) if detail else "",
                    (a.get("prettyTrace") or "(not executed: no trace)").replace("\n", "\n  ")))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--token")
    ap.add_argument("--endpoint", default=ENDPOINT)
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("list", help="rules of one workspace")
    p.add_argument("workspace")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("ids", help="ids needed to write a rule: product, fields, downlinks, devices, push recipients")
    p.add_argument("workspace")
    p.add_argument("--product", help="only products whose name contains this text")
    p.add_argument("--tags", help="comma-separated tags; devices must carry all of them")
    p.add_argument("--devices", type=int, default=50, help="number of devices to list (default 50)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_ids)

    p = sub.add_parser("get", help="full definition of one rule")
    p.add_argument("rule", help="rule id")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_get)

    p = sub.add_parser("export", help="CreateRuleNGInputType payload of an existing rule")
    p.add_argument("rule", help="rule id")
    p.add_argument("--file", help="write the payload here instead of stdout")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("create", help="create a rule from a JSON payload (dry run by default)")
    p.add_argument("workspace")
    p.add_argument("--file", required=True, help="CreateRuleNGInputType JSON (or portal copy/paste JSON)")
    p.add_argument("--execute", action="store_true")
    p.set_defaults(func=cmd_create)

    p = sub.add_parser("update", help="update a rule from a JSON patch (dry run by default)")
    p.add_argument("rule", help="rule id")
    p.add_argument("--file", required=True, help="UpdateRuleNGInputType JSON with only the fields to change")
    p.add_argument("--execute", action="store_true")
    p.set_defaults(func=cmd_update)

    for name in ("enable", "disable"):
        p = sub.add_parser(name, help="%s a rule" % name)
        p.add_argument("rule", help="rule id")
        p.add_argument("--execute", action="store_true")
        p.set_defaults(func=cmd_toggle)

    p = sub.add_parser("delete", help="delete a rule permanently (dry run by default)")
    p.add_argument("rule", help="rule id")
    p.add_argument("--execute", action="store_true")
    p.set_defaults(func=cmd_delete)

    p = sub.add_parser("logs", help="execution log of a rule")
    p.add_argument("rule", help="rule id")
    p.add_argument("--since", help="30m, 24h, 7d or an ISO timestamp")
    p.add_argument("--fired", action="store_true", help="only entries where an action fired")
    p.add_argument("--device", help="only entries triggered by this device id")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--trace", action="store_true", help="print condition and action evaluation traces")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_logs)

    args = ap.parse_args()
    token = resolve_token(args.token)
    if not token:
        sys.exit("no token: export DATACAKE_TOKEN=<token> (a token with the 'rules' permission; see reference/rules-ng.md)")
    args.func(Api(token, args.endpoint), args)


if __name__ == "__main__":
    main()
