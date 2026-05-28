package handler

import (
	"context"
	"sync"
	"time"

	"github.com/gofiber/fiber/v2"
	"github.com/jackc/pgx/v5/pgxpool"
	"signal/api/internal/cache"
)

// HealthResponse is the response body for GET /health.
type HealthResponse struct {
	Status string           `json:"status" enums:"healthy,degraded,unhealthy" example:"healthy"`
	DB     DBHealthStatus   `json:"db"`
	Cache  CacheHealthStatus `json:"cache"`
}

// DBHealthStatus holds PostgreSQL connection pool stats.
type DBHealthStatus struct {
	Status        string `json:"status"         enums:"ok,unreachable" example:"ok"`
	TotalConns    int32  `json:"total_conns"    example:"10"`
	IdleConns     int32  `json:"idle_conns"     example:"8"`
	AcquiredConns int32  `json:"acquired_conns" example:"2"`
	MaxConns      int32  `json:"max_conns"      example:"50"`
}

// CacheHealthStatus holds Redis connectivity status.
type CacheHealthStatus struct {
	Status string `json:"status" enums:"ok,unreachable" example:"ok"`
}

type HealthHandler struct {
	pool  *pgxpool.Pool
	cache *cache.Cache
}

func NewHealthHandler(pool *pgxpool.Pool, c *cache.Cache) *HealthHandler {
	return &HealthHandler{pool: pool, cache: c}
}

// Check godoc
//
//	@Summary		Health check
//	@Description	Returns the overall service health including PostgreSQL connection pool stats and Redis cache status.
//	@Description	Status is "healthy" when both DB and cache are reachable, "degraded" when cache is unreachable,
//	@Description	and "unhealthy" when the database is unreachable.
//	@Tags			system
//	@Produce		json
//	@Success		200	{object}	handler.HealthResponse	"Service is healthy or degraded (cache issue)"
//	@Failure		503	{object}	handler.HealthResponse	"Service is unhealthy (DB unreachable)"
//	@Router			/health [get]
func (h *HealthHandler) Check(c *fiber.Ctx) error {
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()

	var (
		dbErr    error
		cacheErr error
		wg       sync.WaitGroup
	)

	wg.Add(2)
	go func() {
		defer wg.Done()
		dbErr = h.pool.Ping(ctx)
	}()
	go func() {
		defer wg.Done()
		cacheErr = h.cache.Ping(ctx)
	}()
	wg.Wait()

	status := "healthy"
	httpStatus := fiber.StatusOK

	dbStatus := "ok"
	cacheStatus := "ok"

	if dbErr != nil {
		dbStatus = "unreachable"
		status = "unhealthy"
		httpStatus = fiber.StatusServiceUnavailable
	}
	if cacheErr != nil {
		cacheStatus = "unreachable"
		if status == "healthy" {
			status = "degraded"
		}
	}

	s := h.pool.Stat()
	return c.Status(httpStatus).JSON(fiber.Map{
		"status": status,
		"db": fiber.Map{
			"status":         dbStatus,
			"total_conns":    s.TotalConns(),
			"idle_conns":     s.IdleConns(),
			"acquired_conns": s.AcquiredConns(),
			"max_conns":      s.MaxConns(),
		},
		"cache": fiber.Map{
			"status": cacheStatus,
		},
	})
}
