package repository

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

// ------------------------------------------------------------------ //
// Domain types                                                         //
// ------------------------------------------------------------------ //

type Signal struct {
	ID                 int64           `json:"id"                            example:"1"`
	Symbol             string          `json:"symbol"                        example:"BTCUSDT"`
	TraceID            string          `json:"trace_id"                      example:"3f2d1a9b-feed-4c2e-bae4-abc123def456"`
	Source             json.RawMessage `json:"source"                        swaggertype:"object"`
	RawText            *string         `json:"raw_text,omitempty"            example:"BTC breaks key resistance — targeting 52k"`
	AISummary          *string         `json:"ai_summary,omitempty"          example:"Strong bullish breakout confirmed with high volume"`
	CurrentMarketPrice json.RawMessage `json:"current_market_price,omitempty" swaggertype:"object"`
	CreatedAt          time.Time       `json:"created_at"                    example:"2024-01-15T09:00:00Z"`
	AnalyzedAt         *time.Time      `json:"analyzed_at,omitempty"         example:"2024-01-15T09:05:00Z"`
	Scenarios          []Scenario      `json:"scenarios,omitempty"`
}

type Scenario struct {
	ID           int64            `json:"id"                  example:"1"`
	SignalID     int64            `json:"signal_id"           example:"1"`
	Direction    *string          `json:"direction,omitempty" example:"long"    enums:"long,short"`
	EntryPoint   *float64         `json:"entry_point,omitempty" example:"49500.0"`
	EntryType    *string          `json:"entry_type,omitempty"  example:"limit" enums:"market,limit"`
	TakeProfits  json.RawMessage  `json:"take_profits,omitempty" swaggertype:"object"`
	StopLoss     *float64         `json:"stop_loss,omitempty"   example:"47000.0"`
	Invalidation *string          `json:"invalidation,omitempty" example:"Daily close below 47000 invalidates setup"`
	Confidence   *float64         `json:"confidence,omitempty"  example:"0.85" minimum:"0" maximum:"1"`
	Reasoning    *string          `json:"reasoning,omitempty"   example:"Strong support level with increasing volume and RSI divergence"`
	Status       string           `json:"status"                example:"active" enums:"active,closed,invalidated"`
	Results      []ScenarioResult `json:"results,omitempty"`
}

type ScenarioResult struct {
	ID          int64      `json:"id"                    example:"1"`
	ScenarioID  int64      `json:"scenario_id"           example:"1"`
	Result      string     `json:"result"                example:"win" enums:"win,loss,partial,pending"`
	PnlPercent  *float64   `json:"pnl_percent,omitempty" example:"8.5"`
	HitTP       *float64   `json:"hit_tp,omitempty"      example:"51000.0"`
	HitSL       *float64   `json:"hit_sl,omitempty"`
	MaxDrawdown *float64   `json:"max_drawdown,omitempty" example:"-2.3"`
	EvaluatedAt *time.Time `json:"evaluated_at,omitempty" example:"2024-01-16T14:30:00Z"`
}

// ------------------------------------------------------------------ //
// Pagination                                                           //
// ------------------------------------------------------------------ //

type PageMeta struct {
	Page  int   `json:"page"  example:"1"`
	Limit int   `json:"limit" example:"20"`
	Total int64 `json:"total" example:"150"`
}

type SignalsPage struct {
	Data []Signal `json:"data"`
	Meta PageMeta `json:"meta"`
}

// ------------------------------------------------------------------ //
// Query parameters                                                     //
// ------------------------------------------------------------------ //

type SignalListParams struct {
	Page        int
	Limit       int
	Symbol      string // filter by symbol (exact, uppercase)
	SrcType     string // filter by source.type
	SrcProvider string // filter by source.provider
}

// ------------------------------------------------------------------ //
// Repository                                                           //
// ------------------------------------------------------------------ //

type SignalRepository struct {
	pool *pgxpool.Pool
}

func NewSignalRepository(pool *pgxpool.Pool) *SignalRepository {
	return &SignalRepository{pool: pool}
}

// List returns paginated signals without scenarios.
func (r *SignalRepository) List(ctx context.Context, p SignalListParams) (*SignalsPage, error) {
	query, args := buildSignalQuery(p, false)

	rows, err := r.pool.Query(ctx, query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var total int64
	signals := make([]Signal, 0, p.Limit)

	for rows.Next() {
		var s Signal
		var srcRaw, priceRaw []byte
		if err := rows.Scan(
			&s.ID, &s.Symbol, &s.TraceID, &srcRaw,
			&s.RawText, &s.AISummary, &priceRaw,
			&s.CreatedAt, &s.AnalyzedAt, &total,
		); err != nil {
			return nil, err
		}
		s.Source = json.RawMessage(srcRaw)
		if len(priceRaw) > 0 {
			s.CurrentMarketPrice = json.RawMessage(priceRaw)
		}
		signals = append(signals, s)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}

	return &SignalsPage{
		Data: signals,
		Meta: PageMeta{Page: p.Page, Limit: p.Limit, Total: total},
	}, nil
}

// ListWithResults returns paginated signals with scenarios and scenario_results.
// Uses 3 queries total — no N+1.
func (r *SignalRepository) ListWithResults(ctx context.Context, p SignalListParams) (*SignalsPage, error) {
	// Query 1: signals (same as List)
	page, err := r.List(ctx, p)
	if err != nil {
		return nil, err
	}
	if len(page.Data) == 0 {
		return page, nil
	}

	signalIDs := make([]int64, len(page.Data))
	for i, s := range page.Data {
		signalIDs[i] = s.ID
	}

	// Query 2: all scenarios for these signals
	scenarios, err := r.fetchScenarios(ctx, signalIDs)
	if err != nil {
		return nil, err
	}

	// Query 3: all results for those scenarios (if any)
	if len(scenarios) > 0 {
		scenarioIDs := make([]int64, len(scenarios))
		for i, sc := range scenarios {
			scenarioIDs[i] = sc.ID
		}
		results, err := r.fetchScenarioResults(ctx, scenarioIDs)
		if err != nil {
			return nil, err
		}
		// Attach results to their scenarios
		resultsByScenario := make(map[int64][]ScenarioResult, len(results))
		for _, res := range results {
			resultsByScenario[res.ScenarioID] = append(resultsByScenario[res.ScenarioID], res)
		}
		for i := range scenarios {
			scenarios[i].Results = resultsByScenario[scenarios[i].ID]
		}
	}

	// Attach scenarios to their signals
	scenariosBySignal := make(map[int64][]Scenario, len(page.Data))
	for _, sc := range scenarios {
		scenariosBySignal[sc.SignalID] = append(scenariosBySignal[sc.SignalID], sc)
	}
	for i := range page.Data {
		page.Data[i].Scenarios = scenariosBySignal[page.Data[i].ID]
	}

	return page, nil
}

// ------------------------------------------------------------------ //
// Internal fetch helpers (scenario, scenario_result)                   //
// ------------------------------------------------------------------ //

func (r *SignalRepository) fetchScenarios(ctx context.Context, signalIDs []int64) ([]Scenario, error) {
	rows, err := r.pool.Query(ctx, `
		SELECT id, signal_id, direction, entry_point, entry_type,
		       take_profits, stop_loss, invalidation, confidence, reasoning, status
		FROM scenarios
		WHERE signal_id = ANY($1)
		ORDER BY signal_id, id
	`, signalIDs)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var out []Scenario
	for rows.Next() {
		var sc Scenario
		var tpRaw []byte
		if err := rows.Scan(
			&sc.ID, &sc.SignalID, &sc.Direction, &sc.EntryPoint, &sc.EntryType,
			&tpRaw, &sc.StopLoss, &sc.Invalidation, &sc.Confidence, &sc.Reasoning, &sc.Status,
		); err != nil {
			return nil, err
		}
		if len(tpRaw) > 0 {
			sc.TakeProfits = json.RawMessage(tpRaw)
		}
		out = append(out, sc)
	}
	return out, rows.Err()
}

func (r *SignalRepository) fetchScenarioResults(ctx context.Context, scenarioIDs []int64) ([]ScenarioResult, error) {
	rows, err := r.pool.Query(ctx, `
		SELECT id, scenario_id, result, pnl_percent, hit_tp, hit_sl, max_drawdown, evaluated_at
		FROM scenario_results
		WHERE scenario_id = ANY($1)
		ORDER BY scenario_id, id
	`, scenarioIDs)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var out []ScenarioResult
	for rows.Next() {
		var res ScenarioResult
		if err := rows.Scan(
			&res.ID, &res.ScenarioID, &res.Result,
			&res.PnlPercent, &res.HitTP, &res.HitSL,
			&res.MaxDrawdown, &res.EvaluatedAt,
		); err != nil {
			return nil, err
		}
		out = append(out, res)
	}
	return out, rows.Err()
}

// ------------------------------------------------------------------ //
// Query builder                                                        //
// ------------------------------------------------------------------ //

func buildSignalQuery(p SignalListParams, _ bool) (string, []any) {
	var (
		conditions []string
		args       []any
		n          = 1
	)

	if p.Symbol != "" {
		conditions = append(conditions, fmt.Sprintf("symbol = $%d", n))
		args = append(args, strings.ToUpper(p.Symbol))
		n++
	}
	if p.SrcType != "" {
		filter, _ := json.Marshal(map[string]string{"type": p.SrcType})
		conditions = append(conditions, fmt.Sprintf("source @> $%d::jsonb", n))
		args = append(args, filter)
		n++
	}
	if p.SrcProvider != "" {
		filter, _ := json.Marshal(map[string]string{"provider": p.SrcProvider})
		conditions = append(conditions, fmt.Sprintf("source @> $%d::jsonb", n))
		args = append(args, filter)
		n++
	}

	where := ""
	if len(conditions) > 0 {
		where = "WHERE " + strings.Join(conditions, " AND ")
	}

	// LIMIT and OFFSET are always last two positional args
	args = append(args, p.Limit, (p.Page-1)*p.Limit)
	limitN, offsetN := n, n+1

	query := fmt.Sprintf(`
		SELECT
			id, symbol, trace_id, source,
			raw_text, ai_summary, current_market_price,
			created_at, analyzed_at,
			COUNT(*) OVER() AS total
		FROM signals
		%s
		ORDER BY created_at DESC
		LIMIT $%d OFFSET $%d
	`, where, limitN, offsetN)

	return query, args
}
