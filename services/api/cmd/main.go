// Signal API provides a read-only REST interface for trading signals with AI analysis and scenario tracking.
//
//	@title						Signal API
//	@version					1.0
//	@description				Read-only REST API for accessing AI-analyzed trading signals, scenario plans, and result tracking.
//	@contact.name				Signal Team
//	@host						localhost:8080
//	@BasePath					/
//	@schemes					http https
//	@produce					json
//
//	@tag.name					signals
//	@tag.description			Paginated trading signal endpoints with optional filtering by symbol, source type, and provider
//	@tag.name					system
//	@tag.description			Service health and diagnostics
package main

import (
	"context"
	"log"
	"os"
	"os/signal"
	"runtime"
	"strconv"
	"syscall"
	"time"

	"github.com/bytedance/sonic"
	"github.com/gofiber/fiber/v2"
	"github.com/gofiber/fiber/v2/middleware/compress"
	"github.com/gofiber/fiber/v2/middleware/cors"
	fiberlog "github.com/gofiber/fiber/v2/middleware/logger"
	"github.com/gofiber/fiber/v2/middleware/recover"
	fiberSwagger "github.com/gofiber/swagger"
	"signal/api/internal/cache"
	"signal/api/internal/config"
	"signal/api/internal/db"
	_ "signal/api/docs"
	"signal/api/internal/handler"
	"signal/api/internal/middleware"
	"signal/api/internal/repository"
)

func main() {
	// Honour container CPU quota — Go detects host CPU count (e.g. 16) not
	// the container limit (e.g. 2), causing scheduling overhead.
	if v := os.Getenv("GOMAXPROCS"); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			runtime.GOMAXPROCS(n)
		}
	}
	log.Printf("GOMAXPROCS=%d", runtime.GOMAXPROCS(0))

	cfg := config.Load()

	initCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	pool, err := db.NewPool(initCtx, cfg)
	if err != nil {
		log.Fatalf("db connect: %v", err)
	}
	defer pool.Close()

	redisCache, err := cache.New(cfg.RedisAddr, cfg.RedisPassword, cfg.RedisDB, cfg.CacheTTL)
	if err != nil {
		log.Fatalf("cache connect: %v", err)
	}
	defer redisCache.Close()

	app := fiber.New(fiber.Config{
		JSONEncoder:               sonic.Marshal,
		JSONDecoder:               sonic.Unmarshal,
		ReadTimeout:               cfg.ServerReadTimeout,
		WriteTimeout:              cfg.ServerWriteTimeout,
		IdleTimeout:               cfg.ServerIdleTimeout,
		DisableKeepalive:          false,
		DisableDefaultDate:        true,
		DisableHeaderNormalizing:  false,
		DisableDefaultContentType: false,
		Concurrency:               256 * 1024,
	})

	app.Use(recover.New())
	app.Use(fiberlog.New(fiberlog.Config{
		Format: "${time} | ${status} | ${latency} | ${method} ${path}\n",
	}))
	app.Use(cors.New(cors.Config{
		AllowOrigins: cfg.CORSOrigins,
		AllowMethods: "GET,HEAD,OPTIONS",
		AllowHeaders: "Accept,Content-Type,Authorization",
	}))
	app.Use(compress.New(compress.Config{
		Level: compress.LevelBestSpeed,
	}))

	// Global rate limiter — drops excess requests before they reach handlers.
	app.Use(middleware.GlobalRateLimiter(cfg.RateLimitRPS, time.Second))

	// ------------------------------------------------------------------ //
	// Dependencies                                                         //
	// ------------------------------------------------------------------ //

	healthHandler := handler.NewHealthHandler(pool, redisCache)
	signalRepo    := repository.NewSignalRepository(pool)
	signalHandler := handler.NewSignalHandler(signalRepo, redisCache)

	concLimit := middleware.ConcurrencyLimiter(cfg.MaxConcurrent)

	// ------------------------------------------------------------------ //
	// Routes                                                               //
	// ------------------------------------------------------------------ //

	app.Get("/health", healthHandler.Check)
	app.Get("/swagger/*", fiberSwagger.HandlerDefault)

	v1 := app.Group("/v1")

	signals := v1.Group("/signals")

	// Static routes registered before parameter routes so Fiber prefers them.
	// GET /v1/signals
	signals.Get("/", concLimit, signalHandler.List)

	// GET /v1/signals/results  (must be before /:symbol to avoid collision)
	signals.Get("/results", concLimit, signalHandler.ListWithResults)

	// GET /v1/signals/source/:provider
	signals.Get("/source/:provider", concLimit, signalHandler.ListByProvider)

	// GET /v1/signals/source/:provider/results
	signals.Get("/source/:provider/results", concLimit, signalHandler.ListByProviderWithResults)

	// GET /v1/signals/:symbol
	signals.Get("/:symbol", concLimit, signalHandler.ListBySymbol)

	// GET /v1/signals/:symbol/results
	signals.Get("/:symbol/results", concLimit, signalHandler.ListBySymbolWithResults)

	// ------------------------------------------------------------------ //
	// Graceful shutdown                                                    //
	// ------------------------------------------------------------------ //

	quit := make(chan os.Signal, 1)
	signal.Notify(quit, os.Interrupt, syscall.SIGTERM)

	go func() {
		<-quit
		log.Println("shutdown signal received")
		if err := app.ShutdownWithTimeout(15 * time.Second); err != nil {
			log.Printf("shutdown error: %v", err)
		}
	}()

	log.Printf("listening on :%s", cfg.Port)
	if err := app.Listen(":" + cfg.Port); err != nil {
		log.Fatal(err)
	}
}
