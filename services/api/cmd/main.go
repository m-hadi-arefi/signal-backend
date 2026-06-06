// Signal API — read-only REST interface for trading signals.
//
//	@title			Signal API
//	@version		2.0
//	@description	Read-only REST API for AI-analysed trading signals with scenario tracking and evaluation results.
//	@host			localhost:8080
//	@BasePath		/
//	@schemes		http https
//
//	@tag.name		signals
//	@tag.description	Paginated signal endpoints with nested scenarios and evaluation results
//	@tag.name		sources
//	@tag.description	Source provider discovery and filtering
//	@tag.name		coins
//	@tag.description	Active tracked coin list
//	@tag.name		system
//	@tag.description	Health and diagnostics
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
		DisableDefaultDate:        true,
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
	app.Use(compress.New(compress.Config{Level: compress.LevelBestSpeed}))
	app.Use(middleware.GlobalRateLimiter(cfg.RateLimitRPS, time.Second))

	// ── Dependencies ──────────────────────────────────────────────────────────
	healthHandler := handler.NewHealthHandler(pool, redisCache)
	signalRepo    := repository.NewSignalRepository(pool, redisCache) // cache used only for live prices
	signalHandler := handler.NewSignalHandler(signalRepo)
	concLimit     := middleware.ConcurrencyLimiter(cfg.MaxConcurrent)

	// ── Routes ────────────────────────────────────────────────────────────────
	app.Get("/health",    healthHandler.Check)
	app.Get("/swagger/*", fiberSwagger.HandlerDefault)

	v1 := app.Group("/v1")

	// Signals
	// Note: static segments (/coin/) must be registered before parametric (/:id)
	// so Fiber's radix tree routes them correctly.
	v1.Get("/signals",                concLimit, signalHandler.List)
	v1.Get("/signals/coin/:symbol",   concLimit, signalHandler.ListByCoin)
	v1.Get("/signals/:id",            concLimit, signalHandler.GetByID)

	// Sources
	v1.Get("/sources",                         concLimit, signalHandler.ListSources)
	v1.Get("/sources/:provider/signals",       concLimit, signalHandler.ListByProvider)

	// Coins
	v1.Get("/coins/active", concLimit, signalHandler.ListActiveCoins)

	// ── Graceful shutdown ─────────────────────────────────────────────────────
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
