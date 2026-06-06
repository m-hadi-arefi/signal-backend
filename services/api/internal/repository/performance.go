package repository

import (
	"encoding/json"
	"fmt"
	"math"
	"time"
)

// ─── Output types ──────────────────────────────────────────────────────────────

// ScenarioPerformance is the performance snapshot returned by the API.
// All heavy computation (PnL tracking, TP/SL detection, extremes) is done by
// signal_evaluator and stored in DB. This struct is purely a read-out of those
// stored values, with only cosmetic formatting applied here.
type ScenarioPerformance struct {
	ActivationTime   *time.Time `json:"activation_time"`
	ActivationPrice  *float64   `json:"activation_price"`
	SignalAgeSeconds float64    `json:"signal_age_seconds"`

	IsProfit bool    `json:"is_profit"`
	IsLoss   bool    `json:"is_loss"`
	StatusPercentNow *string `json:"status_percent_now"` // formatted "X.XX", nil if no entry

	HighestPriceReached *float64 `json:"highest_price_reached"`
	LowestPriceReached  *float64 `json:"lowest_price_reached"`
	MaxProfitPercent    *string  `json:"max_profit_percent"`  // formatted "X.XX", nil if no entry
	MaxDrawdownPercent  *string  `json:"max_drawdown_percent"` // formatted "X.XX", nil if no entry

	TargetsHit   []float64    `json:"targets_hit"`
	TargetsHitAt []*time.Time `json:"targets_hit_at"`

	StopLossHit   bool       `json:"stop_loss_hit"`
	StopLossHitAt *time.Time `json:"stop_loss_hit_at"`

	TargetsCompletedCount  int      `json:"targets_completed_count"`
	TotalTargetsCount      int      `json:"total_targets_count"`
	SuccessProgressPercent *string  `json:"success_progress_percent"` // "X.XX" or null

	PriceHistory []PricePoint `json:"price_history"`
	EventHistory []EventPoint `json:"event_history"`
}

// PricePoint is one price snapshot from scenario_price_points.
type PricePoint struct {
	Timestamp  time.Time `json:"timestamp"`
	Price      float64   `json:"price"`
	PnlPercent *float64  `json:"pnl_percent,omitempty"` // live PnL at this moment
}

// EventPoint is one auditable state-change from scenario_events.
type EventPoint struct {
	Timestamp   time.Time `json:"timestamp"`
	EventType   string    `json:"event_type"`
	Description string    `json:"description"`
	Price       *float64  `json:"price"`
}

// rawEvent is the internal DB row from scenario_events.
type rawEvent struct {
	EventType  string
	Price      *float64
	EventData  []byte
	OccurredAt time.Time
}

// ─── Main computation ──────────────────────────────────────────────────────────

// computePerformance assembles ScenarioPerformance from pre-stored DB values.
// The only computation here is cosmetic: percent values formatted as strings,
// targets_hit built from hit_tp_index + take_profits, age from signal created_at.
func computePerformance(
	sc Scenario,
	res *ScenarioResult,
	events []rawEvent,
	signalCreatedAt time.Time,
	now time.Time,
) ScenarioPerformance {
	p := ScenarioPerformance{
		TargetsHit:   []float64{},
		TargetsHitAt: []*time.Time{},
		PriceHistory: []PricePoint{},
		EventHistory: []EventPoint{},
	}

	// Signal age from creation (not entry)
	age := now.Sub(signalCreatedAt)
	p.SignalAgeSeconds = math.Round(age.Seconds()*10) / 10

	// Take-profit count
	tpPrices := parseTakeProfitPrices(sc.TakeProfits)
	p.TotalTargetsCount = len(tpPrices)

	if res == nil {
		return p
	}

	p.ActivationTime  = res.EnteredAt
	p.ActivationPrice = res.EntryPrice

	// PnL from DB (evaluator updates every 10s)
	if res.PnlPercent != nil {
		p.StatusPercentNow = fmtPct(res.PnlPercent)
		p.IsProfit = *res.PnlPercent > 0
		p.IsLoss   = *res.PnlPercent < 0
	}

	// Price extremes stored directly by evaluator
	p.HighestPriceReached = res.HighestPrice
	p.LowestPriceReached  = res.LowestPrice

	// Max favorable / drawdown formatted as strings
	p.MaxProfitPercent   = fmtPct(res.MaxFavorable)
	p.MaxDrawdownPercent = fmtPct(res.MaxDrawdown)

	// Targets hit — derive from hit_tp_index + take_profits array
	hitIdx := 0
	if res.HitTPIndex != nil {
		hitIdx = *res.HitTPIndex
	}
	p.TargetsCompletedCount = hitIdx

	if hitIdx > 0 && len(tpPrices) > 0 {
		for i := 0; i < hitIdx && i < len(tpPrices); i++ {
			p.TargetsHit = append(p.TargetsHit, tpPrices[i])
			// timestamps come from tp_hit events in order
			p.TargetsHitAt = append(p.TargetsHitAt, nil) // filled in below from events
		}
	}

	// Stop loss
	p.StopLossHit = res.Result == "failed" || res.HitSL != nil
	if p.StopLossHit {
		p.StopLossHitAt = res.CompletedAt
	}

	// Success progress — null when no targets completed yet
	if p.TotalTargetsCount > 0 && hitIdx > 0 {
		prog := float64(hitIdx) / float64(p.TotalTargetsCount) * 100
		p.SuccessProgressPercent = fmtPct2(prog)
	}

	// Price history — already loaded as []PricePoint from scenario_price_points table
	if len(res.PricePoints) > 0 {
		p.PriceHistory = res.PricePoints
	}

	// Event history + backfill targets_hit_at from tp_hit events
	tpEventIdx := 0
	for _, ev := range events {
		ep := EventPoint{
			Timestamp:   ev.OccurredAt,
			EventType:   ev.EventType,
			Description: describeEvent(ev.EventType, ev.Price, ev.EventData),
			Price:       ev.Price,
		}
		p.EventHistory = append(p.EventHistory, ep)

		if ev.EventType == "tp_hit" && tpEventIdx < len(p.TargetsHitAt) {
			t := ev.OccurredAt
			p.TargetsHitAt[tpEventIdx] = &t
			tpEventIdx++
		}
	}

	return p
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

func parseTakeProfitPrices(raw json.RawMessage) []float64 {
	if len(raw) == 0 {
		return nil
	}
	var items []struct {
		Price float64 `json:"price"`
	}
	if err := json.Unmarshal(raw, &items); err != nil {
		return nil
	}
	prices := make([]float64, 0, len(items))
	for _, item := range items {
		if item.Price > 0 {
			prices = append(prices, item.Price)
		}
	}
	return prices
}


func describeEvent(eventType string, price *float64, eventData []byte) string {
	priceStr := ""
	if price != nil {
		if *price >= 1 {
			priceStr = fmt.Sprintf(" at $%.2f", *price)
		} else {
			priceStr = fmt.Sprintf(" at $%g", *price)
		}
	}
	switch eventType {
	case "entered":
		return "Position activated" + priceStr
	case "tp_hit":
		idx := extractIntField(eventData, "tp_index")
		if idx > 0 {
			return fmt.Sprintf("Target %d reached%s", idx, priceStr)
		}
		return "Take profit reached" + priceStr
	case "sl_hit":
		return "Stop loss triggered" + priceStr
	case "completed":
		result := extractStringField(eventData, "result")
		if result != "" {
			return fmt.Sprintf("Signal closed (%s)%s", result, priceStr)
		}
		return "Signal closed" + priceStr
	case "cancelled":
		reason := extractStringField(eventData, "reason")
		if reason == "sibling_entered" {
			return "Cancelled: another scenario activated first"
		}
		return "Scenario cancelled"
	case "expired":
		return "Signal expired" + priceStr
	case "data_gap_start":
		return "Price feed unavailable (gap started)"
	case "data_gap_end":
		return "Price feed restored"
	default:
		return eventType
	}
}

func extractIntField(data []byte, key string) int {
	var d map[string]interface{}
	if err := json.Unmarshal(data, &d); err != nil {
		return 0
	}
	if v, ok := d[key]; ok {
		switch vt := v.(type) {
		case float64:
			return int(vt)
		case int:
			return vt
		}
	}
	return 0
}

func extractStringField(data []byte, key string) string {
	var d map[string]string
	if err := json.Unmarshal(data, &d); err != nil {
		return ""
	}
	return d[key]
}


// fmtPct formats a *float64 as a "±X.XX" string pointer (nil-safe).
func fmtPct(v *float64) *string {
	if v == nil {
		return nil
	}
	s := fmt.Sprintf("%.2f", *v)
	return &s
}

// fmtPct2 formats a plain float64 as a "X.XX" string pointer.
func fmtPct2(v float64) *string {
	s := fmt.Sprintf("%.2f", v)
	return &s
}

func f64ptr(v float64) *float64 {
	return &v
}
