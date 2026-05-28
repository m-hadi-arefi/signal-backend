package handler

import (
	"context"
	"errors"
	"log"
	"strings"

	"github.com/gofiber/fiber/v2"
	"signal/api/internal/cache"
	"signal/api/internal/repository"
)

// ErrorResponse is the standard error body returned on 4xx/5xx responses.
type ErrorResponse struct {
	Error      string `json:"error"                  example:"query timeout"`
	RetryAfter int    `json:"retry_after,omitempty"  example:"1"`
}

// SignalHandler serves all /v1/signals endpoints.
type SignalHandler struct {
	repo  *repository.SignalRepository
	cache *cache.Cache
}

func NewSignalHandler(repo *repository.SignalRepository, c *cache.Cache) *SignalHandler {
	return &SignalHandler{repo: repo, cache: c}
}

// ------------------------------------------------------------------ //
// Route handlers                                                       //
// ------------------------------------------------------------------ //

// List godoc
//
//	@Summary		List signals
//	@Description	Returns a paginated list of trading signals. Scenarios and results are NOT included.
//	@Description	Results are cached in Redis (TTL configurable, default 30s). Cache state is exposed via X-Cache header.
//	@Tags			signals
//	@Produce		json
//	@Param			page				query		int		false	"Page number (1-based)"								minimum(1)		default(1)
//	@Param			limit				query		int		false	"Items per page"									minimum(1)		maximum(200)	default(20)
//	@Param			symbol				query		string	false	"Filter by trading pair, case-insensitive (e.g. btcusdt or BTCUSDT)"
//	@Param			source_type			query		string	false	"Filter by source type (e.g. telegram, rss, http)"
//	@Param			source_provider		query		string	false	"Filter by source provider name"
//	@Success		200					{object}	repository.SignalsPage						"Paginated signal list"
//	@Failure		408					{object}	handler.ErrorResponse						"DB query exceeded 5s timeout"
//	@Failure		429					{object}	handler.ErrorResponse						"Global rate limit exceeded"
//	@Failure		500					{object}	handler.ErrorResponse						"Internal server error"
//	@Failure		503					{object}	handler.ErrorResponse						"Server at capacity – concurrency limit hit"
//	@Header			200					{string}	X-Cache									"Cache state: HIT or MISS"
//	@Router			/v1/signals [get]
func (h *SignalHandler) List(c *fiber.Ctx) error {
	p := h.parseParams(c)
	key := cache.SignalsListCacheKey(p.Page, p.Limit, p.Symbol, p.SrcType, p.SrcProvider)
	return h.serveList(c, key, p, false)
}

// ListBySymbol godoc
//
//	@Summary		List signals by symbol
//	@Description	Returns a paginated list of signals filtered by the given trading pair symbol.
//	@Description	Symbol matching is case-insensitive on input; stored values are uppercase (e.g. BTCUSDT).
//	@Tags			signals
//	@Produce		json
//	@Param			symbol				path		string	true	"Trading pair symbol (e.g. BTCUSDT)"
//	@Param			page				query		int		false	"Page number (1-based)"				minimum(1)	default(1)
//	@Param			limit				query		int		false	"Items per page"					minimum(1)	maximum(200)	default(20)
//	@Param			source_type			query		string	false	"Filter by source type"
//	@Param			source_provider		query		string	false	"Filter by source provider"
//	@Success		200					{object}	repository.SignalsPage					"Paginated signal list"
//	@Failure		408					{object}	handler.ErrorResponse					"DB query exceeded 5s timeout"
//	@Failure		429					{object}	handler.ErrorResponse					"Global rate limit exceeded"
//	@Failure		500					{object}	handler.ErrorResponse					"Internal server error"
//	@Failure		503					{object}	handler.ErrorResponse					"Server at capacity"
//	@Header			200					{string}	X-Cache								"Cache state: HIT or MISS"
//	@Router			/v1/signals/{symbol} [get]
func (h *SignalHandler) ListBySymbol(c *fiber.Ctx) error {
	p := h.parseParams(c)
	p.Symbol = strings.ToUpper(c.Params("symbol"))
	key := cache.SignalsListCacheKey(p.Page, p.Limit, p.Symbol, p.SrcType, p.SrcProvider)
	return h.serveList(c, key, p, false)
}

// ListByProvider godoc
//
//	@Summary		List signals by source provider
//	@Description	Returns a paginated list of signals filtered by the source provider name.
//	@Tags			signals
//	@Produce		json
//	@Param			provider			path		string	true	"Source provider name (e.g. binance, coinbase, my_channel)"
//	@Param			page				query		int		false	"Page number (1-based)"				minimum(1)	default(1)
//	@Param			limit				query		int		false	"Items per page"					minimum(1)	maximum(200)	default(20)
//	@Param			symbol				query		string	false	"Filter by trading pair"
//	@Param			source_type			query		string	false	"Filter by source type"
//	@Success		200					{object}	repository.SignalsPage					"Paginated signal list"
//	@Failure		408					{object}	handler.ErrorResponse					"DB query exceeded 5s timeout"
//	@Failure		429					{object}	handler.ErrorResponse					"Global rate limit exceeded"
//	@Failure		500					{object}	handler.ErrorResponse					"Internal server error"
//	@Failure		503					{object}	handler.ErrorResponse					"Server at capacity"
//	@Header			200					{string}	X-Cache								"Cache state: HIT or MISS"
//	@Router			/v1/signals/source/{provider} [get]
func (h *SignalHandler) ListByProvider(c *fiber.Ctx) error {
	p := h.parseParams(c)
	p.SrcProvider = c.Params("provider")
	key := cache.SignalsListCacheKey(p.Page, p.Limit, p.Symbol, p.SrcType, p.SrcProvider)
	return h.serveList(c, key, p, false)
}

// ListWithResults godoc
//
//	@Summary		List signals with scenarios and results
//	@Description	Returns a paginated list of signals with full nested data: each Signal includes its Scenarios,
//	@Description	and each Scenario includes its ScenarioResults. Uses 3 DB queries total (no N+1).
//	@Tags			signals
//	@Produce		json
//	@Param			page				query		int		false	"Page number (1-based)"							minimum(1)	default(1)
//	@Param			limit				query		int		false	"Items per page"								minimum(1)	maximum(200)	default(20)
//	@Param			symbol				query		string	false	"Filter by trading pair"
//	@Param			source_type			query		string	false	"Filter by source type"
//	@Param			source_provider		query		string	false	"Filter by source provider"
//	@Success		200					{object}	repository.SignalsPage						"Paginated signal list with nested scenarios and results"
//	@Failure		408					{object}	handler.ErrorResponse						"DB query exceeded 5s timeout"
//	@Failure		429					{object}	handler.ErrorResponse						"Global rate limit exceeded"
//	@Failure		500					{object}	handler.ErrorResponse						"Internal server error"
//	@Failure		503					{object}	handler.ErrorResponse						"Server at capacity"
//	@Header			200					{string}	X-Cache									"Cache state: HIT or MISS"
//	@Router			/v1/signals/results [get]
func (h *SignalHandler) ListWithResults(c *fiber.Ctx) error {
	p := h.parseParams(c)
	key := cache.SignalsResultsCacheKey(p.Page, p.Limit, p.Symbol, p.SrcType, p.SrcProvider)
	return h.serveList(c, key, p, true)
}

// ListBySymbolWithResults godoc
//
//	@Summary		List signals by symbol with scenarios and results
//	@Description	Returns a paginated list of signals for a specific trading pair, with full nested scenarios and results.
//	@Tags			signals
//	@Produce		json
//	@Param			symbol				path		string	true	"Trading pair symbol (e.g. BTCUSDT)"
//	@Param			page				query		int		false	"Page number (1-based)"					minimum(1)	default(1)
//	@Param			limit				query		int		false	"Items per page"						minimum(1)	maximum(200)	default(20)
//	@Param			source_type			query		string	false	"Filter by source type"
//	@Param			source_provider		query		string	false	"Filter by source provider"
//	@Success		200					{object}	repository.SignalsPage						"Paginated signal list with nested scenarios and results"
//	@Failure		408					{object}	handler.ErrorResponse						"DB query exceeded 5s timeout"
//	@Failure		429					{object}	handler.ErrorResponse						"Global rate limit exceeded"
//	@Failure		500					{object}	handler.ErrorResponse						"Internal server error"
//	@Failure		503					{object}	handler.ErrorResponse						"Server at capacity"
//	@Header			200					{string}	X-Cache									"Cache state: HIT or MISS"
//	@Router			/v1/signals/{symbol}/results [get]
func (h *SignalHandler) ListBySymbolWithResults(c *fiber.Ctx) error {
	p := h.parseParams(c)
	p.Symbol = strings.ToUpper(c.Params("symbol"))
	key := cache.SignalsResultsCacheKey(p.Page, p.Limit, p.Symbol, p.SrcType, p.SrcProvider)
	return h.serveList(c, key, p, true)
}

// ListByProviderWithResults godoc
//
//	@Summary		List signals by provider with scenarios and results
//	@Description	Returns a paginated list of signals for a specific source provider, with full nested scenarios and results.
//	@Tags			signals
//	@Produce		json
//	@Param			provider			path		string	true	"Source provider name"
//	@Param			page				query		int		false	"Page number (1-based)"					minimum(1)	default(1)
//	@Param			limit				query		int		false	"Items per page"						minimum(1)	maximum(200)	default(20)
//	@Param			symbol				query		string	false	"Filter by trading pair"
//	@Param			source_type			query		string	false	"Filter by source type"
//	@Success		200					{object}	repository.SignalsPage						"Paginated signal list with nested scenarios and results"
//	@Failure		408					{object}	handler.ErrorResponse						"DB query exceeded 5s timeout"
//	@Failure		429					{object}	handler.ErrorResponse						"Global rate limit exceeded"
//	@Failure		500					{object}	handler.ErrorResponse						"Internal server error"
//	@Failure		503					{object}	handler.ErrorResponse						"Server at capacity"
//	@Header			200					{string}	X-Cache									"Cache state: HIT or MISS"
//	@Router			/v1/signals/source/{provider}/results [get]
func (h *SignalHandler) ListByProviderWithResults(c *fiber.Ctx) error {
	p := h.parseParams(c)
	p.SrcProvider = c.Params("provider")
	key := cache.SignalsResultsCacheKey(p.Page, p.Limit, p.Symbol, p.SrcType, p.SrcProvider)
	return h.serveList(c, key, p, true)
}

// ------------------------------------------------------------------ //
// Shared logic                                                         //
// ------------------------------------------------------------------ //

// serveList is the common path for all signal list endpoints.
// withResults=true includes Scenarios and ScenarioResults.
func (h *SignalHandler) serveList(
	c *fiber.Ctx,
	cacheKey string,
	p repository.SignalListParams,
	withResults bool,
) error {
	if raw, err := h.cache.GetRaw(c.UserContext(), cacheKey); err == nil {
		c.Set("X-Cache", "HIT")
		c.Set(fiber.HeaderContentType, fiber.MIMEApplicationJSONCharsetUTF8)
		return c.Send(raw)
	} else if !errors.Is(err, cache.ErrMiss) {
		log.Printf("cache get %q: %v", cacheKey, err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), queryTimeout)
	defer cancel()

	var (
		result *repository.SignalsPage
		err    error
	)
	if withResults {
		result, err = h.repo.ListWithResults(ctx, p)
	} else {
		result, err = h.repo.List(ctx, p)
	}
	if err != nil {
		return h.handleDBError(c, err)
	}

	go func(val *repository.SignalsPage) {
		wCtx, wCancel := context.WithTimeout(context.Background(), writeTimeout)
		defer wCancel()
		if err := h.cache.Set(wCtx, cacheKey, val); err != nil {
			log.Printf("cache set %q: %v", cacheKey, err)
		}
	}(result)

	c.Set("X-Cache", "MISS")
	return c.JSON(result)
}

// ------------------------------------------------------------------ //
// Parameter parsing                                                    //
// ------------------------------------------------------------------ //

func (h *SignalHandler) parseParams(c *fiber.Ctx) repository.SignalListParams {
	limit := c.QueryInt("limit", defaultLimit)
	page  := c.QueryInt("page", 1)

	if limit < 1 {
		limit = defaultLimit
	}
	if limit > maxLimit {
		limit = maxLimit
	}
	if page < 1 {
		page = 1
	}

	return repository.SignalListParams{
		Page:        page,
		Limit:       limit,
		Symbol:      strings.ToUpper(c.Query("symbol")), // DB stores uppercase
		SrcType:     c.Query("source_type"),
		SrcProvider: c.Query("source_provider"),
	}
}

// ------------------------------------------------------------------ //
// Error handling                                                       //
// ------------------------------------------------------------------ //

func (h *SignalHandler) handleDBError(c *fiber.Ctx, err error) error {
	if errors.Is(err, context.DeadlineExceeded) {
		return c.Status(fiber.StatusGatewayTimeout).JSON(fiber.Map{
			"error": "query timeout",
		})
	}
	log.Printf("signals query error: %v", err)
	return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
		"error": "failed to fetch signals",
	})
}
