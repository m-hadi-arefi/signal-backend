package handler

import (
	"context"
	"errors"
	"log"
	"strconv"
	"strings"

	"github.com/gofiber/fiber/v2"
	"signal/api/internal/cache"
	"signal/api/internal/repository"
)

// ErrorResponse is the standard error body.
type ErrorResponse struct {
	Error string `json:"error" example:"query timeout"`
}

// SignalHandler serves all /v1/signals, /v1/coins, /v1/sources endpoints.
type SignalHandler struct {
	repo  *repository.SignalRepository
	cache *cache.Cache
}

func NewSignalHandler(repo *repository.SignalRepository, c *cache.Cache) *SignalHandler {
	return &SignalHandler{repo: repo, cache: c}
}

// ─── Signal endpoints ─────────────────────────────────────────────────────────

// List godoc
//
//	@Summary		List all signals
//	@Description	Paginated list of signals with scenarios, evaluation results and source info. raw_text is never returned.
//	@Tags			signals
//	@Produce		json
//	@Param			page			query	int		false	"Page (1-based)"	default(1)
//	@Param			limit			query	int		false	"Per page"			default(20)	maximum(200)
//	@Success		200	{object}	repository.SignalsPage
//	@Failure		408	{object}	ErrorResponse
//	@Failure		500	{object}	ErrorResponse
//	@Header			200	{string}	X-Cache	"HIT or MISS"
//	@Router			/v1/signals [get]
func (h *SignalHandler) List(c *fiber.Ctx) error {
	p := h.parseParams(c)
	key := cache.KeySignals(p.Page, p.Limit, "", "")
	return h.serveSignals(c, key, func(ctx context.Context) (*repository.SignalsPage, error) {
		return h.repo.List(ctx, p)
	})
}

// GetByID godoc
//
//	@Summary		Get signal by ID
//	@Description	Returns full signal detail including all scenarios and their latest evaluation result.
//	@Tags			signals
//	@Produce		json
//	@Param			id	path	int	true	"Signal ID"
//	@Success		200	{object}	repository.Signal
//	@Failure		404	{object}	ErrorResponse
//	@Failure		408	{object}	ErrorResponse
//	@Failure		500	{object}	ErrorResponse
//	@Header			200	{string}	X-Cache	"HIT or MISS"
//	@Router			/v1/signals/{id} [get]
func (h *SignalHandler) GetByID(c *fiber.Ctx) error {
	id, err := strconv.ParseInt(c.Params("id"), 10, 64)
	if err != nil {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{"error": "invalid id"})
	}

	key := cache.KeySignalByID(id)

	if raw, err := h.cache.GetRaw(c.UserContext(), key); err == nil {
		c.Set("X-Cache", "HIT")
		c.Set(fiber.HeaderContentType, fiber.MIMEApplicationJSONCharsetUTF8)
		return c.Send(raw)
	}

	ctx, cancel := context.WithTimeout(context.Background(), queryTimeout)
	defer cancel()

	signal, err := h.repo.GetByID(ctx, id)
	if err != nil {
		return h.dbError(c, err)
	}
	if signal == nil {
		return c.Status(fiber.StatusNotFound).JSON(fiber.Map{"error": "signal not found"})
	}

	go func() {
		wCtx, wCancel := context.WithTimeout(context.Background(), writeTimeout)
		defer wCancel()
		_ = h.cache.Set(wCtx, key, signal)
	}()

	c.Set("X-Cache", "MISS")
	return c.JSON(signal)
}

// ListByCoin godoc
//
//	@Summary		Signals for a coin
//	@Description	Paginated signals filtered by coin symbol (case-insensitive).
//	@Tags			signals
//	@Produce		json
//	@Param			symbol	path	string	true	"Coin symbol, e.g. BTC or ETH"
//	@Param			page	query	int		false	"Page"	default(1)
//	@Param			limit	query	int		false	"Per page"	default(20)	maximum(200)
//	@Success		200	{object}	repository.SignalsPage
//	@Failure		408	{object}	ErrorResponse
//	@Failure		500	{object}	ErrorResponse
//	@Header			200	{string}	X-Cache	"HIT or MISS"
//	@Router			/v1/signals/coin/{symbol} [get]
func (h *SignalHandler) ListByCoin(c *fiber.Ctx) error {
	symbol := strings.ToUpper(c.Params("symbol"))
	p := h.parseParams(c)
	key := cache.KeySignals(p.Page, p.Limit, symbol, "")
	return h.serveSignals(c, key, func(ctx context.Context) (*repository.SignalsPage, error) {
		return h.repo.ListByCoin(ctx, symbol, p)
	})
}

// ─── Source endpoints ─────────────────────────────────────────────────────────

// ListSources godoc
//
//	@Summary		List signal sources
//	@Description	Returns all unique source providers that have submitted signals, with signal count and last activity.
//	@Tags			sources
//	@Produce		json
//	@Success		200	{object}	repository.SourcesPage
//	@Failure		408	{object}	ErrorResponse
//	@Failure		500	{object}	ErrorResponse
//	@Header			200	{string}	X-Cache	"HIT or MISS"
//	@Router			/v1/sources [get]
func (h *SignalHandler) ListSources(c *fiber.Ctx) error {
	key := cache.KeySources()

	if raw, err := h.cache.GetRaw(c.UserContext(), key); err == nil {
		c.Set("X-Cache", "HIT")
		c.Set(fiber.HeaderContentType, fiber.MIMEApplicationJSONCharsetUTF8)
		return c.Send(raw)
	}

	ctx, cancel := context.WithTimeout(context.Background(), queryTimeout)
	defer cancel()

	result, err := h.repo.ListSources(ctx)
	if err != nil {
		return h.dbError(c, err)
	}

	go func() {
		wCtx, wCancel := context.WithTimeout(context.Background(), writeTimeout)
		defer wCancel()
		_ = h.cache.Set(wCtx, key, result)
	}()

	c.Set("X-Cache", "MISS")
	return c.JSON(result)
}

// ListByProvider godoc
//
//	@Summary		Signals from a source
//	@Description	Paginated signals submitted by the given source provider.
//	@Tags			sources
//	@Produce		json
//	@Param			provider	path	string	true	"Source provider name"
//	@Param			page		query	int		false	"Page"		default(1)
//	@Param			limit		query	int		false	"Per page"	default(20)	maximum(200)
//	@Success		200	{object}	repository.SignalsPage
//	@Failure		408	{object}	ErrorResponse
//	@Failure		500	{object}	ErrorResponse
//	@Header			200	{string}	X-Cache	"HIT or MISS"
//	@Router			/v1/sources/{provider}/signals [get]
func (h *SignalHandler) ListByProvider(c *fiber.Ctx) error {
	provider := c.Params("provider")
	p := h.parseParams(c)
	key := cache.KeySignals(p.Page, p.Limit, "", provider)
	return h.serveSignals(c, key, func(ctx context.Context) (*repository.SignalsPage, error) {
		return h.repo.ListByProvider(ctx, provider, p)
	})
}

// ─── Coins endpoint ───────────────────────────────────────────────────────────

// ListActiveCoins godoc
//
//	@Summary		Active tracked coins
//	@Description	Returns all coins the admin has enabled for signal tracking.
//	@Tags			coins
//	@Produce		json
//	@Success		200	{object}	repository.CoinsPage
//	@Failure		408	{object}	ErrorResponse
//	@Failure		500	{object}	ErrorResponse
//	@Header			200	{string}	X-Cache	"HIT or MISS"
//	@Router			/v1/coins/active [get]
func (h *SignalHandler) ListActiveCoins(c *fiber.Ctx) error {
	key := cache.KeyActiveCoins()

	if raw, err := h.cache.GetRaw(c.UserContext(), key); err == nil {
		c.Set("X-Cache", "HIT")
		c.Set(fiber.HeaderContentType, fiber.MIMEApplicationJSONCharsetUTF8)
		return c.Send(raw)
	}

	ctx, cancel := context.WithTimeout(context.Background(), queryTimeout)
	defer cancel()

	result, err := h.repo.ListActiveCoins(ctx)
	if err != nil {
		return h.dbError(c, err)
	}

	go func() {
		wCtx, wCancel := context.WithTimeout(context.Background(), writeTimeout)
		defer wCancel()
		_ = h.cache.Set(wCtx, key, result)
	}()

	c.Set("X-Cache", "MISS")
	return c.JSON(result)
}

// ─── Shared helpers ───────────────────────────────────────────────────────────

func (h *SignalHandler) serveSignals(
	c *fiber.Ctx,
	cacheKey string,
	query func(context.Context) (*repository.SignalsPage, error),
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

	result, err := query(ctx)
	if err != nil {
		return h.dbError(c, err)
	}

	go func(v *repository.SignalsPage) {
		wCtx, wCancel := context.WithTimeout(context.Background(), writeTimeout)
		defer wCancel()
		if err := h.cache.Set(wCtx, cacheKey, v); err != nil {
			log.Printf("cache set %q: %v", cacheKey, err)
		}
	}(result)

	c.Set("X-Cache", "MISS")
	return c.JSON(result)
}

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
	return repository.SignalListParams{Page: page, Limit: limit}
}

func (h *SignalHandler) dbError(c *fiber.Ctx, err error) error {
	if errors.Is(err, context.DeadlineExceeded) {
		return c.Status(fiber.StatusGatewayTimeout).JSON(fiber.Map{"error": "query timeout"})
	}
	log.Printf("db error: %v", err)
	return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{"error": "internal server error"})
}
