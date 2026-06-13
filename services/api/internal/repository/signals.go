package repository

import (
	"context"
	"encoding/json"
	"fmt"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	"signal/api/internal/cache"
)

// ─── Domain types ──────────────────────────────────────────────────────────────

// Signal is one AI-analysed trading signal.
type Signal struct {
	ID                int64           `json:"id"`
	Symbol            string          `json:"symbol"`
	TraceID           string          `json:"trace_id"`
	Source            json.RawMessage `json:"source"`
	CreatedAt         time.Time       `json:"created_at"`
	AnalyzedAt        *time.Time      `json:"analyzed_at,omitempty"`
	Active            bool            `json:"active"`
	Status            string          `json:"status"`
	LatestPrice       *float64        `json:"latest_price"`        // live Redis price
	CreatedPrice      *float64        `json:"created_price,omitempty"` // price at signal creation
	ActiveScenariosID *int64          `json:"active_scenarios_id"` // set by evaluator on entry
	Scenarios         []Scenario      `json:"scenarios"`
}

// Scenario is one tradeable setup extracted from a Signal.
type Scenario struct {
	ID          int64           `json:"id"`
	SignalID    int64           `json:"-"`
	Direction   *string         `json:"direction,omitempty"`
	Entry       *string         `json:"entry,omitempty"`      // "now" or price string
	EntryType   *string         `json:"entry_type,omitempty"` // price type: "fix", "range"
	TakeProfits json.RawMessage `json:"take_profits,omitempty"`
	StopLoss    *float64        `json:"stop_loss,omitempty"`
	Reasoning   *string         `json:"reasoning,omitempty"`
	Status      string          `json:"status"`
	Active      bool            `json:"active"`
	ExpiresAt   *time.Time      `json:"expires_at,omitempty"`
	Performance ScenarioPerformance `json:"performance"`

	// internal fields — not serialised
	result        *ScenarioResult
	entryPoint    *float64
	entryTypeRaw  *string
	priceTypeRaw  *string
}

// ScenarioResult is loaded from DB to feed performance computation.
type ScenarioResult struct {
	Result       string
	PnlPercent   *float64
	HitTP        *float64
	HitTPIndex   *int
	HitSL        *float64
	MaxDrawdown  *float64
	MaxFavorable *float64
	EntryPrice   *float64
	ExitPrice    *float64
	EnteredAt    *time.Time
	CompletedAt  *time.Time
	EvaluatedAt  *time.Time
	HighestPrice *float64
	LowestPrice  *float64
	PricePoints  []PricePoint // loaded from scenario_price_points table
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
	Symbol      string
	SrcProvider string
	Statuses    []string // nil = all; e.g. ["active","pending"] or ["expired","completed","cancelled"]
}

// ─── Repository ───────────────────────────────────────────────────────────────

type SignalRepository struct {
	pool  *pgxpool.Pool
	cache *cache.Cache // used only for live price lookups (GetPrice), not response caching
}

func NewSignalRepository(pool *pgxpool.Pool, c *cache.Cache) *SignalRepository {
	return &SignalRepository{pool: pool, cache: c}
}

func (r *SignalRepository) List(ctx context.Context, p SignalListParams) (*SignalsPage, error) {
	return r.querySignals(ctx, "", nil, p)
}

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

func (r *SignalRepository) ListByCoin(ctx context.Context, symbol string, p SignalListParams) (*SignalsPage, error) {
	return r.querySignals(ctx, "s.symbol = $1", []any{strings.ToUpper(symbol)}, p)
}

func (r *SignalRepository) ListByProvider(ctx context.Context, provider string, p SignalListParams) (*SignalsPage, error) {
	filter, _ := json.Marshal(map[string]string{"provider": provider})
	return r.querySignals(ctx, "s.source @> $1::jsonb", []any{filter}, p)
}

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

func (r *SignalRepository) querySignals(
	ctx context.Context,
	cond string,
	condArgs []any,
	p SignalListParams,
) (*SignalsPage, error) {
	wheres := []string{}
	if cond != "" {
		wheres = append(wheres, cond)
	}

	args := make([]any, len(condArgs))
	copy(args, condArgs)
	n := len(condArgs) + 1

	if len(p.Statuses) > 0 {
		wheres = append(wheres, fmt.Sprintf("s.status = ANY($%d)", n))
		args = append(args, p.Statuses)
		n++
	}

	where := ""
	if len(wheres) > 0 {
		where = "WHERE " + strings.Join(wheres, " AND ")
	}

	args = append(args, p.Limit, (p.Page-1)*p.Limit)

	query := fmt.Sprintf(`
		SELECT
			s.id, s.symbol, s.trace_id, s.source,
			s.current_market_price,
			s.created_at, s.analyzed_at,
			s.active,
			s.status,
			s.active_scenarios_id,
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
			&priceRaw,
			&s.CreatedAt, &s.AnalyzedAt,
			&s.Active, &s.Status, &s.ActiveScenariosID,
			&total,
		); err != nil {
			return nil, err
		}
		s.Source = json.RawMessage(srcRaw)
		if len(priceRaw) > 0 {
			s.CreatedPrice = extractPrice(priceRaw)
		}
		s.Scenarios = []Scenario{}
		signals = append(signals, s)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}

	if len(signals) > 0 {
		// 1. Load scenarios + results + events from DB
		eventMap, err := r.attachScenariosWithEvents(ctx, signals)
		if err != nil {
			return nil, err
		}

		// 2. Inject live prices from Redis
		r.attachCurrentPrices(ctx, signals)

		// 3. Compute performance (reads pre-stored DB values, minimal formatting only)
		now := time.Now().UTC()
		for si := range signals {
			for sj := range signals[si].Scenarios {
				sc := &signals[si].Scenarios[sj]

				// Resolve entry and entry_type display fields now that all internal fields are loaded
				sc.Entry     = buildEntryField(sc.entryTypeRaw, sc.entryPoint)
				sc.EntryType = buildPriceTypeField(sc.priceTypeRaw)

				sc.Performance = computePerformance(
					*sc,
					sc.result,
					eventMap[sc.ID],
					signals[si].CreatedAt,
					now,
				)
				// Clear internal-only fields
				sc.result       = nil
				sc.entryPoint   = nil
				sc.entryTypeRaw = nil
				sc.priceTypeRaw = nil
			}
		}
	}

	return &SignalsPage{
		Data: signals,
		Meta: PageMeta{Page: p.Page, Limit: p.Limit, Total: total},
	}, nil
}

// attachScenariosWithEvents loads scenarios, results, and events for the given
// signals in-place (3 queries total).
func (r *SignalRepository) attachScenariosWithEvents(
	ctx context.Context,
	signals []Signal,
) (map[int64][]rawEvent, error) {
	signalIDs := make([]int64, len(signals))
	createdAtMap := make(map[int64]time.Time, len(signals))
	for i, s := range signals {
		signalIDs[i] = s.ID
		createdAtMap[s.ID] = s.CreatedAt
	}

	// ── 1. Scenarios ──────────────────────────────────────────────────────────
	scRows, err := r.pool.Query(ctx, `
		SELECT id, signal_id, direction, entry_point, entry_type,
		       COALESCE(raw->>'type', '') AS price_type,
		       take_profits, stop_loss, reasoning, status,
		       active,
		       expire_at,
		       COALESCE(raw->>'expire_time', '') AS expire_time_str
		FROM   scenarios
		WHERE  signal_id = ANY($1)
		ORDER  BY signal_id, id
	`, signalIDs)
	if err != nil {
		return nil, err
	}
	defer scRows.Close()

	scenarios := make([]Scenario, 0)
	scenarioIDs := make([]int64, 0)

	for scRows.Next() {
		var sc Scenario
		var tpRaw []byte
		var expireAt *time.Time
		var expireStr string
		var priceType string
		if err := scRows.Scan(
			&sc.ID, &sc.SignalID, &sc.Direction, &sc.entryPoint, &sc.entryTypeRaw,
			&priceType,
			&tpRaw, &sc.StopLoss, &sc.Reasoning, &sc.Status,
			&sc.Active,
			&expireAt, &expireStr,
		); err != nil {
			return nil, err
		}
		if priceType != "" {
			sc.priceTypeRaw = &priceType
		}
		if len(tpRaw) > 0 {
			sc.TakeProfits = json.RawMessage(tpRaw)
		}
		if expireAt != nil {
			sc.ExpiresAt = expireAt
		} else if expireStr != "" {
			sc.ExpiresAt = parseExpireTime(createdAtMap[sc.SignalID], expireStr)
		}
		sc.Performance = ScenarioPerformance{
			TargetsHit:   []float64{},
			TargetsHitAt: []*time.Time{},
			PriceHistory: []PricePoint{},
			EventHistory: []EventPoint{},
		}
		scenarioIDs = append(scenarioIDs, sc.ID)
		scenarios = append(scenarios, sc)
	}
	if err := scRows.Err(); err != nil {
		return nil, err
	}

	// ── 2. Scenario results ───────────────────────────────────────────────────
	resultMap := make(map[int64]*ScenarioResult, len(scenarioIDs))
	if len(scenarioIDs) > 0 {
		rRows, err := r.pool.Query(ctx, `
			SELECT scenario_id, result, pnl_percent,
			       hit_tp, hit_tp_index, hit_sl,
			       max_drawdown, max_favorable,
			       entry_price, exit_price,
			       entered_at, completed_at, evaluated_at,
			       COALESCE(highest_price, NULL) AS highest_price,
			       COALESCE(lowest_price,  NULL) AS lowest_price
			FROM   scenario_results
			WHERE  scenario_id = ANY($1)
		`, scenarioIDs)
		if err != nil {
			return nil, err
		}
		defer rRows.Close()

		for rRows.Next() {
			var scID int64
			var res ScenarioResult
			if err := rRows.Scan(
				&scID, &res.Result, &res.PnlPercent,
				&res.HitTP, &res.HitTPIndex, &res.HitSL,
				&res.MaxDrawdown, &res.MaxFavorable,
				&res.EntryPrice, &res.ExitPrice,
				&res.EnteredAt, &res.CompletedAt, &res.EvaluatedAt,
				&res.HighestPrice, &res.LowestPrice,
			); err != nil {
				return nil, err
			}
			r2 := res
			resultMap[scID] = &r2
		}
		if err := rRows.Err(); err != nil {
			return nil, err
		}

		// ── 2b. Price history from dedicated table ────────────────────────────
		ppRows, err := r.pool.Query(ctx, `
			SELECT scenario_id, recorded_at, price, pnl_percent
			FROM   scenario_price_points
			WHERE  scenario_id = ANY($1)
			ORDER  BY scenario_id, recorded_at ASC
		`, scenarioIDs)
		if err == nil {
			defer ppRows.Close()
			for ppRows.Next() {
				var scID int64
				var pt PricePoint
				var pnl *float64
				if err := ppRows.Scan(&scID, &pt.Timestamp, &pt.Price, &pnl); err != nil {
					continue
				}
				pt.PnlPercent = pnl
				if res, ok := resultMap[scID]; ok {
					res.PricePoints = append(res.PricePoints, pt)
				}
			}
			_ = ppRows.Err()
		}
	}

	// ── 3. Scenario events ────────────────────────────────────────────────────
	eventMap := make(map[int64][]rawEvent, len(scenarioIDs))
	if len(scenarioIDs) > 0 {
		evRows, err := r.pool.Query(ctx, `
			SELECT scenario_id, event_type, price, event_data, occurred_at
			FROM   scenario_events
			WHERE  scenario_id = ANY($1)
			ORDER  BY scenario_id, occurred_at ASC
		`, scenarioIDs)
		if err != nil {
			evRows = nil
		}
		if evRows != nil {
			defer evRows.Close()
			for evRows.Next() {
				var scID int64
				var ev rawEvent
				var evDataRaw []byte
				if err := evRows.Scan(
					&scID, &ev.EventType, &ev.Price, &evDataRaw, &ev.OccurredAt,
				); err != nil {
					continue
				}
				ev.EventData = evDataRaw
				eventMap[scID] = append(eventMap[scID], ev)
			}
			_ = evRows.Err()
		}
	}

	// ── Attach results + signals ──────────────────────────────────────────────
	bySignal := make(map[int64][]Scenario, len(signals))
	for i := range scenarios {
		if res, ok := resultMap[scenarios[i].ID]; ok {
			scenarios[i].result = res
		}
		bySignal[scenarios[i].SignalID] = append(bySignal[scenarios[i].SignalID], scenarios[i])
	}
	for i := range signals {
		if sc, ok := bySignal[signals[i].ID]; ok {
			signals[i].Scenarios = sc
		}
	}

	return eventMap, nil
}

// attachCurrentPrices fetches live prices from Redis for each distinct symbol.
func (r *SignalRepository) attachCurrentPrices(ctx context.Context, signals []Signal) {
	priceCache := make(map[string]*float64)
	for i := range signals {
		sym := signals[i].Symbol
		if _, seen := priceCache[sym]; !seen {
			priceCache[sym] = r.cache.GetPrice(ctx, sym)
		}
		signals[i].LatestPrice = priceCache[sym]
	}
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

// extractPrice pulls the numeric price field out of a {price, source, timestamp} JSONB blob.
func extractPrice(raw []byte) *float64 {
	var v struct {
		Price float64 `json:"price"`
	}
	if err := json.Unmarshal(raw, &v); err != nil || v.Price == 0 {
		return nil
	}
	return &v.Price
}

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

// buildEntryField returns the human-readable entry value:
//   "now"   when entry_type is "market" or entry_point is nil
//   "62500" (price as string) for fixed/limit/break entries with a price
//   entry_type string for other named entry conditions
func buildEntryField(entryType *string, entryPoint *float64) *string {
	et := ""
	if entryType != nil {
		et = strings.ToLower(*entryType)
	}
	if et == "market" || et == "" {
		s := "now"
		return &s
	}
	if entryPoint != nil {
		s := strconv.FormatFloat(*entryPoint, 'f', -1, 64)
		return &s
	}
	return entryType
}

// buildPriceTypeField normalises the raw "type" from scenarios.raw JSON:
//   "fixnumber" → "fix"
//   everything else → as-is (or nil if empty)
func buildPriceTypeField(priceType *string) *string {
	if priceType == nil || *priceType == "" {
		s := "fix"
		return &s
	}
	s := strings.ToLower(*priceType)
	if s == "fixnumber" {
		r := "fix"
		return &r
	}
	return priceType
}
