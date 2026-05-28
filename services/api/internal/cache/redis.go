package cache

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/redis/go-redis/v9"
)

// ErrMiss is returned when the key does not exist in cache.
var ErrMiss = errors.New("cache: miss")

type Cache struct {
	client *redis.Client
	ttl    time.Duration
}

// New connects to Redis and returns a ready Cache.
// Fails fast if Redis is unreachable within 5 seconds.
func New(addr, password string, db int, ttl time.Duration) (*Cache, error) {
	client := redis.NewClient(&redis.Options{
		Addr:         addr,
		Password:     password,
		DB:           db,
		PoolSize:     200,
		MinIdleConns: 20,
		MaxIdleConns: 50,
		DialTimeout:  3 * time.Second,
		ReadTimeout:  1 * time.Second,
		WriteTimeout: 1 * time.Second,
		PoolTimeout:  2 * time.Second,
	})

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	if err := client.Ping(ctx).Err(); err != nil {
		_ = client.Close()
		return nil, fmt.Errorf("redis connect: %w", err)
	}

	return &Cache{client: client, ttl: ttl}, nil
}

// Get unmarshals a cached value into dst. Returns ErrMiss on key not found,
// or a wrapped error on Redis/unmarshal failure.
func (c *Cache) Get(ctx context.Context, key string, dst any) error {
	val, err := c.client.Get(ctx, key).Bytes()
	if errors.Is(err, redis.Nil) {
		return ErrMiss
	}
	if err != nil {
		return fmt.Errorf("cache get %q: %w", key, err)
	}
	if err := json.Unmarshal(val, dst); err != nil {
		return fmt.Errorf("cache unmarshal %q: %w", key, err)
	}
	return nil
}

// GetRaw returns the raw cached bytes without unmarshaling.
// Use this when the caller will send the bytes directly as a JSON response,
// avoiding a redundant unmarshal + re-marshal cycle on the hot path.
func (c *Cache) GetRaw(ctx context.Context, key string) ([]byte, error) {
	val, err := c.client.Get(ctx, key).Bytes()
	if errors.Is(err, redis.Nil) {
		return nil, ErrMiss
	}
	if err != nil {
		return nil, fmt.Errorf("cache get raw %q: %w", key, err)
	}
	return val, nil
}

// Set stores value with the default TTL configured at construction time.
func (c *Cache) Set(ctx context.Context, key string, value any) error {
	return c.SetTTL(ctx, key, value, c.ttl)
}

// SetTTL stores value with an explicit TTL.
func (c *Cache) SetTTL(ctx context.Context, key string, value any, ttl time.Duration) error {
	data, err := json.Marshal(value)
	if err != nil {
		return fmt.Errorf("cache marshal %q: %w", key, err)
	}
	if err := c.client.Set(ctx, key, data, ttl).Err(); err != nil {
		return fmt.Errorf("cache set %q: %w", key, err)
	}
	return nil
}

// Del removes one or more keys.
func (c *Cache) Del(ctx context.Context, keys ...string) error {
	return c.client.Del(ctx, keys...).Err()
}

// Ping checks the Redis connection.
func (c *Cache) Ping(ctx context.Context) error {
	return c.client.Ping(ctx).Err()
}

// Close releases the Redis connection pool.
func (c *Cache) Close() error {
	return c.client.Close()
}
