package repository

import (
	"context"
	"encoding/json"
	"fmt"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

// ─── Domain types ──────────────────────────────────────────────────────────────

// Signal is one AI-analysed trading signal. raw_text is intentionally excluded.
type Signal struct {
	ID                 int64           `json:"id"`
	Symbol             string          `json:"symbol"`
	TraceID            string          `json:"trace_id"`
	Source             json.RawMessage `json:"source"`
	AISummary          *string         `json:"ai_summary,omitempty"`
	CurrentMarketPrice json.RawMessage `json:"current_market_price,omitempty"`
	CreatedAt          time.Time       `json:"created_at"`
	AnalyzedAt         *time.Time      `json:"analyzed_at,omitempty"`
	Scenarios          []Scenario      `json:"scenarios"`
}

// Scenario is one tradeable setup extracted from a Signal.
type Scenario struct {
	ID          int64           `json:"id"`
	SignalID    int64           `json:"-"` // internal only
	Direction   *string         `json:"direction,omitempty"`
	EntryPoint  *float64        `json:"entry_point,omitempty"`
	EntryType   *string         `json:"entry_type,omitempty"`
	TakeProfits json.RawMessage `json:"take_profits,omitempty"`
	StopLoss    *float64        `json:"stop_loss,omitempty"`
	Confidence  *float64        `json:"confidence,omitempty"`
	Reasoning   *string         `json:"reasoning,omitempty"`
	Status      string          `json:"status"`     // running / active / success / failed / expired
	IsEntered   bool            `json:"is_entered"` // true when entry condition is confirmed
	ExpiresAt   *time.Time      `json:"expires_at,omitempty"`
	Result      *ScenarioResult `json:"result,omitempty"` // nil until first evaluator cycle
}

// ScenarioResult is the live/final evaluation snapshot.
type ScenarioResult struct {
	Result      string     `json:"result"` // running / success / failed / expired
	PnlPercent  *float64   `json:"pnl_percent,omitempty"`
	HitTP       *float64   `json:"hit_tp,omitempty"`
	HitSL       *float64   `json:"hit_sl,omitempty"`
	MaxDrawdown *float64   `json:"max_drawdown,omitempty"`
	EnteredAt   *time.Time `json:"entered_at,omitempty"`
	EvaluatedAt *time.Time `json:"evaluated_at,omitempty"`
}

// ActiveCoin is a coin that the admin has enabled for tracking.
type ActiveCoin struct {
	Symbol string `json:"symbol"`
	Name   string `json:"name"`
	FaName string `json:"fa_name"`
}

// SourceInfo aggregates stats for one signal source provider.
type SourceInfo struct {
	Provider     string    `json:"provider"`
	Type         string    `json:"type"`
	SignalCount  int64     `json:"signal_count"`
	LastSignalAt time.Time `json:"last_signal_at"`
}

// ─── Pagination wrappers ──────────────────────────────────────────────────────

type PageMeta struct {
	Page  int   `json:"page"`
	Limit int   `json:"limit"`
	Total int64 `json:"total"`
}

type SignalsPage struct {
	Data []Signal `json:"data"`
	Meta PageMeta `json:"meta"`
}

type CoinsPage struct {
	Data []ActiveCoin `json:"data"`
}

type SourcesPage struct {
	Data []SourceInfo `json:"data"`
}

// ─── Query params ─────────────────────────────────────────────────────────────

type SignalListParams struct {
	Page        int
	Limit       int
	Symbol      string // uppercase
	SrcProvider string
}

// ─── Repository ───────────────────────────────────────────────────────────────

type SignalRepository struct {
	pool *pgxpool.Pool
}

func NewSignalRepository(pool *pgxpool.Pool) *SignalRepository {
	return &SignalRepository{pool: pool}
}

// List returns paginated signals with scenarios and latest results.
func (r *SignalRepository) List(ctx context.Context, p SignalListParams) (*SignalsPage, error) {
	return r.querySignals(ctx, "", nil, p)
}

// GetByID returns a single signal with full data, or nil if not found.
func (r *SignalRepository) GetByID(ctx context.Context, id int64) (*Signal, error) {
	p := SignalListParams{Page: 1, Limit: 1}
	page, err := r.querySignals(ctx, "s.id = $1", []any{id}, p)
	if err != nil {
		return nil, err
	}
	if len(page.Data) == 0 {
		return nil, nil
	}
	return &page.Data[0], nil
}

// ListByCoin returns paginated signals for the given coin symbol.
func (r *SignalRepository) ListByCoin(ctx context.Context, symbol string, p SignalListParams) (*SignalsPage, error) {
	return r.querySignals(ctx, "s.symbol = $1", []any{strings.ToUpper(symbol)}, p)
}

// ListByProvider returns paginated signals from the given source provider.
func (r *SignalRepository) ListByProvider(ctx context.Context, provider string, p SignalListParams) (*SignalsPage, error) {
	filter, _ := json.Marshal(map[string]string{"provider": provider})
	return r.querySignals(ctx, "s.source @> $1::jsonb", []any{filter}, p)
}

// ListActiveCoins returns all active tracked coins.
func (r *SignalRepository) ListActiveCoins(ctx context.Context) (*CoinsPage, error) {
	rows, err := r.pool.Query(ctx, `
		SELECT symbol, name, fa_name
		FROM   tracked_coins
		WHERE  is_active = TRUE
		ORDER  BY symbol
	`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	coins := make([]ActiveCoin, 0)
	for rows.Next() {
		var c ActiveCoin
		if err := rows.Scan(&c.Symbol, &c.Name, &c.FaName); err != nil {
			return nil, err
		}
		coins = append(coins, c)
	}
	return &CoinsPage{Data: coins}, rows.Err()
}

// ListSources returns distinct source providers with signal stats.
func (r *SignalRepository) ListSources(ctx context.Context) (*SourcesPage, error) {
	rows, err := r.pool.Query(ctx, `
		SELECT
			COALESCE(source->>'provider', '') AS provider,
			COALESCE(source->>'type', '')     AS type,
			COUNT(*)                          AS signal_count,
			MAX(created_at)                   AS last_signal_at
		FROM   signals
		WHERE  source->>'provider' IS NOT NULL
		GROUP  BY source->>'provider', source->>'type'
		ORDER  BY last_signal_at DESC
	`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	sources := make([]SourceInfo, 0)
	for rows.Next() {
		var s SourceInfo
		if err := rows.Scan(&s.Provider, &s.Type, &s.SignalCount, &s.LastSignalAt); err != nil {
			return nil, err
		}
		sources = append(sources, s)
	}
	return &SourcesPage{Data: sources}, rows.Err()
}

// ─── Internal ─────────────────────────────────────────────────────────────────

// querySignals is the common path for all signal list queries.
// cond is an optional WHERE clause fragment (e.g. "s.symbol = $1").
// condArgs holds the values for the condition placeholders.
func (r *SignalRepository) querySignals(
	ctx context.Context,
	cond string,
	condArgs []any,
	p SignalListParams,
) (*SignalsPage, error) {
	where := ""
	if cond != "" {
		where = "WHERE " + cond
	}

	// LIMIT / OFFSET are always the last two positional args
	n := len(condArgs) + 1
	args := append(condArgs, p.Limit, (p.Page-1)*p.Limit)

	query := fmt.Sprintf(`
		SELECT
			s.id, s.symbol, s.trace_id, s.source,
			s.ai_summary, s.current_market_price,
			s.created_at, s.analyzed_at,
			COUNT(*) OVER() AS total
		FROM   signals s
		%s
		ORDER  BY s.created_at DESC
		LIMIT  $%d OFFSET $%d
	`, where, n, n+1)

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
			&s.AISummary, &priceRaw,
			&s.CreatedAt, &s.AnalyzedAt, &total,
		); err != nil {
			return nil, err
		}
		s.Source = json.RawMessage(srcRaw)
		if len(priceRaw) > 0 {
			s.CurrentMarketPrice = json.RawMessage(priceRaw)
		}
		s.Scenarios = []Scenario{}
		signals = append(signals, s)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}

	if len(signals) > 0 {
		if err := r.attachScenarios(ctx, signals); err != nil {
			return nil, err
		}
	}

	return &SignalsPage{
		Data: signals,
		Meta: PageMeta{Page: p.Page, Limit: p.Limit, Total: total},
	}, nil
}

// attachScenarios loads scenarios + results for the given signals in-place (2 queries).
func (r *SignalRepository) attachScenarios(ctx context.Context, signals []Signal) error {
	signalIDs := make([]int64, len(signals))
	createdAtMap := make(map[int64]time.Time, len(signals))
	for i, s := range signals {
		signalIDs[i] = s.ID
		createdAtMap[s.ID] = s.CreatedAt
	}

	// ── Scenarios ──
	scRows, err := r.pool.Query(ctx, `
		SELECT id, signal_id, direction, entry_point, entry_type,
		       take_profits, stop_loss, confidence, reasoning, status,
		       COALESCE(raw->>'expire_time', '') AS expire_time
		FROM   scenarios
		WHERE  signal_id = ANY($1)
		ORDER  BY signal_id, id
	`, signalIDs)
	if err != nil {
		return err
	}
	defer scRows.Close()

	scenarios := make([]Scenario, 0)
	scenarioIDs := make([]int64, 0)

	for scRows.Next() {
		var sc Scenario
		var tpRaw []byte
		var expireStr string
		if err := scRows.Scan(
			&sc.ID, &sc.SignalID, &sc.Direction, &sc.EntryPoint, &sc.EntryType,
			&tpRaw, &sc.StopLoss, &sc.Confidence, &sc.Reasoning, &sc.Status,
			&expireStr,
		); err != nil {
			return err
		}
		if len(tpRaw) > 0 {
			sc.TakeProfits = json.RawMessage(tpRaw)
		}
		sc.IsEntered = sc.Status == "active"
		if expireStr != "" {
			sc.ExpiresAt = parseExpireTime(createdAtMap[sc.SignalID], expireStr)
		}
		scenarioIDs = append(scenarioIDs, sc.ID)
		scenarios = append(scenarios, sc)
	}
	if err := scRows.Err(); err != nil {
		return err
	}

	// ── Scenario results (one per scenario due to unique constraint) ──
	resultMap := make(map[int64]*ScenarioResult, len(scenarioIDs))
	if len(scenarioIDs) > 0 {
		rRows, err := r.pool.Query(ctx, `
			SELECT scenario_id, result, pnl_percent, hit_tp, hit_sl,
			       max_drawdown, entered_at, evaluated_at
			FROM   scenario_results
			WHERE  scenario_id = ANY($1)
		`, scenarioIDs)
		if err != nil {
			return err
		}
		defer rRows.Close()

		for rRows.Next() {
			var scID int64
			var res ScenarioResult
			if err := rRows.Scan(
				&scID, &res.Result, &res.PnlPercent,
				&res.HitTP, &res.HitSL, &res.MaxDrawdown,
				&res.EnteredAt, &res.EvaluatedAt,
			); err != nil {
				return err
			}
			r2 := res
			resultMap[scID] = &r2
		}
		if err := rRows.Err(); err != nil {
			return err
		}
	}

	// Attach results → scenarios → signals
	bySignal := make(map[int64][]Scenario, len(signals))
	for i := range scenarios {
		if res, ok := resultMap[scenarios[i].ID]; ok {
			scenarios[i].Result = res
		}
		bySignal[scenarios[i].SignalID] = append(bySignal[scenarios[i].SignalID], scenarios[i])
	}
	for i := range signals {
		if sc, ok := bySignal[signals[i].ID]; ok {
			signals[i].Scenarios = sc
		}
	}
	return nil
}

// ─── Duration helper ──────────────────────────────────────────────────────────

func parseExpireTime(createdAt time.Time, expireStr string) *time.Time {
	s := strings.ToLower(strings.TrimSpace(expireStr))
	if len(s) < 2 {
		return nil
	}
	n, err := strconv.Atoi(s[:len(s)-1])
	if err != nil || n <= 0 {
		return nil
	}
	var d time.Duration
	switch s[len(s)-1] {
	case 'd':
		d = time.Duration(n) * 24 * time.Hour
	case 'w':
		d = time.Duration(n) * 7 * 24 * time.Hour
	case 'm':
		d = time.Duration(n) * 30 * 24 * time.Hour
	case 'y':
		d = time.Duration(n) * 365 * 24 * time.Hour
	default:
		return nil
	}
	t := createdAt.Add(d)
	return &t
}
