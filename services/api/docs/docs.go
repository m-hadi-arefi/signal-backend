// Package docs — generated swagger spec for Signal API v2.
package docs

import "github.com/swaggo/swag"

const docTemplate = `{
  "swagger": "2.0",
  "info": {
    "title": "Signal API",
    "description": "Read-only REST API for AI-analysed trading signals with scenario tracking and evaluation results. raw_text is never returned.",
    "version": "2.0"
  },
  "host": "localhost:8080",
  "basePath": "/",
  "schemes": ["http", "https"],
  "produces": ["application/json"],
  "tags": [
    {"name": "signals",  "description": "Paginated signal endpoints with nested scenarios and evaluation results"},
    {"name": "sources",  "description": "Source provider discovery and filtering"},
    {"name": "coins",    "description": "Active tracked coin list"},
    {"name": "system",   "description": "Health and diagnostics"}
  ],
  "paths": {
    "/health": {
      "get": {
        "tags": ["system"],
        "summary": "Health check",
        "description": "Returns DB and Redis connection status.",
        "produces": ["application/json"],
        "responses": {
          "200": {"description": "Healthy or degraded"},
          "503": {"description": "Unhealthy — DB unreachable"}
        }
      }
    },
    "/v1/signals": {
      "get": {
        "tags": ["signals"],
        "summary": "List all signals",
        "description": "Paginated list of signals with scenarios, is_entered flag, expires_at, and latest evaluation result. raw_text is never included.",
        "produces": ["application/json"],
        "parameters": [
          {"name": "page",  "in": "query", "type": "integer", "default": 1,  "description": "Page number (1-based)"},
          {"name": "limit", "in": "query", "type": "integer", "default": 20, "description": "Items per page (max 200)"}
        ],
        "responses": {
          "200": {"description": "Paginated signal list"},
          "408": {"description": "Query timeout"},
          "500": {"description": "Internal server error"}
        }
      }
    },
    "/v1/signals/coin/{symbol}": {
      "get": {
        "tags": ["signals"],
        "summary": "Signals for a coin",
        "description": "Paginated signals filtered by coin symbol (case-insensitive).",
        "produces": ["application/json"],
        "parameters": [
          {"name": "symbol", "in": "path",  "required": true,  "type": "string", "description": "Coin symbol, e.g. BTC or ETH"},
          {"name": "page",   "in": "query", "required": false, "type": "integer", "default": 1},
          {"name": "limit",  "in": "query", "required": false, "type": "integer", "default": 20}
        ],
        "responses": {
          "200": {"description": "Paginated signal list"},
          "408": {"description": "Query timeout"},
          "500": {"description": "Internal server error"}
        }
      }
    },
    "/v1/signals/{id}": {
      "get": {
        "tags": ["signals"],
        "summary": "Get signal by ID",
        "description": "Full signal detail including all scenarios and their latest evaluation result.",
        "produces": ["application/json"],
        "parameters": [
          {"name": "id", "in": "path", "required": true, "type": "integer", "description": "Signal ID"}
        ],
        "responses": {
          "200": {"description": "Signal detail"},
          "404": {"description": "Signal not found"},
          "408": {"description": "Query timeout"},
          "500": {"description": "Internal server error"}
        }
      }
    },
    "/v1/sources": {
      "get": {
        "tags": ["sources"],
        "summary": "List signal sources",
        "description": "All unique source providers that have submitted signals, with signal count and last activity timestamp.",
        "produces": ["application/json"],
        "responses": {
          "200": {"description": "Sources list"},
          "408": {"description": "Query timeout"},
          "500": {"description": "Internal server error"}
        }
      }
    },
    "/v1/sources/{provider}/signals": {
      "get": {
        "tags": ["sources"],
        "summary": "Signals from a source",
        "description": "Paginated signals submitted by the given source provider.",
        "produces": ["application/json"],
        "parameters": [
          {"name": "provider", "in": "path",  "required": true,  "type": "string", "description": "Source provider name"},
          {"name": "page",     "in": "query", "required": false, "type": "integer", "default": 1},
          {"name": "limit",    "in": "query", "required": false, "type": "integer", "default": 20}
        ],
        "responses": {
          "200": {"description": "Paginated signal list"},
          "408": {"description": "Query timeout"},
          "500": {"description": "Internal server error"}
        }
      }
    },
    "/v1/coins/active": {
      "get": {
        "tags": ["coins"],
        "summary": "Active tracked coins",
        "description": "All coins the admin has enabled for signal tracking.",
        "produces": ["application/json"],
        "responses": {
          "200": {"description": "Active coins list"},
          "408": {"description": "Query timeout"},
          "500": {"description": "Internal server error"}
        }
      }
    }
  },
  "definitions": {
    "Signal": {
      "type": "object",
      "properties": {
        "id":            {"type": "integer"},
        "symbol":        {"type": "string",  "example": "BTC"},
        "trace_id":      {"type": "string"},
        "source":        {"type": "object",  "description": "{type, provider, channel?, url?, external_id?}"},
        "ai_summary":    {"type": "string"},
        "created_at":    {"type": "string",  "format": "date-time"},
        "analyzed_at":   {"type": "string",  "format": "date-time"},
        "active":        {"type": "boolean", "description": "true when any scenario has status=active"},
        "current_price": {"type": "number",  "description": "live market price from Redis"},
        "created_price": {"type": "number",  "description": "market price snapshotted at signal creation"},
        "scenarios":     {"type": "array",   "items": {"$ref": "#/definitions/Scenario"}}
      }
    },
    "Scenario": {
      "type": "object",
      "properties": {
        "id":           {"type": "integer"},
        "direction":    {"type": "string",  "enum": ["long","short","neutral"]},
        "entry_point":  {"type": "number"},
        "entry_type":   {"type": "string",  "enum": ["market","fix","break_up","break_down","consolidation_up","consolidation_down"]},
        "take_profits": {"type": "array",   "items": {"type": "object", "properties": {"price": {"type": "number"}, "label": {"type": "string"}}}},
        "stop_loss":    {"type": "number"},
        "confidence":   {"type": "number",  "minimum": 0, "maximum": 1},
        "reasoning":    {"type": "string"},
        "status":       {"type": "string",  "enum": ["running","active","success","failed","expired","cancelled","invalid","rejected","skipped"]},
        "active":       {"type": "boolean", "description": "true when status=active"},
        "expires_at":   {"type": "string",  "format": "date-time"},
        "result":       {"$ref": "#/definitions/ScenarioResult"},
        "performance":  {"$ref": "#/definitions/ScenarioPerformance"}
      }
    },
    "ScenarioResult": {
      "type": "object",
      "properties": {
        "result":        {"type": "string",  "enum": ["running","success","failed","expired","cancelled"]},
        "pnl_percent":   {"type": "number",  "description": "live unrealized or final P&L %"},
        "hit_tp":        {"type": "number",  "description": "best TP price touched"},
        "hit_tp_index":  {"type": "integer", "description": "ordinal of best TP hit: 1=TP1, 2=TP2 …"},
        "hit_sl":        {"type": "number"},
        "max_drawdown":  {"type": "number",  "description": "worst PnL % seen (negative = loss)"},
        "max_favorable": {"type": "number",  "description": "best PnL % ever seen (positive = profit)"},
        "entry_price":   {"type": "number",  "description": "confirmed entry price (limit/market)"},
        "exit_price":    {"type": "number",  "description": "price at which position closed (TP, SL, or expiry)"},
        "entered_at":    {"type": "string",  "format": "date-time"},
        "completed_at":  {"type": "string",  "format": "date-time"},
        "evaluated_at":  {"type": "string",  "format": "date-time"},
        "price_history": {"type": "array",   "description": "one snapshot per timeframe unit",
                          "items": {"type": "object", "properties": {"ts": {"type": "string"}, "price": {"type": "number"}}}}
      }
    },
    "ScenarioPerformance": {
      "type": "object",
      "description": "Fully-computed performance view. Frontend needs zero additional calculations.",
      "properties": {
        "activation_time":                    {"type": "string",  "format": "date-time", "description": "When position was entered"},
        "activation_price":                   {"type": "number",  "description": "Confirmed entry price"},
        "current_price":                      {"type": "number",  "description": "Live market price from Redis"},
        "last_price_update_at":               {"type": "string",  "format": "date-time"},
        "signal_age_seconds":                 {"type": "number"},
        "signal_age_minutes":                 {"type": "number"},
        "signal_age_hours":                   {"type": "number"},
        "signal_age_days":                    {"type": "number"},
        "current_pnl_percent":               {"type": "number",  "description": "Live PnL % (re-calculated from current price when active)"},
        "current_pnl_value":                 {"type": "number",  "description": "Dollar change per unit (entry_price * pnl%)"},
        "is_profit":                          {"type": "boolean"},
        "is_loss":                            {"type": "boolean"},
        "highest_price_reached":             {"type": "number"},
        "lowest_price_reached":              {"type": "number"},
        "max_profit_percent":                {"type": "number",  "description": "Best PnL % ever observed"},
        "max_drawdown_percent":              {"type": "number",  "description": "Worst PnL % ever observed (negative)"},
        "current_distance_from_entry_percent":{"type": "number", "description": "Signed distance from entry: + = favourable"},
        "target_1_hit":                      {"type": "boolean"},
        "target_1_hit_at":                   {"type": "string",  "format": "date-time"},
        "target_2_hit":                      {"type": "boolean"},
        "target_2_hit_at":                   {"type": "string",  "format": "date-time"},
        "target_3_hit":                      {"type": "boolean"},
        "target_3_hit_at":                   {"type": "string",  "format": "date-time"},
        "stop_loss_hit":                     {"type": "boolean"},
        "stop_loss_hit_at":                  {"type": "string",  "format": "date-time"},
        "is_active":                         {"type": "boolean"},
        "is_closed":                         {"type": "boolean"},
        "is_expired":                        {"type": "boolean"},
        "current_status":                    {"type": "string"},
        "targets_completed_count":           {"type": "integer"},
        "total_targets_count":               {"type": "integer"},
        "success_progress_percent":          {"type": "number",  "description": "0–100"},
        "price_history": {
          "type": "array",
          "description": "Price snapshots enriched with PnL",
          "items": {
            "type": "object",
            "properties": {
              "timestamp":   {"type": "string", "format": "date-time"},
              "price":       {"type": "number"},
              "pnl_percent": {"type": "number"}
            }
          }
        },
        "event_history": {
          "type": "array",
          "description": "Full audit timeline of state changes",
          "items": {
            "type": "object",
            "properties": {
              "timestamp":   {"type": "string", "format": "date-time"},
              "event_type":  {"type": "string"},
              "description": {"type": "string"},
              "price":       {"type": "number"},
              "pnl_percent": {"type": "number"}
            }
          }
        },
        "total_price_updates":  {"type": "integer"},
        "first_seen_price":     {"type": "number"},
        "latest_price":         {"type": "number"},
        "best_recorded_price":  {"type": "number", "description": "Direction-aware best absolute price level"},
        "worst_recorded_price": {"type": "number", "description": "Direction-aware worst absolute price level"},
        "best_recorded_pnl":    {"type": "number"},
        "worst_recorded_pnl":   {"type": "number"}
      }
    },
    "ActiveCoin": {
      "type": "object",
      "properties": {
        "symbol":  {"type": "string", "example": "BTC"},
        "name":    {"type": "string", "example": "Bitcoin"},
        "fa_name": {"type": "string", "example": "بیت‌کوین"}
      }
    },
    "SourceInfo": {
      "type": "object",
      "properties": {
        "provider":      {"type": "string"},
        "type":          {"type": "string"},
        "signal_count":  {"type": "integer"},
        "last_signal_at":{"type": "string", "format": "date-time"}
      }
    }
  }
}`

func init() {
	swag.Register(swag.Name, &swag.Spec{
		InfoInstanceName: swag.Name,
		SwaggerTemplate:  docTemplate,
	})
}
