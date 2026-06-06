package cache

// Response caching has been removed — every API request reads directly from
// the database. This file is kept as a placeholder.
//
// The Cache struct in redis.go is still used for:
//   - GetPrice: reads live market prices published by the price-streamer
//   - Ping:     health endpoint checks Redis connectivity
