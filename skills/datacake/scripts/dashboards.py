#!/usr/bin/env python3
"""Datacake dashboards: list, read, create, edit (widgets, tabs), check and save workspace and device dashboards.

Usage:
  python3 scripts/dashboards.py list <workspace> [--json]                  # workspace dashboards + products with their device dashboards
  python3 scripts/dashboards.py get <target> [--tab N] [--json] [--out layout.json]
  python3 scripts/dashboards.py schema [<WidgetType>|presets] [--device]   # widget catalogue (contexts, sizes), one widget's defaults, or the Value presets
  python3 scripts/dashboards.py generate product:<product-id> [--tab N | --new-tab "Name"] [--replace] [--title "..."]
                                       [--fields A,B,C | --exclude '*_INST,*_RAW'] [--timeframe "7 days ago" --resolution 1h] [--controls FIELD,...] [--execute]
                                       # complete device dashboard from the product's fields: headline, values with presets, states, charts
  python3 scripts/dashboards.py generate <dashboard-id> --product <product-id> [--tags site-a,fridge] [--max-devices 12] [--new-tab "Name"] [--execute]
                                       # fleet overview on a workspace dashboard: semantic KPIs, device table, map, per-device chart, heatmap, histogram
  python3 scripts/dashboards.py create <workspace> --name "Fleet" [--icon chart-line] [--sharing workspace|public|restricted]
                                       [--shared-with <user-id>,...] [--home] [--file layout.json] [--execute]
  python3 scripts/dashboards.py save <target> --file layout.json [--message "..."] [--force] [--execute]
  python3 scripts/dashboards.py add-widget <target> --type Value [--title "Temperature"] [--field TEMPERATURE[@<device-id>]] [--preset humidity]
                                       [--meta '{...}' | --meta @meta.json] [--tab N] [--x N --y N --w N --h N | --next] [--execute]
  python3 scripts/dashboards.py update-widget <target> <widget-id> --meta '{...}' [--tab N] [--execute]
  python3 scripts/dashboards.py move-widget <target> <widget-id> [--x N] [--y N] [--w N] [--h N] [--tab N] [--execute]
  python3 scripts/dashboards.py remove-widget <target> <widget-id> [--tab N] [--execute]
  python3 scripts/dashboards.py tab add <target> --name "Energy" [--hide-on-whitelabel] [--execute]
  python3 scripts/dashboards.py tab rename <target> <index> --name "..." [--execute]
  python3 scripts/dashboards.py tab remove <target> <index> [--execute]
  python3 scripts/dashboards.py check <target> [--tab N] [--widget <id>] [--type T --meta '{...}'] [--file layout.json] [--device <id>]
  python3 scripts/dashboards.py validate --file layout.json [--kind workspace|device]   # offline structure check
  python3 scripts/dashboards.py changelog <target> [--first 10] [--json]
  python3 scripts/dashboards.py restore <target> <historyId> [--execute]
  python3 scripts/dashboards.py delete <dashboard-id> [--execute]

<target> is a workspace dashboard id (UUID), or the device dashboard of a product: product:<product-id> or
device:<device-id> (the device's product; the dashboard is shared by every device of that product).
<workspace> is a UUID or slug. Write commands print their plan (diff, warnings); add --execute to run them.

Every write re-reads the dashboard, replaces the WHOLE layout (all tabs) in one mutation and sets a change
message. The portal does not pick up external changes: tell the user to reload the dashboard page.
Token: $DATACAKE_TOKEN or ~/.datacake/token (or --token). Standard library only; reuses dc.py.
Reference: reference/dashboards.md
"""
import argparse
import copy
import fnmatch
import json
import os
import re
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dc import ENDPOINT, gql, report_errors, resolve_token  # noqa: E402

UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
RESOLUTION_RE = re.compile(r"^\d+(m|h|d|w)$")
COLUMNS = {"lg": 12, "sm": 4}          # desktop grid / mobile grid (react-grid-layout breakpoints of the portal)
MESSAGE_MAX = 100                       # changeMessage limit of the portal's save dialog
LANGUAGES = ["ar", "bg", "cs", "da", "de", "el", "en", "es", "et", "fi", "fr", "hr", "hu", "it", "ja", "ko", "lb", "lt", "lv",
             "nl", "no", "pl", "pt", "ro", "ru", "se", "sk", "sl", "th", "tn", "tr", "uk", "vi", "zh"]
NUMERIC = {"FLOAT", "INT", "NUMERIC", "COUNTER"}
# Field types a widget accepts for its field reference (DashboardEditorNG/forms/DeviceField.tsx)
FIELD_TYPES = {"Boolean": {"BOOL"}, "Switch": {"BOOL"}, "Emergency": {"BOOL"}, "Map": {"GEO"},
               "Value": NUMERIC | {"STRING"}, "Slider": {"FLOAT", "INT", "NUMERIC"}, "SetValue": NUMERIC | {"STRING", "BOOL"},
               "LineChart": NUMERIC | {"BOOL"}, "Histogram": NUMERIC, "Heatmap": NUMERIC}
PRODUCT_LOCK_FEATURE = "locked_dashboard"

# Widget catalogue. Defaults and sizes come from the portal's dashboard editor (DashboardEditorNG/widgets/*/index.tsx);
# contexts from AddWidgetModal.tsx. "data": the server-side preview (dashboardData) returns a value key for the widget.
# "portal": True = configure in the portal and copy the JSON; add-widget refuses to invent its meta.
WIDGETS = {
    "Value": {"size": (4, 3), "contexts": "both", "required": ["field"], "data": True,
              "doc": "Current (or aggregated) value of one field with optional gauge. gaugeType: none|linear|vertical|circular|fill|battery|compass|gradientramp. "
                     "gaugeRanges: [{value, color, name}] where value is the LOWER bound of each range (ascending). timerangeOperation: {other: true, operation: "
                     "minimum|maximum|average|sum|abschange|percchange|count, start: '7 days ago', end: 'now', timezone}. Title placeholder '{ device_name }' (workspace).",
              "meta": {"title": {"en": "New Value Widget"}, "decimalPlaces": 2, "fillLevelShape": "circular",
                       "timerangeOperation": {"other": False, "start": "", "end": "", "operation": "", "timezone": "UTC"},
                       "gaugeType": "none", "hasAnimation": False, "showDegree": False, "isTextColorStateBased": False,
                       "isAbbreviatedNumber": False, "hideBackground": False, "hideLastUpdate": False, "hideValue": False, "fontSize": 40,
                       "verticalDirection": "ascending", "gradientRampDirection": "ltr", "gradientRampMode": "ascending",
                       "showRangeLegend": False, "showCurrentRangeName": True, "widgetPreset": "none", "dataSourceMode": "static"}},
    "Boolean": {"size": (4, 2), "contexts": "both", "required": ["field"], "data": True,
                "doc": "On/off state of a BOOL field. displayOn/displayOff (translated), displayOnColor/displayOffColor, icon, isBgColorStateBased.",
                "meta": {"title": {"en": "New Boolean"}, "isBgColorStateBased": False, "hideBackground": False, "hideLastUpdate": False}},
    "Headline": {"size": (4, 1), "contexts": "both", "required": ["title"], "data": False,
                 "doc": "Section heading. size 1 (largest) to 5, layout vertical|horizontal, description, colours, gradient, bottom border. Use w: 12 as a divider.",
                 "meta": {"title": {"en": "New Headline"}, "description": {"en": ""}, "hideBackground": True, "center": False, "layout": "vertical", "size": 2,
                          "useGradient": False, "backgroundColor": "#ffffff", "gradientStartColor": "#ffffff", "gradientEndColor": "#000000",
                          "gradientDirection": "to bottom", "showBottomBorder": False, "bottomBorderColor": "#e5e7eb", "bottomBorderSize": 1}},
    "Text": {"size": (4, 2), "contexts": "both", "required": ["text"], "data": True,
             "doc": "Markdown text. Variables: {{ FIELD_NAME }} on device dashboards, {{ <device-id>[FIELD_NAME] }} on workspace dashboards.",
             "meta": {"text": {"en": ""}, "hideBackground": False, "center": False}},
    "LineChart": {"size": (8, 4), "contexts": "both", "required": ["devices"], "data": True,
                  "doc": "Time series. devices: one series per entry {device, fields: [{field, color, verboseName, chartKind: line|area|bar, strokeWidth}], "
                         "yAxis: {id, orientation: left|right, hidden, scale: auto|linear, domain, unit}, label, interpolationType}. Same yAxis.id = same axis. "
                         "timeframe: {start, end, resolution '<n>m|h|d|w', otherTimeframe, timezone}; historyFunction '' (avg)|min|max|sum; referenceLines.",
                  "meta": {"title": {"en": "New Line Chart"},
                           "timeframe": {"start": "24 hours ago", "end": "now", "resolution": "15m", "otherTimeframe": False, "timezone": "UTC"},
                           "showXGrid": True, "devices": [], "dateFormat": "DATE_SHORT", "hideBackground": False, "historyFunction": "",
                           "allowTimeframeSelect": False, "showExportViewButton": False, "hideLastUpdate": False, "showStatisticsButton": False}},
    "Histogram": {"size": (8, 3), "contexts": "both", "required": ["devices"], "data": False,
                  "doc": "Bar or pie chart of the CURRENT values of several devices. devices: [{device, fieldName, color, title}] (flat). chartType bar|pie, "
                         "valueRanges [{id, min, max, color, name}] with enableValueRanges.",
                  "meta": {"chartType": "bar", "showStatisticsTable": True, "showValuesOnBars": True, "decimalPlaces": 1, "showXGrid": False, "showYAxis": False,
                           "title": {"en": "New Histogram"}, "hideBackground": False, "hideLastUpdate": False, "enableValueRanges": False, "gradientColors": False,
                           "valueRanges": [], "dataSourceMode": "static", "devices": []}},
    "Heatmap": {"size": (8, 3), "contexts": "both", "required": ["devices"], "data": True,
                "doc": "Hourly ('1h') or daily ('24h') cells per device/field. devices: [{device, fieldName, verboseName, unit, rangeSettings: [{value, color, text}]}]. "
                       "timeframe is the string '1h' or '24h'; orientation horizontal|vertical; cellSize small|normal.",
                "meta": {"title": {"en": "Heatmap"}, "cellSize": "normal", "cellCount": 5, "timeframe": "24h", "orientation": "horizontal", "hasBoldValues": False,
                         "hasGradient": True, "hasWeekDays": False, "markStaleData": False, "decimalPlaces": 2, "dataSourceMode": "static",
                         "showExportViewButton": False, "timezone": "UTC", "devices": []}},
    "Table": {"size": (4, 4), "contexts": "workspace", "required": ["columns"], "data": True,
              "doc": "Device table (workspace only). Devices by tagsFilter [tags] and nameFilter; columns: [{id: uuid, name, dataKind: meta|measurement, "
                     "metaKind: LinkedName|Name|LastHeardDevice|Online|SerialNumber|Location|Metadata (+metadataKey), measurementFieldName, "
                     "measurementTimerangeOperation: current|average|sum|minimum|maximum|abschange|percchange|count, floatDigits, unit, footerOperation}]. "
                     "conditionalFormatting: [{column: <column id>, condition: smaller|smallerequals|equals|equalsnot|largerequals|larger, target, textColor, backgroundColor}].",
              "meta": {"title": {"en": "New Table"}, "tagsFilter": [], "nameFilter": "", "columns": [], "defaultPaginateBy": "50", "showPagination": "always",
                       "defaultSortByColumn": 0, "defaultSortDirection": "asc", "conditionalFormatting": [], "hideBackground": False, "showFooter": False,
                       "hideHeaderBackground": False, "tableSize": "small", "showExcelExport": True}},
    "MapNG": {"size": (4, 4), "contexts": "workspace", "required": [], "data": False,
              "doc": "Map of all workspace devices with a location (role DEVICE_LOCATION), filtered by allDevicesFilterTags + allDevicesFilterTagsAnyAll any|all. "
                     "mapStyle light|dark|streets|outdoor|satellite|basic, mapMode marker|heatmap, markerRoleChoice None|Primary|Secondary|DeviceBattery|DeviceSignal "
                     "(value shown/coloured per marker), usesValueBasedColors + gaugeRanges, location {latitude, longitude, zoom} for the initial view.",
              "meta": {"title": {"en": "New Map Widget"}, "useHistory": False, "devices": [], "mapStyle": "light", "mapMode": "marker", "markerRoleChoice": "Primary",
                       "isSlideOverPublic": False, "isClusterDisabled": False, "isFullScreenHeight": False, "hideBackground": False, "isDeviceNameVisible": False,
                       "markerSize": "70", "usesDynamicSizing": False, "dynamicSizingStart": "30", "dynamicSizingEnd": "180", "usesGradientColors": False,
                       "usesValueBasedTextColors": False, "markerTransparency": "0", "markerBlendToggle": False, "showFilterPanel": True,
                       "allDevicesFilterTags": [], "allDevicesFilterTagsAnyAll": "any"}},
    "MeasurementList": {"size": (4, 9), "contexts": "both", "required": ["field"], "data": True,
                        "doc": "Last n readings of one field as a list. limit is a string ('10'); boolean texts/colours; gaugeRanges with useValueBasedColors.",
                        "meta": {"title": {"en": "Measurement List"}, "hideBackground": False, "limit": "10", "useBooleanLookup": False, "booleanTrueText": "True",
                                 "booleanFalseText": "False", "booleanTrueColor": "#22c55e", "booleanFalseColor": "#ef4444", "booleanColumnHeader": "",
                                 "booleanShowColorBubbles": True, "useValueBasedColors": False, "gaugeRanges": [], "showRangeName": False, "hideFieldValue": False,
                                 "useGradientColors": False, "numericalColumnHeader": "", "showColorBubbles": True}},
    "Image": {"size": (4, 3), "contexts": "both", "required": ["image"], "data": False,
              "doc": "Image uploaded in the portal (image = upload id; uploads are portal-only). size contain|cover, link {url, newTab}, useDeviceImage (device dashboards).",
              "meta": {"size": "contain", "hideBackground": True}},
    "Iframe": {"size": (4, 4), "contexts": "both", "required": ["source"], "data": False,
               "doc": "Embeds a URL (source).",
               "meta": {"title": {"en": "New Iframe"}, "hideBackground": False, "isFullScreenHeight": False}},
    "Button": {"size": (3, 1), "contexts": "both", "required": ["function"], "data": False,
               "doc": "Runs a product function (dzero hardware only; the portal hides it elsewhere). function: {device, function, functionId, fieldStates}.",
               "meta": {"title": {"en": "New Button"}, "hideBackground": True}},
    "Switch": {"size": (4, 2), "contexts": "both", "required": ["field"], "data": True,
               "doc": "Toggle that writes 1/0 into a BOOL field (setValue).",
               "meta": {"title": {"en": "New Switch"}, "hideBackground": False}},
    "Slider": {"size": (6, 2), "contexts": "both", "required": ["field"], "data": True,
               "doc": "Writes a numeric value into a field. min, max, step, unit, orientation horizontal|vertical, isRangeVisible.",
               "meta": {"title": {"en": "New Slider"}, "min": 0, "max": 100, "hideBackground": False, "orientation": "horizontal", "devices": [], "step": 1,
                        "isRangeVisible": False}},
    "SetValue": {"size": (3, 1), "contexts": "both", "required": ["field"], "data": True,
                 "doc": "Input + button that writes a value. fieldType measurement (field) or config (configurationField {device, fieldName, fieldType, verboseFieldName}); "
                        "widgetTitle, description.",
                 "meta": {"title": {"en": "Set Value"}, "hideBackground": False, "fieldType": "measurement", "hideLastUpdate": False}},
    "OnlineStatus": {"size": (4, 2), "contexts": "device", "required": [], "data": False,
                     "doc": "Online/offline of the viewed device (device dashboards only; no field). displayOn/displayOff, colours, icon.",
                     "meta": {"title": {"en": "Online status"}, "isBgColorStateBased": False, "hideBackground": False, "hideLastUpdate": False}},
    "Downlink": {"size": (3, 1), "contexts": "both", "required": ["downlink"], "data": False,
                 "doc": "Button that sends a product downlink. downlink: {device, downlink: <downlink id from product.lorawanDownlinks / apiConfiguration.apiDownlinks>}; "
                        "additionalDownlinks: [{device, fields: [{field: <downlink id>, name}]}].",
                 "meta": {"title": {"en": "Downlink"}, "hideBackground": False}},
    # Widgets that are configured in the portal (copy their JSON; add-widget does not generate them).
    "Map": {"size": (4, 4), "contexts": "device", "portal": True, "doc": "Legacy map of GEO fields (device dashboards); MapNG is the workspace map."},
    "DeviceFields": {"size": (4, 4), "contexts": "device", "portal": True, "doc": "List of selected product fields with current values (selectedFields)."},
    "ImageMap": {"size": (4, 3), "contexts": "both", "portal": True, "doc": "Markers with values on an uploaded image (devices with xPosition/yPosition)."},
    "Menu": {"size": (3, 6), "contexts": "both", "portal": True, "doc": "Navigation links (menuItems [{id, label, url, openInNewTab}])."},
    "ScatterPlot": {"size": (6, 5), "contexts": "both", "portal": True, "doc": "x/y scatter of two fields over a timeframe."},
    "AshraeChart": {"size": (8, 4), "contexts": "both", "portal": True, "doc": "ASHRAE class compliance chart (data centre climate)."},
    "CoolingHealth": {"size": (8, 6), "contexts": "both", "portal": True, "doc": "Cooling appliance health score (temperature + humidity fields, thresholds)."},
    "Emergency": {"size": (2, 4), "contexts": "both", "portal": True, "doc": "SOS button bound to a BOOL field."},
    "TextInput": {"size": (4, 2), "contexts": "none", "portal": True, "doc": "Hidden in the portal; do not use."},
}

BUTTON_HARDWARE = "dzero"

# Value presets of the portal editor (DashboardEditorNG/widgets/Value/index.tsx, VALUE_PRESETS): ranges, colours, icons, units.
# gaugeType follows the Datacake styling guidance where it differs from the editor preset: circular gauges read best, the
# gradient ramp suits banded quantities such as temperature, battery and fill-level gauges stay for their kinds.
# batteryPercent is a skill addition for BATTERY fields reported in percent (the editor preset is in volts).
PRESETS = {
    "temperature": {"semantic": "TEMPERATURE", "settings": {
        "title": {"en": "Temperature"}, "unit": {"en": "°C"}, "icon": "thermometer-half", "gaugeType": "gradientramp",
        "gradientRampDirection": "ltr", "gradientRampMode": "ascending", "decimalPlaces": 1, "isTextColorStateBased": True,
        "gaugeRanges": [{"value": "0", "color": "#3B82F6", "name": "Cold"}, {"value": "10", "color": "#06B6D4", "name": "Cool"},
                        {"value": "20", "color": "#10B981", "name": "Comfortable"}, {"value": "25", "color": "#F59E0B", "name": "Warm"},
                        {"value": "30", "color": "#EF4444", "name": "Hot"}]}},
    "humidity": {"semantic": "HUMIDITY", "settings": {
        "title": {"en": "Humidity"}, "unit": {"en": "%"}, "icon": "tint", "gaugeType": "circular", "decimalPlaces": 1, "isTextColorStateBased": True,
        "gaugeRanges": [{"value": "0", "color": "#EF4444", "name": "Too Dry"}, {"value": "30", "color": "#F59E0B", "name": "Dry"},
                        {"value": "40", "color": "#10B981", "name": "Comfortable"}, {"value": "60", "color": "#10B981", "name": "Comfortable"},
                        {"value": "70", "color": "#F59E0B", "name": "Humid"}, {"value": "80", "color": "#EF4444", "name": "Too Humid"}]}},
    "co2": {"semantic": "CO2", "settings": {
        "title": {"en": "CO₂ Level"}, "unit": {"en": "ppm"}, "icon": "smog", "gaugeType": "circular", "decimalPlaces": 0, "isTextColorStateBased": True,
        "gaugeRanges": [{"value": "0", "color": "#0ea5e9", "name": "Excellent"}, {"value": "450", "color": "#22c55e", "name": "Good"},
                        {"value": "600", "color": "#f59e0b", "name": "Moderate"}, {"value": "1000", "color": "#f97316", "name": "Poor"},
                        {"value": "1500", "color": "#ef4444", "name": "Unhealthy"}]}},
    "co2Concentration": {"semantic": None, "settings": {
        "title": {"en": "CO₂ concentration"}, "unit": {"en": "%"}, "icon": "leaf", "gaugeType": "gradientramp", "decimalPlaces": 2,
        "isTextColorStateBased": True, "gradientRampDirection": "ltr", "gradientRampMode": "ascending",
        "gaugeRanges": [{"value": "0", "color": "#22c55e", "name": "Optimal"}, {"value": "30", "color": "#84cc16", "name": "Good"},
                        {"value": "50", "color": "#eab308", "name": "Moderate"}, {"value": "70", "color": "#f97316", "name": "High"},
                        {"value": "85", "color": "#ef4444", "name": "Critical"}]}},
    "battery": {"semantic": "BATTERY", "settings": {
        "title": {"en": "Battery"}, "unit": {"en": "V"}, "icon": "battery-three-quarters", "gaugeType": "battery", "decimalPlaces": 2,
        "gaugeRanges": [{"value": "0", "color": "#f56565"}, {"value": "1.85", "color": "#ecc94b"}, {"value": "3.7", "color": "#48bb78"}]}},
    "batteryPercent": {"semantic": "BATTERY", "settings": {
        "title": {"en": "Battery"}, "unit": {"en": "%"}, "icon": "battery-three-quarters", "gaugeType": "battery", "decimalPlaces": 0,
        "gaugeRanges": [{"value": "0", "color": "#f56565", "name": "Low"}, {"value": "20", "color": "#ecc94b", "name": "Medium"},
                        {"value": "50", "color": "#48bb78", "name": "Good"}]}},
    "fillLevel": {"semantic": "FILL_LEVEL", "settings": {
        "title": {"en": "Fill Level"}, "unit": {"en": "%"}, "icon": "fill-drip", "gaugeType": "fill", "fillLevelShape": "tank", "decimalPlaces": 1,
        "gaugeRanges": [{"value": "0", "color": "#4299e1"}, {"value": "100", "color": "#4299e1"}]}},
    "signalStrength": {"semantic": "SIGNAL", "settings": {
        "title": {"en": "Signal Level"}, "unit": {"en": "dBm"}, "icon": "signal", "gaugeType": "circular", "decimalPlaces": 0, "isTextColorStateBased": True,
        "gaugeRanges": [{"value": "-90", "color": "#dc2626", "name": "Very Poor"}, {"value": "-80", "color": "#f97316", "name": "Poor"},
                        {"value": "-70", "color": "#f59e0b", "name": "Fair"}, {"value": "-60", "color": "#84cc16", "name": "Good"},
                        {"value": "-50", "color": "#22c55e", "name": "Excellent"}, {"value": "-30", "color": "#00ff00", "name": "Perfect"}]}},
    "soilMoisture": {"semantic": "SOIL_MOISTURE", "settings": {
        "title": {"en": "Soil Moisture"}, "unit": {"en": "%"}, "icon": "leaf", "gaugeType": "circular", "decimalPlaces": 0, "isTextColorStateBased": True,
        "gaugeRanges": [{"value": "0", "color": "#f56565", "name": "Extreme stress"}, {"value": "21", "color": "#ecc94b", "name": "Stress"},
                        {"value": "41", "color": "#48bb78", "name": "Good"}, {"value": "61", "color": "#ecc94b", "name": "Excess"},
                        {"value": "100", "color": "#f56565", "name": "Excess"}]}},
    "ambientLight": {"semantic": "AMBIENT_LIGHT", "settings": {
        "title": {"en": "Ambient Light"}, "unit": {"en": "lux"}, "icon": "sun", "gaugeType": "circular", "decimalPlaces": 0, "isTextColorStateBased": True,
        "gaugeRanges": [{"value": "0", "color": "#1E293B", "name": "Night"}, {"value": "10", "color": "#475569", "name": "Very Dark"},
                        {"value": "50", "color": "#64748B", "name": "Dark"}, {"value": "200", "color": "#F59E0B", "name": "Dim"},
                        {"value": "500", "color": "#FCD34D", "name": "Moderate"}, {"value": "1000", "color": "#FDE047", "name": "Bright"}]}},
}
SEMANTIC_PRESET = {"TEMPERATURE": "temperature", "HUMIDITY": "humidity", "CO2": "co2", "BATTERY": "battery", "FILL_LEVEL": "fillLevel",
                   "SIGNAL": "signalStrength", "SOIL_MOISTURE": "soilMoisture", "AMBIENT_LIGHT": "ambientLight"}
CHART_COLORS = ["#ef4444", "#3b82f6", "#10b981", "#f59e0b", "#8b5cf6", "#06b6d4", "#ec4899", "#84cc16"]

PRODUCT_FIELDS = """id name slug hardware features deviceCount dashboards
    workspace { id name slug myPermissions entitlementDashboardHistoryEnabled }
    measurementFields(active: true) { id fieldName verboseFieldName fieldType unit role semantic floatDigits }"""

LIST_QUERY = """
query Dashboards($id: String, $slug: String) {
  workspace(id: $id, slug: $slug) {
    id name slug myPermissions entitlementDashboardHistoryEnabled
    homeDashboard { id }
    dashboards { id name type icon sharingPolicy dashboards }
    products { id name deviceCount features dashboards }
  }
}
"""

DASHBOARD_QUERY = """
query Dashboard($id: String!) {
  dashboard(id: $id) {
    id name type icon sharingPolicy sharedWith { id email } dashboards metaJSON
    workspace { id name slug }
    publicLinks { id name mode }
  }
}
"""

WORKSPACE_QUERY = """
query WorkspaceMeta($id: String!) {
  workspace(id: $id) { id myPermissions entitlementDashboardHistoryEnabled homeDashboard { id } }
}
"""

PRODUCT_QUERY = "query Product($id: String!) { product(id: $id) { %s } }" % PRODUCT_FIELDS
DEVICE_QUERY = "query Device($id: String!) { device(deviceId: $id) { id verboseName product { %s } } }" % PRODUCT_FIELDS

DEVICES_QUERY = """
query ProductDevices($id: String!, $page: Int!, $tags: FilteredDeviceListTagsFilterInput) {
  workspace(id: $id) {
    devicesFiltered(page: $page, pageSize: 100, tags: $tags, orderBy: { verboseName: ASC }) { total devices { id verboseName product { id } } }
  }
}
"""

WORKSPACE_SEMANTICS_QUERY = """
query WorkspaceSemantics($id: String!) {
  workspace(id: $id) { products { id name measurementFields(active: true) { fieldName semantic } } }
}
"""

CHANGELOG_DASHBOARD_QUERY = """
query DashboardChangelog($workspace: String!, $dashboard: String!, $first: Int, $after: String) {
  workspace(id: $workspace) {
    dashboard(id: $dashboard) {
      id
      dashboardChangelog(first: $first, after: $after) {
        pageInfo { hasNextPage endCursor }
        edges { node { historyId historyDate historyUserName historyChangeReason dashboards } }
      }
    }
  }
}
"""

CHANGELOG_PRODUCT_QUERY = """
query ProductDashboardChangelog($product: String!, $first: Int, $after: String) {
  product(id: $product) {
    id
    dashboardChangelog(first: $first, after: $after, filter: { historyChangeReason: { isnull: false } }) {
      pageInfo { hasNextPage endCursor }
      edges { node { historyId historyDate historyUserName historyChangeReason dashboards } }
    }
  }
}
"""

PREVIEW_DEVICE_QUERY = """
query PreviewDeviceDashboard($device: String!, $tab: Int, $config: JSONString, $ids: [String!]) {
  device(deviceId: $device) { id dashboardData(dashboard: $tab, dashboardConfig: $config, widgetIds: $ids) }
}
"""

PREVIEW_DASHBOARD_QUERY = """
query PreviewWorkspaceDashboard($dashboard: String!, $tab: Int, $config: JSONString, $ids: [String!]) {
  dashboard(id: $dashboard) { id dashboardData(dashboard: $tab, dashboardConfig: $config, widgetIds: $ids) deviceInformation(dashboardConfig: $config) }
}
"""

PARSE_DATE_QUERY = "query ParseDate($date: String!, $timezone: String!) { parseDate(date: $date, timezone: $timezone) }"

ADD_DASHBOARD_MUTATION = """
mutation AddDashboard($input: AddDashboardInputType!) {
  addDashboard(input: $input) { ok dashboard { id name type icon sharingPolicy dashboards } }
}
"""

UPDATE_DASHBOARD_MUTATION = """
mutation UpdateDashboard($input: UpdateDashboardInputType!) {
  updateDashboard(input: $input) { ok dashboard { id name dashboards } }
}
"""

UPDATE_PRODUCT_MUTATION = """
mutation UpdateProductDashboard($input: UpdateProductInputType!) {
  updateProduct(input: $input) { ok product { id dashboards } }
}
"""

DELETE_DASHBOARD_MUTATION = """
mutation DeleteDashboard($dashboard: String!, $workspace: String!) { deleteDashboard(dashboard: $dashboard, workspace: $workspace) { ok } }
"""


class Api:
    def __init__(self, token, endpoint):
        self.token, self.endpoint = token, endpoint
        self._product_cache = {}

    def run(self, query, variables=None):
        """Return (data, errors); GraphQL errors are printed to stderr."""
        resp = gql(query, variables, self.token, self.endpoint)
        report_errors(resp)
        return resp.get("data") or {}, resp.get("errors") or []

    def product_fields_of_device(self, device_id):
        """{fieldName: field} of a device's product, None when the device is unknown or not readable. Cached."""
        if device_id in self._product_cache:
            return self._product_cache[device_id]
        fields = None
        if UUID_RE.match(device_id or ""):
            data, _ = self.run(DEVICE_QUERY, {"id": device_id})
            product = (data.get("device") or {}).get("product")
            if product:
                fields = {f["fieldName"]: f for f in product.get("measurementFields") or []}
        self._product_cache[device_id] = fields
        return fields


class Target:
    """A workspace dashboard (kind 'dashboard') or the device dashboard of a product (kind 'product')."""

    def __init__(self, kind, ref, node, workspace_id, device_id=None):
        self.kind, self.ref, self.node, self.workspace_id, self.device_id = kind, ref, node, workspace_id, device_id
        self.raw = node.get("dashboards") or "[]"
        self.dashboards = parse_dashboards(self.raw)
        self.fields = {f["fieldName"]: f for f in node.get("measurementFields") or []} if kind == "product" else {}
        self.permissions = []
        self.history_enabled = False

    @property
    def id(self):
        return self.node["id"]

    @property
    def name(self):
        return self.node.get("name")

    @property
    def label(self):
        if self.kind == "product":
            return "device dashboard of product %s (%s, %s device%s)" % (self.name, self.id, self.node.get("deviceCount"),
                                                                        "" if self.node.get("deviceCount") == 1 else "s")
        return "workspace dashboard %s (%s)" % (self.name, self.id)

    @property
    def locked(self):
        return self.kind == "product" and PRODUCT_LOCK_FEATURE in (self.node.get("features") or [])


def parse_target(ref):
    """'product:<id>' / 'device:<id>' / '<dashboard uuid>' → (kind, id)."""
    if ref.startswith("product:") or ref.startswith("device:"):
        kind, _, ident = ref.partition(":")
    else:
        kind, ident = "dashboard", ref
    if not UUID_RE.match(ident):
        sys.exit("%s id must be a UUID: %s (dashboards.py list <workspace> prints the targets)" % (kind, ident))
    return kind, ident


def load_target(api, ref):
    kind, ident = parse_target(ref)
    if kind == "dashboard":
        data, _ = api.run(DASHBOARD_QUERY, {"id": ident})
        node = data.get("dashboard")
        if not node:
            sys.exit("dashboard not found or no access: %s" % ident)
        if node.get("type") and node["type"] != "CUSTOM":
            sys.exit("dashboard %s is of type %s: its content lives in metaJSON (settings), not in widgets; only CUSTOM dashboards can be edited here" % (ident, node["type"]))
        target = Target("dashboard", ref, node, (node.get("workspace") or {}).get("id"))
        meta, _ = api.run(WORKSPACE_QUERY, {"id": target.workspace_id})
        ws = meta.get("workspace") or {}
        target.permissions = ws.get("myPermissions") or []
        target.history_enabled = bool(ws.get("entitlementDashboardHistoryEnabled"))
        return target
    if kind == "device":
        data, _ = api.run(DEVICE_QUERY, {"id": ident})
        device = data.get("device")
        if not device or not device.get("product"):
            sys.exit("device not found or no access: %s" % ident)
        node, device_id = device["product"], ident
    else:
        data, _ = api.run(PRODUCT_QUERY, {"id": ident})
        node, device_id = data.get("product"), None
        if not node:
            sys.exit("product not found or no access: %s" % ident)
    ws = node.get("workspace") or {}
    target = Target("product", ref, node, ws.get("id"), device_id)
    target.permissions = ws.get("myPermissions") or []
    target.history_enabled = bool(ws.get("entitlementDashboardHistoryEnabled"))
    return target


def parse_dashboards(raw):
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError as exc:
        sys.exit("dashboards is not valid JSON: %s" % exc)
    if value is None:
        return []
    if not isinstance(value, list):
        sys.exit("dashboards must be a JSON array of tabs, got %s" % type(value).__name__)
    return value


def workspace_vars(ref):
    return {"id" if UUID_RE.match(ref) else "slug": ref}


def table(rows, headers):
    rows = [[("" if c is None else str(c)) for c in r] for r in rows]
    widths = [max(len(h), *(len(r[i]) for r in rows)) if rows else len(h) for i, h in enumerate(headers)]
    out = ["  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)), "  ".join("-" * w for w in widths)]
    out.extend("  ".join(r[i].ljust(widths[i]) for i in range(len(headers))) for r in rows)
    return "\n".join(out)


def load_json_arg(value, what):
    """JSON from a string, or from a file when it starts with '@'."""
    if value is None:
        return None
    try:
        if value.startswith("@"):
            return json.load(open(value[1:], encoding="utf-8"))
        return json.loads(value)
    except (ValueError, OSError) as exc:
        sys.exit("%s is not valid JSON: %s" % (what, exc))


def is_translatable(value):
    return isinstance(value, dict) and "en" in value


def text_of(value):
    if isinstance(value, dict):
        return value.get("en") or value.get("de") or next((v for v in value.values() if v), "")
    return "" if value is None else str(value)


def dashboard_languages(dashboards):
    langs = {"en"}
    for tab in dashboards:
        for w in (tab.get("widgets") or {}).values() if isinstance(tab.get("widgets"), dict) else []:
            for v in (w.get("meta") or {}).values():
                if is_translatable(v):
                    langs.update(k for k in v if k in LANGUAGES)
    return sorted(langs)


def layout_of(widget):
    """(breakpoint, layout) of a widget: lg first, else sm."""
    layouts = widget.get("layouts") or {}
    for bp in ("lg", "sm"):
        if isinstance(layouts.get(bp), dict):
            return bp, layouts[bp]
    return None, None


def field_refs(widget):
    """Yield (path, device, fieldName) for every field reference the widget type stores."""
    meta = widget.get("meta") or {}
    kind = widget.get("widget")
    if kind in ("Value", "Boolean", "Switch", "Slider", "MeasurementList") or (kind == "SetValue" and meta.get("fieldType", "measurement") == "measurement"):
        ref = meta.get("field")
        if isinstance(ref, dict):
            yield "field", ref.get("device"), ref.get("fieldName")
    if kind == "LineChart":
        for i, series in enumerate(meta.get("devices") or []):
            if isinstance(series, dict):
                for j, f in enumerate(series.get("fields") or []):
                    if isinstance(f, dict):
                        yield "devices[%d].fields[%d]" % (i, j), series.get("device"), f.get("field")
    if kind in ("Histogram", "Heatmap"):
        for i, series in enumerate(meta.get("devices") or []):
            if isinstance(series, dict):
                yield "devices[%d]" % i, series.get("device"), series.get("fieldName")


def normalize(dashboards):
    """Repair what the portal tolerates but code should not rely on. Returns notes; edits in place."""
    notes = []
    for t, tab in enumerate(dashboards):
        if not isinstance(tab, dict):
            continue
        if isinstance(tab.get("widgets"), list) and not tab["widgets"]:
            tab["widgets"] = {}
            notes.append("tab %d: widgets [] → {}" % t)
        for key, w in (tab.get("widgets") or {}).items() if isinstance(tab.get("widgets"), dict) else []:
            for bp, layout in (w.get("layouts") or {}).items():
                if isinstance(layout, dict) and layout.get("i") != key:
                    layout["i"] = key
                    notes.append("tab %d widget %s: layouts.%s.i set to the widget key" % (t, key[:8], bp))
    return notes


def validate(dashboards, kind, resolver=None, product_hardware=None):
    """Structural + semantic check. kind: 'dashboard' (workspace) or 'product' (device dashboard).
    resolver(device_id) → {fieldName: field} or None (unknown). Returns (errors, warnings)."""
    errors, warnings = [], []
    if not isinstance(dashboards, list) or not dashboards:
        return ["dashboards must be a non-empty JSON array of tabs"], warnings
    for t, tab in enumerate(dashboards):
        where = "tab %d" % t
        if not isinstance(tab, dict):
            errors.append("%s: not an object" % where)
            continue
        if not isinstance(tab.get("name"), str):
            errors.append("%s: name must be a string" % where)
        widgets = tab.get("widgets")
        if isinstance(widgets, list) and widgets:
            errors.append("%s: widgets must be an object keyed by widget id, not a list" % where)
            continue
        if not isinstance(widgets, dict):
            if widgets not in ([], None):
                errors.append("%s: widgets must be an object keyed by widget id" % where)
            continue
        occupied = {"lg": [], "sm": []}
        has_sm = False
        for key, w in widgets.items():
            wh = "%s widget %s" % (where, key[:8])
            if not isinstance(w, dict):
                errors.append("%s: not an object" % wh)
                continue
            wtype = w.get("widget")
            spec = WIDGETS.get(wtype)
            if not spec:
                errors.append("%s: unknown widget type %r (the portal shows an empty tile for it)" % (wh, wtype))
                continue
            ctx = spec["contexts"]
            if ctx == "none" or (ctx == "workspace" and kind == "product") or (ctx == "device" and kind == "dashboard"):
                errors.append("%s: %s is not available on %s dashboards" % (wh, wtype, "device" if kind == "product" else "workspace"))
            if wtype == "Button" and product_hardware is not None and BUTTON_HARDWARE not in (product_hardware or ""):
                warnings.append("%s: Button is only offered for dzero hardware (product hardware: %s)" % (wh, product_hardware or "?"))
            layouts = w.get("layouts")
            if not isinstance(layouts, dict) or not any(isinstance(layouts.get(bp), dict) for bp in COLUMNS):
                errors.append("%s: layouts needs lg (desktop) and/or sm (mobile): {\"lg\": {\"i\", \"x\", \"y\", \"w\", \"h\"}}" % wh)
            else:
                for bp, cols in COLUMNS.items():
                    layout = layouts.get(bp)
                    if not isinstance(layout, dict):
                        continue
                    has_sm = has_sm or bp == "sm"
                    try:
                        x, y, ww, hh = (int(layout.get(k)) for k in ("x", "y", "w", "h"))
                    except (TypeError, ValueError):
                        errors.append("%s: layouts.%s needs integer x, y, w, h" % (wh, bp))
                        continue
                    if layout.get("i") != key:
                        warnings.append("%s: layouts.%s.i differs from the widget key (normalize fixes it)" % (wh, bp))
                    if x < 0 or y < 0 or ww < 1 or hh < 1 or x + ww > cols:
                        errors.append("%s: layouts.%s x=%d y=%d w=%d h=%d must satisfy 0 ≤ x, x + w ≤ %d, w ≥ 1, h ≥ 1" % (wh, bp, x, y, ww, hh, cols))
                        continue
                    for other_key, ox, oy, ow, oh in occupied[bp]:
                        if x < ox + ow and ox < x + ww and y < oy + oh and oy < y + hh:
                            warnings.append("%s: layouts.%s overlaps widget %s (the grid will push one of them down)" % (wh, bp, other_key[:8]))
                            break
                    occupied[bp].append((key, x, y, ww, hh))
            meta = w.get("meta")
            if not isinstance(meta, dict):
                errors.append("%s: meta must be an object" % wh)
                continue
            if spec.get("portal"):
                continue
            semantics_mode = wtype in ("Value", "Histogram") and str(meta.get("dataSourceMode", "static")).startswith("semantic")
            if semantics_mode:
                sem = meta.get("semantics")
                if not isinstance(sem, list) or not sem or not all(isinstance(s, dict) and s.get("identity") and
                                                                   (s.get("aggregatedSemanticRequests") or s.get("aggregatedSemanticDeviceRequests")) for s in sem):
                    errors.append("%s: %s in semantics mode needs meta.semantics [{identity, aggregatedSemanticRequests: [{kind, semantic, aggregation}], tags?}]" % (wh, wtype))
                if kind == "product":
                    warnings.append("%s: semantics mode aggregates across the workspace; on a device dashboard it does not follow the viewed device" % wh)
            for req in spec["required"]:
                value = meta.get(req)
                if value in (None, "", [], {}) and not (semantics_mode and req in ("field", "devices")):
                    errors.append("%s: %s needs meta.%s" % (wh, wtype, req))
            for mk in ("title", "unit", "text", "description"):
                if mk in meta and not is_translatable(meta[mk]) and not isinstance(meta[mk], str):
                    errors.append("%s: meta.%s must be a translated string {\"en\": \"...\"}" % (wh, mk))
                elif isinstance(meta.get(mk), str):
                    warnings.append("%s: meta.%s is a plain string; the portal expects {\"en\": \"...\"}" % (wh, mk))
            allowed = FIELD_TYPES.get(wtype)
            for path, device, field_name in field_refs(w):
                if not field_name:
                    errors.append("%s: meta.%s needs fieldName (the product field identifier)" % (wh, path))
                    continue
                if kind == "dashboard" and not UUID_RE.match(device or ""):
                    errors.append("%s: meta.%s.device must be a device id on workspace dashboards (got %r)" % (wh, path, device))
                    continue
                if resolver is None:
                    continue
                fields = resolver(device)
                if fields is None:
                    warnings.append("%s: meta.%s: device %s not readable, field %s unchecked" % (wh, path, device, field_name))
                elif field_name not in fields:
                    errors.append("%s: meta.%s: field %s does not exist on the product (have: %s)" % (
                        wh, path, field_name, ", ".join(sorted(fields)) or "no fields"))
                elif allowed and fields[field_name].get("fieldType") not in allowed:
                    warnings.append("%s: meta.%s: field %s is %s, %s expects %s" % (
                        wh, path, field_name, fields[field_name].get("fieldType"), wtype, "|".join(sorted(allowed))))
            tf = meta.get("timeframe")
            if isinstance(tf, dict) and tf.get("resolution") and not RESOLUTION_RE.match(str(tf["resolution"])):
                errors.append("%s: timeframe.resolution %r must be <n>m|h|d|w (e.g. 15m, 1h, 1d); anything else is served as 30m" % (wh, tf["resolution"]))
            if wtype == "Heatmap" and isinstance(tf, dict):
                errors.append("%s: Heatmap timeframe is the string \"1h\" or \"24h\"" % wh)
            tro = meta.get("timerangeOperation")
            if isinstance(tro, dict) and tro.get("other") and not tro.get("operation"):
                errors.append("%s: timerangeOperation.other is true but operation is empty (use operation, not operator)" % wh)
            if wtype == "LineChart" and any(isinstance(f, dict) and f.get("isDeltaEnabled")
                                            for s in meta.get("devices") or [] if isinstance(s, dict) for f in s.get("fields") or []) \
                    and meta.get("historyFunction") != "max":
                warnings.append("%s: a delta series needs historyFunction \"max\" (the chart subtracts consecutive bucket values; "
                                "averaged buckets distort counter deltas), got %r" % (wh, meta.get("historyFunction")))
            if wtype == "Value" and meta.get("gaugeRanges"):
                try:
                    values = [float(r.get("value")) for r in meta["gaugeRanges"]]
                    if values != sorted(values):
                        warnings.append("%s: gaugeRanges are not ascending; value is the lower bound of each range" % wh)
                except (TypeError, ValueError, AttributeError):
                    errors.append("%s: gaugeRanges must be [{value: number, color: '#hex', name}]" % wh)
            if wtype == "Table":
                for c, col in enumerate(meta.get("columns") or []):
                    if not isinstance(col, dict) or not col.get("id") or col.get("dataKind") not in ("meta", "measurement"):
                        errors.append("%s: columns[%d] needs id, name and dataKind meta|measurement" % (wh, c))
                    elif col["dataKind"] == "measurement" and not col.get("measurementFieldName"):
                        errors.append("%s: columns[%d] needs measurementFieldName" % (wh, c))
        if has_sm:
            lg_only = [k[:8] for k, w in widgets.items() if isinstance(w, dict) and isinstance((w.get("layouts") or {}).get("lg"), dict)
                       and not isinstance((w.get("layouts") or {}).get("sm"), dict)]
            if lg_only:
                warnings.append("%s has a mobile layout (sm widgets); %d desktop-only widget%s will not show on phones: %s" % (
                    where, len(lg_only), "" if len(lg_only) == 1 else "s", ", ".join(lg_only[:6])))
    return errors, warnings


def time_expressions(dashboards):
    """Unique (expression, timezone) pairs used in timeframes and timerange operations."""
    found = set()
    for tab in dashboards:
        for w in (tab.get("widgets") or {}).values() if isinstance(tab.get("widgets"), dict) else []:
            meta = w.get("meta") or {}
            tf = meta.get("timeframe")
            if isinstance(tf, dict):
                for k in ("start", "end"):
                    if tf.get(k):
                        found.add((tf[k], tf.get("timezone") or "UTC"))
            tro = meta.get("timerangeOperation")
            if isinstance(tro, dict) and tro.get("other"):
                for k in ("start", "end"):
                    if tro.get(k):
                        found.add((tro[k], tro.get("timezone") or "UTC"))
    return sorted(found)


def check_time_expressions(api, dashboards):
    problems = []
    for expr, tz in time_expressions(dashboards):
        data, errors = api.run(PARSE_DATE_QUERY, {"date": expr, "timezone": tz})
        if errors or not data.get("parseDate"):
            problems.append("time expression %r (timezone %s) is not understood by the API" % (expr, tz))
    return problems


def summarize_widget(key, w):
    bp, layout = layout_of(w)
    meta = w.get("meta") or {}
    refs = ["%s%s" % (f, "" if not d else "@" + d[:8]) for _, d, f in field_refs(w)]
    extra = ", ".join(refs[:3]) + (" …" if len(refs) > 3 else "")
    if str(meta.get("dataSourceMode", "")).startswith("semantic") and meta.get("semantics"):
        reqs = [r for s in meta["semantics"] if isinstance(s, dict) for r in (s.get("aggregatedSemanticRequests") or s.get("aggregatedSemanticDeviceRequests") or [])]
        extra = ", ".join("semantic %s %s" % (r.get("semantic"), r.get("aggregation")) for r in reqs[:3]) or "semantics"
        tags = next((s.get("tags") for s in meta["semantics"] if isinstance(s, dict) and s.get("tags")), None)
        if tags:
            extra += " tags %s" % json.dumps(tags)
    if w.get("widget") == "Table":
        extra = "%d column%s, tags %s" % (len(meta.get("columns") or []), "" if len(meta.get("columns") or []) == 1 else "s", meta.get("tagsFilter") or "all")
    if w.get("widget") == "MapNG":
        extra = "tags %s" % (meta.get("allDevicesFilterTags") or "all")
    pos = "%s %d,%d %dx%d" % (bp, layout.get("x", 0), layout.get("y", 0), layout.get("w", 0), layout.get("h", 0)) if layout else "-"
    title = text_of(meta.get("title") if "title" in meta else meta.get("text"))[:40]
    return [key[:8], w.get("widget"), pos, title, extra]


def print_summary(target, tab_index=None):
    print("%s: %d tab%s, %d widget%s%s" % (target.label, len(target.dashboards), "" if len(target.dashboards) == 1 else "s",
                                         sum(len(t.get("widgets") or {}) for t in target.dashboards),
                                         "" if sum(len(t.get("widgets") or {}) for t in target.dashboards) == 1 else "s",
                                         " [portal editing locked]" if target.locked else ""))
    for t, tab in enumerate(target.dashboards):
        if tab_index is not None and t != tab_index:
            continue
        widgets = tab.get("widgets") or {}
        flags = " (hidden on white label)" if tab.get("hideOnWhitelabel") else ""
        print("\ntab %d: %s%s, %d widget%s" % (t, tab.get("name"), flags, len(widgets), "" if len(widgets) == 1 else "s"))
        rows = sorted(((k, w) for k, w in widgets.items()), key=lambda kw: ((layout_of(kw[1])[1] or {}).get("y", 0), (layout_of(kw[1])[1] or {}).get("x", 0)))
        if rows:
            print(table([summarize_widget(k, w) for k, w in rows], ["id", "type", "layout x,y wxh", "title", "fields"]))


def diff_summary(old, new):
    """Human-readable list of changes between two dashboards arrays."""
    lines = []
    for t in range(max(len(old), len(new))):
        o = old[t] if t < len(old) else None
        n = new[t] if t < len(new) else None
        if o is None:
            lines.append("+ tab %d %r with %d widget(s)" % (t, n.get("name"), len(n.get("widgets") or {})))
            continue
        if n is None:
            lines.append("- tab %d %r with %d widget(s)" % (t, o.get("name"), len(o.get("widgets") or {})))
            continue
        if o.get("name") != n.get("name"):
            lines.append("~ tab %d renamed %r → %r" % (t, o.get("name"), n.get("name")))
        if o.get("hideOnWhitelabel", False) != n.get("hideOnWhitelabel", False):
            lines.append("~ tab %d hideOnWhitelabel → %s" % (t, n.get("hideOnWhitelabel", False)))
        ow, nw = o.get("widgets") or {}, n.get("widgets") or {}
        for k in nw:
            if k not in ow:
                lines.append("+ tab %d widget %s %s %r" % (t, k[:8], nw[k].get("widget"), text_of((nw[k].get("meta") or {}).get("title"))[:30]))
            elif ow[k] != nw[k]:
                changed = [p for p in ("widget", "layouts", "meta") if ow[k].get(p) != nw[k].get(p)]
                if "meta" in changed:
                    om, nm = ow[k].get("meta") or {}, nw[k].get("meta") or {}
                    keys = sorted(set(om) | set(nm))
                    changed_meta = ["%s: %s → %s" % (mk, json.dumps(om.get(mk))[:40], json.dumps(nm.get(mk))[:40]) for mk in keys if om.get(mk) != nm.get(mk)]
                    lines.append("~ tab %d widget %s %s meta: %s" % (t, k[:8], nw[k].get("widget"), "; ".join(changed_meta)[:400]))
                    changed.remove("meta")
                if changed:
                    lines.append("~ tab %d widget %s %s changed: %s" % (t, k[:8], nw[k].get("widget"), ", ".join(changed)))
        for k in ow:
            if k not in nw:
                lines.append("- tab %d widget %s %s %r" % (t, k[:8], ow[k].get("widget"), text_of((ow[k].get("meta") or {}).get("title"))[:30]))
    return lines


def resolver_for(api, target):
    if target.kind == "product":
        return lambda device_id: target.fields
    return api.product_fields_of_device


def persist(api, target, new_dashboards, message, execute, force=False):
    """Validate, show the plan, write the whole layout back (with --execute) and confirm."""
    notes = normalize(new_dashboards)
    errors, warnings = validate(new_dashboards, target.kind, resolver_for(api, target), target.node.get("hardware") if target.kind == "product" else None)
    if execute:
        errors += check_time_expressions(api, new_dashboards)
    changes = diff_summary(target.dashboards, new_dashboards)
    print("PLAN: update %s" % target.label)
    for line in changes:
        print("  " + line)
    for n in notes:
        print("  note: " + n)
    for w in warnings:
        print("  WARNING: " + w)
    for e in errors:
        print("  ERROR: " + e)
    needed = "dashboards" if target.kind == "dashboard" else "devices"
    if target.permissions and needed not in target.permissions:
        print("  WARNING: token lacks the %r workspace permission; the write will probably fail" % needed)
    if target.locked:
        print("  WARNING: the product has the %s feature: the portal editor is locked, API writes still apply" % PRODUCT_LOCK_FEATURE)
    if errors:
        sys.exit("not written: fix the errors above")
    if not changes:
        print("no changes: nothing to write")
        return
    message = (message or "dashboards.py")[:MESSAGE_MAX]
    if not execute:
        print("dry run: add --execute to write (change message: %r)" % message)
        return
    fresh = load_target(api, target.ref)
    if fresh.raw != target.raw and not force:
        sys.exit("not written: the dashboard changed on the server since it was read (someone saved in the portal?). "
                 "Re-run the command to work on the new state, or add --force to overwrite it.")
    payload = json.dumps(new_dashboards)
    if target.kind == "dashboard":
        data, errors = api.run(UPDATE_DASHBOARD_MUTATION, {"input": {"workspace": target.workspace_id, "dashboard": target.id,
                                                                     "dashboards": payload, "changeMessage": message}})
        result = data.get("updateDashboard") or {}
    else:
        data, errors = api.run(UPDATE_PRODUCT_MUTATION, {"input": {"product": target.id, "dashboards": payload, "changeMessage": message}})
        result = data.get("updateProduct") or {}
    if errors or not result.get("ok"):
        sys.exit("write failed: %s" % (json.dumps(errors)[:800] or "ok=false"))
    after = load_target(api, target.ref)
    print("saved: %s now has %d tab(s) and %d widget(s)%s" % (
        target.label, len(after.dashboards), sum(len(t.get("widgets") or {}) for t in after.dashboards),
        "" if target.history_enabled else " (no changelog on this plan)"))
    print("Reload the dashboard page in the portal to see the change (there is no live update).")
    if target.kind == "product":
        print("The change applies to every device of the product.")
    return after


def tab_of(target, index):
    if index < 0 or index >= len(target.dashboards):
        sys.exit("tab %d does not exist (%s has %d tab%s)" % (index, target.label, len(target.dashboards), "" if len(target.dashboards) == 1 else "s"))
    tab = target.dashboards[index]
    if isinstance(tab.get("widgets"), list) and not tab["widgets"]:
        tab["widgets"] = {}
    if not isinstance(tab.get("widgets"), dict):
        sys.exit("tab %d has no widgets object" % index)
    return tab


def widget_of(tab, widget_id):
    widgets = tab.get("widgets") or {}
    if widget_id in widgets:
        return widget_id
    matches = [k for k in widgets if k.startswith(widget_id)]
    if len(matches) == 1:
        return matches[0]
    sys.exit("widget %s not found in this tab (ids: %s)" % (widget_id, ", ".join(k[:8] for k in widgets) or "none"))


def next_position(tab, w, h, use_next):
    """Bottom of the desktop layout, or (--next) to the right of the last row when it fits."""
    layouts = [wd["layouts"]["lg"] for wd in (tab.get("widgets") or {}).values()
               if isinstance(wd, dict) and isinstance((wd.get("layouts") or {}).get("lg"), dict)]
    if not layouts:
        return 0, 0
    bottom = max(int(l.get("y", 0)) + int(l.get("h", 1)) for l in layouts)
    if use_next:
        last_y = max(int(l.get("y", 0)) for l in layouts)
        row = [l for l in layouts if int(l.get("y", 0)) == last_y]
        right = max(int(l.get("x", 0)) + int(l.get("w", 1)) for l in row)
        if right + w <= COLUMNS["lg"]:
            return right, last_y
    return 0, bottom


def build_widget(target, api, wtype, user_meta, title=None, field=None, preset=None):
    """DefaultMeta (+ preset) + user meta (+ languages, ids, field details) for a new widget."""
    spec = WIDGETS.get(wtype)
    if not spec:
        sys.exit("unknown widget type %r (dashboards.py schema lists them)" % wtype)
    if spec.get("portal"):
        sys.exit("%s is configured in the portal; copy its JSON from an existing dashboard (dashboards.py get --json)" % wtype)
    meta = copy.deepcopy(spec["meta"])
    if preset:
        if wtype != "Value":
            sys.exit("--preset applies to Value widgets only")
        if preset not in PRESETS:
            sys.exit("unknown preset %r; known: %s" % (preset, ", ".join(PRESETS)))
        meta.update(copy.deepcopy(PRESETS[preset]["settings"]))
        meta["widgetPreset"] = preset
    for lang in dashboard_languages(target.dashboards):
        if lang != "en":
            for k, v in meta.items():
                if is_translatable(v):
                    v.setdefault(lang, "")
    user_meta = user_meta or {}
    for k, v in user_meta.items():
        if isinstance(v, dict) and isinstance(meta.get(k), dict) and k in ("timeframe", "timerangeOperation"):
            meta[k] = {**meta[k], **v}
        else:
            meta[k] = v
    if title is not None:
        meta["title"] = {"en": title}
    if field is not None:
        name, _, device = field.partition("@")
        meta["field"] = {"device": device, "fieldName": name}
    fields = resolver_for(api, target)
    ref = meta.get("field")
    if isinstance(ref, dict) and ref.get("fieldName"):
        known = fields(ref.get("device"))
        f = (known or {}).get(ref["fieldName"])
        if f:
            ref.setdefault("fieldType", f.get("fieldType"))
            ref.setdefault("verboseFieldName", f.get("verboseFieldName"))
            if is_translatable(meta.get("title")) and meta["title"].get("en") == spec["meta"].get("title", {}).get("en") and title is None:
                meta["title"]["en"] = f.get("verboseFieldName") or ref["fieldName"]
            if wtype == "Value" and "unit" not in meta and f.get("unit"):
                meta["unit"] = {"en": f["unit"]}
    if wtype == "LineChart" and "historyFunction" not in user_meta and any(
            isinstance(f, dict) and f.get("isDeltaEnabled") for s in meta.get("devices") or [] if isinstance(s, dict) for f in s.get("fields") or []):
        meta["historyFunction"] = "max"
        print("  note: delta series present, historyFunction set to \"max\" (bucket averages would distort the deltas)")
    if wtype == "Table":
        meta.setdefault("uuid", str(uuid.uuid4()))
        for col in meta.get("columns") or []:
            if isinstance(col, dict):
                col.setdefault("id", str(uuid.uuid4()))
                col.setdefault("measurementTimerangeOperation", "current")
    return meta


# ----------------------------------------------------------------------------------------------- commands


def cmd_list(api, args):
    data, _ = api.run(LIST_QUERY, workspace_vars(args.workspace))
    ws = data.get("workspace")
    if not ws:
        sys.exit("workspace not found or no access: %s" % args.workspace)
    home = (ws.get("homeDashboard") or {}).get("id")
    dashboards = ws.get("dashboards") or []
    products = ws.get("products") or []
    if args.json:
        print(json.dumps({"workspace": {k: ws[k] for k in ("id", "name", "slug", "myPermissions", "entitlementDashboardHistoryEnabled")},
                          "homeDashboard": home,
                          "dashboards": [{**{k: d[k] for k in ("id", "name", "type", "icon", "sharingPolicy")},
                                          "tabs": [{"name": t.get("name"), "widgets": len(t.get("widgets") or {})} for t in parse_dashboards(d.get("dashboards") or "[]")]} for d in dashboards],
                          "products": [{"id": p["id"], "name": p["name"], "deviceCount": p["deviceCount"], "locked": PRODUCT_LOCK_FEATURE in (p.get("features") or []),
                                        "tabs": [{"name": t.get("name"), "widgets": len(t.get("widgets") or {})} for t in parse_dashboards(p.get("dashboards") or "[]")]} for p in products]},
                         indent=1, ensure_ascii=False))
        return
    print("workspace %s (%s): permissions %s, dashboard changelog %s" % (
        ws["name"], ws["slug"], ",".join(ws.get("myPermissions") or []), "on" if ws.get("entitlementDashboardHistoryEnabled") else "off"))
    print("\nWorkspace dashboards (target = id):")
    rows = []
    for d in dashboards:
        tabs = parse_dashboards(d.get("dashboards") or "[]")
        rows.append([d["id"], d["name"], d["type"], d["icon"], d["sharingPolicy"], len(tabs), sum(len(t.get("widgets") or {}) for t in tabs), "home" if d["id"] == home else ""])
    print(table(rows, ["id", "name", "type", "icon", "sharing", "tabs", "widgets", ""]) if rows else "  (none)")
    print("\nDevice dashboards (target = product:<id>, shared by all devices of the product):")
    rows = []
    for p in products:
        tabs = parse_dashboards(p.get("dashboards") or "[]")
        rows.append(["product:" + p["id"], p["name"], p["deviceCount"], len(tabs), sum(len(t.get("widgets") or {}) for t in tabs),
                     "locked" if PRODUCT_LOCK_FEATURE in (p.get("features") or []) else ""])
    print(table(rows, ["target", "product", "devices", "tabs", "widgets", ""]) if rows else "  (none)")


def cmd_get(api, args):
    target = load_target(api, args.target)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(target.dashboards, fh, indent=1, ensure_ascii=False)
        print("wrote %s (%d tab(s)); edit it and run: dashboards.py save %s --file %s" % (args.out, len(target.dashboards), args.target, args.out))
        return
    if args.json:
        print(json.dumps(target.dashboards if args.tab is None else tab_of(target, args.tab), indent=1, ensure_ascii=False))
        return
    print_summary(target, args.tab)
    if target.kind == "dashboard":
        n = target.node
        print("\ntype %s, icon %s, sharing %s%s, public links %d, workspace %s" % (
            n.get("type"), n.get("icon"), n.get("sharingPolicy"),
            " (shared with %s)" % ", ".join(u.get("email") or u["id"] for u in n.get("sharedWith") or []) if n.get("sharedWith") else "",
            len(n.get("publicLinks") or []), (n.get("workspace") or {}).get("slug")))
    else:
        print("\nproduct fields: %s" % ", ".join("%s (%s)" % (f["fieldName"], f["fieldType"]) for f in target.node.get("measurementFields") or []))
    errors, warnings = validate(target.dashboards, target.kind, resolver_for(api, target), target.node.get("hardware") if target.kind == "product" else None)
    for w in warnings:
        print("WARNING: " + w)
    for e in errors:
        print("ERROR: " + e)


def cmd_schema(api, args):
    if not args.type:
        rows = []
        for name, spec in WIDGETS.items():
            if args.device and spec["contexts"] not in ("both", "device"):
                continue
            ctx = {"both": "device, workspace", "device": "device only", "workspace": "workspace only", "none": "hidden"}[spec["contexts"]]
            rows.append([name, ctx, "%dx%d" % spec["size"], ", ".join(spec.get("required") or []) or "-",
                         "portal" if spec.get("portal") else ("yes" if spec.get("data") else "no"), spec["doc"][:70]])
        print(table(rows, ["type", "context", "size", "required meta", "preview", "purpose"]))
        print("\npreview = the server-side check (dashboards.py check) returns data for it; portal = configure in the portal, copy the JSON.")
        return
    if args.type == "presets":
        rows = [[name, p["semantic"] or "-", p["settings"]["gaugeType"], text_of(p["settings"].get("unit")),
                 " / ".join("%s %s" % (r["value"], r.get("name") or r["color"]) for r in p["settings"]["gaugeRanges"])[:80]]
                for name, p in PRESETS.items()]
        print(table(rows, ["preset", "semantic", "gauge", "unit", "ranges (lower bounds)"]))
        print("\nadd-widget --type Value --preset <name> applies title, unit, icon, gauge and ranges; your --meta/--title/--field override them.")
        return
    spec = WIDGETS.get(args.type)
    if not spec:
        sys.exit("unknown widget type %r; known: %s" % (args.type, ", ".join(WIDGETS)))
    print("%s: %s" % (args.type, spec["doc"]))
    if args.type == "Value":
        print("presets: %s (dashboards.py schema presets)" % ", ".join(PRESETS))
    print("contexts: %s; default size: %dx%d; required meta: %s; field types: %s" % (
        spec["contexts"], spec["size"][0], spec["size"][1], ", ".join(spec.get("required") or []) or "-",
        "|".join(sorted(FIELD_TYPES.get(args.type) or [])) or "any"))
    if spec.get("portal"):
        print("configure in the portal and copy the JSON (dashboards.py get <target> --json); add-widget does not generate it")
        return
    print("default meta:")
    print(json.dumps(spec["meta"], indent=1, ensure_ascii=False))


def cmd_create(api, args):
    data, _ = api.run(LIST_QUERY, workspace_vars(args.workspace))
    ws = data.get("workspace")
    if not ws:
        sys.exit("workspace not found or no access: %s" % args.workspace)
    layout = load_json_arg("@" + args.file, "--file") if args.file else [{"name": "Dashboard", "widgets": {}}]
    layout = parse_dashboards(layout)
    normalize(layout)
    errors, warnings = validate(layout, "dashboard", api.product_fields_of_device)
    payload = {"workspace": ws["id"], "name": args.name, "icon": args.icon, "type": "CUSTOM", "sharingPolicy": args.sharing,
               "sharedWith": [s for s in (args.shared_with or "").split(",") if s], "isHomeDashboard": bool(args.home),
               "dashboards": json.dumps(layout)}
    print("PLAN: create workspace dashboard %r in %s (%s): icon %s, sharing %s%s, %d tab(s), %d widget(s)%s" % (
        args.name, ws["name"], ws["slug"], args.icon, args.sharing, " with " + ",".join(payload["sharedWith"]) if payload["sharedWith"] else "",
        len(layout), sum(len(t.get("widgets") or {}) for t in layout), ", home dashboard" if args.home else ""))
    for w in warnings:
        print("  WARNING: " + w)
    for e in errors:
        print("  ERROR: " + e)
    if "dashboards" not in (ws.get("myPermissions") or []):
        print("  WARNING: token lacks the 'dashboards' workspace permission")
    if errors:
        sys.exit("not created: fix the errors above")
    if not args.execute:
        print("dry run: add --execute to create it")
        return
    data, errors = api.run(ADD_DASHBOARD_MUTATION, {"input": payload})
    result = data.get("addDashboard") or {}
    if errors or not result.get("ok"):
        sys.exit("create failed: %s" % (json.dumps(errors)[:800] or "ok=false"))
    d = result["dashboard"]
    print("created dashboard %s (%s); target for further commands: %s" % (d["name"], d["id"], d["id"]))
    print("Open or reload the dashboards page in the portal to see it.")


def cmd_save(api, args):
    target = load_target(api, args.target)
    new = parse_dashboards(load_json_arg("@" + args.file, "--file"))
    persist(api, target, new, args.message or "dashboards.py: save layout from %s" % os.path.basename(args.file), args.execute, args.force)


def cmd_add_widget(api, args):
    target = load_target(api, args.target)
    new = copy.deepcopy(target.dashboards)
    tab = tab_of(Target(target.kind, target.ref, {**target.node, "dashboards": json.dumps(new)}, target.workspace_id), args.tab)
    tab = new[args.tab]
    if isinstance(tab.get("widgets"), list):
        tab["widgets"] = {}
    meta = build_widget(target, api, args.type, load_json_arg(args.meta, "--meta"), args.title, args.field, args.preset)
    spec = WIDGETS[args.type]
    w = args.w or spec["size"][0]
    h = args.h or spec["size"][1]
    if args.x is None or args.y is None:
        x, y = next_position(tab, w, h, args.next)
        x = args.x if args.x is not None else x
        y = args.y if args.y is not None else y
    else:
        x, y = args.x, args.y
    key = str(uuid.uuid4())
    tab["widgets"][key] = {"widget": args.type, "layouts": {"lg": {"i": key, "x": x, "y": y, "w": w, "h": h}}, "meta": meta}
    print("widget %s %s at lg x=%d y=%d w=%d h=%d, meta:" % (key, args.type, x, y, w, h))
    print(json.dumps(meta, indent=1, ensure_ascii=False))
    persist(api, target, new, args.message or "dashboards.py: add %s %s" % (args.type, text_of(meta.get("title"))[:40]), args.execute, args.force)


def cmd_update_widget(api, args):
    target = load_target(api, args.target)
    new = copy.deepcopy(target.dashboards)
    tab = tab_of(target, args.tab)
    key = widget_of(tab, args.widget)
    widget = new[args.tab]["widgets"][key]
    updates = load_json_arg(args.meta, "--meta") or {}
    if not isinstance(updates, dict):
        sys.exit("--meta must be a JSON object with the keys to change")
    meta = widget.setdefault("meta", {})
    for k, v in updates.items():
        if isinstance(meta.get(k), dict) and isinstance(v, dict):
            lost = sorted(set(meta[k]) - set(v))
            if lost:
                print("  note: meta.%s is replaced as a whole; keys dropped: %s (pass the complete object to keep them)" % (k, ", ".join(lost)))
        if v is None:
            meta.pop(k, None)
        else:
            meta[k] = v
    persist(api, target, new, args.message or "dashboards.py: update %s %s" % (widget.get("widget"), text_of(meta.get("title"))[:40]), args.execute, args.force)


def cmd_move_widget(api, args):
    target = load_target(api, args.target)
    new = copy.deepcopy(target.dashboards)
    tab = tab_of(target, args.tab)
    key = widget_of(tab, args.widget)
    widget = new[args.tab]["widgets"][key]
    layouts = widget.setdefault("layouts", {})
    bp = args.breakpoint
    layout = layouts.get(bp)
    if not isinstance(layout, dict):
        if bp == "sm":
            sys.exit("widget has no sm layout; mobile layouts are separate widgets created in the portal (Create from desktop)")
        layout = {"i": key, "x": 0, "y": 0, "w": WIDGETS.get(widget.get("widget"), {}).get("size", (4, 3))[0], "h": WIDGETS.get(widget.get("widget"), {}).get("size", (4, 3))[1]}
    for k in ("x", "y", "w", "h"):
        if getattr(args, k) is not None:
            layout[k] = getattr(args, k)
    layout["i"] = key
    layouts[bp] = layout
    persist(api, target, new, args.message or "dashboards.py: move %s" % widget.get("widget"), args.execute, args.force)


def cmd_remove_widget(api, args):
    target = load_target(api, args.target)
    new = copy.deepcopy(target.dashboards)
    tab = tab_of(target, args.tab)
    key = widget_of(tab, args.widget)
    removed = new[args.tab]["widgets"].pop(key)
    if any(isinstance((w.get("layouts") or {}).get("sm"), dict) for w in new[args.tab]["widgets"].values() if isinstance(w, dict)):
        print("  note: this tab has mobile (sm) widgets; a mobile copy of this widget, if any, is a separate widget and stays")
    persist(api, target, new, args.message or "dashboards.py: remove %s %s" % (removed.get("widget"), text_of((removed.get("meta") or {}).get("title"))[:40]), args.execute, args.force)


def cmd_tab(api, args):
    target = load_target(api, args.target)
    new = copy.deepcopy(target.dashboards)
    if args.action == "add":
        tab = {"name": args.name, "widgets": {}}
        if target.kind == "product":
            tab = {"id": str(uuid.uuid4()), "name": args.name, "widgets": {}, "hideOnWhitelabel": bool(args.hide_on_whitelabel)}
        elif args.hide_on_whitelabel:
            print("  note: hideOnWhitelabel only applies to device dashboard tabs")
        new.append(tab)
        message = "dashboards.py: add tab %s" % args.name
    elif args.action == "rename":
        tab_of(target, args.index)
        new[args.index]["name"] = args.name
        if args.hide_on_whitelabel and target.kind == "product":
            new[args.index]["hideOnWhitelabel"] = True
        message = "dashboards.py: rename tab %d to %s" % (args.index, args.name)
    else:
        tab_of(target, args.index)
        if len(new) == 1:
            sys.exit("a dashboard needs at least one tab; remove the widgets instead")
        if target.kind == "product" and args.index == 0:
            sys.exit("tab 0 of a device dashboard is the default tab and cannot be removed")
        new.pop(args.index)
        message = "dashboards.py: remove tab %d" % args.index
    persist(api, target, new, args.message or message, args.execute, args.force)


def preview(api, target, tab_index, widgets, device_id=None):
    """Server-side dry run: dashboardData for the given widgets (a {id: {widget, meta}} map)."""
    config = json.dumps({"widgets": {k: {"widget": w.get("widget"), "meta": w.get("meta") or {}} for k, w in widgets.items()}})
    ids = list(widgets)
    if target.kind == "product":
        if not device_id:
            sys.exit("check on a product dashboard needs a device of the product: use device:<id> as target or --device <id>")
        data, errors = api.run(PREVIEW_DEVICE_QUERY, {"device": device_id, "tab": tab_index, "config": config, "ids": ids})
        raw = (data.get("device") or {}).get("dashboardData")
        info = None
    else:
        data, errors = api.run(PREVIEW_DASHBOARD_QUERY, {"dashboard": target.id, "tab": tab_index, "config": config, "ids": ids})
        raw = (data.get("dashboard") or {}).get("dashboardData")
        info = (data.get("dashboard") or {}).get("deviceInformation")
    if errors:
        sys.exit("preview failed: %s" % json.dumps(errors)[:600])
    try:
        parsed = json.loads((raw or "[{}, []]").replace("NaN", "null"))
    except ValueError:
        parsed = [{}, []]
    values = parsed[0] if isinstance(parsed, list) and parsed else {}
    devices = parsed[1] if isinstance(parsed, list) and len(parsed) > 1 else []
    try:
        info = json.loads(info) if info else {}
    except ValueError:
        info = {}
    return values, devices, info


def find_product_device(api, target):
    """First device of the product (for previews on product targets)."""
    if target.device_id:
        return target.device_id
    for page in range(5):
        data, _ = api.run(DEVICES_QUERY, {"id": target.workspace_id, "page": page})
        block = (data.get("workspace") or {}).get("devicesFiltered") or {}
        for d in block.get("devices") or []:
            if (d.get("product") or {}).get("id") == target.id:
                return d["id"]
        if (page + 1) * 100 >= (block.get("total") or 0):
            break
    return None


def cmd_check(api, args):
    target = load_target(api, args.target)
    if args.file:
        dashboards = parse_dashboards(load_json_arg("@" + args.file, "--file"))
        normalize(dashboards)
    else:
        dashboards = copy.deepcopy(target.dashboards)
    if args.type:
        meta = build_widget(target, api, args.type, load_json_arg(args.meta, "--meta"), args.title, args.field, args.preset)
        widgets = {str(uuid.uuid4()): {"widget": args.type, "meta": meta}}
        print("ad-hoc %s widget, meta:\n%s" % (args.type, json.dumps(meta, indent=1, ensure_ascii=False)))
    else:
        tab = dashboards[args.tab] if args.tab < len(dashboards) else sys.exit("tab %d does not exist" % args.tab)
        widgets = tab.get("widgets") or {}
        if args.widget:
            key = widget_of(tab, args.widget)
            widgets = {key: widgets[key]}
    errors, warnings = validate(dashboards if not args.type else [{"name": "check", "widgets": {k: {**w, "layouts": {"lg": {"i": k, "x": 0, "y": 0, "w": 1, "h": 1}}} for k, w in widgets.items()}}],
                                target.kind, resolver_for(api, target), target.node.get("hardware") if target.kind == "product" else None)
    errors += check_time_expressions(api, [{"widgets": widgets}])
    for w in warnings:
        print("WARNING: " + w)
    for e in errors:
        print("ERROR: " + e)
    device_id = args.device or (find_product_device(api, target) if target.kind == "product" else None)
    if len(widgets) > 40:
        sys.exit("check previews at most 40 widgets per call; use --widget <id>")
    print("server preview%s, one request per widget:" % (" on device %s" % device_id if device_id else ""))
    rows, all_values, all_info, missing = [], {}, {}, 0
    for key, w in widgets.items():
        spec = WIDGETS.get(w.get("widget")) or {}
        if not spec.get("data"):
            rows.append([key[:8], w.get("widget"), text_of((w.get("meta") or {}).get("title"))[:30], "n/a (no server data for this type)"])
            continue
        values, devices, info = preview(api, target, args.tab, {key: w}, device_id)
        all_values.update(values)
        all_info.update(info or {})
        if values:
            state = "data (%d key%s, %d device%s)" % (len(values), "" if len(values) == 1 else "s", len(devices), "" if len(devices) == 1 else "s")
        else:
            state = "NO DATA: check device id / field name"
            missing += 1
        rows.append([key[:8], w.get("widget"), text_of((w.get("meta") or {}).get("title"))[:30], state])
    print(table(rows, ["id", "type", "title", "result"]))
    if all_values and not args.quiet:
        print("values: " + json.dumps(all_values, ensure_ascii=False)[:600])
    if all_info:
        print("devices: " + ", ".join("%s (%s%s)" % (v.get("verboseName"), k[:8], ", online" if v.get("online") else "") for k, v in all_info.items())[:400])
    if errors or missing:
        sys.exit(1)


KPI_AGGREGATION = {"TEMPERATURE": "Avg", "HUMIDITY": "Avg", "CO2": "Max", "BATTERY": "Min", "SIGNAL": "Min", "FILL_LEVEL": "Avg",
                   "SOIL_MOISTURE": "Avg", "AMBIENT_LIGHT": "Avg"}


class LayoutBuilder:
    """Collects widgets with a running y cursor on the 12-column desktop grid."""

    def __init__(self, languages):
        self.widgets, self.notes, self.languages, self.y = {}, [], languages, 0

    def add(self, wtype, meta, x, w, h, y=None):
        full = copy.deepcopy(WIDGETS[wtype]["meta"])
        full.update(meta)
        for lang in self.languages:
            if lang != "en":
                for v in full.values():
                    if is_translatable(v):
                        v.setdefault(lang, "")
        key = str(uuid.uuid4())
        self.widgets[key] = {"widget": wtype, "layouts": {"lg": {"i": key, "x": x, "y": self.y if y is None else y, "w": w, "h": h}}, "meta": full}
        return key

    def headline(self, text, size=2):
        self.add("Headline", {"title": {"en": text}, "size": size}, 0, 12, 1)
        self.y += 1

    def rows_of(self, items, w, h, make):
        """Place items left to right, wrapping at the grid width; make(item, x, w, h) adds the widget."""
        per_row = COLUMNS["lg"] // w
        for i, item in enumerate(items):
            if i and i % per_row == 0:
                self.y += h
            make(item, (i % per_row) * w, w, h)
        if items:
            self.y += h


def field_ref(f, device=""):
    return {"device": device, "fieldName": f["fieldName"], "fieldType": f["fieldType"], "verboseFieldName": f.get("verboseFieldName") or f["fieldName"]}


def preset_for(f):
    preset = SEMANTIC_PRESET.get(f.get("semantic") or "")
    if preset == "battery" and "%" in (f.get("unit") or ""):
        preset = "batteryPercent"
    return preset


def value_meta(f, device=""):
    """Value widget meta for one product field: preset by semantic, else a plain number with the field's unit."""
    preset = preset_for(f)
    meta = copy.deepcopy(PRESETS[preset]["settings"]) if preset else {"gaugeType": "none"}
    if preset:
        meta["widgetPreset"] = preset
    meta["title"] = {"en": f.get("verboseFieldName") or f["fieldName"]}
    if f.get("unit"):
        meta["unit"] = {"en": f["unit"]}
    elif not preset:
        meta.pop("unit", None)
    if f.get("floatDigits") is not None:
        meta["decimalPlaces"] = f["floatDigits"]
    if f["fieldType"] == "COUNTER":
        meta["decimalPlaces"] = 0
    meta["field"] = field_ref(f, device)
    return meta


def chart_meta(title, series, timeframe, history_function=""):
    return {"title": {"en": title}, "timeframe": timeframe, "devices": series, "historyFunction": history_function, "allowTimeframeSelect": True}


def chart_series(f, device, label, color, kind):
    series = {"device": device, "label": label,
              "fields": [{"field": f["fieldName"], "color": color, "verboseName": label, "chartKind": kind}],
              "yAxis": {"id": 1, "orientation": "left", "hidden": False, "scale": "auto", **({"unit": f["unit"]} if f.get("unit") else {})}}
    return series


def select_fields(product, include=None, exclude=None):
    """Product fields minus platform fields, filtered by --fields (ordered include list) and --exclude (glob patterns)."""
    fields = [f for f in product.get("measurementFields") or [] if not f["fieldName"].startswith("_")]
    if exclude:
        patterns = [p for p in exclude.split(",") if p]
        fields = [f for f in fields if not any(fnmatch.fnmatchcase(f["fieldName"], p) for p in patterns)]
    if include:
        wanted = [n for n in include.split(",") if n]
        by_name = {f["fieldName"]: f for f in fields}
        missing = [n for n in wanted if n not in by_name]
        if missing:
            sys.exit("--fields: unknown or excluded field(s) %s (product has: %s)" % (", ".join(missing), ", ".join(sorted(by_name))))
        fields = [by_name[n] for n in wanted]
    return fields


def sorted_fields(product, include=None, exclude=None):
    fields = select_fields(product, include, exclude)
    role_rank = {"PRIMARY": 0, "SECONDARY": 1}
    numeric = [f for f in fields if f["fieldType"] in NUMERIC]
    if not include:  # keep the order of --fields when given, otherwise primary/secondary, semantics, then battery and signal last
        numeric = sorted(numeric, key=lambda f: (2 if f.get("role") in ("DEVICE_BATTERY", "DEVICE_SIGNAL") else 0, role_rank.get(f.get("role"), 1),
                                                 0 if f.get("semantic") else 1, f["fieldName"]))
    geo = [f for f in select_fields(product, None, exclude) if f["fieldType"] == "GEO" or f.get("role") == "DEVICE_LOCATION"]
    return fields, numeric, [f for f in fields if f["fieldType"] == "STRING"], [f for f in fields if f["fieldType"] == "BOOL"], geo


def generate_device_layout(target, args):
    """Widgets for a complete device dashboard built from the product's measurement fields."""
    fields, numeric, strings, bools, geo = sorted_fields(target.node, args.fields, args.exclude)
    if not fields:
        sys.exit("no measurement fields left after --fields/--exclude (or the product has none)")
    b = LayoutBuilder(dashboard_languages(target.dashboards))
    b.headline(args.title or target.name)
    b.rows_of(numeric + strings, 4, 3, lambda f, x, w, h: b.add("Value", value_meta(f), x, w, h))
    b.rows_of([None] + bools, 4, 2, lambda f, x, w, h: b.add("OnlineStatus", {"title": {"en": "Online"}, "icon": "wifi", "isBgColorStateBased": True}, x, w, h)
              if f is None else b.add("Boolean", {"title": {"en": f.get("verboseFieldName") or f["fieldName"]}, "field": field_ref(f), "isBgColorStateBased": True}, x, w, h))
    chart_fields = [f for f in numeric if f.get("role") not in ("DEVICE_BATTERY", "DEVICE_SIGNAL")][:5]
    if chart_fields:
        b.headline("History", 3)
        timeframe = {"start": args.timeframe, "end": "now", "resolution": args.resolution, "otherTimeframe": False, "timezone": args.timezone}

        def chart(f, x, w, h, index):
            counter = f["fieldType"] == "COUNTER"
            label = f.get("verboseFieldName") or f["fieldName"]
            series = chart_series(f, "", label, CHART_COLORS[index % len(CHART_COLORS)], "bar" if counter else "area")
            if counter:
                series["fields"][0].update({"isDeltaEnabled": True, "colorPositive": "#10b981", "colorNegative": "#ef4444"})
                b.notes.append("%s is a COUNTER: charted as deltas per bucket with historyFunction max" % f["fieldName"])
            b.add("LineChart", chart_meta(label + (" (delta)" if counter else ""), [series], timeframe, "max" if counter else ""), x, w, h)

        chart(chart_fields[0], 0, 12, 4, 0)
        b.y += 4
        rest = chart_fields[1:]
        for i, f in enumerate(rest):
            if i and i % 2 == 0:
                b.y += 4
            chart(f, (i % 2) * 6, 6, 4, i + 1)
        if rest:
            b.y += 4
    controls = [c for c in (args.controls or "").split(",") if c]
    if controls:
        by_name = {f["fieldName"]: f for f in fields}
        unknown = [c for c in controls if c not in by_name]
        if unknown:
            sys.exit("--controls: unknown field(s) %s" % ", ".join(unknown))
        b.headline("Controls", 3)
        x = 0
        for name in controls:
            f = by_name[name]
            label = f.get("verboseFieldName") or name
            if f["fieldType"] == "BOOL":
                w, wtype, meta = 4, "Switch", {"title": {"en": label}, "field": field_ref(f)}
            else:
                w, wtype, meta = 6, "Slider", {"title": {"en": label}, "field": field_ref(f), "min": 0, "max": 100, "step": 1,
                                               **({"unit": {"en": f["unit"]}} if f.get("unit") else {})}
                b.notes.append("%s slider uses the range 0..100; adjust min/max/step with update-widget" % name)
            if x + w > COLUMNS["lg"]:
                x, b.y = 0, b.y + 2
            b.add(wtype, meta, x, w, 2)
            x += w
        b.y += 2
    if geo:
        b.notes.append("location field(s) %s skipped: add the Map widget in the portal" % ", ".join(f["fieldName"] for f in geo))
    return b.widgets, b.notes


def product_devices(api, workspace_id, product_id, tags, limit):
    """Devices of one product (optionally carrying all of the tags), up to limit; returns (devices, total_matching)."""
    found, total = [], 0
    for page in range(20):
        data, _ = api.run(DEVICES_QUERY, {"id": workspace_id, "page": page, "tags": {"contains": tags} if tags else None})
        block = (data.get("workspace") or {}).get("devicesFiltered") or {}
        for d in block.get("devices") or []:
            if (d.get("product") or {}).get("id") == product_id:
                total += 1
                if len(found) < limit:
                    found.append(d)
        if (page + 1) * 100 >= (block.get("total") or 0):
            break
    return found, total


def generate_workspace_layout(api, target, product, args):
    """Fleet overview of one product on a workspace dashboard: KPIs, device table, map, multi-device chart, heatmap, histogram."""
    fields, numeric, strings, bools, geo = sorted_fields(product, args.fields, args.exclude)
    if not fields:
        sys.exit("no measurement fields left after --fields/--exclude (or the product has none)")
    tags = [t for t in (args.tags or "").split(",") if t]
    b = LayoutBuilder(dashboard_languages(target.dashboards))
    b.headline(args.title or product["name"])
    # KPIs: semantic aggregates over the fleet. Without tags only semantics that no other product of the workspace uses.
    data, _ = api.run(WORKSPACE_SEMANTICS_QUERY, {"id": target.workspace_id})
    others = {}
    for p in (data.get("workspace") or {}).get("products") or []:
        if p["id"] != product["id"]:
            for f in p.get("measurementFields") or []:
                if f.get("semantic"):
                    others.setdefault(f["semantic"], []).append(p["name"])
    kpis = []
    for f in numeric:
        sem = f.get("semantic")
        if not sem or sem not in KPI_AGGREGATION:
            continue
        if not tags and sem in others:
            b.notes.append("KPI for %s skipped: product(s) %s share that semantic; use --tags to scope it" % (sem, ", ".join(sorted(set(others[sem]))[:3])))
            continue
        kpis.append(f)

    def kpi(f, x, w, h):
        sem, agg = f["semantic"], KPI_AGGREGATION[f["semantic"]]
        meta = value_meta(f)
        meta.pop("field", None)
        base = text_of(PRESETS[meta["widgetPreset"]]["settings"].get("title")) if meta.get("widgetPreset") else (f.get("verboseFieldName") or f["fieldName"])
        meta["title"] = {"en": "%s %s" % ({"Avg": "Average", "Min": "Lowest", "Max": "Highest"}[agg], base.lower() if base.isascii() else base)}
        meta["dataSourceMode"] = "semantics"
        meta["tagsFilterMode"] = "contains"
        request = {"identity": "semantic_" + uuid.uuid4().hex[:8], "includeDevices": False,
                   "aggregatedSemanticRequests": [{"kind": "AGGREGATED_NUMERIC_SEMANTIC_VALUE", "semantic": sem.lower(), "aggregation": agg}]}
        if tags:
            request["tags"] = {"contains": tags}
        meta["semantics"] = [request]
        b.add("Value", meta, x, w, h)

    b.rows_of(kpis, 4, 3, kpi)
    # Table (+ map)
    columns = [{"id": str(uuid.uuid4()), "name": "Device", "dataKind": "meta", "metaKind": "LinkedName"},
               {"id": str(uuid.uuid4()), "name": "Online", "dataKind": "meta", "metaKind": "Online"},
               {"id": str(uuid.uuid4()), "name": "Last heard", "dataKind": "meta", "metaKind": "LastHeardDevice"}]
    for f in numeric + strings:
        col = {"id": str(uuid.uuid4()), "name": f.get("verboseFieldName") or f["fieldName"], "dataKind": "measurement",
               "measurementFieldName": f["fieldName"], "measurementTimerangeOperation": "current"}
        if f.get("unit"):
            col["unit"] = f["unit"]
        if f.get("floatDigits") is not None:
            col["floatDigits"] = f["floatDigits"]
        if f["fieldType"] in NUMERIC:
            col["footerOperation"] = "average"
        columns.append(col)
    for f in bools:
        columns.append({"id": str(uuid.uuid4()), "name": f.get("verboseFieldName") or f["fieldName"], "dataKind": "measurement",
                        "measurementFieldName": f["fieldName"], "measurementTimerangeOperation": "current",
                        "booleanTrueText": "yes", "booleanFalseText": "no", "booleanShowAsTags": True, "booleanUseColors": True})
    table_meta = {"title": {"en": "Devices"}, "tagsFilter": tags, "nameFilter": "", "uuid": str(uuid.uuid4()), "columns": columns,
                  "showFooter": any(f["fieldType"] in NUMERIC for f in numeric), "defaultSortByColumn": 0}
    if not tags and others:
        b.notes.append("the table lists every device of the workspace (no --tags); other products show empty measurement columns")
    if geo:
        b.add("Table", table_meta, 0, 8, 4)
        b.add("MapNG", {"title": {"en": "Map"}, "allDevicesFilterTags": tags, "allDevicesFilterTagsAnyAll": "all", "markerRoleChoice": "Primary"}, 8, 4, 4)
    else:
        b.add("Table", table_meta, 0, 12, 4)
        b.notes.append("no location field on the product: MapNG skipped")
    b.y += 4
    # Per-device history of the primary field
    chart_fields = [f for f in numeric if f.get("role") not in ("DEVICE_BATTERY", "DEVICE_SIGNAL")]
    devices, total = product_devices(api, target.workspace_id, product["id"], tags, args.max_devices)
    if chart_fields and devices:
        f = chart_fields[0]
        label = f.get("verboseFieldName") or f["fieldName"]
        b.headline("%s per device" % label, 3)
        timeframe = {"start": args.timeframe, "end": "now", "resolution": args.resolution, "otherTimeframe": False, "timezone": args.timezone}
        kind = "area" if len(devices) <= 2 else "line"
        series = [chart_series(f, d["id"], d["verboseName"], CHART_COLORS[i % len(CHART_COLORS)], kind) for i, d in enumerate(devices)]
        b.add("LineChart", chart_meta(label, series, timeframe), 0, 12, 4)
        b.y += 4
        heat = [{"device": d["id"], "fieldName": f["fieldName"], "verboseName": d["verboseName"], **({"unit": f["unit"]} if f.get("unit") else {})} for d in devices]
        heat_h = min(8, max(3, (len(devices) + 2) // 3 + 1))
        b.add("Heatmap", {"title": {"en": "%s, daily" % label}, "devices": heat, "timeframe": "24h", "orientation": "horizontal", "timezone": args.timezone}, 0, 12, heat_h)
        b.y += heat_h
        if len(devices) > 1:
            hist = [{"device": d["id"], "fieldName": f["fieldName"], "color": CHART_COLORS[i % len(CHART_COLORS)], "title": d["verboseName"]} for i, d in enumerate(devices)]
            b.add("Histogram", {"title": {"en": "%s now" % label}, "devices": hist, "chartType": "bar", **({"unit": {"en": f["unit"]}} if f.get("unit") else {})}, 0, 12, 3)
            b.y += 3
        if total > len(devices):
            b.notes.append("%d of %d matching devices charted (--max-devices %d)" % (len(devices), total, args.max_devices))
    elif chart_fields:
        b.notes.append("no device of the product%s found: per-device chart, heatmap and histogram skipped" % (" with tags " + ",".join(tags) if tags else ""))
    return b.widgets, b.notes


def cmd_generate(api, args):
    target = load_target(api, args.target)
    if target.kind == "product":
        widgets, notes = generate_device_layout(target, args)
    else:
        if not args.product:
            sys.exit("generate on a workspace dashboard needs --product <product-id> (dashboards.py list <workspace> prints them)")
        if not UUID_RE.match(args.product):
            sys.exit("--product must be a product UUID")
        data, _ = api.run(PRODUCT_QUERY, {"id": args.product})
        product = data.get("product")
        if not product:
            sys.exit("product not found or no access: %s" % args.product)
        if (product.get("workspace") or {}).get("id") != target.workspace_id:
            sys.exit("product %s belongs to another workspace than the dashboard" % product["name"])
        widgets, notes = generate_workspace_layout(api, target, product, args)
    new = copy.deepcopy(target.dashboards)
    if args.new_tab:
        tab = {"name": args.new_tab, "widgets": widgets}
        if target.kind == "product":
            tab = {"id": str(uuid.uuid4()), **tab}
        new.append(tab)
        index = len(new) - 1
    else:
        index = args.tab
        tab_of(target, index)
        if new[index].get("widgets") and not args.replace:
            sys.exit("tab %d already has %d widget(s): add --replace to overwrite it, or --new-tab \"Name\" to keep it" % (index, len(new[index]["widgets"])))
        new[index]["widgets"] = widgets
    kinds = {}
    for w in widgets.values():
        kinds[w["widget"]] = kinds.get(w["widget"], 0) + 1
    print("generated %d widgets for tab %d: %s" % (len(widgets), index, ", ".join("%d %s" % (n, k) for k, n in sorted(kinds.items()))))
    for n in notes:
        print("  note: " + n)
    persist(api, target, new, args.message or "dashboards.py: generate %s dashboard" % ("device" if target.kind == "product" else "fleet"),
            args.execute, args.force)


def cmd_validate(api, args):
    dashboards = parse_dashboards(load_json_arg("@" + args.file, "--file"))
    notes = normalize(dashboards)
    errors, warnings = validate(dashboards, "product" if args.kind == "device" else "dashboard")
    for n in notes:
        print("note: " + n)
    for w in warnings:
        print("WARNING: " + w)
    for e in errors:
        print("ERROR: " + e)
    print("%d tab(s), %d widget(s), %d error(s), %d warning(s)" % (len(dashboards), sum(len(t.get("widgets") or {}) for t in dashboards), len(errors), len(warnings)))
    sys.exit(1 if errors else 0)


def changelog_entries(api, target, first, after=None):
    if target.kind == "dashboard":
        data, _ = api.run(CHANGELOG_DASHBOARD_QUERY, {"workspace": target.workspace_id, "dashboard": target.id, "first": first, "after": after})
        conn = ((data.get("workspace") or {}).get("dashboard") or {}).get("dashboardChangelog") or {}
    else:
        data, _ = api.run(CHANGELOG_PRODUCT_QUERY, {"product": target.id, "first": first, "after": after})
        conn = (data.get("product") or {}).get("dashboardChangelog") or {}
    return [e["node"] for e in conn.get("edges") or [] if e and e.get("node")], (conn.get("pageInfo") or {})


def cmd_changelog(api, args):
    target = load_target(api, args.target)
    entries, page = changelog_entries(api, target, args.first)
    if args.json:
        print(json.dumps(entries, indent=1, ensure_ascii=False))
        return
    if not entries:
        print("no changelog entries%s" % ("" if target.history_enabled else " (dashboard history is not enabled on this workspace's plan)"))
        return
    rows = []
    for e in entries:
        tabs = parse_dashboards(e.get("dashboards") or "[]")
        rows.append([e["historyId"], e["historyDate"], e.get("historyUserName") or "", (e.get("historyChangeReason") or "")[:50], len(tabs), sum(len(t.get("widgets") or {}) for t in tabs)])
    print(table(rows, ["historyId", "date", "user", "message", "tabs", "widgets"]))
    if page.get("hasNextPage"):
        print("(more entries: raise --first)")
    print("restore one: dashboards.py restore %s <historyId> --execute" % args.target)


def cmd_restore(api, args):
    target = load_target(api, args.target)
    after, entry = None, None
    for _ in range(10):
        entries, page = changelog_entries(api, target, 20, after)
        entry = next((e for e in entries if str(e["historyId"]) == str(args.history_id)), None)
        if entry or not page.get("hasNextPage"):
            break
        after = page.get("endCursor")
    if not entry:
        sys.exit("history entry %s not found (dashboards.py changelog %s)" % (args.history_id, args.target))
    snapshot = parse_dashboards(entry["dashboards"])
    persist(api, target, snapshot, "Restored version from %s" % entry["historyDate"][:19], args.execute, args.force)


def cmd_delete(api, args):
    target = load_target(api, args.dashboard)
    if target.kind != "dashboard":
        sys.exit("only workspace dashboards can be deleted; a device dashboard is emptied by saving a layout without widgets")
    print("PLAN: delete %s permanently (%d tab(s), %d widget(s), %d public link(s))" % (
        target.label, len(target.dashboards), sum(len(t.get("widgets") or {}) for t in target.dashboards), len(target.node.get("publicLinks") or [])))
    if not args.execute:
        print("dry run: add --execute to delete it")
        return
    data, errors = api.run(DELETE_DASHBOARD_MUTATION, {"dashboard": target.id, "workspace": target.workspace_id})
    if errors or not (data.get("deleteDashboard") or {}).get("ok"):
        sys.exit("delete failed: %s" % (json.dumps(errors)[:600] or "ok=false"))
    print("deleted %s" % target.label)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--token")
    ap.add_argument("--endpoint", default=ENDPOINT)
    sub = ap.add_subparsers(dest="command", required=True)

    def write_args(p, tab=True):
        if tab:
            p.add_argument("--tab", type=int, default=0, help="tab index (default 0)")
        p.add_argument("--message", help="change message for the dashboard changelog (max %d characters)" % MESSAGE_MAX)
        p.add_argument("--force", action="store_true", help="write even if the dashboard changed on the server since it was read")
        p.add_argument("--execute", action="store_true")

    p = sub.add_parser("list", help="dashboards of a workspace")
    p.add_argument("workspace")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("get", help="summary or JSON of one dashboard")
    p.add_argument("target")
    p.add_argument("--tab", type=int)
    p.add_argument("--json", action="store_true", help="print the dashboards JSON (all tabs, or --tab N)")
    p.add_argument("--out", help="write the dashboards JSON to this file for editing")
    p.set_defaults(func=cmd_get)

    p = sub.add_parser("schema", help="widget catalogue, defaults of one widget type, or 'presets' for the Value presets")
    p.add_argument("type", nargs="?")
    p.add_argument("--device", action="store_true", help="only widgets available on device dashboards")
    p.set_defaults(func=cmd_schema)

    p = sub.add_parser("generate", help="build a device dashboard (product:/device: target) or a fleet overview (workspace dashboard + --product) from the product's fields; dry run by default")
    p.add_argument("target", help="product:<product-id>, device:<device-id>, or a workspace dashboard id (then --product is required)")
    p.add_argument("--product", help="workspace dashboards: the product whose fields and devices make up the fleet overview")
    p.add_argument("--tags", help="workspace dashboards: comma-separated tags that scope KPIs, table, map and device charts (devices must carry all of them)")
    p.add_argument("--max-devices", type=int, default=12, help="workspace dashboards: devices in the per-device chart/heatmap/histogram (default 12)")
    p.add_argument("--fields", help="comma-separated field identifiers to use, in this order (first numeric field = main chart); default: all")
    p.add_argument("--exclude", help="comma-separated glob patterns of fields to leave out, e.g. '*_INST,*_RAW,LATITUDE'")
    p.add_argument("--new-tab", metavar="NAME", help="write into a new tab instead of --tab")
    p.add_argument("--replace", action="store_true", help="overwrite the widgets of the target tab")
    p.add_argument("--title", help="headline text (default: product name)")
    p.add_argument("--timeframe", default="7 days ago", help="chart start, e.g. '24 hours ago' (default: 7 days ago)")
    p.add_argument("--resolution", default="1h", help="chart resolution <n>m|h|d|w (default 1h)")
    p.add_argument("--timezone", default="UTC")
    p.add_argument("--controls", help="comma-separated fields that get a Switch (BOOL) or Slider (numeric)")
    write_args(p)
    p.set_defaults(func=cmd_generate)

    p = sub.add_parser("create", help="create a workspace dashboard (dry run by default)")
    p.add_argument("workspace")
    p.add_argument("--name", required=True)
    p.add_argument("--icon", default="chart-line")
    p.add_argument("--sharing", default="workspace", choices=["workspace", "public", "restricted"])
    p.add_argument("--shared-with", help="comma-separated user ids (sharing restricted)")
    p.add_argument("--home", action="store_true", help="make it the workspace home dashboard")
    p.add_argument("--file", help="dashboards JSON (tabs with widgets); default: one empty tab")
    p.add_argument("--execute", action="store_true")
    p.set_defaults(func=cmd_create)

    p = sub.add_parser("save", help="replace the whole layout from a JSON file (dry run by default)")
    p.add_argument("target")
    p.add_argument("--file", required=True)
    write_args(p, tab=False)
    p.set_defaults(func=cmd_save)

    p = sub.add_parser("add-widget", help="add one widget (dry run by default)")
    p.add_argument("target")
    p.add_argument("--type", required=True, help="widget type, e.g. Value, LineChart, Headline")
    p.add_argument("--title", help="sets meta.title {en}")
    p.add_argument("--field", help="FIELD_NAME or FIELD_NAME@<device-id>: sets meta.field (device empty = the viewed device on device dashboards)")
    p.add_argument("--preset", help="Value preset (dashboards.py schema presets): title, unit, icon, gauge type and ranges")
    p.add_argument("--meta", help="JSON object merged over the defaults, or @file.json")
    p.add_argument("--x", type=int)
    p.add_argument("--y", type=int)
    p.add_argument("--w", type=int)
    p.add_argument("--h", type=int)
    p.add_argument("--next", action="store_true", help="place to the right of the last row when it fits (default: new row at the bottom)")
    write_args(p)
    p.set_defaults(func=cmd_add_widget)

    p = sub.add_parser("update-widget", help="merge meta keys into one widget (dry run by default)")
    p.add_argument("target")
    p.add_argument("widget", help="widget id (or unique prefix)")
    p.add_argument("--meta", required=True, help="JSON object with the keys to change (null removes a key), or @file.json")
    write_args(p)
    p.set_defaults(func=cmd_update_widget)

    p = sub.add_parser("move-widget", help="change position or size of one widget (dry run by default)")
    p.add_argument("target")
    p.add_argument("widget")
    p.add_argument("--x", type=int)
    p.add_argument("--y", type=int)
    p.add_argument("--w", type=int)
    p.add_argument("--h", type=int)
    p.add_argument("--breakpoint", default="lg", choices=["lg", "sm"])
    write_args(p)
    p.set_defaults(func=cmd_move_widget)

    p = sub.add_parser("remove-widget", help="remove one widget (dry run by default)")
    p.add_argument("target")
    p.add_argument("widget")
    write_args(p)
    p.set_defaults(func=cmd_remove_widget)

    p = sub.add_parser("tab", help="add, rename or remove a tab (dry run by default)")
    p.add_argument("action", choices=["add", "rename", "remove"])
    p.add_argument("target")
    p.add_argument("index", nargs="?", type=int, help="tab index (rename, remove)")
    p.add_argument("--name")
    p.add_argument("--hide-on-whitelabel", action="store_true", help="device dashboards: hide the tab on white label sites")
    write_args(p, tab=False)
    p.set_defaults(func=cmd_tab)

    p = sub.add_parser("check", help="server-side preview of a tab, one widget or an ad-hoc widget (writes nothing)")
    p.add_argument("target")
    p.add_argument("--tab", type=int, default=0)
    p.add_argument("--widget", help="only this widget id")
    p.add_argument("--type", help="ad-hoc widget type (with --meta/--title/--field/--preset) instead of the stored tab")
    p.add_argument("--title")
    p.add_argument("--field")
    p.add_argument("--preset")
    p.add_argument("--meta")
    p.add_argument("--file", help="check this dashboards JSON instead of the stored one")
    p.add_argument("--device", help="device id used for the preview of a product dashboard (default: first device of the product)")
    p.add_argument("--quiet", action="store_true", help="do not print the raw values")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("validate", help="offline structure check of a dashboards JSON file")
    p.add_argument("--file", required=True)
    p.add_argument("--kind", default="workspace", choices=["workspace", "device"])
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("changelog", help="saved versions (needs the dashboard history entitlement)")
    p.add_argument("target")
    p.add_argument("--first", type=int, default=10)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_changelog)

    p = sub.add_parser("restore", help="write an old version back (dry run by default)")
    p.add_argument("target")
    p.add_argument("history_id")
    write_args(p, tab=False)
    p.set_defaults(func=cmd_restore)

    p = sub.add_parser("delete", help="delete a workspace dashboard permanently (dry run by default)")
    p.add_argument("dashboard")
    p.add_argument("--execute", action="store_true")
    p.set_defaults(func=cmd_delete)

    args = ap.parse_args()
    if args.command == "tab":
        if args.action in ("rename", "remove") and args.index is None:
            ap.error("tab %s needs the tab index" % args.action)
        if args.action in ("add", "rename") and not args.name:
            ap.error("tab %s needs --name" % args.action)
    if args.command == "validate":
        args.func(None, args)
        return
    token = resolve_token(args.token)
    if not token:
        sys.exit("no token: export DATACAKE_TOKEN=<token> (see reference/dashboards.md)")
    args.func(Api(token, args.endpoint), args)


if __name__ == "__main__":
    main()
