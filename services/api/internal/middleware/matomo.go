package middleware

import (
	"github.com/gofiber/fiber/v2"
	"signal/api/internal/tracking"
)

// MatomoTracker records each API request to Matomo after the response is sent.
// Has zero latency impact — tracking fires in a goroutine after c.Next() returns.
func MatomoTracker(client *tracking.MatomoClient) fiber.Handler {
	return func(c *fiber.Ctx) error {
		err := c.Next()
		client.Track(
			c.Path(),
			c.Method(),
			c.IP(),
			c.Get(fiber.HeaderUserAgent),
			c.Response().StatusCode(),
		)
		return err
	}
}
