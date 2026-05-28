package middleware

import (
	"sync"
	"time"

	"github.com/gofiber/fiber/v2"
)

type fixedWindow struct {
	mu      sync.Mutex
	count   int
	resetAt time.Time
	max     int
	window  time.Duration
}

func (fw *fixedWindow) allow() bool {
	fw.mu.Lock()
	defer fw.mu.Unlock()

	now := time.Now()
	if now.After(fw.resetAt) {
		fw.count = 0
		fw.resetAt = now.Add(fw.window)
	}
	fw.count++
	return fw.count <= fw.max
}

// GlobalRateLimiter caps requests per window across all clients (single global bucket).
// For multi-instance deployments, replace with a Redis-backed counter.
func GlobalRateLimiter(max int, window time.Duration) fiber.Handler {
	fw := &fixedWindow{
		max:     max,
		window:  window,
		resetAt: time.Now().Add(window),
	}
	return func(c *fiber.Ctx) error {
		if !fw.allow() {
			return c.Status(fiber.StatusTooManyRequests).JSON(fiber.Map{
				"error":       "rate limit exceeded",
				"retry_after": 1,
			})
		}
		return c.Next()
	}
}

// ConcurrencyLimiter caps the number of goroutines concurrently executing
// the next handler. Excess requests get 503 immediately — backpressure, not a queue.
func ConcurrencyLimiter(max int) fiber.Handler {
	sem := make(chan struct{}, max)
	return func(c *fiber.Ctx) error {
		select {
		case sem <- struct{}{}:
			defer func() { <-sem }()
			return c.Next()
		default:
			return c.Status(fiber.StatusServiceUnavailable).JSON(fiber.Map{
				"error":       "server at capacity, try again shortly",
				"retry_after": 1,
			})
		}
	}
}
