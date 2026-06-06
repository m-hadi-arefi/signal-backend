package config

import (
	"fmt"
	"os"
	"strconv"
	"time"
)

type Config struct {
	Port                string
	PostgresDSN         string
	DBMaxConns          int32
	DBMinConns          int32
	DBMaxConnLifetime   time.Duration
	DBMaxConnIdleTime   time.Duration
	DBHealthCheckPeriod time.Duration
	ServerReadTimeout   time.Duration
	ServerWriteTimeout  time.Duration
	ServerIdleTimeout   time.Duration
	CORSOrigins         string

	RedisAddr     string
	RedisPassword string
	RedisDB       int
	CacheTTL      time.Duration

	// Backpressure controls
	MaxConcurrent int // max in-flight requests hitting the DB layer
	RateLimitRPS  int // max requests per second (global, in-memory)
}

func Load() *Config {
	return &Config{
		Port:                getEnv("API_PORT", "8080"),
		PostgresDSN:         buildDSN(),
		DBMaxConns:          int32(getEnvInt("DB_MAX_CONNS", 50)),
		DBMinConns:          int32(getEnvInt("DB_MIN_CONNS", 10)),
		DBMaxConnLifetime:   getEnvDuration("DB_MAX_CONN_LIFETIME", 30*time.Minute),
		DBMaxConnIdleTime:   getEnvDuration("DB_MAX_CONN_IDLE_TIME", 5*time.Minute),
		DBHealthCheckPeriod: getEnvDuration("DB_HEALTH_CHECK_PERIOD", 30*time.Second),
		ServerReadTimeout:   getEnvDuration("SERVER_READ_TIMEOUT", 10*time.Second),
		ServerWriteTimeout:  getEnvDuration("SERVER_WRITE_TIMEOUT", 10*time.Second),
		ServerIdleTimeout:   getEnvDuration("SERVER_IDLE_TIMEOUT", 60*time.Second),
		CORSOrigins:         getEnv("CORS_ORIGINS", "*"),

		RedisAddr:     getEnv("REDIS_ADDR", "redis:6379"),
		RedisPassword: getEnv("REDIS_PASSWORD", ""),
		RedisDB:       getEnvInt("REDIS_DB", 0),
		CacheTTL:      getEnvDuration("CACHE_TTL", 3*time.Second),

		MaxConcurrent: getEnvInt("MAX_CONCURRENT", 300),
		RateLimitRPS:  getEnvInt("RATE_LIMIT_RPS", 5000),
	}
}

func buildDSN() string {
	if dsn := os.Getenv("POSTGRES_DSN"); dsn != "" {
		return dsn
	}
	host := getEnv("POSTGRES_HOST", "postgres")
	port := getEnv("POSTGRES_PORT", "5432")
	user := getEnv("POSTGRES_USER", "postgres")
	pass := getEnv("POSTGRES_PASSWORD", "postgres")
	db := getEnv("POSTGRES_DB", "events")
	return fmt.Sprintf("postgres://%s:%s@%s:%s/%s?sslmode=disable", user, pass, host, port, db)
}

func getEnv(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func getEnvInt(key string, fallback int) int {
	if v := os.Getenv(key); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			return n
		}
	}
	return fallback
}

func getEnvDuration(key string, fallback time.Duration) time.Duration {
	if v := os.Getenv(key); v != "" {
		if d, err := time.ParseDuration(v); err == nil {
			return d
		}
	}
	return fallback
}
